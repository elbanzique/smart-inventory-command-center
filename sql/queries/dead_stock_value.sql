-- How much inventory value is tied up in dead stock?
--
-- "Dead stock" = quantity_on_hand at least 4x the product's safety_stock —
-- far more inventory than any reasonable demand buffer would require. This
-- threshold mirrors the one documented in docs/data_dictionary.md for the
-- data-generation step, so the analysis is checking the same definition
-- the data was built around.
--
-- Valued at unit_cost (not unit_price) because dead stock represents
-- capital NovaLog already spent acquiring the inventory — that's the real
-- money tied up, not the revenue it would have generated if sold.

SELECT
    p.category,
    COUNT(*)                                       AS dead_stock_positions,
    SUM(i.quantity_on_hand)                        AS total_units_tied_up,
    ROUND(SUM(i.quantity_on_hand * p.unit_cost), 2) AS dead_stock_value
FROM inventory i
JOIN products p ON p.product_id = i.product_id
WHERE i.quantity_on_hand >= p.safety_stock * 4
GROUP BY p.category
ORDER BY dead_stock_value DESC;
