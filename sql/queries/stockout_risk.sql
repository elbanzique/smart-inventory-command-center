-- Which SKUs are at risk of stockout?
--
-- "At risk" = current quantity_on_hand has already fallen below the
-- product's reorder_point in a specific warehouse. This is reported at the
-- warehouse level (not aggregated company-wide) because stockout is an
-- operational, per-location problem — a product might be fine overall but
-- critically low in one specific warehouse that needs to act on it.

SELECT
    p.product_id,
    p.sku,
    p.category,
    w.name AS warehouse_name,
    i.quantity_on_hand,
    p.reorder_point,
    p.safety_stock,
    ROUND(100.0 * i.quantity_on_hand / NULLIF(p.reorder_point, 0), 1) AS pct_of_reorder_point
FROM inventory i
JOIN products p   ON p.product_id   = i.product_id
JOIN warehouses w ON w.warehouse_id = i.warehouse_id
WHERE i.quantity_on_hand < p.reorder_point
ORDER BY pct_of_reorder_point ASC
LIMIT 50;
