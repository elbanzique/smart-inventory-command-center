"""Generate the inventory fact table (current stock snapshot per product per warehouse)."""

import numpy as np
import pandas as pd

from src import config
from src.data_generation.utils import get_rng


def generate_inventory(products_df: pd.DataFrame, warehouses_df: pd.DataFrame) -> pd.DataFrame:
    """Return one inventory row per (warehouse, product) combination.

    Stock-level design
    -------------------
    quantity_on_hand is generated relative to each product's reorder_point
    and safety_stock, with intentional variance across three buckets:
      - ~12% of rows land BELOW reorder_point (stockout-risk candidates —
        this is what Phase 4's "which SKUs are at risk of stockout?"
        analysis needs to find)
      - ~10% land at 4-8x safety_stock (dead-stock candidates — capital
        tied up in slow-moving inventory, for Phase 5)
      - the remaining ~78% sit in a healthy band between the two

    This mirrors the real shape of inventory data: most SKUs are managed
    fine, with a meaningful minority in each problem category. A uniform
    spread would make the business questions trivial or meaningless to ask.
    """
    rng = get_rng()
    n_products = len(products_df)
    n_warehouses = len(warehouses_df)

    product_ids = np.repeat(products_df["product_id"].to_numpy(), n_warehouses)
    warehouse_ids = np.tile(warehouses_df["warehouse_id"].to_numpy(), n_products)
    reorder_points = np.repeat(products_df["reorder_point"].to_numpy(), n_warehouses)
    safety_stocks = np.repeat(products_df["safety_stock"].to_numpy(), n_warehouses)

    n_rows = len(product_ids)
    bucket_roll = rng.random(n_rows)

    quantity = np.empty(n_rows, dtype=int)

    stockout_mask = bucket_roll < 0.12
    dead_stock_mask = (bucket_roll >= 0.12) & (bucket_roll < 0.22)
    healthy_mask = bucket_roll >= 0.22

    quantity[stockout_mask] = (
        reorder_points[stockout_mask] * rng.uniform(0.1, 0.95, size=int(stockout_mask.sum()))
    ).astype(int)
    quantity[dead_stock_mask] = (
        safety_stocks[dead_stock_mask] * rng.uniform(4, 8, size=int(dead_stock_mask.sum()))
    ).astype(int)
    # Anchored to reorder_point (not safety_stock) with a strictly positive
    # offset, so "healthy" rows never accidentally fall back below the
    # reorder threshold — otherwise the stockout-risk bucket would silently
    # balloon past its intended ~12% share (this is exactly what happened
    # in an earlier version of this formula; keep it anchored this way).
    quantity[healthy_mask] = (
        reorder_points[healthy_mask]
        + safety_stocks[healthy_mask] * rng.uniform(0.1, 2.0, size=int(healthy_mask.sum()))
    ).astype(int)
    quantity = np.clip(quantity, 0, None)

    last_restock_offset_days = rng.integers(1, 120, size=n_rows)
    sim_end = pd.Timestamp(config.SIMULATION_END_DATE)
    last_restock_date = sim_end - pd.to_timedelta(last_restock_offset_days, unit="D")

    inventory = pd.DataFrame({
        "warehouse_id": warehouse_ids,
        "product_id": product_ids,
        "quantity_on_hand": quantity,
        "last_restock_date": last_restock_date.strftime("%Y-%m-%d"),
    })
    return inventory
