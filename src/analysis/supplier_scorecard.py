"""
Supplier performance scorecard.

Goes beyond the Phase 4 SQL query (a single lateness rate) to build a
composite, weighted score and a risk tier — the form procurement teams
actually use to make "keep / monitor / replace" decisions.
"""

import numpy as np
import pandas as pd

from src.analysis.db import load_table


def build_supplier_scorecard(min_delivered_pos: int = 5) -> pd.DataFrame:
    """Return a per-supplier scorecard with a composite reliability score.

    Scoring design
    ---------------
    Three components, each normalized to 0-100 (higher = better), then
    combined with weights:

      on_time_score   (50%) - the share of POs delivered by the promised
                              date. Weighted highest because it's the
                              commitment the supplier actually made.
      delay_score     (30%) - severity of lateness when it happens. A
                              supplier who is late by 1 day is not
                              equivalent to one late by 15, and a pure
                              on-time rate can't distinguish them.
      consistency     (20%) - inverse of the standard deviation of delay.
                              A supplier who is *predictably* 5 days late
                              is easier to plan around than one who
                              randomly swings between 0 and 20 days.
                              Variability is its own cost.

    Suppliers below min_delivered_pos completed POs are excluded: with too
    few deliveries, any rate computed is noise rather than signal.
    """
    purchase_orders = load_table("purchase_orders")
    suppliers = load_table("suppliers")

    po = purchase_orders.copy()
    po["expected_delivery_date"] = pd.to_datetime(po["expected_delivery_date"])
    po["actual_delivery_date"] = pd.to_datetime(po["actual_delivery_date"])

    delivered = po.dropna(subset=["actual_delivery_date"]).copy()
    delivered["delay_days"] = (
        delivered["actual_delivery_date"] - delivered["expected_delivery_date"]
    ).dt.days
    delivered["is_late"] = delivered["delay_days"] > 0
    # Early deliveries are clipped to 0: arriving early is not a defect,
    # and letting negative delays offset positive ones would let a supplier
    # mask genuine lateness with a few early shipments.
    delivered["late_days_only"] = delivered["delay_days"].clip(lower=0)

    agg = (
        delivered.groupby("supplier_id", as_index=False)
        .agg(
            delivered_pos=("po_id", "count"),
            late_pos=("is_late", "sum"),
            avg_delay_days=("late_days_only", "mean"),
            max_delay_days=("late_days_only", "max"),
            delay_std=("late_days_only", "std"),
            total_units=("quantity", "sum"),
        )
    )
    agg = agg[agg["delivered_pos"] >= min_delivered_pos].copy()
    agg["delay_std"] = agg["delay_std"].fillna(0)

    agg["on_time_rate"] = 1 - (agg["late_pos"] / agg["delivered_pos"])
    agg["on_time_score"] = (agg["on_time_rate"] * 100).round(2)

    # Both severity and consistency are scaled against the worst observed
    # supplier in the dataset (relative scoring) rather than an arbitrary
    # absolute cap, so the scale adapts to whatever the real spread is.
    worst_avg_delay = agg["avg_delay_days"].max()
    agg["delay_score"] = (
        100 * (1 - agg["avg_delay_days"] / worst_avg_delay) if worst_avg_delay > 0 else 100
    )
    worst_std = agg["delay_std"].max()
    agg["consistency_score"] = (
        100 * (1 - agg["delay_std"] / worst_std) if worst_std > 0 else 100
    )

    agg["composite_score"] = (
        0.50 * agg["on_time_score"]
        + 0.30 * agg["delay_score"]
        + 0.20 * agg["consistency_score"]
    ).round(2)

    # Fixed thresholds (not quantiles) so a supplier's tier reflects its
    # absolute performance, not just how it compares to this year's peers —
    # otherwise every supplier improving would still leave someone in
    # "High Risk" by construction.
    agg["risk_tier"] = np.select(
        [agg["composite_score"] >= 85, agg["composite_score"] >= 65],
        ["Preferred", "Monitor"],
        default="High Risk",
    )

    scorecard = agg.merge(
        suppliers[["supplier_id", "name", "region", "primary_category", "base_reliability_score"]],
        on="supplier_id",
        how="left",
    ).rename(columns={"name": "supplier_name"})

    scorecard["late_delivery_rate_pct"] = (100 * scorecard["late_pos"] / scorecard["delivered_pos"]).round(2)
    scorecard["avg_delay_days"] = scorecard["avg_delay_days"].round(2)
    scorecard["delay_score"] = scorecard["delay_score"].round(2)
    scorecard["consistency_score"] = scorecard["consistency_score"].round(2)

    columns = [
        "supplier_id", "supplier_name", "region", "primary_category",
        "delivered_pos", "late_pos", "late_delivery_rate_pct",
        "avg_delay_days", "max_delay_days",
        "on_time_score", "delay_score", "consistency_score",
        "composite_score", "risk_tier", "base_reliability_score",
    ]
    return scorecard[columns].sort_values("composite_score").reset_index(drop=True)


def validate_scorecard_against_seed(scorecard: pd.DataFrame) -> dict:
    """Check the empirical composite score against the hidden generation seed.

    This is a deliberate self-audit, not part of the business analysis.
    `base_reliability_score` is the value the Phase 2 generator used to
    *create* the delay patterns — a real analyst would never have it. The
    scorecard above is built purely from observed delivery behavior and
    never reads that column.

    So correlating the two afterwards answers a genuinely useful question:
    "did my analysis successfully recover the underlying truth from
    observed data alone?" A strong positive correlation means the
    methodology works. That's exactly the kind of validation you can't
    normally do on real data, and it's a strong thing to be able to show.
    """
    corr = scorecard["composite_score"].corr(scorecard["base_reliability_score"])
    return {
        "correlation": round(corr, 3),
        "interpretation": (
            "Strong - the scorecard recovers the underlying reliability well"
            if corr > 0.7
            else "Moderate - scorecard partially recovers underlying reliability"
            if corr > 0.4
            else "Weak - methodology may need review"
        ),
    }
