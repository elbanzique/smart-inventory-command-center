"""
Export a BI-ready star schema for Power BI.

Why transform at all — why not point Power BI at novalog.db directly?
----------------------------------------------------------------------
The database is normalized OLTP-style (see docs/architecture.md), which is
right for transactional integrity but wrong for a BI tool. Power BI's
VertiPaq engine and DAX are built around a star schema: narrow dimension
tables joined one-to-many onto a central fact table. Feeding it a
normalized model forces bidirectional filters and snowflaked relationships,
which produce slow visuals and — worse — ambiguous filter propagation that
silently returns wrong numbers.

So this module does the dimensional modeling step explicitly:

  fact_sales          one row per order line, with FKs + pre-computed measures
  fact_inventory      one row per (warehouse, product) stock position
  fact_purchase_orders one row per PO, with lateness already derived
  dim_product         product attributes + ABC class
  dim_supplier        supplier attributes + risk tier from the scorecard
  dim_warehouse       warehouse attributes
  dim_date            contiguous date table (see below — this one matters)

The dim_date table is the piece most beginners omit. Power BI's time
intelligence functions (TOTALYTD, SAMEPERIODLASTYEAR, DATEADD) require a
dedicated, contiguous, gap-free date dimension marked as the model's date
table. Without it those functions silently misbehave around gaps, and
month-over-month comparisons break.

Run from the project root (after load_to_db and generate_report):
    python -m src.etl.export_for_powerbi
"""

import time

import pandas as pd

from src import config
from src.analysis.abc_analysis import classify_abc
from src.analysis.db import load_sales_detail, load_table
from src.analysis.supplier_scorecard import build_supplier_scorecard

POWERBI_DIR = config.DATA_DIR / "powerbi_export"


def build_dim_date(start: str, end: str) -> pd.DataFrame:
    """Contiguous date dimension covering the simulation window.

    Includes a fiscal-year column (FY starting July) because distribution
    businesses commonly report on a non-calendar fiscal year, and adding it
    here is far cheaper than retrofitting it into every DAX measure later.
    """
    dates = pd.date_range(start, end, freq="D")
    dim = pd.DataFrame({"date": dates})
    dim["date_key"] = dim["date"].dt.strftime("%Y%m%d").astype(int)
    dim["year"] = dim["date"].dt.year
    dim["quarter"] = dim["date"].dt.quarter
    dim["month"] = dim["date"].dt.month
    dim["month_name"] = dim["date"].dt.strftime("%b")
    dim["year_month"] = dim["date"].dt.strftime("%Y-%m")
    dim["day_of_week"] = dim["date"].dt.dayofweek
    dim["day_name"] = dim["date"].dt.strftime("%a")
    dim["is_weekend"] = dim["day_of_week"] >= 5
    dim["fiscal_year"] = dim["year"].where(dim["month"] < 7, dim["year"] + 1)
    # month_sort exists so Power BI sorts "Jan, Feb, Mar" chronologically
    # instead of alphabetically ("Apr, Aug, Dec..."), which is the single
    # most common beginner mistake in a Power BI date table.
    dim["month_sort"] = dim["month"]
    return dim


def main() -> None:
    start = time.time()
    POWERBI_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading source tables...")
    products = load_table("products")
    suppliers = load_table("suppliers")
    warehouses = load_table("warehouses")
    inventory = load_table("inventory")
    purchase_orders = load_table("purchase_orders")
    sales = load_sales_detail()

    # --- dim_date ---------------------------------------------------------
    print("Building dim_date...")
    dim_date = build_dim_date(config.SIMULATION_START_DATE, config.SIMULATION_END_DATE)

    # --- dim_product (enriched with ABC class) ----------------------------
    print("Building dim_product...")
    abc = classify_abc(sales)[["product_id", "abc_class"]]
    dim_product = products.merge(abc, on="product_id", how="left")
    dim_product["abc_class"] = dim_product["abc_class"].fillna("C")
    dim_product["margin_pct"] = (
        100 * (dim_product["unit_price"] - dim_product["unit_cost"]) / dim_product["unit_price"]
    ).round(2)
    # popularity_score is a generation artifact, not a business attribute —
    # excluded so it can't accidentally be dragged onto a report page.
    dim_product = dim_product.drop(columns=["popularity_score"])

    # --- dim_supplier (enriched with risk tier) ---------------------------
    print("Building dim_supplier...")
    scorecard = build_supplier_scorecard()[
        ["supplier_id", "composite_score", "risk_tier", "late_delivery_rate_pct", "avg_delay_days"]
    ]
    dim_supplier = suppliers.merge(scorecard, on="supplier_id", how="left")
    # base_reliability_score is the hidden generation seed — dropping it
    # keeps the BI model honest (the risk tier is earned from observed
    # behavior, and leaving the seed in would let someone "cheat" the analysis).
    dim_supplier = dim_supplier.drop(columns=["base_reliability_score"])
    dim_supplier["risk_tier"] = dim_supplier["risk_tier"].fillna("Insufficient Data")

    # --- dim_warehouse ----------------------------------------------------
    dim_warehouse = warehouses.copy()

    # --- fact_sales -------------------------------------------------------
    print("Building fact_sales...")
    fact_sales = sales[[
        "order_line_id", "order_id", "product_id", "warehouse_id",
        "customer_id", "order_date", "status", "quantity",
        "unit_price_at_sale", "line_revenue", "line_margin", "line_cogs",
    ]].copy()
    fact_sales["date_key"] = pd.to_datetime(fact_sales["order_date"]).dt.strftime("%Y%m%d").astype(int)
    fact_sales = fact_sales.drop(columns=["order_date"])

    # --- fact_inventory ---------------------------------------------------
    print("Building fact_inventory...")
    fact_inventory = inventory.merge(
        products[["product_id", "unit_cost", "reorder_point", "safety_stock"]],
        on="product_id",
        how="left",
    )
    fact_inventory["inventory_value"] = (
        fact_inventory["quantity_on_hand"] * fact_inventory["unit_cost"]
    ).round(2)
    fact_inventory["is_below_reorder_point"] = (
        fact_inventory["quantity_on_hand"] < fact_inventory["reorder_point"]
    )
    fact_inventory["units_above_safety_stock"] = (
        fact_inventory["quantity_on_hand"] - fact_inventory["safety_stock"]
    ).clip(lower=0)
    fact_inventory = fact_inventory.drop(columns=["unit_cost"])

    # --- fact_purchase_orders ---------------------------------------------
    print("Building fact_purchase_orders...")
    fact_po = purchase_orders.copy()
    for col in ["order_date", "expected_delivery_date", "actual_delivery_date"]:
        fact_po[col] = pd.to_datetime(fact_po[col])
    fact_po["delay_days"] = (
        fact_po["actual_delivery_date"] - fact_po["expected_delivery_date"]
    ).dt.days
    fact_po["is_delivered"] = fact_po["actual_delivery_date"].notna()
    fact_po["is_late"] = fact_po["delay_days"] > 0
    fact_po["date_key"] = fact_po["order_date"].dt.strftime("%Y%m%d").astype(int)
    fact_po = fact_po.drop(columns=["order_date"])

    # --- write ------------------------------------------------------------
    exports = {
        "dim_date": dim_date,
        "dim_product": dim_product,
        "dim_supplier": dim_supplier,
        "dim_warehouse": dim_warehouse,
        "fact_sales": fact_sales,
        "fact_inventory": fact_inventory,
        "fact_purchase_orders": fact_po,
    }

    print()
    for name, df in exports.items():
        path = POWERBI_DIR / f"{name}.csv"
        df.to_csv(path, index=False)
        print(f"  {name:22s} {len(df):>8,} rows x {len(df.columns):>2} cols")

    print("\nValidating star schema...")
    if not validate_star_schema(exports):
        raise RuntimeError("Star schema validation failed — see output above.")

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s. Star schema exported to {POWERBI_DIR}")
    print("Next: follow docs/powerbi_guide.md to build the report.")


def validate_star_schema(t: dict) -> bool:
    """Verify every fact-to-dimension key resolves before Power BI sees it.

    A broken relationship in Power BI doesn't throw an error — it silently
    drops rows or produces blanks in visuals, which is far harder to spot
    than a crash. Catching it here means the CSVs are known-good before
    they're ever loaded.
    """
    checks = []

    def chk(label: str, ok: bool) -> bool:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        checks.append(bool(ok))
        return bool(ok)

    chk("fact_sales.date_key resolves", t["fact_sales"]["date_key"].isin(t["dim_date"]["date_key"]).all())
    chk("fact_sales.product_id resolves", t["fact_sales"]["product_id"].isin(t["dim_product"]["product_id"]).all())
    chk("fact_sales.warehouse_id resolves", t["fact_sales"]["warehouse_id"].isin(t["dim_warehouse"]["warehouse_id"]).all())
    chk("fact_inventory.product_id resolves", t["fact_inventory"]["product_id"].isin(t["dim_product"]["product_id"]).all())
    chk("fact_inventory.warehouse_id resolves", t["fact_inventory"]["warehouse_id"].isin(t["dim_warehouse"]["warehouse_id"]).all())
    chk("fact_purchase_orders.supplier_id resolves", t["fact_purchase_orders"]["supplier_id"].isin(t["dim_supplier"]["supplier_id"]).all())
    chk("fact_purchase_orders.date_key resolves", t["fact_purchase_orders"]["date_key"].isin(t["dim_date"]["date_key"]).all())

    dates = pd.to_datetime(t["dim_date"]["date"])
    chk("dim_date is contiguous (required for DAX time intelligence)",
        len(t["dim_date"]) == (dates.diff().dt.days.dropna() == 1).sum() + 1)

    for dim, key in [("dim_date", "date_key"), ("dim_product", "product_id"),
                     ("dim_supplier", "supplier_id"), ("dim_warehouse", "warehouse_id")]:
        chk(f"{dim}.{key} is unique (required for 1-to-many relationships)", t[dim][key].is_unique)

    # Generation artifacts must never reach the BI model — see module docstring.
    chk("no generation-artifact leakage",
        "popularity_score" not in t["dim_product"].columns
        and "base_reliability_score" not in t["dim_supplier"].columns)

    ok = all(checks)
    print(f"  -> {'ALL CHECKS PASSED' if ok else 'FAILURES DETECTED'}")
    return ok


if __name__ == "__main__":
    main()
