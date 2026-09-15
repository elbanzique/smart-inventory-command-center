"""
Matplotlib visualizations for the analysis layer.

Design notes
-------------
A single house style is applied once (apply_house_style) rather than
restyling each chart, so every figure in the report and README looks like
it came from the same deliverable.

Charts use the "Agg" backend explicitly — these run headless in scripts and
CI, where no display is attached.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

from src import config

FIGURES_DIR = config.PROJECT_ROOT / "reports" / "figures"

# A restrained, consistent palette. Categorical colors are muted; the
# accent/warning colors are reserved for drawing the eye to problems
# (dead stock, high-risk suppliers), so color carries meaning instead of
# just decoration.
PALETTE = {
    "primary": "#2B6CB0",
    "secondary": "#4A9D7F",
    "accent": "#D69E2E",
    "warning": "#C05621",
    "danger": "#9B2C2C",
    "neutral": "#718096",
}
CATEGORICAL = ["#2B6CB0", "#4A9D7F", "#D69E2E", "#C05621", "#9B2C2C",
               "#553C9A", "#2C7A7B", "#97266D", "#4A5568", "#276749"]


def apply_house_style() -> None:
    plt.rcParams.update({
        "figure.dpi": 110,
        "savefig.dpi": 160,
        "savefig.bbox": "tight",
        "font.size": 10,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linestyle": "-",
        "legend.frameon": False,
    })


def _save(fig, name: str) -> str:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURES_DIR / f"{name}.png"
    fig.savefig(path)
    plt.close(fig)
    return str(path.relative_to(config.PROJECT_ROOT))


def _thousands(x, _pos):
    if abs(x) >= 1_000_000:
        return f"${x / 1_000_000:.1f}M"
    if abs(x) >= 1_000:
        return f"${x / 1_000:.0f}K"
    return f"${x:.0f}"


def plot_monthly_revenue_trend(sales_df: pd.DataFrame) -> str:
    """Monthly revenue by warehouse — surfaces seasonality and warehouse mix."""
    monthly = (
        sales_df.assign(month=sales_df["order_date"].dt.to_period("M").dt.to_timestamp())
        .groupby(["month", "warehouse_name"], as_index=False)["line_revenue"].sum()
    )

    fig, ax = plt.subplots(figsize=(11, 5))
    for i, (wh, grp) in enumerate(monthly.groupby("warehouse_name")):
        ax.plot(grp["month"], grp["line_revenue"], marker="o", markersize=3,
                linewidth=1.8, label=wh, color=CATEGORICAL[i])

    ax.set_title("Monthly Revenue by Warehouse")
    ax.set_xlabel("")
    ax.set_ylabel("Revenue")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_thousands))
    ax.legend(loc="upper left")
    return _save(fig, "monthly_revenue_trend")


def plot_abc_pareto(abc_df: pd.DataFrame) -> str:
    """Classic Pareto chart: cumulative revenue share against SKU rank."""
    fig, ax = plt.subplots(figsize=(10, 5))

    sku_pct = 100 * abc_df["rank"] / len(abc_df)
    cum_pct = 100 * abc_df["cumulative_revenue_share"]

    ax.plot(sku_pct, cum_pct, color=PALETTE["primary"], linewidth=2)
    ax.fill_between(sku_pct, cum_pct, alpha=0.12, color=PALETTE["primary"])

    for threshold, color, label in [(80, PALETTE["accent"], "80% of revenue"),
                                    (95, PALETTE["warning"], "95% of revenue")]:
        ax.axhline(threshold, color=color, linestyle="--", linewidth=1.2, alpha=0.8)
        # Where does the curve actually cross this threshold?
        crossing = sku_pct[cum_pct >= threshold]
        if len(crossing) > 0:
            x = crossing.iloc[0]
            ax.axvline(x, color=color, linestyle=":", linewidth=1, alpha=0.6)
            ax.annotate(f"{label}\nfrom {x:.0f}% of SKUs",
                        xy=(x, threshold), xytext=(x + 4, threshold - 9),
                        fontsize=9, color=color)

    ax.set_title("ABC Analysis — Revenue Concentration (Pareto Curve)")
    ax.set_xlabel("Cumulative share of SKUs (%, ranked by revenue)")
    ax.set_ylabel("Cumulative share of revenue (%)")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 102)
    return _save(fig, "abc_pareto")


def plot_supplier_risk(scorecard: pd.DataFrame, top_n: int = 15) -> str:
    """Worst-performing suppliers by composite score, colored by risk tier."""
    worst = scorecard.nsmallest(top_n, "composite_score").iloc[::-1]

    tier_colors = {
        "High Risk": PALETTE["danger"],
        "Monitor": PALETTE["accent"],
        "Preferred": PALETTE["secondary"],
    }
    colors = [tier_colors.get(t, PALETTE["neutral"]) for t in worst["risk_tier"]]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(worst["supplier_name"], worst["composite_score"], color=colors)

    for bar, rate in zip(bars, worst["late_delivery_rate_pct"]):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f"{rate:.0f}% late", va="center", fontsize=8,
                color=PALETTE["neutral"])

    ax.set_title(f"Lowest-Scoring Suppliers (bottom {top_n} by composite score)")
    ax.set_xlabel("Composite reliability score (0-100, higher is better)")
    ax.set_xlim(0, 112)

    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in tier_colors.values()]
    # Anchored outside the axes: the bars carry "% late" annotations at their
    # right-hand ends, which an in-plot legend sat directly on top of.
    ax.legend(
        handles,
        tier_colors.keys(),
        title="Risk tier",
        loc="lower right",
        bbox_to_anchor=(1.0, -0.22),
        ncol=3,
    )
    return _save(fig, "supplier_risk")


def plot_dead_stock_by_category(by_category: pd.DataFrame) -> str:
    """Capital tied up in dead/slow-moving stock, by category."""
    df = by_category.sort_values("capital_tied_up")

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.barh(df["category"], df["capital_tied_up"], color=PALETTE["warning"])

    ax.set_title("Capital Tied Up in Dead & Slow-Moving Stock, by Category")
    ax.set_xlabel("Inventory value at cost")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_thousands))
    return _save(fig, "dead_stock_by_category")


def plot_inventory_health_mix(summary: pd.DataFrame) -> str:
    """Share of total inventory value by stock status."""
    order = ["Healthy", "Overstocked", "Slow-Moving", "Dead"]
    df = summary.set_index("stock_status").reindex(order).dropna().reset_index()

    status_colors = {
        "Healthy": PALETTE["secondary"],
        "Overstocked": PALETTE["accent"],
        "Slow-Moving": PALETTE["warning"],
        "Dead": PALETTE["danger"],
    }
    colors = [status_colors[s] for s in df["stock_status"]]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(df["stock_status"], df["total_value"], color=colors, width=0.6)

    for bar, pct in zip(bars, df["pct_of_inventory_value"]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"{pct:.1f}%", ha="center", va="bottom", fontweight="bold")

    ax.set_title("Inventory Value by Stock Health Status")
    ax.set_ylabel("Inventory value at cost")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_thousands))
    return _save(fig, "inventory_health_mix")


def plot_warehouse_comparison(sales_df: pd.DataFrame, orders_df: pd.DataFrame) -> str:
    """Two-panel warehouse comparison: revenue scale vs. order quality.

    Deliberately paired: revenue alone would crown the biggest warehouse
    the "winner" even if it has the worst return rate. Showing both panels
    side by side forces the trade-off into view.
    """
    revenue = sales_df.groupby("warehouse_name", as_index=False)["line_revenue"].sum()

    quality = (
        orders_df.groupby("warehouse_name")
        .agg(
            return_rate=("status", lambda s: 100 * (s == "Returned").mean()),
            cancel_rate=("status", lambda s: 100 * (s == "Cancelled").mean()),
        )
        .reset_index()
    )

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    ax1.bar(revenue["warehouse_name"], revenue["line_revenue"],
            color=PALETTE["primary"], width=0.55)
    ax1.set_title("Delivered Revenue")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(_thousands))
    ax1.tick_params(axis="x", labelrotation=20)

    x = np.arange(len(quality))
    width = 0.35
    ax2.bar(x - width / 2, quality["return_rate"], width,
            label="Return rate", color=PALETTE["warning"])
    ax2.bar(x + width / 2, quality["cancel_rate"], width,
            label="Cancellation rate", color=PALETTE["neutral"])
    ax2.set_xticks(x)
    ax2.set_xticklabels(quality["warehouse_name"], rotation=20, ha="right")
    ax2.set_title("Order Quality Issues")
    ax2.set_ylabel("% of orders")
    ax2.legend()

    fig.suptitle("Warehouse Performance: Scale vs. Quality",
                 fontsize=14, fontweight="bold", y=1.02)
    return _save(fig, "warehouse_comparison")


def plot_inventory_turnover(turnover_df: pd.DataFrame) -> str:
    """Inventory turnover by category — how fast each category's stock cycles."""
    df = turnover_df.dropna(subset=["inventory_turnover"]).sort_values("inventory_turnover")

    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.barh(df["category"], df["inventory_turnover"], color=PALETTE["secondary"])

    for bar, dos in zip(bars, df["days_of_supply"]):
        ax.text(bar.get_width() + 0.02, bar.get_y() + bar.get_height() / 2,
                f"{dos:.0f}d supply", va="center", fontsize=8, color=PALETTE["neutral"])

    ax.set_title("Annualized Inventory Turnover by Category")
    ax.set_xlabel("Turnover (times per year — higher means stock cycles faster)")
    ax.set_xlim(0, df["inventory_turnover"].max() * 1.25)
    return _save(fig, "inventory_turnover")
