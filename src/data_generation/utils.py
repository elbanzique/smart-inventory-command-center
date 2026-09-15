"""
Shared utilities for synthetic data generation.

Centralizing randomness, category definitions, and seasonal patterns here
means every generator module (warehouses, suppliers, products, ...) draws
from the same calibrated assumptions instead of each script reinventing its
own ad-hoc randomness. See docs/architecture.md, section 5, for why these
specific calibrations were chosen (reference-informed simulation).
"""

import zlib

import numpy as np
import pandas as pd
from faker import Faker

from src import config


def get_rng(stream: str, seed: int = config.RANDOM_SEED) -> np.random.Generator:
    """Return a reproducible Generator on its own independent random stream.

    `stream` is a short name identifying the caller (e.g. "orders",
    "order_lines"). Each distinct name yields a statistically independent
    sequence, while the same name always yields the same sequence — so the
    pipeline stays byte-for-byte reproducible from a clean checkout.

    Why named streams instead of one shared seed
    ----------------------------------------------
    Every module used to call an unparameterized get_rng(), which returned
    default_rng(42) — literally the same stream in each module. Because
    numpy draws categorical samples by inverse-CDF on an underlying
    uniform sequence, two modules whose FIRST draw was an
    rng.choice(size=100_000, p=...) both consumed the same uniforms u[i].
    That silently made their outputs rank-correlated: in this project,
    orders.py drew each order's month and order_lines.py drew each order's
    line count from identical u[i], so a low u meant "early month AND 1
    line" and a high u meant "late month AND 4 lines". The result was that
    every 2024 order had exactly 1 line and every Dec-2025 order had
    exactly 4 — a 2.4x phantom revenue "growth trend" that was purely an
    artifact of seed reuse.

    Crucially, every marginal distribution was still perfect (line counts
    were 45/30/15/10 as specified, months followed the seasonal curve), so
    single-table validation passed. Only a cross-table check — lines per
    order BY MONTH — could expose it. Hence tests/test_data_generation.py
    now asserts stream independence directly.
    """
    # SeedSequence hashes the (seed, stream-name) pair into a high-quality
    # independent entropy source. This is numpy's supported way to derive
    # decorrelated streams; simple seed+1, seed+2 offsets are not
    # guaranteed to be independent.
    entropy = [seed, zlib.crc32(stream.encode("utf-8"))]
    return np.random.default_rng(np.random.SeedSequence(entropy))


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
    rng = get_rng("pareto_weights", seed)
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
