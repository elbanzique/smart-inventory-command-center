# Power BI Build Guide — Smart Inventory Command Center

This guide takes you from the exported CSVs to a finished four-page report.
Budget roughly 60–90 minutes for the first build.

> **Why there's no `.pbix` in this repo.** Power BI's `.pbix` is a
> proprietary, Windows-only binary format with no supported programmatic
> authoring path — it can't be generated from Python. What *can* be
> prepared in advance is everything that carries the analytical substance:
> the dimensional model (`src/etl/export_for_powerbi.py`), the complete
> measure library (`powerbi/measures.dax`), and this build spec. You
> assemble the visuals in Power BI Desktop, which also means the report is
> genuinely your own work to talk through in an interview.

---

## Step 0 — Prerequisites

Run the pipeline in order, from the project root:

```bash
python -m src.data_generation.generate_all   # writes data/raw/*.csv
python -m src.etl.load_to_db                 # builds data/database/novalog.db
python -m src.analysis.generate_report       # Phase 5 analysis (scorecard feeds dim_supplier)
python -m src.etl.export_for_powerbi         # writes data/powerbi_export/*.csv
```

The last step prints a validation report. Every check must pass before you
load anything into Power BI — a broken key produces silent blanks in
visuals rather than an error, which is much harder to debug later.

You'll need **Power BI Desktop** (free, Windows only). On macOS or Linux,
use a Windows VM, or substitute Tableau Public / Looker Studio — the star
schema and measure logic transfer with minor syntax changes.

---

## Step 1 — Load the data

1. Open Power BI Desktop → **Home → Get data → Text/CSV**.
2. Load all seven files from `data/powerbi_export/`:
   `dim_date`, `dim_product`, `dim_supplier`, `dim_warehouse`,
   `fact_sales`, `fact_inventory`, `fact_purchase_orders`.
3. For each, click **Transform Data** rather than Load directly, and check
   the column types Power Query inferred. Specifically confirm:
   - `dim_date[date]` is **Date** (not Text)
   - all `*_id` and `date_key` columns are **Whole Number**
   - `line_revenue`, `line_margin`, `inventory_value` are **Decimal Number**
   - `is_late`, `is_delivered`, `is_below_reorder_point` are **True/False**

   Getting these wrong is the most common cause of relationships that
   refuse to connect, and of measures that return blank.
4. **Close & Apply**.

---

## Step 2 — Build the relationships

Go to **Model view**. Power BI will have auto-detected some relationships;
delete all of them and create these explicitly so you know exactly what the
model contains.

| From (fact, many side) | To (dimension, one side) | Cardinality | Cross-filter |
|---|---|---|---|
| `fact_sales[date_key]` | `dim_date[date_key]` | Many-to-one | Single |
| `fact_sales[product_id]` | `dim_product[product_id]` | Many-to-one | Single |
| `fact_sales[warehouse_id]` | `dim_warehouse[warehouse_id]` | Many-to-one | Single |
| `fact_inventory[product_id]` | `dim_product[product_id]` | Many-to-one | Single |
| `fact_inventory[warehouse_id]` | `dim_warehouse[warehouse_id]` | Many-to-one | Single |
| `fact_purchase_orders[supplier_id]` | `dim_supplier[supplier_id]` | Many-to-one | Single |
| `fact_purchase_orders[product_id]` | `dim_product[product_id]` | Many-to-one | Single |
| `fact_purchase_orders[date_key]` | `dim_date[date_key]` | Many-to-one | Single |

**Keep every cross-filter direction as Single.** Bidirectional filtering is
tempting and occasionally necessary, but it creates ambiguous filter paths
in a model with multiple facts sharing dimensions, which leads to numbers
that are wrong in ways no error message will tell you about. If you need to
filter in the other direction for one specific measure, use `CROSSFILTER()`
inside that measure rather than changing the model.

### Two required model settings

1. **Mark the date table.** Select `dim_date` → **Table tools → Mark as
   date table** → Date column: `date`. Every time-intelligence measure
   (`TOTALYTD`, `SAMEPERIODLASTYEAR`, `DATEADD`) depends on this. Skip it
   and they return plausible-looking wrong answers.
2. **Fix month sorting.** Select `dim_date[month_name]` → **Column tools →
   Sort by column → `month_sort`**. Without this, every chart sorts months
   alphabetically (Apr, Aug, Dec, Feb…).

---

## Step 3 — Add the measures

1. **Home → Enter data**, leave the table empty, name it `_Measures`, Load.
   (This gives you one tidy home for measures instead of scattering them
   across fact tables.)
2. Open `powerbi/measures.dax` and add each measure: select `_Measures` →
   **New measure** → paste one measure → Enter.
3. Set formatting as you go — it's much more annoying retroactively:
   - Currency measures (`Total Revenue`, `Total Margin`, `Inventory Value`,
     `Dead Stock Value`): Currency, 0 decimals
   - Percentage measures (`Margin %`, `Return Rate %`, `Stockout Risk %`,
     `Late Delivery Rate %`, `Revenue YoY %`): Percentage, 1 decimal
   - `Inventory Turnover`: Decimal, 2 decimals

**Sanity check before going further.** Drop a card visual with
`[Total Revenue]` on the page. It should read approximately **$51.6M**,
matching the "Delivered revenue" line in `reports/insights_report.md`. If it
doesn't, your relationships or column types are wrong — fix that now rather
than building four pages on a broken model.

---

## Step 4 — Build the report pages

### Page 1: Executive Overview

*Purpose: the single page an operations director looks at each morning.*

- **KPI cards across the top:** `Total Revenue`, `Margin %`,
  `Inventory Value`, `Stockout Risk %`, `High Risk Suppliers`
- **Line chart:** `dim_date[year_month]` on the axis, `Total Revenue` as
  values, `dim_warehouse[name]` as legend — this is the seasonality story
- **Bar chart:** `dim_product[category]` by `Total Revenue`
- **Slicers:** `dim_date[year]`, `dim_warehouse[region]`

### Page 2: Warehouse Performance

*Purpose: answer "which warehouse performs best?" without letting size alone decide.*

- **Table:** `dim_warehouse[name]` with `Total Revenue`,
  `Order Count`, `Average Order Value`, `Return Rate %`
- **Clustered column + line combo:** revenue as columns, `Return Rate %` as
  the line on a secondary axis — this is the visual that makes the
  scale-vs-quality trade-off obvious
- **Matrix:** warehouses as rows, `dim_product[category]` as columns,
  `Total Revenue` as values

> Put conditional formatting on `Return Rate %` (red above ~7.5%). Ranking
> warehouses on revenue alone rewards whichever facility is biggest; the
> whole point of this page is showing both dimensions together.

### Page 3: Inventory Health

*Purpose: where is capital stuck, and what needs reordering?*

- **KPI cards:** `Inventory Value`, `Dead Stock Value`,
  `Dead Stock % of Inventory`, `SKUs Below Reorder Point`
- **Donut:** `Inventory Value` by `dim_product[abc_class]`
- **Bar:** `Dead Stock Value` by `dim_product[category]`
- **Table (the actionable one):** `dim_product[sku]`, `category`,
  `quantity_on_hand`, `reorder_point`, filtered to
  `is_below_reorder_point = True`, sorted ascending by `quantity_on_hand`
- **Scatter:** `Inventory Turnover` (x) vs `Inventory Value` (y), one point
  per category — bottom-right quadrant is the problem zone (high value,
  low turnover)

### Page 4: Supplier Scorecard

*Purpose: who do we escalate with, and who do we keep?*

- **KPI cards:** `On-Time Delivery Rate %`, `Average Delay Days`,
  `High Risk Suppliers`
- **Table:** `dim_supplier[name]`, `region`, `composite_score`,
  `risk_tier`, `Late Delivery Rate %`, `Average Delay Days`, sorted
  ascending by `composite_score`
- **Bar:** bottom 15 suppliers by `composite_score`, colored by `risk_tier`
  (High Risk red / Monitor amber / Preferred green)
- **Line:** `Late Delivery Rate %` by `dim_date[year_month]` — shows whether
  reliability is degrading over time
- **Slicer:** `dim_supplier[risk_tier]`

---

## Step 5 — Polish

These are what separate a report that looks like a tutorial exercise from
one that looks like a deliverable:

- Consistent theme (**View → Themes**); pick one accent color and stay with it
- Every visual gets a title stating the insight, not the mechanics —
  "Central DC leads revenue but carries the highest return rate" beats
  "Sum of Revenue by Warehouse"
- Turn off visual interactions that aren't useful (**Format → Edit interactions**)
- Add a title bar with the report name and a `[Selected Period Label]` card
- Set **Page view → Fit to page** so it renders predictably for reviewers

---

## Step 6 — Ship it

1. Save as `powerbi/novalog_dashboard.pbix`.
2. Export each page: **File → Export → Export to PDF**, or screenshot each
   page to `powerbi/screenshots/`.
3. Add 2–3 screenshots to the project README — most people reviewing a
   GitHub portfolio will never open Power BI, so the screenshots *are* the
   dashboard as far as they're concerned.

---

## Refreshing after a data change

If you re-run the pipeline, the CSV paths don't change, so in Power BI it's
just **Home → Refresh**. Nothing in the model or measures needs rebuilding.

## Talking points for an interview

Worth being able to speak to, since these are the deliberate decisions:

- **Why a star schema rather than connecting to the normalized database.**
  DAX and the VertiPaq engine are built for one-to-many dimension-to-fact
  filtering; a normalized model forces bidirectional and snowflaked
  relationships that are slow and ambiguous.
- **Why a dedicated `dim_date` table.** Time intelligence functions require
  a contiguous, gap-free date dimension marked as the model's date table.
- **Why every cross-filter stays Single.** Bidirectional filters in a
  multi-fact model create ambiguous paths and silently wrong numbers.
- **Why generation artifacts are dropped from the export.**
  `popularity_score` and `base_reliability_score` were inputs the synthetic
  data generator used. A real analyst never has them, and leaving them in
  would let the analysis trivially "cheat" — the supplier risk tiers are
  earned from observed delivery behavior instead.
