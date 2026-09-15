# Data Dictionary

This file is the single source of truth for every field in the project's
database. It is updated at the end of each phase as new tables/columns are
introduced. See `docs/architecture.md` for the full ERD and design rationale.

> Status: Phase 4 complete — data generated (Phase 2), loaded into SQLite
> with full constraints (Phase 3), and analyzed with 6 business-question
> SQL queries (Phase 4). See `sql/schema.sql` for DDL and `sql/queries/`
> for the analysis queries.

## warehouses (3 rows)
| Column | Type | Notes |
|---|---|---|
| warehouse_id | int | PK |
| name | str | |
| region | str | West / Central / East |
| capacity_units | int | drives warehouse's share of order volume |

## suppliers (50 rows)
| Column | Type | Notes |
|---|---|---|
| supplier_id | int | PK |
| name | str | Faker-generated company name |
| region | str | North America / Europe / Asia / South America |
| primary_category | str | **Addition beyond original Phase 1 design** — see docs/architecture.md §5 and suppliers.py docstring for rationale |
| base_reliability_score | float (0-1) | Beta(8,2)-distributed; mean ≈0.8, long left tail of unreliable suppliers |
| avg_lead_time_days | int | correlated with reliability (less reliable → longer/more variable) |

## products (5,000 rows)
| Column | Type | Notes |
|---|---|---|
| product_id | int | PK |
| sku | str | e.g. `ELE-00001` |
| category | str | one of 10 categories, uneven catalog share |
| unit_cost | float | category-calibrated cost range |
| unit_price | float | unit_cost × (1 + category margin) |
| supplier_id | int | FK → suppliers; matched to supplier's primary_category where possible |
| reorder_point | int | inventory threshold that should trigger a reorder |
| safety_stock | int | buffer stock; scales with demand percentile |
| popularity_score | float | **Simulation-only field** — Pareto/Zipf demand weight, not present in a real system. Drives order_lines product selection. Documented for transparency; see products.py docstring |

## inventory (15,000 rows — one per product × warehouse)
| Column | Type | Notes |
|---|---|---|
| warehouse_id | int | FK → warehouses |
| product_id | int | FK → products |
| quantity_on_hand | int | ~12% intentionally below reorder_point (stockout risk), ~10% at 4-8x safety_stock (dead stock), rest healthy |
| last_restock_date | date | within ~120 days of simulation end |

## purchase_orders (~25,000 rows)
| Column | Type | Notes |
|---|---|---|
| po_id | int | PK |
| supplier_id | int | FK → suppliers |
| product_id | int | FK → products |
| order_date | date | within simulation window |
| expected_delivery_date | date | order_date + supplier's avg_lead_time_days |
| actual_delivery_date | date, nullable | null = still in transit as of simulation "today" |
| quantity | int | scales with product demand percentile |

## orders (100,000 rows)
| Column | Type | Notes |
|---|---|---|
| order_id | int | PK |
| order_date | date | seasonally weighted (Nov/Dec peak) |
| warehouse_id | int | FK → warehouses; weighted by capacity_units |
| customer_id | int | ~35,000 unique customers, repeat purchases expected |
| status | str | Delivered (90%) / Cancelled (3%) / Returned (7%) |

## order_lines (~190,000 rows)
| Column | Type | Notes |
|---|---|---|
| order_line_id | int | PK |
| order_id | int | FK → orders |
| product_id | int | FK → products; selection weighted by popularity_score |
| quantity | int | 1-5 units, mostly 1 |
| unit_price_at_sale | float | catalog price, ~12% of lines discounted 5-20% |

## Calibration checks (run automatically by `src/data_generation/validate.py`)
- Purchase order on-time rate: ~90% (target band 75-97%, DataCo benchmark)
- Stockout-risk share of inventory: ~12% (target band 8-16%)
- Dead-stock share of inventory: ~10% (target band 6-14%)
- Revenue concentration: top 20% of products drive ≥55% of revenue (observed ~86%)

## SQLite schema (Phase 3)

`sql/schema.sql` implements the tables above with:
- `PRIMARY KEY` on every table's natural ID column (`inventory` uses a
  composite key on `(warehouse_id, product_id)` since it has no single ID)
- `FOREIGN KEY` constraints on every relationship, enforced via
  `PRAGMA foreign_keys = ON` (SQLite disables FK enforcement by default —
  easy to forget, and silently lets bad data in if you do)
- `CHECK` constraints mirroring the business rules already enforced during
  generation (e.g. `unit_price >= unit_cost`, `status IN (...)`) so the
  database itself — not just the Python generator — refuses invalid data
- Indexes on every foreign key column plus the two date columns
  (`orders.order_date`, `purchase_orders.order_date`) the Phase 4 queries
  filter and sort on most heavily
- All dates stored as `TEXT` in ISO-8601 (`YYYY-MM-DD`) — SQLite has no
  native date type; ISO-8601 text sorts correctly as a plain string and
  works directly with SQLite's `date()`/`julianday()` functions

`src/etl/load_to_db.py` rebuilds the database from scratch on every run
(drop + recreate + reload) rather than attempting incremental updates,
because the database is a derived artifact of the CSVs, not a hand-edited
source of truth — there's nothing to "merge."

## Analytical queries (Phase 4)

Each business question from the project brief has its own file under
`sql/queries/`, run in sequence by `src/analysis/run_queries.py`, which
prints a preview + a data-driven headline for each and saves the full
result to `data/processed/<query_name>.csv`.

| Query file | Business question | Key design choice |
|---|---|---|
| `warehouse_performance.sql` | Which warehouse performs best? | Revenue aggregated once per order in a CTE before joining to warehouses — joining `order_lines` directly would multiply status flags by line-item count and silently inflate return/cancellation rates |
| `top_revenue_products.sql` | Which products generate the most revenue? | Reports margin alongside revenue, since a high-revenue/low-margin product may matter less than it looks |
| `stockout_risk.sql` | Which SKUs are at risk of stockout? | Reported per (product, warehouse) — stockout is a per-location operational problem, not a company-wide average |
| `supplier_reliability.sql` | Which suppliers are unreliable? | Computed purely from `purchase_orders` history (actual vs. expected delivery dates) — deliberately ignores `suppliers.base_reliability_score`, which is a data-generation artifact a real analyst would never have access to |
| `dead_stock_value.sql` | How much value is tied up in dead stock? | Valued at `unit_cost`, not `unit_price` — dead stock represents capital already spent, not lost revenue |
| `reorder_recommendations.sql` | Which products should be reordered? | Sizes a concrete `recommended_order_quantity` (safety stock + 30-day sales velocity − on hand) at the (product, warehouse) grain — a bug caught during development: aggregating stock across all 3 warehouses before comparing to a single-warehouse `reorder_point` made almost every product look artificially healthy |
