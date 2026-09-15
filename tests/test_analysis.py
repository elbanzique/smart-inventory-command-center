"""
Tests for sql/queries/*.sql and src/analysis/run_queries.py.

Each query is executed against a small, hermetic in-memory-backed database
(built from the same small-dataset fixture pattern used in test_etl.py) to
confirm it's valid SQL, returns the expected columns, and doesn't blow up
on edge cases like a product with zero sales history.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.analysis.run_queries import QUERIES, run_query
from src.data_generation.inventory import generate_inventory
from src.data_generation.order_lines import generate_order_lines
from src.data_generation.orders import generate_orders
from src.data_generation.products import generate_products
from src.data_generation.purchase_orders import generate_purchase_orders
from src.data_generation.suppliers import generate_suppliers
from src.data_generation.warehouses import generate_warehouses
from src.etl import load_to_db


@pytest.fixture
def small_db(tmp_path, monkeypatch):
    """Generate a small dataset, load it through the real ETL pipeline, and
    return an open connection to the resulting hermetic SQLite database."""
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
    monkeypatch.setattr(config, "RAW_DATA_DIR", raw_dir)
    monkeypatch.setattr(config, "DATABASE_DIR", db_path.parent)
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)

    load_to_db.main()

    conn = sqlite3.connect(db_path)
    yield conn
    conn.close()


EXPECTED_COLUMNS = {
    "warehouse_performance.sql": {
        "warehouse_id", "warehouse_name", "region", "total_orders",
        "total_revenue", "avg_order_value", "return_rate_pct", "cancellation_rate_pct",
    },
    "top_revenue_products.sql": {
        "product_id", "sku", "category", "orders_containing_product",
        "units_sold", "total_revenue", "total_margin",
    },
    "stockout_risk.sql": {
        "product_id", "sku", "category", "warehouse_name",
        "quantity_on_hand", "reorder_point", "safety_stock", "pct_of_reorder_point",
    },
    "supplier_reliability.sql": {
        "supplier_id", "supplier_name", "region", "primary_category",
        "total_purchase_orders", "delivered_pos", "late_delivery_rate_pct", "avg_delay_days",
    },
    "dead_stock_value.sql": {
        "category", "dead_stock_positions", "total_units_tied_up", "dead_stock_value",
    },
    "reorder_recommendations.sql": {
        "product_id", "sku", "category", "warehouse_name", "quantity_on_hand",
        "reorder_point", "safety_stock", "units_sold_last_30_days",
        "avg_daily_demand", "recommended_order_quantity",
    },
}


@pytest.mark.parametrize("filename", [q[0] for q in QUERIES])
def test_query_executes_and_has_expected_columns(small_db, filename):
    df = run_query(small_db, filename)
    assert set(df.columns) == EXPECTED_COLUMNS[filename]


def test_warehouse_performance_revenue_matches_manual_total(small_db):
    """Sanity-check the query's total_revenue against an independent, plain
    Python computation from the raw tables — catches silent double-counting
    bugs (e.g. joining order_lines directly without pre-aggregating)."""
    import pandas as pd

    df = run_query(small_db, "warehouse_performance.sql")

    orders = pd.read_sql_query("SELECT * FROM orders", small_db)
    order_lines = pd.read_sql_query("SELECT * FROM order_lines", small_db)
    order_lines["line_revenue"] = order_lines["quantity"] * order_lines["unit_price_at_sale"]
    order_revenue = order_lines.groupby("order_id")["line_revenue"].sum().reset_index()
    merged = orders.merge(order_revenue, on="order_id")
    manual_total = merged["line_revenue"].sum()

    assert df["total_revenue"].sum() == pytest.approx(manual_total, rel=1e-6)


def test_stockout_risk_rows_are_actually_below_reorder_point(small_db):
    df = run_query(small_db, "stockout_risk.sql")
    if len(df) > 0:
        assert (df["quantity_on_hand"] < df["reorder_point"]).all()


def test_dead_stock_positions_meet_the_4x_threshold(small_db):
    df = run_query(small_db, "dead_stock_value.sql")
    # Cross-check against a from-scratch calculation on the raw tables.
    import pandas as pd

    inventory = pd.read_sql_query("SELECT * FROM inventory", small_db)
    products = pd.read_sql_query("SELECT * FROM products", small_db)
    merged = inventory.merge(products, on="product_id")
    expected_value = merged.loc[
        merged["quantity_on_hand"] >= merged["safety_stock"] * 4, "quantity_on_hand"
    ].sum()
    assert df["total_units_tied_up"].sum() == expected_value
