"""
Post-generation validation checks.

These are lightweight, fast sanity checks run immediately after generation —
not a replacement for the pytest suite in tests/, but a human-readable report
so you know immediately whether the generated data is trustworthy before
moving on to the ETL phase.
"""

import pandas as pd

from src import config


def _check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    suffix = f" - {detail}" if detail else ""
    print(f"  [{status}] {label}{suffix}")
    return bool(condition)


def validate_all(tables: dict) -> bool:
    warehouses = tables["warehouses"]
    suppliers = tables["suppliers"]
    products = tables["products"]
    inventory = tables["inventory"]
    purchase_orders = tables["purchase_orders"]
    orders = tables["orders"]
    order_lines = tables["order_lines"]

    checks = []

    checks.append(_check("warehouses has expected row count", len(warehouses) == config.N_WAREHOUSES))
    checks.append(_check("suppliers has expected row count", len(suppliers) == config.N_SUPPLIERS))
    checks.append(_check("products has expected row count", len(products) == config.N_PRODUCTS))
    checks.append(_check("orders has expected row count", len(orders) == config.N_ORDERS))

    checks.append(_check(
        "products.supplier_id all reference existing suppliers",
        products["supplier_id"].isin(suppliers["supplier_id"]).all(),
    ))
    checks.append(_check(
        "inventory.product_id all reference existing products",
        inventory["product_id"].isin(products["product_id"]).all(),
    ))
    checks.append(_check(
        "inventory.warehouse_id all reference existing warehouses",
        inventory["warehouse_id"].isin(warehouses["warehouse_id"]).all(),
    ))
    checks.append(_check(
        "purchase_orders.supplier_id all reference existing suppliers",
        purchase_orders["supplier_id"].isin(suppliers["supplier_id"]).all(),
    ))
    checks.append(_check(
        "purchase_orders.product_id all reference existing products",
        purchase_orders["product_id"].isin(products["product_id"]).all(),
    ))
    checks.append(_check(
        "orders.warehouse_id all reference existing warehouses",
        orders["warehouse_id"].isin(warehouses["warehouse_id"]).all(),
    ))
    checks.append(_check(
        "order_lines.order_id all reference existing orders",
        order_lines["order_id"].isin(orders["order_id"]).all(),
    ))
    checks.append(_check(
        "order_lines.product_id all reference existing products",
        order_lines["product_id"].isin(products["product_id"]).all(),
    ))

    checks.append(_check("no non-positive unit_cost", (products["unit_cost"] > 0).all()))
    checks.append(_check("no non-positive unit_price", (products["unit_price"] > 0).all()))
    checks.append(_check(
        "unit_price always >= unit_cost (positive margin)",
        (products["unit_price"] >= products["unit_cost"]).all(),
    ))
    checks.append(_check("no negative quantity_on_hand", (inventory["quantity_on_hand"] >= 0).all()))
    checks.append(_check("no non-positive order_lines.quantity", (order_lines["quantity"] > 0).all()))

    order_dates = pd.to_datetime(orders["order_date"])
    checks.append(_check(
        "order_date within simulation window",
        (order_dates >= config.SIMULATION_START_DATE).all() and (order_dates <= config.SIMULATION_END_DATE).all(),
    ))

    delivered_pos = purchase_orders[purchase_orders["actual_delivery_date"].notna()]
    late = pd.to_datetime(delivered_pos["actual_delivery_date"]) > pd.to_datetime(
        delivered_pos["expected_delivery_date"]
    )
    on_time_share = 1 - late.mean()
    checks.append(_check(
        "purchase_orders on-time share is in a realistic band",
        0.75 <= on_time_share <= 0.97,
        detail=f"got {on_time_share:.1%}",
    ))

    inv_with_thresholds = inventory.merge(
        products[["product_id", "reorder_point", "safety_stock"]], on="product_id"
    )
    stockout_share = (inv_with_thresholds["quantity_on_hand"] < inv_with_thresholds["reorder_point"]).mean()
    checks.append(_check(
        "stockout-risk share of inventory is in the intended ~12% band",
        0.08 <= stockout_share <= 0.16,
        detail=f"got {stockout_share:.1%}",
    ))
    dead_stock_share = (
        inv_with_thresholds["quantity_on_hand"] >= inv_with_thresholds["safety_stock"] * 4
    ).mean()
    checks.append(_check(
        "dead-stock share of inventory is in the intended ~10% band",
        0.06 <= dead_stock_share <= 0.14,
        detail=f"got {dead_stock_share:.1%}",
    ))

    revenue = order_lines.assign(revenue=order_lines["quantity"] * order_lines["unit_price_at_sale"])
    revenue_by_product = revenue.groupby("product_id")["revenue"].sum().sort_values(ascending=False)
    top20_cutoff = max(1, int(len(revenue_by_product) * 0.2))
    top20_share = revenue_by_product.iloc[:top20_cutoff].sum() / revenue_by_product.sum()
    checks.append(_check(
        "top 20% of products drive a majority of revenue",
        top20_share >= 0.55,
        detail=f"got {top20_share:.1%}",
    ))

    all_ok = all(checks)
    print(f"\nOverall: {'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED - see above'}")
    return all_ok
