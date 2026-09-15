"""
Tests for src/data_generation/*.

These call the generator functions directly with small n values rather than
reading data/raw/*.csv from disk. That's a deliberate choice: it keeps the
test suite fast, keeps it independent of whether anyone has run the full
generation pipeline yet, and still exercises exactly the same code paths
(referential integrity, positivity constraints, distribution shape) that
matter for the full-scale run.

Run from the project root with:
    pytest
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensures `from src...` imports resolve regardless of the directory pytest
# is invoked from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_generation.inventory import generate_inventory
from src.data_generation.order_lines import generate_order_lines
from src.data_generation.orders import generate_orders
from src.data_generation.products import generate_products
from src.data_generation.purchase_orders import generate_purchase_orders
from src.data_generation.suppliers import generate_suppliers
from src.data_generation.warehouses import generate_warehouses


@pytest.fixture(scope="module")
def small_dataset():
    """A small, fast end-to-end dataset for testing (not the full 100k-order run)."""
    warehouses = generate_warehouses()
    suppliers = generate_suppliers(n=10)
    products = generate_products(suppliers, n=200)
    inventory = generate_inventory(products, warehouses)
    purchase_orders = generate_purchase_orders(products, suppliers)
    orders = generate_orders(warehouses, n=1_000)
    order_lines = generate_order_lines(orders, products)
    return {
        "warehouses": warehouses,
        "suppliers": suppliers,
        "products": products,
        "inventory": inventory,
        "purchase_orders": purchase_orders,
        "orders": orders,
        "order_lines": order_lines,
    }


def test_row_counts(small_dataset):
    assert len(small_dataset["warehouses"]) == 3
    assert len(small_dataset["suppliers"]) == 10
    assert len(small_dataset["products"]) == 200
    assert len(small_dataset["orders"]) == 1_000
    assert len(small_dataset["inventory"]) == 200 * 3  # one row per product per warehouse


def test_referential_integrity(small_dataset):
    products = small_dataset["products"]
    suppliers = small_dataset["suppliers"]
    warehouses = small_dataset["warehouses"]
    inventory = small_dataset["inventory"]
    purchase_orders = small_dataset["purchase_orders"]
    orders = small_dataset["orders"]
    order_lines = small_dataset["order_lines"]

    assert products["supplier_id"].isin(suppliers["supplier_id"]).all()
    assert inventory["product_id"].isin(products["product_id"]).all()
    assert inventory["warehouse_id"].isin(warehouses["warehouse_id"]).all()
    assert purchase_orders["product_id"].isin(products["product_id"]).all()
    assert purchase_orders["supplier_id"].isin(suppliers["supplier_id"]).all()
    assert orders["warehouse_id"].isin(warehouses["warehouse_id"]).all()
    assert order_lines["order_id"].isin(orders["order_id"]).all()
    assert order_lines["product_id"].isin(products["product_id"]).all()


def test_no_invalid_numeric_values(small_dataset):
    products = small_dataset["products"]
    inventory = small_dataset["inventory"]
    order_lines = small_dataset["order_lines"]

    assert (products["unit_cost"] > 0).all()
    assert (products["unit_price"] > 0).all()
    assert (products["unit_price"] >= products["unit_cost"]).all()
    assert (inventory["quantity_on_hand"] >= 0).all()
    assert (order_lines["quantity"] > 0).all()
    assert (order_lines["unit_price_at_sale"] > 0).all()


def test_dates_within_simulation_window(small_dataset):
    from src import config

    order_dates = pd.to_datetime(small_dataset["orders"]["order_date"])
    assert (order_dates >= config.SIMULATION_START_DATE).all()
    assert (order_dates <= config.SIMULATION_END_DATE).all()


def test_reproducibility():
    """Re-running a generator with the same seed must produce identical output."""
    suppliers_a = generate_suppliers(n=20)
    suppliers_b = generate_suppliers(n=20)
    pd.testing.assert_frame_equal(suppliers_a, suppliers_b)

    warehouses = generate_warehouses()
    products_a = generate_products(suppliers_a, n=50)
    products_b = generate_products(suppliers_b, n=50)
    pd.testing.assert_frame_equal(products_a, products_b)


def test_supplier_reliability_is_skewed_not_uniform():
    """Guards the Beta(8, 2) design choice: most suppliers should be reliable."""
    suppliers = generate_suppliers(n=50)
    reliability = suppliers["base_reliability_score"]
    assert reliability.mean() > 0.7, "expected most suppliers to be reliable on average"
    assert reliability.min() < 0.7, "expected at least one clearly unreliable supplier"


def test_purchase_order_delivery_status_is_valid(small_dataset):
    po = small_dataset["purchase_orders"]
    delivered = po.dropna(subset=["actual_delivery_date"])
    assert (pd.to_datetime(delivered["actual_delivery_date"]) >= pd.to_datetime(delivered["order_date"])).all()


# ---------------------------------------------------------------------------
# Cross-table independence regression tests
#
# These exist because of a real bug: every generator module called an
# unparameterized get_rng() returning default_rng(42) — the SAME stream. Since
# numpy draws categorical samples by inverse-CDF on an underlying uniform
# sequence, orders.py (drawing each order's month) and order_lines.py (drawing
# each order's line count) consumed identical uniforms u[i], making the two
# perfectly rank-correlated: every 2024 order had exactly 1 line and every
# Dec-2025 order had exactly 4, producing a phantom 2.4x revenue "growth trend".
#
# Every marginal distribution was still correct, so no single-table check
# caught it. Only a cross-table assertion can.
# ---------------------------------------------------------------------------

def test_random_streams_are_independent():
    """Two named streams must not produce rank-correlated draws."""
    import numpy as np
    from src.data_generation.utils import get_rng

    a = get_rng("orders").choice(24, size=20_000, p=np.full(24, 1 / 24))
    b = get_rng("order_lines").choice([1, 2, 3, 4], size=20_000, p=[0.45, 0.30, 0.15, 0.10])
    corr = np.corrcoef(a, b)[0, 1]
    assert abs(corr) < 0.05, f"streams are correlated (r={corr:.3f}) — seed reuse regression"


def test_same_stream_name_is_reproducible():
    """Independence must not come at the cost of reproducibility."""
    from src.data_generation.utils import get_rng

    first = get_rng("orders").integers(0, 1_000_000, size=500)
    second = get_rng("orders").integers(0, 1_000_000, size=500)
    assert (first == second).all()


def test_lines_per_order_is_stable_over_time(small_dataset):
    """Basket size must not drift with order date.

    This is the assertion that would have caught the seed-reuse bug: it
    joins two separately-generated tables and checks that a property of one
    is independent of a property of the other.
    """
    import pandas as pd

    orders = small_dataset["orders"].copy()
    order_lines = small_dataset["order_lines"]

    lines_per_order = order_lines.groupby("order_id").size().rename("n_lines")
    merged = orders.join(lines_per_order, on="order_id")
    merged["order_date"] = pd.to_datetime(merged["order_date"])
    merged["half"] = (merged["order_date"] >= merged["order_date"].median()).map(
        {False: "first", True: "second"}
    )

    means = merged.groupby("half")["n_lines"].mean()
    # Allow generous tolerance for the small test dataset; the bug produced
    # a 4x gap, so anything near parity proves independence.
    assert abs(means["first"] - means["second"]) < 0.4, (
        f"basket size drifts with date: {means.to_dict()}"
    )
