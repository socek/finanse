-- Ilość, cena i wartość produktu mają teraz do 5 miejsc po przecinku, jako liczby
-- całkowite w stutysięcznych. Salda i raporty nadal sumują `total_cents`, czyli wartość
-- zaokrągloną do groszy, bo tyle pieniędzy faktycznie się przemieszcza.

CREATE TABLE new_products (
    id            INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions (id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    name          TEXT NOT NULL,
    category_id   INTEGER REFERENCES categories (id) ON DELETE SET NULL,
    quantity_e5   INTEGER NOT NULL CHECK (quantity_e5 > 0),
    unit_price_e5 INTEGER NOT NULL CHECK (unit_price_e5 >= 0),
    total_e5      INTEGER NOT NULL CHECK (total_e5 >= 0),
    total_cents   INTEGER NOT NULL CHECK (total_cents >= 0)
);
INSERT INTO new_products (
    id, transaction_id, position, name, category_id,
    quantity_e5, unit_price_e5, total_e5, total_cents
)
SELECT id, transaction_id, position, name, category_id,
       quantity_milli * 100, unit_price_cents * 1000, total_cents * 1000, total_cents
FROM products;
DROP TABLE products;
ALTER TABLE new_products RENAME TO products;

CREATE TRIGGER log_products_insert AFTER INSERT ON products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'products', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'transaction_id', NEW.transaction_id, 'position', NEW.position, 'name', NEW.name, 'category_id', NEW.category_id, 'quantity_e5', NEW.quantity_e5, 'unit_price_e5', NEW.unit_price_e5, 'total_e5', NEW.total_e5, 'total_cents', NEW.total_cents));
END;
CREATE TRIGGER log_products_update AFTER UPDATE ON products
WHEN OLD.id IS NOT NEW.id OR OLD.transaction_id IS NOT NEW.transaction_id OR OLD.position IS NOT NEW.position OR OLD.name IS NOT NEW.name OR OLD.category_id IS NOT NEW.category_id OR OLD.quantity_e5 IS NOT NEW.quantity_e5 OR OLD.unit_price_e5 IS NOT NEW.unit_price_e5 OR OLD.total_e5 IS NOT NEW.total_e5 OR OLD.total_cents IS NOT NEW.total_cents BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'products', NEW.id, 'update', json_object('id', OLD.id, 'transaction_id', OLD.transaction_id, 'position', OLD.position, 'name', OLD.name, 'category_id', OLD.category_id, 'quantity_e5', OLD.quantity_e5, 'unit_price_e5', OLD.unit_price_e5, 'total_e5', OLD.total_e5, 'total_cents', OLD.total_cents), json_object('id', NEW.id, 'transaction_id', NEW.transaction_id, 'position', NEW.position, 'name', NEW.name, 'category_id', NEW.category_id, 'quantity_e5', NEW.quantity_e5, 'unit_price_e5', NEW.unit_price_e5, 'total_e5', NEW.total_e5, 'total_cents', NEW.total_cents));
END;
CREATE TRIGGER log_products_delete AFTER DELETE ON products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'products', OLD.id, 'delete', json_object('id', OLD.id, 'transaction_id', OLD.transaction_id, 'position', OLD.position, 'name', OLD.name, 'category_id', OLD.category_id, 'quantity_e5', OLD.quantity_e5, 'unit_price_e5', OLD.unit_price_e5, 'total_e5', OLD.total_e5, 'total_cents', OLD.total_cents), NULL);
END;
CREATE INDEX idx_products_transaction ON products (transaction_id, position);
CREATE INDEX idx_products_category ON products (category_id);

CREATE TABLE new_recurring_products (
    id            INTEGER PRIMARY KEY,
    recurring_id INTEGER NOT NULL REFERENCES recurring_transactions (id) ON DELETE CASCADE,
    position      INTEGER NOT NULL,
    name          TEXT NOT NULL,
    category_id   INTEGER REFERENCES categories (id) ON DELETE SET NULL,
    quantity_e5   INTEGER NOT NULL CHECK (quantity_e5 > 0),
    unit_price_e5 INTEGER NOT NULL CHECK (unit_price_e5 >= 0),
    total_e5      INTEGER NOT NULL CHECK (total_e5 >= 0),
    total_cents   INTEGER NOT NULL CHECK (total_cents >= 0)
);
INSERT INTO new_recurring_products (
    id, recurring_id, position, name, category_id,
    quantity_e5, unit_price_e5, total_e5, total_cents
)
SELECT id, recurring_id, position, name, category_id,
       quantity_milli * 100, unit_price_cents * 1000, total_cents * 1000, total_cents
FROM recurring_products;
DROP TABLE recurring_products;
ALTER TABLE new_recurring_products RENAME TO recurring_products;

CREATE TRIGGER log_recurring_products_insert AFTER INSERT ON recurring_products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_products', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'recurring_id', NEW.recurring_id, 'position', NEW.position, 'name', NEW.name, 'category_id', NEW.category_id, 'quantity_e5', NEW.quantity_e5, 'unit_price_e5', NEW.unit_price_e5, 'total_e5', NEW.total_e5, 'total_cents', NEW.total_cents));
END;
CREATE TRIGGER log_recurring_products_update AFTER UPDATE ON recurring_products
WHEN OLD.id IS NOT NEW.id OR OLD.recurring_id IS NOT NEW.recurring_id OR OLD.position IS NOT NEW.position OR OLD.name IS NOT NEW.name OR OLD.category_id IS NOT NEW.category_id OR OLD.quantity_e5 IS NOT NEW.quantity_e5 OR OLD.unit_price_e5 IS NOT NEW.unit_price_e5 OR OLD.total_e5 IS NOT NEW.total_e5 OR OLD.total_cents IS NOT NEW.total_cents BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_products', NEW.id, 'update', json_object('id', OLD.id, 'recurring_id', OLD.recurring_id, 'position', OLD.position, 'name', OLD.name, 'category_id', OLD.category_id, 'quantity_e5', OLD.quantity_e5, 'unit_price_e5', OLD.unit_price_e5, 'total_e5', OLD.total_e5, 'total_cents', OLD.total_cents), json_object('id', NEW.id, 'recurring_id', NEW.recurring_id, 'position', NEW.position, 'name', NEW.name, 'category_id', NEW.category_id, 'quantity_e5', NEW.quantity_e5, 'unit_price_e5', NEW.unit_price_e5, 'total_e5', NEW.total_e5, 'total_cents', NEW.total_cents));
END;
CREATE TRIGGER log_recurring_products_delete AFTER DELETE ON recurring_products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_products', OLD.id, 'delete', json_object('id', OLD.id, 'recurring_id', OLD.recurring_id, 'position', OLD.position, 'name', OLD.name, 'category_id', OLD.category_id, 'quantity_e5', OLD.quantity_e5, 'unit_price_e5', OLD.unit_price_e5, 'total_e5', OLD.total_e5, 'total_cents', OLD.total_cents), NULL);
END;
CREATE INDEX idx_recurring_products ON recurring_products (recurring_id, position);
