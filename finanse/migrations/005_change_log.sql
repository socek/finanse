-- Dziennik zmian. Operacja łączy zmiany z jednego działania w aplikacji; zmiana
-- spoza aplikacji, np. z konsoli sqlite3, nie ma operacji. Triggery celowo nie
-- używają funkcji definiowanych w Pythonie, żeby konsola nadal mogła zmieniać dane.
-- Nowa kolumna lub tabela wymaga przebudowy triggerów w kolejnej migracji.
CREATE TABLE operations (
    id         INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_open    INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX idx_one_open_operation ON operations (is_open) WHERE is_open = 1;

CREATE TABLE change_log (
    id           INTEGER PRIMARY KEY,
    operation_id INTEGER REFERENCES operations (id),
    changed_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    table_name   TEXT NOT NULL,
    row_id       INTEGER NOT NULL,
    action       TEXT NOT NULL CHECK (action IN ('insert', 'update', 'delete')),
    old_values   TEXT,
    new_values   TEXT
);
CREATE INDEX idx_change_log_operation ON change_log (operation_id);

CREATE TRIGGER log_wallets_insert AFTER INSERT ON wallets BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'wallets', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'name', NEW.name, 'currency', NEW.currency, 'initial_balance_cents', NEW.initial_balance_cents, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_wallets_update AFTER UPDATE ON wallets
WHEN OLD.id IS NOT NEW.id OR OLD.name IS NOT NEW.name OR OLD.currency IS NOT NEW.currency OR OLD.initial_balance_cents IS NOT NEW.initial_balance_cents OR OLD.created_at IS NOT NEW.created_at BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'wallets', NEW.id, 'update', json_object('id', OLD.id, 'name', OLD.name, 'currency', OLD.currency, 'initial_balance_cents', OLD.initial_balance_cents, 'created_at', OLD.created_at), json_object('id', NEW.id, 'name', NEW.name, 'currency', NEW.currency, 'initial_balance_cents', NEW.initial_balance_cents, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_wallets_delete AFTER DELETE ON wallets BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'wallets', OLD.id, 'delete', json_object('id', OLD.id, 'name', OLD.name, 'currency', OLD.currency, 'initial_balance_cents', OLD.initial_balance_cents, 'created_at', OLD.created_at), NULL);
END;

CREATE TRIGGER log_categories_insert AFTER INSERT ON categories BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'categories', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'name', NEW.name));
END;
CREATE TRIGGER log_categories_update AFTER UPDATE ON categories
WHEN OLD.id IS NOT NEW.id OR OLD.name IS NOT NEW.name BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'categories', NEW.id, 'update', json_object('id', OLD.id, 'name', OLD.name), json_object('id', NEW.id, 'name', NEW.name));
END;
CREATE TRIGGER log_categories_delete AFTER DELETE ON categories BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'categories', OLD.id, 'delete', json_object('id', OLD.id, 'name', OLD.name), NULL);
END;

CREATE TRIGGER log_transactions_insert AFTER INSERT ON transactions BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'transactions', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'wallet_id', NEW.wallet_id, 'kind', NEW.kind, 'occurred_on', NEW.occurred_on, 'description', NEW.description, 'created_at', NEW.created_at, 'import_hash', NEW.import_hash));
END;
CREATE TRIGGER log_transactions_update AFTER UPDATE ON transactions
WHEN OLD.id IS NOT NEW.id OR OLD.wallet_id IS NOT NEW.wallet_id OR OLD.kind IS NOT NEW.kind OR OLD.occurred_on IS NOT NEW.occurred_on OR OLD.description IS NOT NEW.description OR OLD.created_at IS NOT NEW.created_at OR OLD.import_hash IS NOT NEW.import_hash BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'transactions', NEW.id, 'update', json_object('id', OLD.id, 'wallet_id', OLD.wallet_id, 'kind', OLD.kind, 'occurred_on', OLD.occurred_on, 'description', OLD.description, 'created_at', OLD.created_at, 'import_hash', OLD.import_hash), json_object('id', NEW.id, 'wallet_id', NEW.wallet_id, 'kind', NEW.kind, 'occurred_on', NEW.occurred_on, 'description', NEW.description, 'created_at', NEW.created_at, 'import_hash', NEW.import_hash));
END;
CREATE TRIGGER log_transactions_delete AFTER DELETE ON transactions BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'transactions', OLD.id, 'delete', json_object('id', OLD.id, 'wallet_id', OLD.wallet_id, 'kind', OLD.kind, 'occurred_on', OLD.occurred_on, 'description', OLD.description, 'created_at', OLD.created_at, 'import_hash', OLD.import_hash), NULL);
END;

CREATE TRIGGER log_products_insert AFTER INSERT ON products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'products', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'transaction_id', NEW.transaction_id, 'position', NEW.position, 'name', NEW.name, 'quantity_milli', NEW.quantity_milli, 'unit_price_cents', NEW.unit_price_cents, 'total_cents', NEW.total_cents, 'category_id', NEW.category_id));
END;
CREATE TRIGGER log_products_update AFTER UPDATE ON products
WHEN OLD.id IS NOT NEW.id OR OLD.transaction_id IS NOT NEW.transaction_id OR OLD.position IS NOT NEW.position OR OLD.name IS NOT NEW.name OR OLD.quantity_milli IS NOT NEW.quantity_milli OR OLD.unit_price_cents IS NOT NEW.unit_price_cents OR OLD.total_cents IS NOT NEW.total_cents OR OLD.category_id IS NOT NEW.category_id BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'products', NEW.id, 'update', json_object('id', OLD.id, 'transaction_id', OLD.transaction_id, 'position', OLD.position, 'name', OLD.name, 'quantity_milli', OLD.quantity_milli, 'unit_price_cents', OLD.unit_price_cents, 'total_cents', OLD.total_cents, 'category_id', OLD.category_id), json_object('id', NEW.id, 'transaction_id', NEW.transaction_id, 'position', NEW.position, 'name', NEW.name, 'quantity_milli', NEW.quantity_milli, 'unit_price_cents', NEW.unit_price_cents, 'total_cents', NEW.total_cents, 'category_id', NEW.category_id));
END;
CREATE TRIGGER log_products_delete AFTER DELETE ON products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'products', OLD.id, 'delete', json_object('id', OLD.id, 'transaction_id', OLD.transaction_id, 'position', OLD.position, 'name', OLD.name, 'quantity_milli', OLD.quantity_milli, 'unit_price_cents', OLD.unit_price_cents, 'total_cents', OLD.total_cents, 'category_id', OLD.category_id), NULL);
END;

CREATE TRIGGER log_transfers_insert AFTER INSERT ON transfers BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'transfers', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'from_wallet_id', NEW.from_wallet_id, 'to_wallet_id', NEW.to_wallet_id, 'occurred_on', NEW.occurred_on, 'description', NEW.description, 'amount_from_cents', NEW.amount_from_cents, 'amount_to_cents', NEW.amount_to_cents, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_transfers_update AFTER UPDATE ON transfers
WHEN OLD.id IS NOT NEW.id OR OLD.from_wallet_id IS NOT NEW.from_wallet_id OR OLD.to_wallet_id IS NOT NEW.to_wallet_id OR OLD.occurred_on IS NOT NEW.occurred_on OR OLD.description IS NOT NEW.description OR OLD.amount_from_cents IS NOT NEW.amount_from_cents OR OLD.amount_to_cents IS NOT NEW.amount_to_cents OR OLD.created_at IS NOT NEW.created_at BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'transfers', NEW.id, 'update', json_object('id', OLD.id, 'from_wallet_id', OLD.from_wallet_id, 'to_wallet_id', OLD.to_wallet_id, 'occurred_on', OLD.occurred_on, 'description', OLD.description, 'amount_from_cents', OLD.amount_from_cents, 'amount_to_cents', OLD.amount_to_cents, 'created_at', OLD.created_at), json_object('id', NEW.id, 'from_wallet_id', NEW.from_wallet_id, 'to_wallet_id', NEW.to_wallet_id, 'occurred_on', NEW.occurred_on, 'description', NEW.description, 'amount_from_cents', NEW.amount_from_cents, 'amount_to_cents', NEW.amount_to_cents, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_transfers_delete AFTER DELETE ON transfers BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'transfers', OLD.id, 'delete', json_object('id', OLD.id, 'from_wallet_id', OLD.from_wallet_id, 'to_wallet_id', OLD.to_wallet_id, 'occurred_on', OLD.occurred_on, 'description', OLD.description, 'amount_from_cents', OLD.amount_from_cents, 'amount_to_cents', OLD.amount_to_cents, 'created_at', OLD.created_at), NULL);
END;

CREATE TRIGGER log_recurring_transactions_insert AFTER INSERT ON recurring_transactions BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_transactions', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'wallet_id', NEW.wallet_id, 'kind', NEW.kind, 'description', NEW.description, 'amount_cents', NEW.amount_cents, 'category_id', NEW.category_id, 'remaining', NEW.remaining, 'last_paid_on', NEW.last_paid_on, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_recurring_transactions_update AFTER UPDATE ON recurring_transactions
WHEN OLD.id IS NOT NEW.id OR OLD.wallet_id IS NOT NEW.wallet_id OR OLD.kind IS NOT NEW.kind OR OLD.description IS NOT NEW.description OR OLD.amount_cents IS NOT NEW.amount_cents OR OLD.category_id IS NOT NEW.category_id OR OLD.remaining IS NOT NEW.remaining OR OLD.last_paid_on IS NOT NEW.last_paid_on OR OLD.created_at IS NOT NEW.created_at BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_transactions', NEW.id, 'update', json_object('id', OLD.id, 'wallet_id', OLD.wallet_id, 'kind', OLD.kind, 'description', OLD.description, 'amount_cents', OLD.amount_cents, 'category_id', OLD.category_id, 'remaining', OLD.remaining, 'last_paid_on', OLD.last_paid_on, 'created_at', OLD.created_at), json_object('id', NEW.id, 'wallet_id', NEW.wallet_id, 'kind', NEW.kind, 'description', NEW.description, 'amount_cents', NEW.amount_cents, 'category_id', NEW.category_id, 'remaining', NEW.remaining, 'last_paid_on', NEW.last_paid_on, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_recurring_transactions_delete AFTER DELETE ON recurring_transactions BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_transactions', OLD.id, 'delete', json_object('id', OLD.id, 'wallet_id', OLD.wallet_id, 'kind', OLD.kind, 'description', OLD.description, 'amount_cents', OLD.amount_cents, 'category_id', OLD.category_id, 'remaining', OLD.remaining, 'last_paid_on', OLD.last_paid_on, 'created_at', OLD.created_at), NULL);
END;

CREATE TRIGGER log_recurring_products_insert AFTER INSERT ON recurring_products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_products', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'recurring_id', NEW.recurring_id, 'position', NEW.position, 'name', NEW.name, 'category_id', NEW.category_id, 'quantity_milli', NEW.quantity_milli, 'unit_price_cents', NEW.unit_price_cents, 'total_cents', NEW.total_cents));
END;
CREATE TRIGGER log_recurring_products_update AFTER UPDATE ON recurring_products
WHEN OLD.id IS NOT NEW.id OR OLD.recurring_id IS NOT NEW.recurring_id OR OLD.position IS NOT NEW.position OR OLD.name IS NOT NEW.name OR OLD.category_id IS NOT NEW.category_id OR OLD.quantity_milli IS NOT NEW.quantity_milli OR OLD.unit_price_cents IS NOT NEW.unit_price_cents OR OLD.total_cents IS NOT NEW.total_cents BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_products', NEW.id, 'update', json_object('id', OLD.id, 'recurring_id', OLD.recurring_id, 'position', OLD.position, 'name', OLD.name, 'category_id', OLD.category_id, 'quantity_milli', OLD.quantity_milli, 'unit_price_cents', OLD.unit_price_cents, 'total_cents', OLD.total_cents), json_object('id', NEW.id, 'recurring_id', NEW.recurring_id, 'position', NEW.position, 'name', NEW.name, 'category_id', NEW.category_id, 'quantity_milli', NEW.quantity_milli, 'unit_price_cents', NEW.unit_price_cents, 'total_cents', NEW.total_cents));
END;
CREATE TRIGGER log_recurring_products_delete AFTER DELETE ON recurring_products BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_products', OLD.id, 'delete', json_object('id', OLD.id, 'recurring_id', OLD.recurring_id, 'position', OLD.position, 'name', OLD.name, 'category_id', OLD.category_id, 'quantity_milli', OLD.quantity_milli, 'unit_price_cents', OLD.unit_price_cents, 'total_cents', OLD.total_cents), NULL);
END;
