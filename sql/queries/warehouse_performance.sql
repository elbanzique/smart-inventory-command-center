-- Which warehouse performs best?
--
-- "Best" isn't just "biggest" — a warehouse with huge revenue but a high
-- return/cancellation rate is doing something worse operationally than a
-- smaller one running cleanly. This query surfaces both dimensions
-- together so the reader can judge trade-offs rather than being handed a
-- single misleading ranking.
--
-- order_revenue is computed once per order (not per order_line) in a CTE
-- before joining to warehouses — joining order_lines directly to warehouses
-- would multiply each order's status flag by however many line items it
-- has, silently inflating the return/cancellation rate calculations.

WITH order_revenue AS (
    SELECT
        order_id,
        SUM(quantity * unit_price_at_sale) AS order_revenue
    FROM order_lines
    GROUP BY order_id
)
SELECT
    w.warehouse_id,
    w.name                                                          AS warehouse_name,
    w.region,
    COUNT(*)                                                        AS total_orders,
    ROUND(SUM(orv.order_revenue), 2)                                AS total_revenue,
    ROUND(AVG(orv.order_revenue), 2)                                AS avg_order_value,
    ROUND(100.0 * SUM(CASE WHEN o.status = 'Returned' THEN 1 ELSE 0 END) / COUNT(*), 2)
                                                                     AS return_rate_pct,
    ROUND(100.0 * SUM(CASE WHEN o.status = 'Cancelled' THEN 1 ELSE 0 END) / COUNT(*), 2)
                                                                     AS cancellation_rate_pct
FROM orders o
JOIN warehouses w      ON w.warehouse_id = o.warehouse_id
JOIN order_revenue orv ON orv.order_id   = o.order_id
GROUP BY w.warehouse_id, w.name, w.region
ORDER BY total_revenue DESC;
