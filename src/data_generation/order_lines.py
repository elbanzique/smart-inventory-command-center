"""Generate the order_lines fact table (line items within each order)."""

import numpy as np
import pandas as pd

from src.data_generation.utils import get_rng


def generate_order_lines(orders_df: pd.DataFrame, products_df: pd.DataFrame) -> pd.DataFrame:
    """Return order line items for every order in orders_df.

    Line count per order
    ----------------------
    Most orders contain 1-2 line items, a smaller share contain 3-4 —
    calibrated to typical e-commerce basket sizes rather than a flat
    random count.

    Product selection (demand concentration)
    -------------------------------------------
    Products are drawn using each product's popularity_score as sampling
    weight (set back in products.py). The weight only actually shapes the
    data once it's used HERE, at the point products get sold — this is
    what produces the "20% of SKUs generate ~80% of revenue" pattern that
    Phase 4's revenue analysis will need to discover.

    Pricing
    --------
    unit_price_at_sale is drawn from the product's current catalog price
    with a small amount of noise (occasional discounts), which is the
    concrete justification for storing this as its own column rather than
    just joining to products.unit_price (see docs/architecture.md).
    """
    rng = get_rng()
    n_orders = len(orders_df)

    line_counts = rng.choice([1, 2, 3, 4], size=n_orders, p=[0.45, 0.30, 0.15, 0.10])
    total_lines = int(line_counts.sum())

    order_id_repeated = np.repeat(orders_df["order_id"].to_numpy(), line_counts)

    weights = products_df["popularity_score"].to_numpy()
    weights = weights / weights.sum()
    chosen_product_idx = rng.choice(len(products_df), size=total_lines, p=weights)
    product_ids = products_df["product_id"].to_numpy()[chosen_product_idx]
    catalog_prices = products_df["unit_price"].to_numpy()[chosen_product_idx]

    quantity = rng.choice([1, 2, 3, 4, 5], size=total_lines, p=[0.55, 0.20, 0.13, 0.07, 0.05])

    discount_roll = rng.random(total_lines)
    price_multiplier = np.where(
        discount_roll < 0.12, rng.uniform(0.80, 0.95, size=total_lines), 1.0
    )
    unit_price_at_sale = (catalog_prices * price_multiplier).round(2)

    order_lines = pd.DataFrame({
        "order_line_id": np.arange(1, total_lines + 1),
        "order_id": order_id_repeated,
        "product_id": product_ids,
        "quantity": quantity,
        "unit_price_at_sale": unit_price_at_sale,
    })
    return order_lines
