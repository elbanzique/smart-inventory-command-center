# Architecture — Smart Inventory Command Center

## 1. Business context

NovaLog Distribution is a fictional e-commerce logistics company operating
3 warehouses, sourcing from 50 suppliers, selling 5,000 products, and
processing ~100,000 customer orders over a 2-year window (2024-01-01 to
2025-12-31).

## 2. Pipeline overview

```
[Python data generation] --> [raw CSVs] --> [ETL / load] --> [SQLite DB]
                                                                   |
                                                                   v
                                          [SQL analysis]  <---  [Python/Pandas analysis]
                                                                   |
                                                                   v
                                                             [Power BI dashboard]
```

Each stage's output is the next stage's input. Raw CSVs are treated as an
immutable "source system" snapshot — once generated, we never hand-edit them;
if something needs to change, we change the generation script and regenerate.

## 3. Entity-relationship model

### Dimension tables

**warehouses**
| Column | Type | Notes |
|---|---|---|
| warehouse_id | INTEGER PK | |
| name | TEXT | e.g. "West Coast DC" |
| region | TEXT | |
| capacity_units | INTEGER | max stock units the warehouse can hold |

**suppliers**
| Column | Type | Notes |
|---|---|---|
| supplier_id | INTEGER PK | |
| name | TEXT | |
| region | TEXT | |
| base_reliability_score | REAL | 0-1, seeds realistic late-delivery behavior |
| avg_lead_time_days | INTEGER | contractual lead time |

**products**
| Column | Type | Notes |
|---|---|---|
| product_id | INTEGER PK | |
| sku | TEXT | unique stock-keeping unit code |
| category | TEXT | e.g. Electronics, Home, Apparel |
| unit_cost | REAL | cost to NovaLog per unit |
| unit_price | REAL | sale price to customer |
| supplier_id | INTEGER FK -> suppliers | primary supplier |
| reorder_point | INTEGER | inventory threshold that triggers reorder |
| safety_stock | INTEGER | buffer stock to absorb demand variability |

### Fact / transactional tables

**inventory** (current stock snapshot per product per warehouse)
| Column | Type | Notes |
|---|---|---|
| warehouse_id | INTEGER FK | |
| product_id | INTEGER FK | |
| quantity_on_hand | INTEGER | |
| last_restock_date | DATE | |

**orders**
| Column | Type | Notes |
|---|---|---|
| order_id | INTEGER PK | |
| order_date | DATE | |
| warehouse_id | INTEGER FK | fulfilling warehouse |
| customer_id | INTEGER | synthetic customer identifier |
| status | TEXT | Delivered / Cancelled / Returned |

**order_lines**
| Column | Type | Notes |
|---|---|---|
| order_line_id | INTEGER PK | |
| order_id | INTEGER FK | |
| product_id | INTEGER FK | |
| quantity | INTEGER | |
| unit_price_at_sale | REAL | price at time of sale (may differ from current catalog price) |

**purchase_orders** (supplier replenishment events)
| Column | Type | Notes |
|---|---|---|
| po_id | INTEGER PK | |
| supplier_id | INTEGER FK | |
| product_id | INTEGER FK | |
| order_date | DATE | date PO was placed |
| expected_delivery_date | DATE | |
| actual_delivery_date | DATE | NULL if not yet delivered |
| quantity | INTEGER | |

## 4. Design decisions & rationale

- **Normalized OLTP-style schema, not a pre-built star schema.** Real
  companies don't hand you a data warehouse — they hand you operational
  tables. Modeling it this way lets the project demonstrate the full skill:
  designing a data model, then transforming it into analysis-ready shapes
  (which happens in the SQL/analysis layer, not the raw schema).
- **`unit_price_at_sale` is stored separately from `products.unit_price`.**
  Prices change over time; storing the historical price on the order line is
  what real transactional systems do, and it matters for accurate revenue
  reporting.
- **`purchase_orders` has both expected and actual delivery dates.** This is
  the foundation for supplier reliability scoring (Phase 5) — reliability is
  computed from behavior (actual vs. promised), not from a hardcoded label.
- **Reorder logic lives on `products` (reorder_point, safety_stock), not
  hardcoded in queries.** This mirrors real inventory management systems and
  lets our "should we reorder?" logic be a simple, explainable comparison
  against `inventory.quantity_on_hand`.

## 5. Data realism strategy — reference-informed simulation

Rather than generating purely random synthetic data, we calibrate our
generator's statistical distributions against publicly documented patterns
from the **DataCo Smart Supply Chain for Big Data Analysis** dataset
(Kaggle, ~18,000 orders, 50+ features — a widely used reference dataset in
supply chain analytics). We do not import this dataset directly (Kaggle
requires authenticated API access not available in this environment);
instead we use its published statistical summaries as calibration targets:

- **On-time delivery rate ≈ 90%** (≈10% late deliveries) — used to calibrate
  `purchase_orders.actual_delivery_date` vs `expected_delivery_date`.
- **Late-delivery risk is skewed by shipping/supplier**, not uniform — a
  minority of suppliers/shipping modes account for most delays. We model
  supplier reliability as a skewed distribution (most suppliers reliable,
  a long tail of unreliable ones) rather than uniform randomness.
- **Revenue concentration follows a Pareto-like pattern** (a small share of
  SKUs drive most revenue) — standard in retail/e-commerce and consistent
  with category-level sales skew observed in the reference dataset.
- **Seasonal order volume** peaks around known e-commerce high seasons
  (e.g. Nov–Dec) and dips mid-year.
- **Order status mix** (Delivered / Cancelled / Returned) is set to
  realistic e-commerce norms (small single-digit percentages for
  cancellations and returns).

This "reference-informed simulation" approach is documented here explicitly
so the sourcing and reasoning is transparent and reproducible — every
calibration choice in `src/data_generation/` should trace back to a
rationale in this section.

## 6. Why SQLite

SQLite requires no server setup, ships as a single file, and is fully
supported by Python's standard library. For a portfolio project, this
removes friction for anyone reviewing the code (no DB server to install)
while still letting us write and showcase real SQL.
