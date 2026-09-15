"""
Shared database access for the analysis layer.

Every analysis module needs the same few base tables. Loading them through
one place means connection handling, the "did you run the ETL yet?" check,
and the enriched order-line join all live in exactly one spot instead of
being copy-pasted across modules.
"""

import sqlite3
from contextlib import contextmanager

import pandas as pd

from src import config


@contextmanager
def get_connection():
    """Yield a SQLite connection, closing it even if the caller raises."""
    if not config.DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"No database found at {config.DATABASE_PATH}. "
            "Run `python -m src.etl.load_to_db` first."
        )
    conn = sqlite3.connect(config.DATABASE_PATH)
    try:
        yield conn
    finally:
        conn.close()


def load_table(name: str) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(f"SELECT * FROM {name}", conn)


def load_sales_detail() -> pd.DataFrame:
    """Return order lines enriched with order, product, and warehouse context.

    This is the workhorse dataset for most of the analysis layer, so the
    join happens once in SQL (where the indexes are) rather than being
    reassembled with several pandas merges in every module that needs it.

    Only 'Delivered' orders are included: cancelled and returned orders
    didn't produce realized revenue, and counting them would overstate
    sales performance. Modules that specifically need to analyze returns
    (e.g. warehouse quality metrics) load the orders table directly.
    """
    query = """
        SELECT
            ol.order_line_id,
            ol.order_id,
            ol.product_id,
            ol.quantity,
            ol.unit_price_at_sale,
            ol.quantity * ol.unit_price_at_sale                      AS line_revenue,
            ol.quantity * (ol.unit_price_at_sale - p.unit_cost)      AS line_margin,
            ol.quantity * p.unit_cost                                AS line_cogs,
            o.order_date,
            o.warehouse_id,
            o.customer_id,
            o.status,
            p.sku,
            p.category,
            p.unit_cost,
            p.supplier_id,
            w.name                                                    AS warehouse_name,
            w.region                                                  AS warehouse_region
        FROM order_lines ol
        JOIN orders o     ON o.order_id     = ol.order_id
        JOIN products p   ON p.product_id   = ol.product_id
        JOIN warehouses w ON w.warehouse_id = o.warehouse_id
        WHERE o.status = 'Delivered'
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    df["order_date"] = pd.to_datetime(df["order_date"])
    return df


def load_inventory_detail() -> pd.DataFrame:
    """Return inventory positions enriched with product and warehouse context."""
    query = """
        SELECT
            i.warehouse_id,
            i.product_id,
            i.quantity_on_hand,
            i.last_restock_date,
            i.quantity_on_hand * p.unit_cost AS inventory_value,
            p.sku,
            p.category,
            p.unit_cost,
            p.unit_price,
            p.reorder_point,
            p.safety_stock,
            p.supplier_id,
            w.name                            AS warehouse_name,
            w.region                          AS warehouse_region
        FROM inventory i
        JOIN products p   ON p.product_id   = i.product_id
        JOIN warehouses w ON w.warehouse_id = i.warehouse_id
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)
    df["last_restock_date"] = pd.to_datetime(df["last_restock_date"])
    return df
