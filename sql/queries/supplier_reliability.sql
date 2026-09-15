-- Which suppliers are unreliable?
--
-- Deliberately does NOT use suppliers.base_reliability_score — that column
-- only exists because the data-generation script needed a seed value to
-- produce realistic delay patterns (see docs/data_dictionary.md). A real
-- analyst has no such column; reliability has to be measured empirically
-- from what actually happened, which is exactly what this query does:
-- lateness rate and average delay, computed purely from purchase_orders
-- history.
--
-- HAVING delivered_pos >= 5 excludes suppliers with too few completed POs
-- to draw a meaningful conclusion from (a supplier with 1 late delivery
-- out of 1 total looks "100% unreliable" but that's noise, not signal).

SELECT
    s.supplier_id,
    s.name AS supplier_name,
    s.region,
    s.primary_category,
    COUNT(*)                                                            AS total_purchase_orders,
    SUM(CASE WHEN po.actual_delivery_date IS NOT NULL THEN 1 ELSE 0 END) AS delivered_pos,
    ROUND(
        100.0 * SUM(CASE
                WHEN po.actual_delivery_date IS NOT NULL
                     AND po.actual_delivery_date > po.expected_delivery_date
                THEN 1 ELSE 0 END)
        / NULLIF(SUM(CASE WHEN po.actual_delivery_date IS NOT NULL THEN 1 ELSE 0 END), 0),
        2
    ) AS late_delivery_rate_pct,
    ROUND(
        AVG(CASE
                WHEN po.actual_delivery_date IS NOT NULL
                THEN JULIANDAY(po.actual_delivery_date) - JULIANDAY(po.expected_delivery_date)
            END),
        2
    ) AS avg_delay_days
FROM purchase_orders po
JOIN suppliers s ON s.supplier_id = po.supplier_id
GROUP BY s.supplier_id, s.name, s.region, s.primary_category
HAVING delivered_pos >= 5
ORDER BY late_delivery_rate_pct DESC
LIMIT 20;
