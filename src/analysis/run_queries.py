"""
Runs the core business-question SQL queries (sql/queries/*.sql) against the
SQLite database and saves each result to data/processed/ as CSV.

Run from the project root (after src/etl/load_to_db.py has been run):
    python -m src.analysis.run_queries
"""

import sqlite3
from pathlib import Path

import pandas as pd

from src import config

# (query filename, human-readable title, headline function).
# Each headline is computed from the actual query result at runtime — not
# a hardcoded guess — so it stays correct even if the underlying data
# changes (e.g. after Phase 2's generator is re-run or re-tuned).
QUERIES = [
    (
        "warehouse_performance.sql",
        "Which warehouse performs best?",
        lambda df: (
            f"Top performer by revenue: {df.iloc[0]['warehouse_name']} "
            f"(${df.iloc[0]['total_revenue']:,.0f}, "
            f"{df.iloc[0]['return_rate_pct']}% return rate)."
        ),
    ),
    (
        "top_revenue_products.sql",
        "Which products generate the most revenue?",
        lambda df: (
            f"Top SKU: {df.iloc[0]['sku']} ({df.iloc[0]['category']}) — "
            f"${df.iloc[0]['total_revenue']:,.0f} from {int(df.iloc[0]['units_sold'])} units sold."
        ),
    ),
    (
        "stockout_risk.sql",
        "Which SKUs are at risk of stockout?",
        lambda df: (
            f"Showing the {len(df)} worst product-warehouse positions currently "
            f"below reorder point (out of the full at-risk population)."
        ),
    ),
    (
        "supplier_reliability.sql",
        "Which suppliers are unreliable?",
        lambda df: (
            f"Least reliable: {df.iloc[0]['supplier_name']} — "
            f"{df.iloc[0]['late_delivery_rate_pct']}% late across "
            f"{int(df.iloc[0]['total_purchase_orders'])} purchase orders."
        ),
    ),
    (
        "dead_stock_value.sql",
        "How much inventory value is tied up in dead stock?",
        lambda df: f"Total dead stock value across all categories: ${df['dead_stock_value'].sum():,.0f}.",
    ),
    (
        "reorder_recommendations.sql",
        "Which products should be reordered?",
        lambda df: (
            f"{len(df)} products shown need reordering; largest recommendation: "
            f"{int(df.iloc[0]['recommended_order_quantity'])} units of {df.iloc[0]['sku']}."
        ),
    ),
]


def run_query(conn: sqlite3.Connection, filename: str) -> pd.DataFrame:
    query = (config.SQL_QUERIES_DIR / filename).read_text()
    return pd.read_sql_query(query, conn)


def main() -> None:
    if not config.DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"No database found at {config.DATABASE_PATH}. "
            "Run `python -m src.etl.load_to_db` first."
        )

    config.PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)

    try:
        for filename, title, headline_fn in QUERIES:
            print(f"\n{'=' * 78}")
            print(title)
            print("=" * 78)

            df = run_query(conn, filename)

            out_path = config.PROCESSED_DATA_DIR / f"{Path(filename).stem}.csv"
            df.to_csv(out_path, index=False)

            if len(df) == 0:
                print("No rows returned.")
                continue

            print(df.head(10).to_string(index=False))
            if len(df) > 10:
                rel_path = out_path.relative_to(config.PROJECT_ROOT)
                print(f"... ({len(df)} rows total — full result saved to {rel_path})")

            print(f"\n>> {headline_fn(df)}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
