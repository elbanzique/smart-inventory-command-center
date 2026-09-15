"""Generate the purchase_orders fact table (supplier replenishment events)."""

import numpy as np
import pandas as pd

from src import config
from src.data_generation.utils import get_rng, rank_percentile


def generate_purchase_orders(products_df: pd.DataFrame, suppliers_df: pd.DataFrame) -> pd.DataFrame:
    """Return a purchase_orders event log spanning the simulation window.

    Replenishment frequency
    ------------------------
    Each product gets a number of restock events proportional to its
    popularity_score: high-demand products are replenished roughly 3-10
    times over the 2-year window, low-demand products only 1-3 times —
    mirroring how real reorder frequency tracks sell-through velocity.

    Supplier reliability -> delivery lateness
    -------------------------------------------
    Lateness is modeled in two steps, not one continuous noise term:
      1. Whether a PO is late at all is a coin flip whose probability is
         driven by the supplier's base_reliability_score:
         late_probability = clip((1 - reliability)^5 * 60, 0.01, 0.90).
         This exponent was chosen empirically (see docs/architecture.md)
         so that the overall on-time rate lands near the ~90% DataCo
         benchmark, while a small minority of clearly unreliable suppliers
         (reliability roughly below 0.65) end up with a genuinely high
         late rate (30-90%) rather than everyone drifting a little late.
      2. IF late, the delay magnitude (in days) is drawn from an
         exponential distribution whose scale also grows as reliability
         drops — so unreliable suppliers aren't just late more *often*,
         they're late by *more* when it happens.
    This two-step design is what makes the Phase 5 "which suppliers are
    unreliable?" analysis meaningful: lateness is a genuine, learnable
    signal tied to a real per-supplier cause, not undifferentiated noise.

    In-transit purchase orders
    -----------------------------
    Any PO whose actual delivery would fall after the simulation's "today"
    (SIMULATION_END_DATE) is left with a null actual_delivery_date — it
    simply hasn't happened yet from the business's point of view. This
    gives later phases a realistic, small population of still-open POs.
    """
    rng = get_rng()
    sim_start = pd.Timestamp(config.SIMULATION_START_DATE)
    sim_end = pd.Timestamp(config.SIMULATION_END_DATE)
    window_days = (sim_end - sim_start).days

    popularity = products_df["popularity_score"].to_numpy()
    # rank_percentile, not raw popularity/max — see rank_percentile()'s
    # docstring in utils.py for why dividing by the single top seller's
    # weight would collapse almost the whole catalog to the same value.
    demand_percentile = rank_percentile(popularity)
    n_events_per_product = (1 + demand_percentile * 9).astype(int)  # 1..10 restock events

    product_ids = np.repeat(products_df["product_id"].to_numpy(), n_events_per_product)
    supplier_ids = np.repeat(products_df["supplier_id"].to_numpy(), n_events_per_product)
    demand_percentile_repeated = np.repeat(demand_percentile, n_events_per_product)
    n_rows = len(product_ids)

    order_offsets = rng.integers(0, window_days, size=n_rows)
    order_dates = sim_start + pd.to_timedelta(order_offsets, unit="D")

    reliability_lookup = suppliers_df.set_index("supplier_id")["base_reliability_score"]
    lead_time_lookup = suppliers_df.set_index("supplier_id")["avg_lead_time_days"]
    reliability = reliability_lookup.loc[supplier_ids].to_numpy()
    lead_times = lead_time_lookup.loc[supplier_ids].to_numpy()

    expected_delivery_dates = order_dates + pd.to_timedelta(lead_times, unit="D")

    # Step 1: is this PO late at all? (see calibration rationale above)
    late_probability = np.clip((1 - reliability) ** 5 * 60, 0.01, 0.90)
    is_late = rng.random(n_rows) < late_probability

    # Step 2: if late, how late? Scale grows as reliability drops, so
    # unreliable suppliers are late by more, not just more often.
    delay_scale_days = 2 + (1 - reliability) * 15
    delay_days = np.zeros(n_rows, dtype=int)
    delay_days[is_late] = np.maximum(
        1, np.round(rng.exponential(scale=delay_scale_days[is_late])).astype(int)
    )

    actual_delivery_dates = expected_delivery_dates + pd.to_timedelta(delay_days, unit="D")
    quantity = (20 + demand_percentile_repeated * 200).astype(int)

    po_df = pd.DataFrame({
        "po_id": np.arange(1, n_rows + 1),
        "supplier_id": supplier_ids,
        "product_id": product_ids,
        "order_date": order_dates,
        "expected_delivery_date": expected_delivery_dates,
        "actual_delivery_date": actual_delivery_dates,
        "quantity": quantity,
    })

    still_in_transit = po_df["actual_delivery_date"] > sim_end
    po_df.loc[still_in_transit, "actual_delivery_date"] = pd.NaT

    for col in ["order_date", "expected_delivery_date", "actual_delivery_date"]:
        po_df[col] = po_df[col].dt.strftime("%Y-%m-%d")

    return po_df
