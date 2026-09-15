"""Generate the products dimension table."""

import numpy as np
import pandas as pd

from src import config
from src.data_generation.utils import (
    CATEGORIES,
    CATEGORY_CATALOG_WEIGHTS,
    CATEGORY_NAMES,
    get_rng,
    pareto_weights,
)


def generate_products(suppliers_df: pd.DataFrame, n: int = config.N_PRODUCTS) -> pd.DataFrame:
    """Return the products dimension table.

    Category & pricing
    --------------------
    Categories are assigned with deliberately uneven weights (see
    CATEGORY_CATALOG_WEIGHTS). Within each category, unit_cost and
    unit_price are drawn from that category's realistic cost/margin ranges
    (CATEGORIES in utils.py), so a $6,000-margin toy or a $2-cost laptop
    never appears.

    Supplier assignment
    --------------------
    Each product is assigned a supplier whose `primary_category` matches
    the product's category where possible, falling back to any supplier
    if no category match exists. This keeps the products<->suppliers
    relationship business-plausible rather than arbitrary.

    popularity_score (simulation-only field)
    ------------------------------------------
    This column does NOT exist in a real operational system. It's an
    internal demand-concentration weight (Pareto/Zipf-distributed) that
    order_lines.py uses later to decide how often each product actually
    gets purchased, producing the standard retail pattern where ~20% of
    SKUs generate ~80% of revenue. It's kept in the CSV for transparency
    and documented as a synthetic field in docs/data_dictionary.md — real
    systems don't have this column, but a real analyst reverse-engineers
    something very similar from sales history (that's exactly what Phase 5
    will do independently, so this can also serve as a hidden "answer key"
    to sanity-check that later analysis).

    reorder_point / safety_stock — derived from expected demand
    --------------------------------------------------------------
    These use the standard inventory-management formulas rather than an
    arbitrary scale:

        lead_time_demand = daily_demand x supplier_lead_time_days
        safety_stock     = lead_time_demand x SAFETY_STOCK_FACTOR
        reorder_point    = lead_time_demand + safety_stock

    daily_demand is derived analytically from the product's popularity
    share of config.TOTAL_ANNUAL_UNITS, divided across the warehouse
    network (these thresholds are per-warehouse — see stockout_risk.sql).
    We can compute this *before* any orders exist because popularity_score
    is exactly the weight order_lines.py will later use to select products.

    Why this isn't optional: an earlier version sized safety_stock on a
    rank percentile (20 + percentile x 480), disconnected from demand. The
    result was a median SKU holding ~260 units while selling ~8 units a
    year — inventory turnover of 0.04x against a realistic 4-8x, and 96%
    of all inventory classifiable as dead or slow-moving. Every
    single-table validation passed; the bug only appeared once turnover
    cross-referenced sales against inventory.
    """
    rng = get_rng("products")

    categories = rng.choice(
        list(CATEGORY_CATALOG_WEIGHTS.keys()),
        size=n,
        p=list(CATEGORY_CATALOG_WEIGHTS.values()),
    )

    unit_cost = np.empty(n)
    unit_price = np.empty(n)
    for cat in CATEGORY_NAMES:
        mask = categories == cat
        count = int(mask.sum())
        if count == 0:
            continue
        cost_lo, cost_hi = CATEGORIES[cat]["cost_range"]
        margin_lo, margin_hi = CATEGORIES[cat]["margin_range"]
        costs = rng.uniform(cost_lo, cost_hi, size=count)
        margins = rng.uniform(margin_lo, margin_hi, size=count)
        unit_cost[mask] = costs
        unit_price[mask] = costs * (1 + margins)

    supplier_pool_by_category = {
        cat: suppliers_df.loc[suppliers_df["primary_category"] == cat, "supplier_id"].to_numpy()
        for cat in CATEGORY_NAMES
    }
    all_supplier_ids = suppliers_df["supplier_id"].to_numpy()
    supplier_ids = np.empty(n, dtype=int)
    for cat in CATEGORY_NAMES:
        mask = categories == cat
        count = int(mask.sum())
        if count == 0:
            continue
        pool = supplier_pool_by_category[cat]
        if len(pool) == 0:
            pool = all_supplier_ids
        supplier_ids[mask] = rng.choice(pool, size=count)

    popularity_score = pareto_weights(n)

    # Expected demand per SKU, derived analytically from its popularity
    # share. Divided by the warehouse count because reorder_point and
    # safety_stock are per-warehouse thresholds.
    expected_annual_units = popularity_score * config.TOTAL_ANNUAL_UNITS
    daily_demand_per_warehouse = expected_annual_units / 365 / config.N_WAREHOUSES

    supplier_lead_times = (
        suppliers_df.set_index("supplier_id")["avg_lead_time_days"].loc[supplier_ids].to_numpy()
    )
    lead_time_demand = daily_demand_per_warehouse * supplier_lead_times

    safety_stock = np.maximum(
        np.ceil(lead_time_demand * config.SAFETY_STOCK_FACTOR), config.MIN_SAFETY_STOCK
    ).astype(int)
    reorder_point = np.maximum(
        np.ceil(lead_time_demand + safety_stock), safety_stock + 1
    ).astype(int)

    sku = [f"{cat[:3].upper()}-{i + 1:05d}" for i, cat in enumerate(categories)]

    products = pd.DataFrame({
        "product_id": np.arange(1, n + 1),
        "sku": sku,
        "category": categories,
        "unit_cost": unit_cost.round(2),
        "unit_price": unit_price.round(2),
        "supplier_id": supplier_ids,
        "reorder_point": reorder_point,
        "safety_stock": safety_stock,
        "popularity_score": popularity_score.round(8),
    })
    return products
