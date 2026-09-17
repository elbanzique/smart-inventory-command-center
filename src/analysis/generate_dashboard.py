"""
Generates a self-contained, static HTML dashboard as an alternative to the
Power BI report (see docs/powerbi_guide.md) for anyone who wants to see the
results immediately without installing Power BI Desktop.

This deliberately reuses the same Phase 5 analysis functions that produce
reports/insights_report.md (classify_abc, build_supplier_scorecard,
analyze_dead_stock, ...) rather than re-deriving the numbers independently.
That matters: if this script computed its own revenue or dead-stock figures
via a second, parallel calculation, a bug in either one could make the two
reports silently disagree. Reusing the same functions means there is
exactly one definition of "dead stock" or "revenue" in the whole project,
and this dashboard and the markdown report are guaranteed to agree.

All data is embedded directly in the HTML as a JSON blob (no fetch calls,
no server) so the single output file can be opened straight from the
filesystem in any browser - no `python -m http.server` required.

Run from the project root (after src/etl/load_to_db.py):
    python -m src.analysis.generate_dashboard

Output: reports/dashboard.html
"""

import json

import numpy as np
import pandas as pd

from src import config
from src.analysis.abc_analysis import abc_summary, classify_abc
from src.analysis.dead_stock import analyze_dead_stock, dead_stock_by_category
from src.analysis.db import load_inventory_detail, load_sales_detail, load_table
from src.analysis.supplier_scorecard import build_supplier_scorecard

REPORTS_DIR = config.PROJECT_ROOT / "reports"


def _build_dashboard_data() -> dict:
    """Compute every number the dashboard needs, all derived from the same
    Phase 5 functions used to build reports/insights_report.md."""

    print("Loading data...")
    sales = load_sales_detail()
    inventory = load_inventory_detail()
    orders = load_table("orders").merge(
        load_table("warehouses")[["warehouse_id", "name"]].rename(columns={"name": "warehouse_name"}),
        on="warehouse_id",
    )

    print("Running ABC analysis...")
    abc = classify_abc(sales)
    abc_sum = abc_summary(abc)

    print("Building supplier scorecard...")
    scorecard = build_supplier_scorecard()

    print("Analyzing dead stock...")
    dead = analyze_dead_stock()
    dead_cat = dead_stock_by_category(dead)

    # --- KPI ribbon ---------------------------------------------------------
    total_revenue = sales["line_revenue"].sum()
    total_margin = sales["line_margin"].sum()
    inventory_value = inventory["inventory_value"].sum()
    # "Dead stock" as the headline KPI matches reports/insights_report.md's
    # own primary figure (Dead only). Dead + Slow-Moving is a broader, related
    # number the report lists separately as secondary context - conflating
    # the two here would make this dashboard's headline silently disagree
    # with the written report's headline, even though neither number is
    # wrong on its own.
    dead_only_value = dead[dead["stock_status"] == "Dead"]["inventory_value"].sum()
    dead_plus_slow_value = dead[dead["stock_status"].isin(["Dead", "Slow-Moving"])]["inventory_value"].sum()
    stockout_mask = inventory["quantity_on_hand"] < inventory["reorder_point"]
    risk_counts = scorecard["risk_tier"].value_counts().to_dict()

    kpi = {
        "revenue_m": round(total_revenue / 1e6, 1),
        "margin_m": round(total_margin / 1e6, 1),
        "margin_pct": round(100 * total_margin / total_revenue, 1),
        "inventory_value_m": round(inventory_value / 1e6, 1),
        "dead_stock_m": round(dead_only_value / 1e6, 1),
        "dead_stock_pct": round(100 * dead_only_value / inventory_value, 1),
        "dead_plus_slow_m": round(dead_plus_slow_value / 1e6, 1),
        "stockout_count": int(stockout_mask.sum()),
        "stockout_total": int(len(inventory)),
        "stockout_pct": round(100 * stockout_mask.mean(), 1),
        "high_risk_suppliers": int(risk_counts.get("High Risk", 0)),
        "total_suppliers": int(len(scorecard)),
    }

    # --- Monthly revenue by warehouse (line chart) --------------------------
    sales_m = sales.copy()
    sales_m["year_month"] = sales_m["order_date"].dt.to_period("M").astype(str)
    monthly = (
        sales_m.groupby(["year_month", "warehouse_name"])["line_revenue"]
        .sum()
        .unstack()
        .fillna(0)
        .round(0)
        .sort_index()
    )

    # --- Warehouse performance table -----------------------------------------
    # Revenue/AOV from `sales` (Delivered only, matches the KPI ribbon and
    # viz.plot_warehouse_comparison); return/cancel rate from `orders` (all
    # statuses) since that rate is meaningless restricted to Delivered orders.
    revenue_by_wh = sales.groupby("warehouse_name").agg(
        total_revenue=("line_revenue", "sum"),
        delivered_orders=("order_id", "nunique"),
    )
    quality_by_wh = orders.groupby("warehouse_name").agg(
        total_orders=("order_id", "nunique"),
        return_rate_pct=("status", lambda s: round(100 * (s == "Returned").mean(), 2)),
        cancel_rate_pct=("status", lambda s: round(100 * (s == "Cancelled").mean(), 2)),
    )
    wh_table = revenue_by_wh.join(quality_by_wh).reset_index()
    wh_table["avg_order_value"] = (wh_table["total_revenue"] / wh_table["delivered_orders"]).round(2)
    wh_table["total_revenue"] = wh_table["total_revenue"].round(2)
    wh_table = wh_table.sort_values("total_revenue", ascending=False)

    # --- Top revenue products (already ranked by classify_abc) --------------
    top_products = abc.head(10)[["sku", "category", "units_sold", "total_revenue"]]

    # --- ABC pareto curve, downsampled to ~60 points for a smooth SVG path ---
    step = max(1, len(abc) // 60)
    pareto = list(
        zip(
            (100 * (abc["rank"].iloc[::step]) / len(abc)).round(2),
            (100 * abc["cumulative_revenue_share"].iloc[::step]).round(2),
        )
    )

    # --- Supplier risk (bottom 15 by composite score) ------------------------
    suppliers = scorecard.head(15)[["supplier_name", "composite_score", "risk_tier", "late_delivery_rate_pct"]]

    return {
        "kpi": kpi,
        "months": monthly.index.tolist(),
        "monthly_series": {col: monthly[col].tolist() for col in monthly.columns},
        "warehouses": wh_table.to_dict("records"),
        "top_products": top_products.to_dict("records"),
        "dead_stock_by_category": dead_cat.rename(
            columns={"problem_positions": "positions", "capital_tied_up": "value"}
        ).to_dict("records"),
        "dead_stock_total": round(float(dead_cat["capital_tied_up"].sum()), 2),
        "suppliers": suppliers.to_dict("records"),
        "abc_summary": abc_sum.to_dict("records"),
        "pareto": [[float(x), float(y)] for x, y in pareto],
    }


# ---------------------------------------------------------------------------
# HTML template. Kept as one string (rather than a Jinja/template-file setup)
# because this is the only place it's used and a templating dependency would
# be overkill for a single static page.
# ---------------------------------------------------------------------------
_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Smart Inventory Command Center</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #f3f4f7; --panel: #ffffff; --panel-border: #dde1e8; --header-strip: #eceef2;
    --text: #131a26; --text-dim: #5c6b82; --text-faint: #8b97ab;
    --amber: #b9822e; --teal: #2e9483; --red: #b03f30; --blue: #3a6fd8;
    --grid-line: rgba(0,0,0,0.06);
    --mono: 'IBM Plex Mono', 'SFMono-Regular', Consolas, monospace;
    --display: 'Space Grotesk', -apple-system, 'Segoe UI', sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #0b1220; --panel: #121b2e; --panel-border: #24304a; --header-strip: #182338;
      --text: #e6eaf2; --text-dim: #93a0b8; --text-faint: #64708a;
      --amber: #d6a24b; --teal: #4fb7a8; --red: #d16853; --blue: #6f9aef;
      --grid-line: rgba(255,255,255,0.06);
    }
  }
  :root[data-theme="dark"] {
    --bg: #0b1220; --panel: #121b2e; --panel-border: #24304a; --header-strip: #182338;
    --text: #e6eaf2; --text-dim: #93a0b8; --text-faint: #64708a;
    --amber: #d6a24b; --teal: #4fb7a8; --red: #d16853; --blue: #6f9aef;
    --grid-line: rgba(255,255,255,0.06);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font-family: var(--mono); font-size: 13px; line-height: 1.5; }
  .wrap { max-width: 1360px; margin: 0 auto; padding: 28px 20px 60px; }
  header.top { display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 12px; border-bottom: 2px solid var(--panel-border); padding-bottom: 18px; margin-bottom: 22px; }
  header.top h1 { font-family: var(--display); font-weight: 700; font-size: 26px; letter-spacing: 0.3px; margin: 0 0 4px; }
  header.top .sub { color: var(--text-dim); font-size: 13px; }
  header.top .badge { font-family: var(--mono); font-size: 11.5px; color: var(--text-dim); border: 1px solid var(--panel-border); padding: 6px 10px; white-space: nowrap; }
  .kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; margin-bottom: 22px; }
  .kpi { background: var(--panel); border: 1px solid var(--panel-border); border-top: 3px solid var(--accent, var(--teal)); padding: 14px 16px; }
  .kpi .val { font-family: var(--display); font-weight: 700; font-size: 24px; }
  .kpi .label { color: var(--text-dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.6px; margin-top: 2px; }
  .kpi .sub { color: var(--text-faint); font-size: 11px; margin-top: 6px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(480px, 1fr)); gap: 14px; margin-bottom: 14px; }
  .panel { background: var(--panel); border: 1px solid var(--panel-border); grid-column: span 1; min-width: 0; }
  .panel.full { grid-column: 1 / -1; }
  .panel .phead { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: var(--header-strip); border-bottom: 1px solid var(--panel-border); }
  .panel .phead .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dotcolor, var(--teal)); flex-shrink: 0; }
  .panel .phead h2 { font-family: var(--display); font-size: 13.5px; font-weight: 600; margin: 0; flex: 1; }
  .panel .phead .meta { color: var(--text-faint); font-size: 11px; }
  .panel .pbody { padding: 14px; overflow-x: auto; }
  table { border-collapse: collapse; width: 100%; font-size: 12px; white-space: nowrap; }
  th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--grid-line); }
  th { color: var(--text-dim); font-weight: 500; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.4px; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  tr:last-child td { border-bottom: none; }
  canvas { max-width: 100%; }
  footer { margin-top: 26px; padding-top: 16px; border-top: 1px solid var(--panel-border); color: var(--text-faint); font-size: 11px; line-height: 1.7; }
  footer b { color: var(--text-dim); }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div>
      <h1>SMART INVENTORY COMMAND CENTER</h1>
      <div class="sub">NovaLog Distribution &mdash; Supply Chain Analytics Snapshot</div>
    </div>
    <div class="badge">GENERATED: __GENERATED_AT__ &nbsp;&middot;&nbsp; STATIC SNAPSHOT (not live&#8209;connected)</div>
  </header>

  <div class="kpi-row" id="kpiRow"></div>

  <div class="grid">
    <div class="panel full">
      <div class="phead"><span class="dot" style="--dotcolor:var(--teal)"></span><h2>MONTHLY REVENUE BY WAREHOUSE</h2><span class="meta">delivered orders only</span></div>
      <div class="pbody"><canvas id="chartMonthly" height="80"></canvas></div>
    </div>
  </div>
  <div class="grid">
    <div class="panel">
      <div class="phead"><span class="dot" style="--dotcolor:var(--blue)"></span><h2>WAREHOUSE PERFORMANCE</h2></div>
      <div class="pbody" id="whTable"></div>
    </div>
    <div class="panel">
      <div class="phead"><span class="dot" style="--dotcolor:var(--amber)"></span><h2>ABC REVENUE CONCENTRATION</h2><span class="meta" id="abcMeta"></span></div>
      <div class="pbody"><canvas id="chartAbc" height="180"></canvas></div>
    </div>
  </div>
  <div class="grid">
    <div class="panel">
      <div class="phead"><span class="dot" style="--dotcolor:var(--teal)"></span><h2>TOP REVENUE PRODUCTS</h2><span class="meta">top 10</span></div>
      <div class="pbody" id="topTable"></div>
    </div>
    <div class="panel">
      <div class="phead"><span class="dot" style="--dotcolor:var(--red)"></span><h2>DEAD + SLOW-MOVING STOCK BY CATEGORY</h2><span class="meta" id="deadMeta"></span></div>
      <div class="pbody"><canvas id="chartDead" height="200"></canvas></div>
    </div>
  </div>
  <div class="grid">
    <div class="panel full">
      <div class="phead"><span class="dot" style="--dotcolor:var(--red)"></span><h2>SUPPLIER RELIABILITY &mdash; BOTTOM 15 BY COMPOSITE SCORE</h2><span class="meta">computed from observed purchase-order behavior only</span></div>
      <div class="pbody"><canvas id="chartSupplier" height="230"></canvas></div>
    </div>
  </div>

  <footer>
    Generated by <b>src/analysis/generate_dashboard.py</b> directly from <b>novalog.db</b>,
    reusing the same Phase 5 functions (<b>classify_abc</b>, <b>build_supplier_scorecard</b>,
    <b>analyze_dead_stock</b>) that produce <b>reports/insights_report.md</b> &mdash; the
    numbers here and in that report are guaranteed to match. This exists as an
    immediately-viewable alternative to the Power BI report in
    <b>docs/powerbi_guide.md</b>, which requires Power BI Desktop (Windows only).
  </footer>
</div>

<script id="dashboard-data" type="application/json">__DATA_JSON__</script>
<script>
const DATA = JSON.parse(document.getElementById('dashboard-data').textContent);
const css = getComputedStyle(document.documentElement);
const col = (name) => css.getPropertyValue(name).trim();
const fmtM = (n) => '$' + n.toFixed(1) + 'M';
const fmtUSD = (n) => '$' + Number(n).toLocaleString(undefined, {maximumFractionDigits: 0});
const fmtNum = (n) => Number(n).toLocaleString();

Chart.defaults.font.family = "'IBM Plex Mono', monospace";
Chart.defaults.font.size = 11;
Chart.defaults.color = col('--text-dim');
Chart.defaults.borderColor = col('--grid-line');

const k = DATA.kpi;
const kpis = [
  {v: fmtM(k.revenue_m), l: 'Delivered Revenue', s: '2-year window', a: '--teal'},
  {v: fmtM(k.margin_m), l: 'Gross Margin', s: k.margin_pct + '% of revenue', a: '--teal'},
  {v: fmtM(k.inventory_value_m), l: 'Inventory Value', s: fmtNum(k.stockout_total) + ' positions', a: '--amber'},
  {v: fmtM(k.dead_stock_m), l: 'Dead Stock Capital', s: k.dead_stock_pct + '% of inventory &middot; +' + fmtM(k.dead_plus_slow_m - k.dead_stock_m) + ' slow-moving', a: '--red'},
  {v: fmtNum(k.stockout_count), l: 'Stockout-Risk Positions', s: k.stockout_pct + '% of positions', a: '--amber'},
  {v: k.high_risk_suppliers + ' / ' + k.total_suppliers, l: 'High-Risk Suppliers', s: 'flagged by composite score', a: '--red'},
];
document.getElementById('kpiRow').innerHTML = kpis.map(x =>
  `<div class="kpi" style="--accent:var(${x.a})"><div class="val">${x.v}</div><div class="label">${x.l}</div><div class="sub">${x.s}</div></div>`
).join('');

const whColors = { 'Central Distribution Center': col('--teal'), 'East Coast Distribution Center': col('--blue'), 'West Coast Distribution Center': col('--amber') };
new Chart(document.getElementById('chartMonthly'), {
  type: 'line',
  data: { labels: DATA.months, datasets: Object.keys(DATA.monthly_series).map(name => ({
    label: name, data: DATA.monthly_series[name], borderColor: whColors[name] || col('--text-dim'),
    backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.25,
  })) },
  options: { responsive: true, interaction: { mode: 'index', intersect: false },
    plugins: { legend: { position: 'top', labels: { boxWidth: 10, usePointStyle: true } } },
    scales: { y: { ticks: { callback: (v) => '$' + (v/1000).toFixed(0) + 'k' }, grid: { color: col('--grid-line') } }, x: { grid: { display: false } } } }
});

document.getElementById('whTable').innerHTML = `<table>
  <tr><th>Warehouse</th><th class="num">Orders</th><th class="num">Revenue</th><th class="num">AOV</th><th class="num">Return %</th><th class="num">Cancel %</th></tr>
  ${DATA.warehouses.map(w => `<tr>
    <td>${w.warehouse_name}</td><td class="num">${fmtNum(w.total_orders)}</td>
    <td class="num">${fmtUSD(w.total_revenue)}</td><td class="num">$${w.avg_order_value.toFixed(2)}</td>
    <td class="num">${w.return_rate_pct}%</td><td class="num">${w.cancel_rate_pct}%</td>
  </tr>`).join('')}
</table>`;

const classA = DATA.abc_summary.find(r => r.abc_class === 'A');
document.getElementById('abcMeta').textContent = `Class A: ${classA.pct_of_skus}% of SKUs -> ${classA.pct_of_revenue}% of revenue`;
new Chart(document.getElementById('chartAbc'), {
  type: 'line',
  data: { datasets: [{ label: 'Cumulative revenue share', data: DATA.pareto.map(p => ({x: p[0], y: p[1]})),
    borderColor: col('--amber'), backgroundColor: col('--amber') + '22', fill: true, borderWidth: 2, pointRadius: 0, tension: 0.15 }] },
  options: { responsive: true, plugins: { legend: { display: false } },
    scales: { x: { type: 'linear', min: 0, max: 100, title: { display: true, text: '% of SKUs (ranked by revenue)' }, grid: { color: col('--grid-line') } },
              y: { min: 0, max: 100, title: { display: true, text: '% of revenue' }, grid: { color: col('--grid-line') } } } }
});

document.getElementById('topTable').innerHTML = `<table>
  <tr><th>SKU</th><th>Category</th><th class="num">Units</th><th class="num">Revenue</th></tr>
  ${DATA.top_products.map(p => `<tr><td>${p.sku}</td><td>${p.category}</td>
    <td class="num">${fmtNum(p.units_sold)}</td><td class="num">${fmtUSD(p.total_revenue)}</td></tr>`).join('')}
</table>`;

document.getElementById('deadMeta').textContent = 'total ' + fmtUSD(DATA.dead_stock_total);
new Chart(document.getElementById('chartDead'), {
  type: 'bar',
  data: { labels: DATA.dead_stock_by_category.map(d => d.category),
    datasets: [{ data: DATA.dead_stock_by_category.map(d => d.value), backgroundColor: col('--red') }] },
  options: { indexAxis: 'y', responsive: true, plugins: { legend: { display: false } },
    scales: { x: { ticks: { callback: (v) => '$' + (v/1000).toFixed(0) + 'k' }, grid: { color: col('--grid-line') } }, y: { grid: { display: false } } } }
});

const tierColor = (t) => t === 'High Risk' ? col('--red') : t === 'Monitor' ? col('--amber') : col('--teal');
new Chart(document.getElementById('chartSupplier'), {
  type: 'bar',
  data: { labels: DATA.suppliers.map(s => s.supplier_name),
    datasets: [{ data: DATA.suppliers.map(s => s.composite_score), backgroundColor: DATA.suppliers.map(s => tierColor(s.risk_tier)) }] },
  options: { indexAxis: 'y', responsive: true,
    plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: (ctx) => DATA.suppliers[ctx.dataIndex].late_delivery_rate_pct + '% late deliveries' } } },
    scales: { x: { min: 0, max: 100, title: { display: true, text: 'Composite reliability score (0-100)' }, grid: { color: col('--grid-line') } }, y: { grid: { display: false } } } }
});
</script>
</body>
</html>
"""


def main() -> None:
    import datetime

    data = _build_dashboard_data()

    print("Rendering HTML...")
    html = _HTML_TEMPLATE.replace("__DATA_JSON__", json.dumps(data))
    html = html.replace("__GENERATED_AT__", datetime.date.today().isoformat())

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / "dashboard.html"
    out_path.write_text(html, encoding="utf-8")

    print(f"\nWrote {out_path} ({len(html):,} bytes)")
    print(f"Open it directly in a browser: file://{out_path.resolve()}")


if __name__ == "__main__":
    main()
