"""
ETL: load synthetic CSVs from data/raw/ into the SQLite database defined by
sql/schema.sql.

Run from the project root:
    python -m src.etl.load_to_db
"""

import sqlite3
import time

import pandas as pd

from src import config

# Dependency order matters here even though foreign_keys enforcement is
# per-row, not deferred: a table can't successfully insert rows that
# reference a parent row which doesn't exist yet.
TABLE_LOAD_ORDER = [
    "warehouses",
    "suppliers",
    "products",
    "inventory",
    "purchase_orders",
    "orders",
    "order_lines",
]


def _create_schema(conn: sqlite3.Connection) -> None:
    schema_sql = (config.SQL_DIR / "schema.sql").read_text()
    conn.executescript(schema_sql)


def _load_table(conn: sqlite3.Connection, name: str) -> int:
    csv_path = config.RAW_DATA_DIR / f"{name}.csv"
    df = pd.read_csv(csv_path)
    # if_exists="append" because the table was already created by schema.sql
    # with the real constraints (PK/FK/CHECK) — we never want pandas to
    # infer and create its own looser table definition here.
    df.to_sql(name, conn, if_exists="append", index=False)
    return len(df)


def main() -> None:
    start = time.time()
    config.DATABASE_DIR.mkdir(parents=True, exist_ok=True)

    # The database is a derived artifact of CSVs + schema.sql, not a
    # hand-edited source of truth, so a full rebuild on every run is the
    # right behavior — there's no meaningful "incremental load" here.
    if config.DATABASE_PATH.exists():
        config.DATABASE_PATH.unlink()

    conn = sqlite3.connect(config.DATABASE_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")

        print("Creating schema...")
        _create_schema(conn)

        for table in TABLE_LOAD_ORDER:
            print(f"Loading {table}...")
            n = _load_table(conn, table)
            print(f"  loaded {n:,} rows into {table}")

        conn.commit()

        print("\nChecking foreign key integrity...")
        violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if violations:
            print(f"  FAILED: {len(violations)} foreign key violations found")
            for v in violations[:10]:
                print(f"    {v}")
            raise RuntimeError("Foreign key violations detected after load — see output above.")
        print("  PASS: no foreign key violations")

        print("\nRow counts per table:")
        for table in TABLE_LOAD_ORDER:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {count:,}")

    finally:
        conn.close()

    elapsed = time.time() - start
    try:
        db_display = config.DATABASE_PATH.relative_to(config.PROJECT_ROOT)
    except ValueError:
        # DATABASE_PATH isn't under PROJECT_ROOT — e.g. tests monkeypatch it
        # to a tmp_path. Fall back to the absolute path rather than crashing
        # on what's just a cosmetic print statement.
        db_display = config.DATABASE_PATH
    print(f"\nDone in {elapsed:.1f}s. Database at {db_display}")


if __name__ == "__main__":
    main()
