"""
Shared utilities for synthetic data generation.

Centralizing randomness, category definitions, and seasonal patterns here
means every generator module (warehouses, suppliers, products, ...) draws
from the same calibrated assumptions instead of each script reinventing its
own ad-hoc randomness. See docs/architecture.md, section 5, for why these
specific calibrations were chosen (reference-informed simulation).
"""

import numpy as np
import pandas as pd
from faker import Faker

from src import config


def get_rng(seed: int = config.RANDOM_SEED) -> np.random.Generator:
    """Return a fresh, seeded numpy random Generator.

    We use numpy's modern Generator API (np.random.default_rng) rather than
    the legacy global np.random.seed(). Every generator function calls this
    with the same default seed, so re-running the full pipeline from a
    clean checkout always reproduces byte-identical CSVs — a hard
    requirement for a portfolio project (your README/Power BI screenshots
    must match what a reviewer sees when they run the code themselves).
    """
    return np.random.default_rng(seed)


def get_faker(seed: int = config.RANDOM_SEED) -> Faker:
    """Return a Faker instance seeded for reproducible fake names/companies."""
    fake = Faker()
    Faker.seed(seed)
    return fake


# ---------------------------------------------------------------------------
# Product categories
# ---------------------------------------------------------------------------
# Each category carries a realistic (unit_cost_range, margin_range) so that
# generated prices resemble real retail economics instead of pure noise.
# margin = (unit_price - unit_cost) / unit_cost
CATEGORIES = {
    "Electronics": {"cost_range": (15, 500), "margin_range": (0.15, 0.40)},
    "Home & Kitchen": {"cost_range": (5, 200), "margin_range": (0.30, 0.70)},
    "Apparel": {"cost_range": (4, 80), "margin_range": (0.50, 1.20)},
    "Sports & Outdoors": {"cost_range": (8, 300), "margin_range": (0.25, 0.60)},
    "Toys & Games": {"cost_range": (3, 100), "margin_range": (0.30, 0.80)},
    "Office Supplies": {"cost_range": (2, 150), "margin_range": (0.20, 0.50)},
    "Beauty & Personal Care": {"cost_range": (3, 90), "margin_range": (0.40, 1.00)},
    "Automotive": {"cost_range": (10, 400), "margin_range": (0.20, 0.45)},
    "Grocery": {"cost_range": (1, 40), "margin_range": (0.10, 0.30)},
    "Books & Media": {"cost_range": (2, 60), "margin_range": (0.15, 0.40)},
}

CATEGORY_NAMES = list(CATEGORIES.keys())

# Real product catalogs aren't split evenly across departments — some
# categories (Apparel, Home & Kitchen) typically carry more SKUs than
# others (Automotive, Books). Weights are deliberately uneven and sum to 1.
CATEGORY_CATALOG_WEIGHTS = {
    "Electronics": 0.12,
    "Home & Kitchen": 0.15,
    "Apparel": 0.18,
    "Sports & Outdoors": 0.10,
    "Toys & Games": 0.08,
    "Office Supplies": 0.09,
    "Beauty & Personal Care": 0.12,
    "Automotive": 0.06,
    "Grocery": 0.06,
    "Books & Media": 0.04,
}


def pareto_weights(n: int, alpha: float = 1.0, seed: int = config.RANDOM_SEED) -> np.ndarray:
    """Generate n normalized demand weights following a Pareto/Zipf-like skew.

    alpha=1.0 (classic Zipf) produces the familiar "80/20" retail pattern:
    a small share of SKUs account for most revenue. Weights are shuffled so
    "popular" products aren't simply the ones with the lowest product_id.
    Uses its own local RNG (independent of caller's) so this function is
    deterministic no matter when/how many other random draws happened
    before it — important since it's called from multiple modules.
    """
    rng = np.random.default_rng(seed)
    ranks = np.arange(1, n + 1)
    raw = 1 / np.power(ranks, alpha)
    rng.shuffle(raw)
    return raw / raw.sum()


def rank_percentile(values: np.ndarray) -> np.ndarray:
    """Convert an array of weights into rank-percentiles in [0, 1].

    Why not just divide by the max value?
    ----------------------------------------
    popularity_score follows a Pareto/Zipf skew where the single top
    product can carry ~100x the weight of a typical product. Normalizing
    by dividing every value by that one maximum crushes almost every other
    product toward 0 — e.g. a formula like `1 + normalized * 9` would then
    round down to 1 for effectively the entire catalog, destroying the
    variation we actually want (only the single top seller would show any
    effect). Rank-percentile instead spreads products evenly across [0, 1]
    regardless of how skewed the underlying weights are, which is what
    lets downstream formulas (restock frequency, safety stock sizing)
    produce a realistic, smoothly varying spread across the whole catalog.
    """
    return pd.Series(values).rank(pct=True).to_numpy()


def seasonal_month_weights() -> dict:
    """Relative order-volume weight per calendar month (1-12).

    Calibrated to reflect the Nov/Dec e-commerce peak (Black Friday /
    Cyber Monday / holiday shopping) and a modest mid-year dip — consistent
    with standard e-commerce seasonality and the seasonal patterns referenced
    in docs/architecture.md (DataCo benchmark).
    """
    return {
        1: 0.8, 2: 0.75, 3: 0.85, 4: 0.9, 5: 0.9, 6: 0.85,
        7: 0.8, 8: 0.85, 9: 0.95, 10: 1.1, 11: 1.6, 12: 1.8,
    }
