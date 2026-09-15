-- Which products should be reordered?
--
-- Goes beyond "flag anything below reorder_point" by sizing a concrete
-- recommended_order_quantity: enough to cover safety_stock plus the last
-- 30 days of actual sales velocity, minus what's already on hand.
--
-- Grain: this runs at (product, warehouse), matching stockout_risk.sql —
-- reorder_point/safety_stock are per-warehouse thresholds (that's how
-- inventory.py used them during data generation), so stock and demand
-- must both be compared at that same per-warehouse level. Aggregating
-- stock across all 3 warehouses first and comparing it to a single
-- warehouse's threshold would almost always look "healthy" even when one
-- specific warehouse is genuinely running low — exactly the bug this
-- query avoids.
--
-- "Last 30 days" is anchored to the most recent order_date in the dataset
-- (via the sim_today CTE) rather than a real wall-clock date, since this
-- is a fixed historical simulation, not a live system with a real "today".

WITH sim_today AS (
    SELECT MAX(order_date) AS today FROM orders
),
recent_sales AS (
    SELECT
        o.warehouse_id,
        ol.product_id,
        SUM(ol.quantity) AS units_sold_last_30_days
    FROM order_lines ol
    JOIN orders o ON o.order_id = ol.order_id
    CROSS JOIN sim_today
    WHERE o.order_date >= date(sim_today.today, '-30 days')
    GROUP BY o.warehouse_id, ol.product_id
)
SELECT
    p.product_id,
    p.sku,
    p.category,
    w.name AS warehouse_name,
    i.quantity_on_hand,
    p.reorder_point,
    p.safety_stock,
    COALESCE(rs.units_sold_last_30_days, 0)                  AS units_sold_last_30_days,
    ROUND(COALESCE(rs.units_sold_last_30_days, 0) / 30.0, 2) AS avg_daily_demand,
    MAX(0, p.safety_stock + COALESCE(rs.units_sold_last_30_days, 0) - i.quantity_on_hand)
                                                              AS recommended_order_quantity
FROM inventory i
JOIN products p   ON p.product_id   = i.product_id
JOIN warehouses w ON w.warehouse_id = i.warehouse_id
LEFT JOIN recent_sales rs
    ON rs.product_id = i.product_id AND rs.warehouse_id = i.warehouse_id
WHERE i.quantity_on_hand < p.reorder_point
ORDER BY recommended_order_quantity DESC
LIMIT 50;
