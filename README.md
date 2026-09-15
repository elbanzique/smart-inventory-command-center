# Smart Inventory Command Center

An end-to-end logistics analytics platform built for **NovaLog Distribution**,
a fictional e-commerce logistics company with 3 warehouses, 50 suppliers,
5,000 products, and ~100,000 customer orders.

This project simulates a realistic business dataset and builds a full
analytics pipeline — from raw data generation through SQL analysis to a
Power BI dashboard — to answer the operational questions a supply chain
data analyst is asked in practice.

## Business questions answered

- Which warehouse performs best?
- Which products generate the most revenue?
- Which SKUs are at risk of stockout?
- Which suppliers are unreliable?
- How much inventory value is tied up in dead stock?
- Which products should be reordered?

## Tech stack

- **SQL (SQLite)** — schema design, analytical queries
- **Python / Pandas / NumPy** — data generation, transformation, analysis
- **Matplotlib** — exploratory visualization
- **Power BI** — final interactive dashboard
- **Git & GitHub** — version control

## Project status

Built incrementally in numbered phases (see `docs/` for design notes as
they're added). Current phase: **Phase 1 — project setup & data architecture**.

| Phase | Description | Status |
|---|---|---|
| 1 | Project setup, architecture & data model design | Done |
| 2 | Synthetic data generation | Done |
| 3 | ETL — load into SQLite | Done |
| 4 | SQL analysis — core business questions | Done |
| 5 | Python/Pandas deep-dive analysis (supplier reliability, dead stock) | Pending |
| 6 | Power BI dashboard | Pending |
| 7 | Documentation, tests & polish | Pending |

## Repository structure

```
smart-inventory-command-center/
├── data/             # raw/processed data & SQLite database (gitignored)
├── docs/             # architecture & data dictionary
├── src/              # Python source: config, data generation, ETL, analysis
├── sql/              # DDL schema + analytical queries
├── notebooks/        # exploratory analysis
├── powerbi/          # Power BI dashboard file
└── tests/            # data validation tests
```

## Setup

```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Generating the synthetic dataset

```bash
python -m src.data_generation.generate_all
```

This writes 7 CSVs to `data/raw/` (warehouses, suppliers, products,
inventory, purchase_orders, orders, order_lines) and runs an automatic
validation report (referential integrity, positivity constraints, and
calibration checks against the realism targets in
`docs/data_dictionary.md`). Everything is seeded (`config.RANDOM_SEED`),
so re-running this produces byte-identical output.

Run the test suite with:

```bash
pytest
```

## Loading into SQLite and running the analysis

```bash
python -m src.etl.load_to_db      # builds sql/schema.sql, loads all CSVs, verifies FK integrity
python -m src.analysis.run_queries  # runs all 6 business-question queries, saves results to data/processed/
```

Each business question has its own file under `sql/queries/` (see
`docs/data_dictionary.md` for the full list and design rationale behind
each one).

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full data model
(ERD), pipeline diagram, and design rationale.
