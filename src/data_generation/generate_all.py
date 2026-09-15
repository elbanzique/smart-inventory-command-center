"""
Orchestrates full synthetic data generation for NovaLog Distribution.

Run directly from the project root:
    python -m src.data_generation.generate_all
"""

import time

import pandas as pd

from src import config
from src.data_generation.inventory import generate_inventory
from src.data_generation.order_lines import generate_order_lines
from src.data_generation.orders import generate_orders
from src.data_generation.products import generate_products
from src.data_generation.purchase_orders import generate_purchase_orders
from src.data_generation.suppliers import generate_suppliers
from src.data_generation.validate import validate_all
from src.data_generation.warehouses import generate_warehouses


def _save(df: pd.DataFrame, name: str) -> None:
    path = config.RAW_DATA_DIR / f"{name}.csv"
    df.to_csv(path, index=False)
    print(f"  wrote {path.relative_to(config.PROJECT_ROOT)}  ({len(df):,} rows)")


def main() -> None:
    start = time.time()
    config.RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating warehouses...")
    warehouses = generate_warehouses()
    _save(warehouses, "warehouses")

    print("Generating suppliers...")
    suppliers = generate_suppliers()
    _save(suppliers, "suppliers")

    print("Generating products...")
    products = generate_products(suppliers)
    _save(products, "products")

    print("Generating inventory...")
    inventory = generate_inventory(products, warehouses)
    _save(inventory, "inventory")

    print("Generating purchase_orders...")
    purchase_orders = generate_purchase_orders(products, suppliers)
    _save(purchase_orders, "purchase_orders")

    print("Generating orders...")
    orders = generate_orders(warehouses)
    _save(orders, "orders")

    print("Generating order_lines...")
    order_lines = generate_order_lines(orders, products)
    _save(order_lines, "order_lines")

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s. Running validation...\n")

    validate_all({
        "warehouses": warehouses,
        "suppliers": suppliers,
        "products": products,
        "inventory": inventory,
        "purchase_orders": purchase_orders,
        "orders": orders,
        "order_lines": order_lines,
    })


if __name__ == "__main__":
    main()
