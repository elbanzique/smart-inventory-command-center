"""Generate the warehouses dimension table."""

import pandas as pd

# Hardcoded because there are only 3, and each needs a plausible regional
# identity — region and capacity later drive how orders get distributed
# across the network (see orders.py).
_WAREHOUSE_DEFS = [
    {"warehouse_id": 1, "name": "West Coast Distribution Center", "region": "West", "capacity_units": 500_000},
    {"warehouse_id": 2, "name": "Central Distribution Center", "region": "Central", "capacity_units": 650_000},
    {"warehouse_id": 3, "name": "East Coast Distribution Center", "region": "East", "capacity_units": 550_000},
]


def generate_warehouses() -> pd.DataFrame:
    """Return the 3-row warehouses dimension table.

    Capacities differ slightly to reflect a realistic network (a larger
    central hub flanked by two coastal DCs) rather than three identical
    facilities, which would make "which warehouse performs best?" a
    meaningless question to ask of the data.
    """
    return pd.DataFrame(_WAREHOUSE_DEFS)
