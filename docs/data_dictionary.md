# Data Dictionary

This file is the single source of truth for every field in the project's
database. It is updated at the end of each phase as new tables/columns are
introduced. See `docs/architecture.md` for the full ERD and design rationale.

> Status: Phase 2 complete — synthetic data generated to `data/raw/*.csv`.
> Not yet loaded into SQLite (that's Phase 3, `sql/schema.sql`).

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
