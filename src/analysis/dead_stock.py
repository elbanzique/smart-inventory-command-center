"""
Dead stock and slow-moving inventory analysis.

Improves on the Phase 4 SQL definition (quantity >= 4x safety stock) by
bringing in actual sales velocity and restock aging. High stock alone
isn't dead stock — a fast-selling product can legitimately hold a lot of
units. What makes inventory *dead* is stock that isn't moving.
"""

import numpy as np
import pandas as pd

from src.analysis.db import load_inventory_detail, load_sales_detail


def analyze_dead_stock(velocity_window_days: int = 90) -> pd.DataFrame:
    """Classify every inventory position by how much it's actually moving.

    Three signals are combined per (warehouse, product) position:
      1. stock_ratio       - quantity on hand relative to safety stock
      2. units_sold_recent - units sold from that warehouse in the window
      3. days_since_restock - how long the stock has been sitting

    Classification (evaluated in order):
      Dead        - zero sales in the window AND stock >= 2x safety stock
      Slow-Moving - stock covers more than 180 days of demand
      Overstocked - stock >= 4x safety stock but still selling
      Healthy     - everything else

    The distinction between Dead and Overstocked is the point: both look
    identical on a stock-level-only view, but only one is genuinely
    stranded capital. Overstocked inventory will clear on its own; dead
    stock needs intervention (markdown, liquidation, write-off).
    """
    inventory = load_inventory_detail()
    sales = load_sales_detail()

    cutoff = sales["order_date"].max() - pd.Timedelta(days=velocity_window_days)
    recent = sales[sales["order_date"] >= cutoff]

    velocity = (
        recent.groupby(["warehouse_id", "product_id"], as_index=False)
        .agg(units_sold_recent=("quantity", "sum"), revenue_recent=("line_revenue", "sum"))
    )

    df = inventory.merge(velocity, on=["warehouse_id", "product_id"], how="left")
    df[["units_sold_recent", "revenue_recent"]] = df[["units_sold_recent", "revenue_recent"]].fillna(0)

    df["daily_demand"] = df["units_sold_recent"] / velocity_window_days
    # np.nan (not inf) for zero-demand positions: "infinite days of supply"
    # is arithmetically true but breaks means/sorts downstream. The Dead
    # classification below catches these on the sales-volume condition
    # instead, so nothing is lost.
    df["days_of_supply"] = np.where(
        df["daily_demand"] > 0, df["quantity_on_hand"] / df["daily_demand"], np.nan
    ).round(1)

    df["stock_ratio"] = (df["quantity_on_hand"] / df["safety_stock"].replace(0, np.nan)).round(2)
    snapshot_date = sales["order_date"].max()
    df["days_since_restock"] = (snapshot_date - df["last_restock_date"]).dt.days

    conditions = [
        (df["units_sold_recent"] == 0) & (df["stock_ratio"] >= 2),
        df["days_of_supply"] > 180,
        df["stock_ratio"] >= 4,
    ]
    df["stock_status"] = np.select(
        conditions, ["Dead", "Slow-Moving", "Overstocked"], default="Healthy"
    )

    columns = [
        "warehouse_id", "warehouse_name", "product_id", "sku", "category",
        "quantity_on_hand", "safety_stock", "stock_ratio", "unit_cost",
        "inventory_value", "units_sold_recent", "daily_demand",
        "days_of_supply", "days_since_restock", "stock_status",
    ]
    return df[columns].sort_values("inventory_value", ascending=False).reset_index(drop=True)


def dead_stock_summary(dead_stock_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate capital tied up by stock status — the CFO-facing view."""
    total_value = dead_stock_df["inventory_value"].sum()

    summary = (
        dead_stock_df.groupby("stock_status", as_index=False)
        .agg(
            positions=("product_id", "count"),
            total_units=("quantity_on_hand", "sum"),
            total_value=("inventory_value", "sum"),
        )
        .sort_values("total_value", ascending=False)
    )
    summary["pct_of_inventory_value"] = (100 * summary["total_value"] / total_value).round(2)
    summary["total_value"] = summary["total_value"].round(2)
    return summary.reset_index(drop=True)


def dead_stock_by_category(dead_stock_df: pd.DataFrame) -> pd.DataFrame:
    """Dead + slow-moving capital per category, for targeting remediation."""
    problem = dead_stock_df[dead_stock_df["stock_status"].isin(["Dead", "Slow-Moving"])]

    by_cat = (
        problem.groupby("category", as_index=False)
        .agg(
            problem_positions=("product_id", "count"),
            capital_tied_up=("inventory_value", "sum"),
        )
        .sort_values("capital_tied_up", ascending=False)
    )
    by_cat["capital_tied_up"] = by_cat["capital_tied_up"].round(2)
    return by_cat.reset_index(drop=True)
