"""
Tests for src/etl/export_for_powerbi.py.

Two levels:
  - build_dim_date() is a pure function, tested directly with no I/O.
  - The full export (main()) is tested end-to-end against a small, hermetic
    dataset generated -> loaded -> exported, then run through
    validate_star_schema() itself — the same function the real pipeline
    uses to gate its own output.
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.data_generation.inventory import generate_inventory
from src.data_generation.order_lines import generate_order_lines
from src.data_generation.orders import generate_orders
from src.data_generation.products import generate_products
from src.data_generation.purchase_orders import generate_purchase_orders
from src.data_generation.suppliers import generate_suppliers
from src.data_generation.warehouses import generate_warehouses
from src.etl import export_for_powerbi, load_to_db


# ---------------------------------------------------------------------------
# build_dim_date — pure function, no I/O
# ---------------------------------------------------------------------------

def test_dim_date_is_contiguous_with_no_gaps():
    dim = export_for_powerbi.build_dim_date("2024-01-01", "2024-03-31")
    assert len(dim) == 91  # Jan(31) + Feb(29, 2024 is a leap year) + Mar(31)
    diffs = pd.to_datetime(dim["date"]).diff().dt.days.dropna()
    assert (diffs == 1).all()


def test_dim_date_key_is_unique_and_matches_yyyymmdd():
    dim = export_for_powerbi.build_dim_date("2024-01-01", "2024-01-05")
    assert dim["date_key"].is_unique
    assert dim.loc[0, "date_key"] == 20240101


def test_dim_date_fiscal_year_rolls_over_in_july():
    dim = export_for_powerbi.build_dim_date("2024-06-01", "2024-08-01")
    june_row = dim[dim["date"] == "2024-06-15"].iloc[0]
    july_row = dim[dim["date"] == "2024-07-15"].iloc[0]
    assert june_row["fiscal_year"] == 2024
    assert july_row["fiscal_year"] == 2025


def test_dim_date_month_sort_enables_chronological_ordering():
    dim = export_for_powerbi.build_dim_date("2024-01-01", "2024-12-31")
    by_month = dim.drop_duplicates("month").sort_values("month_sort")
    assert by_month["month_name"].tolist()[:3] == ["Jan", "Feb", "Mar"]


# ---------------------------------------------------------------------------
# validate_star_schema — tested against both a broken and a valid schema
# ---------------------------------------------------------------------------

def test_validate_star_schema_detects_broken_foreign_key():
    good_dim = pd.DataFrame({"product_id": [1, 2, 3]})
    broken_fact = pd.DataFrame({"product_id": [1, 2, 999]})  # 999 doesn't exist
    tables = {
        "dim_date": pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3), "date_key": [20240101, 20240102, 20240103]}),
        "dim_product": good_dim,
        "dim_supplier": pd.DataFrame({"supplier_id": [1]}),
        "dim_warehouse": pd.DataFrame({"warehouse_id": [1]}),
        "fact_sales": broken_fact.assign(date_key=20240101, warehouse_id=1),
        "fact_inventory": pd.DataFrame({"product_id": [1], "warehouse_id": [1]}),
        "fact_purchase_orders": pd.DataFrame({"supplier_id": [1], "date_key": [20240101]}),
    }
    assert export_for_powerbi.validate_star_schema(tables) is False


# ---------------------------------------------------------------------------
# End-to-end: generate -> load -> export -> validate, on a small hermetic dataset
# ---------------------------------------------------------------------------

@pytest.fixture
def small_export(tmp_path, monkeypatch):
    warehouses = generate_warehouses()
    suppliers = generate_suppliers(n=10)
    products = generate_products(suppliers, n=150)
    inventory = generate_inventory(products, warehouses)
    purchase_orders = generate_purchase_orders(products, suppliers)
    orders = generate_orders(warehouses, n=800)
    order_lines = generate_order_lines(orders, products)

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for name, df in {
        "warehouses": warehouses, "suppliers": suppliers, "products": products,
        "inventory": inventory, "purchase_orders": purchase_orders,
        "orders": orders, "order_lines": order_lines,
    }.items():
        df.to_csv(raw_dir / f"{name}.csv", index=False)

    db_path = tmp_path / "database" / "test.db"
    export_dir = tmp_path / "powerbi_export"

    monkeypatch.setattr(config, "RAW_DATA_DIR", raw_dir)
    monkeypatch.setattr(config, "DATABASE_DIR", db_path.parent)
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    # POWERBI_DIR is resolved at import time from config.DATA_DIR, so the
    # module attribute itself needs patching, not just config.DATA_DIR.
    monkeypatch.setattr(export_for_powerbi, "POWERBI_DIR", export_dir)

    load_to_db.main()
    export_for_powerbi.main()

    return export_dir


def test_export_produces_all_seven_tables(small_export):
    expected = {
        "dim_date", "dim_product", "dim_supplier", "dim_warehouse",
        "fact_sales", "fact_inventory", "fact_purchase_orders",
    }
    produced = {f.stem for f in small_export.glob("*.csv")}
    assert expected == produced


def test_export_drops_generation_artifact_columns(small_export):
    dim_product = pd.read_csv(small_export / "dim_product.csv")
    dim_supplier = pd.read_csv(small_export / "dim_supplier.csv")
    assert "popularity_score" not in dim_product.columns
    assert "base_reliability_score" not in dim_supplier.columns


def test_export_keys_all_resolve(small_export):
    fact_sales = pd.read_csv(small_export / "fact_sales.csv")
    dim_product = pd.read_csv(small_export / "dim_product.csv")
    dim_warehouse = pd.read_csv(small_export / "dim_warehouse.csv")
    dim_date = pd.read_csv(small_export / "dim_date.csv")

    assert fact_sales["product_id"].isin(dim_product["product_id"]).all()
    assert fact_sales["warehouse_id"].isin(dim_warehouse["warehouse_id"]).all()
    assert fact_sales["date_key"].isin(dim_date["date_key"]).all()


def test_export_abc_classes_are_valid(small_export):
    dim_product = pd.read_csv(small_export / "dim_product.csv")
    assert set(dim_product["abc_class"].unique()).issubset({"A", "B", "C"})
    assert dim_product["abc_class"].notna().all()


def test_export_risk_tiers_are_valid(small_export):
    dim_supplier = pd.read_csv(small_export / "dim_supplier.csv")
    valid_tiers = {"High Risk", "Monitor", "Preferred", "Insufficient Data"}
    assert set(dim_supplier["risk_tier"].unique()).issubset(valid_tiers)
