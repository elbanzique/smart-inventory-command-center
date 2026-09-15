"""Generate the orders fact table (customer order headers)."""

import numpy as np
import pandas as pd

from src import config
from src.data_generation.utils import get_rng, seasonal_month_weights


def generate_orders(warehouses_df: pd.DataFrame, n: int = config.N_ORDERS) -> pd.DataFrame:
    """Return n order header rows spanning the simulation window.

    Seasonality
    ------------
    Order dates are NOT uniform across the 2-year window. We first sample
    a calendar month per order (weighted toward Nov/Dec per
    seasonal_month_weights()), then a uniform day within that month. This
    produces realistic month-over-month volume swings for a dashboard to
    surface, instead of a flat line that tells no story. The whole date
    assignment is vectorized (no per-row Python loop) so it stays fast
    even at 100,000 rows.

    Warehouse assignment
    -----------------------
    Orders are assigned to warehouses proportional to `capacity_units` — a
    larger DC plausibly serves a larger customer base / order volume.

    Customer pool
    ---------------
    We simulate ~35% as many unique customers as orders (repeat customers
    are the norm in e-commerce), sampled with replacement so some customers
    naturally appear multiple times.

    Order status
    -------------
    ~90% Delivered, ~3% Cancelled, ~7% Returned — consistent with the
    ~90% on-time/successful delivery benchmark referenced in
    docs/architecture.md and typical e-commerce return rates.
    """
    rng = get_rng()
    sim_start = pd.Timestamp(config.SIMULATION_START_DATE)
    sim_end = pd.Timestamp(config.SIMULATION_END_DATE)

    n_months = (sim_end.year - sim_start.year) * 12 + (sim_end.month - sim_start.month) + 1
    month_starts = pd.date_range(sim_start, periods=n_months, freq="MS")
    month_ends = pd.date_range(sim_start, periods=n_months, freq="ME")

    month_weights = seasonal_month_weights()
    month_probs = np.array([month_weights[d.month] for d in month_starts], dtype=float)
    month_probs /= month_probs.sum()

    chosen_idx = rng.choice(n_months, size=n, p=month_probs)
    chosen_month_start = month_starts.to_numpy()[chosen_idx]
    chosen_month_end = month_ends.to_numpy()[chosen_idx]

    days_in_chosen_month = ((chosen_month_end - chosen_month_start) / np.timedelta64(1, "D")).astype(int) + 1
    day_offset = rng.integers(0, days_in_chosen_month)

    order_dates_raw = chosen_month_start + day_offset.astype("timedelta64[D]")
    order_dates = pd.Series(order_dates_raw).clip(lower=sim_start, upper=sim_end)

    warehouse_ids = warehouses_df["warehouse_id"].to_numpy()
    warehouse_weights = warehouses_df["capacity_units"].to_numpy().astype(float)
    warehouse_weights /= warehouse_weights.sum()
    assigned_warehouse = rng.choice(warehouse_ids, size=n, p=warehouse_weights)

    n_customers = max(1, int(n * 0.35))
    customer_ids = rng.integers(1, n_customers + 1, size=n)

    status = rng.choice(["Delivered", "Cancelled", "Returned"], size=n, p=[0.90, 0.03, 0.07])

    orders = pd.DataFrame({
        "order_id": np.arange(1, n + 1),
        "order_date": order_dates.dt.strftime("%Y-%m-%d"),
        "warehouse_id": assigned_warehouse,
        "customer_id": customer_ids,
        "status": status,
    })
    return orders
