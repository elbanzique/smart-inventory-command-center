"""
Tests for sql/schema.sql and src/etl/load_to_db.py.

The schema tests use an in-memory SQLite database directly (fastest, no
file I/O). The loader tests generate a small dataset, write it to a
tmp_path, monkeypatch config's data paths to point there, and run the real
load_to_db.main() — this exercises the exact code path used in production
without ever touching the real data/ directory.
"""

import sqlite3
import sys
from pathlib import Path

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
from src.etl import load_to_db


# ---------------------------------------------------------------------------
# Schema-level tests (constraints work as declared, independent of any data)
# ---------------------------------------------------------------------------

def _fresh_schema_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    schema_sql = (config.SQL_DIR / "schema.sql").read_text()
    conn.executescript(schema_sql)
    return conn


def test_schema_creates_all_tables():
    conn = _fresh_schema_conn()
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    expected = {
        "warehouses", "suppliers", "products", "inventory",
        "purchase_orders", "orders", "order_lines",
    }
    assert expected.issubset(tables)


def test_schema_rejects_invalid_order_status():
    conn = _fresh_schema_conn()
    conn.execute("INSERT INTO warehouses VALUES (1, 'Test WH', 'West', 1000)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO orders (order_id, order_date, warehouse_id, customer_id, status) "
            "VALUES (1, '2024-01-01', 1, 1, 'Shipped')"
        )


def test_schema_enforces_foreign_keys():
    conn = _fresh_schema_conn()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO orders (order_id, order_date, warehouse_id, customer_id, status) "
            "VALUES (1, '2024-01-01', 999, 1, 'Delivered')"
        )


def test_schema_rejects_negative_price():
    conn = _fresh_schema_conn()
    conn.execute(
        "INSERT INTO suppliers VALUES (1, 'Test Supplier', 'Asia', 'Electronics', 0.9, 10)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO products (product_id, sku, category, unit_cost, unit_price, "
            "supplier_id, reorder_point, safety_stock, popularity_score) "
            "VALUES (1, 'TEST-001', 'Electronics', -5.0, 10.0, 1, 50, 20, 0.001)"
        )


# ---------------------------------------------------------------------------
# Loader tests (small dataset, hermetic tmp_path)
# ---------------------------------------------------------------------------

@pytest.fixture
def small_raw_csvs(tmp_path, monkeypatch):
    warehouses = generate_warehouses()
    suppliers = generate_suppliers(n=10)
    products = generate_products(suppliers, n=100)
    inventory = generate_inventory(products, warehouses)
    purchase_orders = generate_purchase_orders(products, suppliers)
    orders = generate_orders(warehouses, n=300)
    order_lines = generate_order_lines(orders, products)

    tables = {
        "warehouses": warehouses,
        "suppliers": suppliers,
        "products": products,
        "inventory": inventory,
        "purchase_orders": purchase_orders,
        "orders": orders,
        "order_lines": order_lines,
    }

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    for name, df in tables.items():
        df.to_csv(raw_dir / f"{name}.csv", index=False)

    db_dir = tmp_path / "database"
    db_path = db_dir / "test.db"

    monkeypatch.setattr(config, "RAW_DATA_DIR", raw_dir)
    monkeypatch.setattr(config, "DATABASE_DIR", db_dir)
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)

    return db_path, tables


def test_load_produces_expected_row_counts(small_raw_csvs):
    db_path, tables = small_raw_csvs
    load_to_db.main()

    conn = sqlite3.connect(db_path)
    try:
        for name, df in tables.items():
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            assert count == len(df), f"{name}: expected {len(df)}, got {count}"
    finally:
        conn.close()


def test_load_passes_foreign_key_check(small_raw_csvs):
    db_path, _ = small_raw_csvs
    load_to_db.main()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        assert conn.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        conn.close()


def test_load_is_idempotent_on_rerun(small_raw_csvs):
    """Running the loader twice should not fail or double-count rows."""
    db_path, tables = small_raw_csvs
    load_to_db.main()
    load_to_db.main()

    conn = sqlite3.connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM warehouses").fetchone()[0]
        assert count == len(tables["warehouses"])
    finally:
        conn.close()
