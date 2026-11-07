-- Kwotę i kategorię transakcji cyklicznej wyznaczają wyłącznie jej produkty. Kwota
-- szablonu bez produktów staje się produktem, żeby nie przepadła. Sama kategoria bez
-- kwoty nie ma gdzie trafić, bo produkt wymaga ceny.
INSERT INTO recurring_products (
    recurring_id, position, name, category_id,
    quantity_milli, unit_price_cents, total_cents
)
SELECT r.id, 0, r.description, r.category_id, 1000, r.amount_cents, r.amount_cents
FROM recurring_transactions r
WHERE r.amount_cents IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM recurring_products p WHERE p.recurring_id = r.id);

-- SQLite nie usunie kolumny z kluczem obcym, więc tabela jest przebudowywana. Usunięcie
-- starej tabeli usuwa też jej triggery dziennika, dlatego powstają na nowo.
CREATE TABLE new_recurring_transactions (
    id           INTEGER PRIMARY KEY,
    wallet_id    INTEGER NOT NULL REFERENCES wallets (id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    description  TEXT NOT NULL,
    remaining    INTEGER CHECK (remaining >= 0),
    last_paid_on TEXT,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO new_recurring_transactions
    (id, wallet_id, kind, description, remaining, last_paid_on, created_at)
SELECT id, wallet_id, kind, description, remaining, last_paid_on, created_at
FROM recurring_transactions;
DROP TABLE recurring_transactions;
ALTER TABLE new_recurring_transactions RENAME TO recurring_transactions;
CREATE INDEX idx_recurring_wallet ON recurring_transactions (wallet_id);

CREATE TRIGGER log_recurring_transactions_insert AFTER INSERT ON recurring_transactions BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_transactions', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'wallet_id', NEW.wallet_id, 'kind', NEW.kind, 'description', NEW.description, 'remaining', NEW.remaining, 'last_paid_on', NEW.last_paid_on, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_recurring_transactions_update AFTER UPDATE ON recurring_transactions
WHEN OLD.id IS NOT NEW.id OR OLD.wallet_id IS NOT NEW.wallet_id OR OLD.kind IS NOT NEW.kind OR OLD.description IS NOT NEW.description OR OLD.remaining IS NOT NEW.remaining OR OLD.last_paid_on IS NOT NEW.last_paid_on OR OLD.created_at IS NOT NEW.created_at BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_transactions', NEW.id, 'update', json_object('id', OLD.id, 'wallet_id', OLD.wallet_id, 'kind', OLD.kind, 'description', OLD.description, 'remaining', OLD.remaining, 'last_paid_on', OLD.last_paid_on, 'created_at', OLD.created_at), json_object('id', NEW.id, 'wallet_id', NEW.wallet_id, 'kind', NEW.kind, 'description', NEW.description, 'remaining', NEW.remaining, 'last_paid_on', NEW.last_paid_on, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_recurring_transactions_delete AFTER DELETE ON recurring_transactions BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_transactions', OLD.id, 'delete', json_object('id', OLD.id, 'wallet_id', OLD.wallet_id, 'kind', OLD.kind, 'description', OLD.description, 'remaining', OLD.remaining, 'last_paid_on', OLD.last_paid_on, 'created_at', OLD.created_at), NULL);
END;
