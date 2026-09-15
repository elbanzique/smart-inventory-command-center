-- Which products generate the most revenue?
--
-- Revenue alone can be misleading (a high-revenue product with razor-thin
-- margin may matter less than a mid-revenue, high-margin one), so this
-- query reports total_margin alongside total_revenue — both computed from
-- the actual sale price (unit_price_at_sale), not the current catalog
-- price, since prices can drift over the 2-year window.

SELECT
    p.product_id,
    p.sku,
    p.category,
    COUNT(DISTINCT ol.order_id)                                        AS orders_containing_product,
    SUM(ol.quantity)                                                   AS units_sold,
    ROUND(SUM(ol.quantity * ol.unit_price_at_sale), 2)                 AS total_revenue,
    ROUND(SUM(ol.quantity * (ol.unit_price_at_sale - p.unit_cost)), 2)  AS total_margin
FROM order_lines ol
JOIN products p ON p.product_id = ol.product_id
GROUP BY p.product_id, p.sku, p.category
ORDER BY total_revenue DESC
LIMIT 20;
