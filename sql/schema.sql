-- Smart Inventory Command Center — database schema
-- SQLite DDL for NovaLog Distribution's operational data model.
-- See docs/architecture.md for the full ERD and design rationale.
--
-- Date storage convention: all date/datetime columns are stored as TEXT in
-- ISO-8601 format ('YYYY-MM-DD'). SQLite has no native DATE type; ISO-8601
-- text sorts correctly with plain string comparison and works directly with
-- SQLite's built-in date()/julianday() functions, so there's no need for a
-- custom type or format.

PRAGMA foreign_keys = ON;

-- Drop in reverse dependency order so this script is safe to re-run.
DROP TABLE IF EXISTS order_lines;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS purchase_orders;
DROP TABLE IF EXISTS inventory;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS suppliers;
DROP TABLE IF EXISTS warehouses;

-- ---------------------------------------------------------------------------
-- Dimension tables
-- ---------------------------------------------------------------------------

CREATE TABLE warehouses (
    warehouse_id    INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    region          TEXT NOT NULL,
    capacity_units  INTEGER NOT NULL CHECK (capacity_units > 0)
);

CREATE TABLE suppliers (
    supplier_id             INTEGER PRIMARY KEY,
    name                    TEXT NOT NULL,
    region                  TEXT NOT NULL,
    primary_category        TEXT NOT NULL,
    base_reliability_score  REAL NOT NULL CHECK (base_reliability_score BETWEEN 0 AND 1),
    avg_lead_time_days      INTEGER NOT NULL CHECK (avg_lead_time_days > 0)
);

CREATE TABLE products (
    product_id       INTEGER PRIMARY KEY,
    sku              TEXT NOT NULL UNIQUE,
    category         TEXT NOT NULL,
    unit_cost        REAL NOT NULL CHECK (unit_cost > 0),
    unit_price       REAL NOT NULL CHECK (unit_price >= unit_cost),
    supplier_id      INTEGER NOT NULL REFERENCES suppliers(supplier_id),
    reorder_point    INTEGER NOT NULL CHECK (reorder_point >= 0),
    safety_stock     INTEGER NOT NULL CHECK (safety_stock >= 0),
    popularity_score REAL NOT NULL
);

-- ---------------------------------------------------------------------------
-- Fact / transactional tables
-- ---------------------------------------------------------------------------

CREATE TABLE inventory (
    warehouse_id       INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    product_id         INTEGER NOT NULL REFERENCES products(product_id),
    quantity_on_hand   INTEGER NOT NULL CHECK (quantity_on_hand >= 0),
    last_restock_date  TEXT NOT NULL,
    PRIMARY KEY (warehouse_id, product_id)
);

CREATE TABLE purchase_orders (
    po_id                   INTEGER PRIMARY KEY,
    supplier_id             INTEGER NOT NULL REFERENCES suppliers(supplier_id),
    product_id              INTEGER NOT NULL REFERENCES products(product_id),
    order_date              TEXT NOT NULL,
    expected_delivery_date  TEXT NOT NULL,
    actual_delivery_date    TEXT,                 -- NULL = still in transit
    quantity                INTEGER NOT NULL CHECK (quantity > 0)
);

CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    order_date    TEXT NOT NULL,
    warehouse_id  INTEGER NOT NULL REFERENCES warehouses(warehouse_id),
    customer_id   INTEGER NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('Delivered', 'Cancelled', 'Returned'))
);

CREATE TABLE order_lines (
    order_line_id       INTEGER PRIMARY KEY,
    order_id             INTEGER NOT NULL REFERENCES orders(order_id),
    product_id           INTEGER NOT NULL REFERENCES products(product_id),
    quantity             INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_at_sale   REAL NOT NULL CHECK (unit_price_at_sale > 0)
);

-- ---------------------------------------------------------------------------
-- Indexes — every foreign key gets one (SQLite does not index FKs
-- automatically), plus the date columns the Phase 4 analytical queries
-- filter/sort on most heavily.
-- ---------------------------------------------------------------------------

CREATE INDEX idx_products_supplier_id        ON products(supplier_id);
CREATE INDEX idx_inventory_product_id        ON inventory(product_id);
CREATE INDEX idx_purchase_orders_supplier_id ON purchase_orders(supplier_id);
CREATE INDEX idx_purchase_orders_product_id  ON purchase_orders(product_id);
CREATE INDEX idx_purchase_orders_order_date  ON purchase_orders(order_date);
CREATE INDEX idx_orders_warehouse_id         ON orders(warehouse_id);
CREATE INDEX idx_orders_order_date           ON orders(order_date);
CREATE INDEX idx_order_lines_order_id        ON order_lines(order_id);
CREATE INDEX idx_order_lines_product_id      ON order_lines(product_id);
