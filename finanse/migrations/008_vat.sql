-- Portfel z VAT. Wartość produktu pozostaje kwotą brutto, bo tyle pieniędzy się przemieszcza,
-- a netto to `total_cents - vat_cents`. Pusta stawka oznacza zwolnienie lub brak VAT.
ALTER TABLE wallets ADD COLUMN wallet_type TEXT NOT NULL DEFAULT 'plain'
    CHECK (wallet_type IN ('plain', 'vat'));

ALTER TABLE products ADD COLUMN vat_rate INTEGER CHECK (vat_rate IN (0, 5, 8, 23));
ALTER TABLE products ADD COLUMN vat_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE recurring_products ADD COLUMN vat_rate INTEGER CHECK (vat_rate IN (0, 5, 8, 23));
ALTER TABLE recurring_products ADD COLUMN vat_cents INTEGER NOT NULL DEFAULT 0;

DROP TRIGGER log_wallets_insert;
DROP TRIGGER log_wallets_update;
DROP TRIGGER log_wallets_delete;
CREATE TRIGGER log_wallets_insert AFTER INSERT ON wallets BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'wallets', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'name', NEW.name, 'currency', NEW.currency, 'initial_balance_cents', NEW.initial_balance_cents, 'created_at', NEW.created_at, 'wallet_type', NEW.wallet_type));
END;
CREATE TRIGGER log_wallets_update AFTER UPDATE ON wallets
WHEN OLD.id IS NOT NEW.id OR OLD.name IS NOT NEW.name OR OLD.currency IS NOT NEW.currency OR OLD.initial_balance_cents IS NOT NEW.initial_balance_cents OR OLD.created_at IS NOT NEW.created_at OR OLD.wallet_type IS NOT NEW.wallet_type BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'wallets', NEW.id, 'update', json_object('id', OLD.id, 'name', OLD.name, 'currency', OLD.currency, 'initial_balance_cents', OLD.initial_balance_cents, 'created_at', OLD.created_at, 'wallet_type', OLD.wallet_type), json_object('id', NEW.id, 'name', NEW.name, 'currency', NEW.currency, 'initial_balance_cents', NEW.initial_balance_cents, 'created_at', NEW.created_at, 'wallet_type', NEW.wallet_type));
END;
CREATE TRIGGER log_wallets_delete AFTER DELETE ON wallets BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'wallets', OLD.id, 'delete', json_object('id', OLD.id, 'name', OLD.name, 'currency', OLD.currency, 'initial_balance_cents', OLD.initial_balance_cents, 'created_at', OLD.created_at, 'wallet_type', OLD.wallet_type), NULL);
END;

DROP TRIGGER log_products_insert;
DROP TRIGGER log_products_update;
DROP TRIGGER log_products_delete;
CREATE TRIGGER log_products_insert AFTER INSERT ON products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'products', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'transaction_id', NEW.transaction_id, 'position', NEW.position, 'name', NEW.name, 'category_id', NEW.category_id, 'quantity_e5', NEW.quantity_e5, 'unit_price_e5', NEW.unit_price_e5, 'total_e5', NEW.total_e5, 'total_cents', NEW.total_cents, 'vat_rate', NEW.vat_rate, 'vat_cents', NEW.vat_cents));
END;
CREATE TRIGGER log_products_update AFTER UPDATE ON products
WHEN OLD.id IS NOT NEW.id OR OLD.transaction_id IS NOT NEW.transaction_id OR OLD.position IS NOT NEW.position OR OLD.name IS NOT NEW.name OR OLD.category_id IS NOT NEW.category_id OR OLD.quantity_e5 IS NOT NEW.quantity_e5 OR OLD.unit_price_e5 IS NOT NEW.unit_price_e5 OR OLD.total_e5 IS NOT NEW.total_e5 OR OLD.total_cents IS NOT NEW.total_cents OR OLD.vat_rate IS NOT NEW.vat_rate OR OLD.vat_cents IS NOT NEW.vat_cents BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'products', NEW.id, 'update', json_object('id', OLD.id, 'transaction_id', OLD.transaction_id, 'position', OLD.position, 'name', OLD.name, 'category_id', OLD.category_id, 'quantity_e5', OLD.quantity_e5, 'unit_price_e5', OLD.unit_price_e5, 'total_e5', OLD.total_e5, 'total_cents', OLD.total_cents, 'vat_rate', OLD.vat_rate, 'vat_cents', OLD.vat_cents), json_object('id', NEW.id, 'transaction_id', NEW.transaction_id, 'position', NEW.position, 'name', NEW.name, 'category_id', NEW.category_id, 'quantity_e5', NEW.quantity_e5, 'unit_price_e5', NEW.unit_price_e5, 'total_e5', NEW.total_e5, 'total_cents', NEW.total_cents, 'vat_rate', NEW.vat_rate, 'vat_cents', NEW.vat_cents));
END;
CREATE TRIGGER log_products_delete AFTER DELETE ON products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'products', OLD.id, 'delete', json_object('id', OLD.id, 'transaction_id', OLD.transaction_id, 'position', OLD.position, 'name', OLD.name, 'category_id', OLD.category_id, 'quantity_e5', OLD.quantity_e5, 'unit_price_e5', OLD.unit_price_e5, 'total_e5', OLD.total_e5, 'total_cents', OLD.total_cents, 'vat_rate', OLD.vat_rate, 'vat_cents', OLD.vat_cents), NULL);
END;

DROP TRIGGER log_recurring_products_insert;
DROP TRIGGER log_recurring_products_update;
DROP TRIGGER log_recurring_products_delete;
CREATE TRIGGER log_recurring_products_insert AFTER INSERT ON recurring_products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_products', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'recurring_id', NEW.recurring_id, 'position', NEW.position, 'name', NEW.name, 'category_id', NEW.category_id, 'quantity_e5', NEW.quantity_e5, 'unit_price_e5', NEW.unit_price_e5, 'total_e5', NEW.total_e5, 'total_cents', NEW.total_cents, 'vat_rate', NEW.vat_rate, 'vat_cents', NEW.vat_cents));
END;
CREATE TRIGGER log_recurring_products_update AFTER UPDATE ON recurring_products
WHEN OLD.id IS NOT NEW.id OR OLD.recurring_id IS NOT NEW.recurring_id OR OLD.position IS NOT NEW.position OR OLD.name IS NOT NEW.name OR OLD.category_id IS NOT NEW.category_id OR OLD.quantity_e5 IS NOT NEW.quantity_e5 OR OLD.unit_price_e5 IS NOT NEW.unit_price_e5 OR OLD.total_e5 IS NOT NEW.total_e5 OR OLD.total_cents IS NOT NEW.total_cents OR OLD.vat_rate IS NOT NEW.vat_rate OR OLD.vat_cents IS NOT NEW.vat_cents BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_products', NEW.id, 'update', json_object('id', OLD.id, 'recurring_id', OLD.recurring_id, 'position', OLD.position, 'name', OLD.name, 'category_id', OLD.category_id, 'quantity_e5', OLD.quantity_e5, 'unit_price_e5', OLD.unit_price_e5, 'total_e5', OLD.total_e5, 'total_cents', OLD.total_cents, 'vat_rate', OLD.vat_rate, 'vat_cents', OLD.vat_cents), json_object('id', NEW.id, 'recurring_id', NEW.recurring_id, 'position', NEW.position, 'name', NEW.name, 'category_id', NEW.category_id, 'quantity_e5', NEW.quantity_e5, 'unit_price_e5', NEW.unit_price_e5, 'total_e5', NEW.total_e5, 'total_cents', NEW.total_cents, 'vat_rate', NEW.vat_rate, 'vat_cents', NEW.vat_cents));
END;
CREATE TRIGGER log_recurring_products_delete AFTER DELETE ON recurring_products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_products', OLD.id, 'delete', json_object('id', OLD.id, 'recurring_id', OLD.recurring_id, 'position', OLD.position, 'name', OLD.name, 'category_id', OLD.category_id, 'quantity_e5', OLD.quantity_e5, 'unit_price_e5', OLD.unit_price_e5, 'total_e5', OLD.total_e5, 'total_cents', OLD.total_cents, 'vat_rate', OLD.vat_rate, 'vat_cents', OLD.vat_cents), NULL);
END;
