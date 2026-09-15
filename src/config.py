"""
Central configuration for the Smart Inventory Command Center project.

Why this file exists:
Every script in this project (data generation, ETL, analysis) needs to know
where files live and agree on the same business constants (number of
warehouses, suppliers, products...). Hardcoding these in every script means
that changing "5000 products" to "8000 products" later requires editing
10 files and risking inconsistency. Centralizing them here means we change
one value in one place.
"""

from pathlib import Path

# --- Project root & folder paths -------------------------------------------------
# PROJECT_ROOT resolves to the repo root regardless of which script imports this,
# as long as this file stays at <root>/src/config.py.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
DATABASE_DIR = DATA_DIR / "database"

SQL_DIR = PROJECT_ROOT / "sql"
SQL_QUERIES_DIR = SQL_DIR / "queries"

DATABASE_PATH = DATABASE_DIR / "novalog.db"

# --- Business scale constants (the "size" of our fictional company) -------------
N_WAREHOUSES = 3
N_SUPPLIERS = 50
N_PRODUCTS = 5_000
N_ORDERS = 100_000

# --- Reproducibility --------------------------------------------------------------
# A fixed random seed means anyone who clones this repo and re-runs the
# generation scripts gets IDENTICAL synthetic data. This is essential for a
# portfolio project: your README screenshots and Power BI numbers must match
# what a recruiter sees when they run your code themselves.
RANDOM_SEED = 42

# --- Simulation time window -------------------------------------------------------
# Two years of order history gives us enough data for seasonality analysis
# (e.g. holiday peaks) without generating an unrealistic amount of data.
SIMULATION_START_DATE = "2024-01-01"
SIMULATION_END_DATE = "2025-12-31"
SIMULATION_YEARS = 2

# --- Demand shape constants -------------------------------------------------------
# These describe the average basket and are used in TWO places that must
# agree with each other:
#   1. order_lines.py, when actually generating line items
#   2. products.py, to derive each SKU's expected demand BEFORE any orders
#      exist, so that safety_stock and reorder_point can be sized against
#      real expected demand rather than an arbitrary scale.
#
# Why this matters: sizing stock thresholds independently of demand
# produces an internally inconsistent dataset. An early version of this
# project sized safety_stock on a rank percentile, which left the median
# SKU holding ~260 units while selling ~8 units a year — an inventory
# turnover of 0.04x against a realistic 4-8x. The bug was invisible to
# every single-table validation check and only surfaced once turnover
# (which cross-references sales against inventory) was computed.
AVG_LINES_PER_ORDER = 1.9
AVG_UNITS_PER_LINE = 1.86

# Total units sold per year across the whole catalog, derived from the
# constants above. Individual SKUs claim a share of this proportional to
# their popularity weight.
TOTAL_ANNUAL_UNITS = int(N_ORDERS * AVG_LINES_PER_ORDER * AVG_UNITS_PER_LINE / SIMULATION_YEARS)

# Safety stock covers this multiple of lead-time demand, on top of the
# lead-time demand itself. 0.5 is a moderate service-level posture.
SAFETY_STOCK_FACTOR = 0.5

# Even a near-zero-demand SKU carries a couple of units on the shelf.
MIN_SAFETY_STOCK = 2
