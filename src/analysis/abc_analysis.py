"""
ABC classification and inventory turnover.

Why these two techniques specifically
--------------------------------------
Neither is in the original project brief, but both are standard vocabulary
in supply chain and inventory management, and their absence would be
conspicuous to anyone interviewing for a logistics analyst role.

ABC analysis (a Pareto application) segments SKUs by revenue contribution
so that inventory policy can be differentiated: A items justify tight
control and frequent review, C items don't. It turns "here are your top
sellers" into "here is how you should manage each tier differently."

Inventory turnover (COGS / average inventory value) measures how many
times stock is sold and replaced in a period. It's the single most cited
inventory efficiency KPI, and it's the number that makes dead stock
*actionable* — a category with high dead-stock value AND low turnover is a
much stronger signal than either metric alone.
"""

import numpy as np
import pandas as pd


def classify_abc(
    sales_df: pd.DataFrame,
    a_threshold: float = 0.80,
    b_threshold: float = 0.95,
) -> pd.DataFrame:
    """Classify products into A/B/C tiers by cumulative revenue share.

    Standard thresholds: A = the SKUs making up the top 80% of revenue,
    B = the next 15% (up to 95%), C = the remaining 5%. The thresholds are
    parameters rather than hardcoded values because different businesses
    draw these lines differently, and an interviewer may well ask "what if
    we used 70/90 instead?" — this makes that a one-line change.
    """
    revenue_by_product = (
        sales_df.groupby(["product_id", "sku", "category"], as_index=False)
        .agg(
            total_revenue=("line_revenue", "sum"),
            total_margin=("line_margin", "sum"),
            units_sold=("quantity", "sum"),
        )
        .sort_values("total_revenue", ascending=False)
        .reset_index(drop=True)
    )

    total_revenue = revenue_by_product["total_revenue"].sum()
    revenue_by_product["revenue_share"] = revenue_by_product["total_revenue"] / total_revenue
    revenue_by_product["cumulative_revenue_share"] = revenue_by_product["revenue_share"].cumsum()

    # np.select evaluates conditions in order, so the A test runs first and
    # a SKU can only fall into one bucket.
    conditions = [
        revenue_by_product["cumulative_revenue_share"] <= a_threshold,
        revenue_by_product["cumulative_revenue_share"] <= b_threshold,
    ]
    revenue_by_product["abc_class"] = np.select(conditions, ["A", "B"], default="C")

    revenue_by_product["rank"] = np.arange(1, len(revenue_by_product) + 1)
    return revenue_by_product


def abc_summary(abc_df: pd.DataFrame) -> pd.DataFrame:
    """Summarize each ABC tier: SKU count, SKU share, and revenue share.

    This is the table that actually communicates the Pareto insight — the
    interesting output isn't which SKU is class A, it's "X% of SKUs drive
    Y% of revenue."
    """
    total_skus = len(abc_df)
    total_revenue = abc_df["total_revenue"].sum()

    summary = (
        abc_df.groupby("abc_class", as_index=False)
        .agg(
            sku_count=("product_id", "count"),
            total_revenue=("total_revenue", "sum"),
            total_margin=("total_margin", "sum"),
            units_sold=("units_sold", "sum"),
        )
        .sort_values("abc_class")
    )
    summary["pct_of_skus"] = (100 * summary["sku_count"] / total_skus).round(2)
    summary["pct_of_revenue"] = (100 * summary["total_revenue"] / total_revenue).round(2)
    return summary


def inventory_turnover_by_category(
    sales_df: pd.DataFrame, inventory_df: pd.DataFrame
) -> pd.DataFrame:
    """Compute annualized inventory turnover and days-of-supply per category.

    turnover = annualized COGS / current inventory value
    days_of_supply = 365 / turnover

    Caveat worth stating out loud (and worth saying in an interview):
    proper turnover uses *average* inventory value over the period, but
    this dataset holds only a single current inventory snapshot, not a
    historical series. So this is a snapshot-based approximation. The
    comparison *between* categories remains valid and useful — it's the
    absolute values that should be read with that limitation in mind.
    """
    period_days = (sales_df["order_date"].max() - sales_df["order_date"].min()).days
    # Guard against a degenerate single-day dataset (possible in tests).
    period_days = max(period_days, 1)

    cogs = sales_df.groupby("category", as_index=False)["line_cogs"].sum()
    cogs["annualized_cogs"] = cogs["line_cogs"] * (365 / period_days)

    inv_value = inventory_df.groupby("category", as_index=False)["inventory_value"].sum()

    merged = cogs.merge(inv_value, on="category", how="outer").fillna(0)
    merged["inventory_turnover"] = (
        merged["annualized_cogs"] / merged["inventory_value"].replace(0, np.nan)
    ).round(2)
    merged["days_of_supply"] = (365 / merged["inventory_turnover"]).round(1)

    return merged.sort_values("inventory_turnover", ascending=False).reset_index(drop=True)
