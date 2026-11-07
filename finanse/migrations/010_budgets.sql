-- Miesięczny limit wydatków w kategorii, osobno dla każdej waluty, bo kwot w różnych
-- walutach nie sumujemy. Ten sam limit obowiązuje w każdym miesiącu.
CREATE TABLE budgets (
    id           INTEGER PRIMARY KEY,
    category_id  INTEGER NOT NULL REFERENCES categories (id) ON DELETE CASCADE,
    currency     TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    UNIQUE (category_id, currency)
);

CREATE TRIGGER log_budgets_insert AFTER INSERT ON budgets BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'budgets', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'category_id', NEW.category_id, 'currency', NEW.currency, 'amount_cents', NEW.amount_cents));
END;
CREATE TRIGGER log_budgets_update AFTER UPDATE ON budgets
WHEN OLD.id IS NOT NEW.id OR OLD.category_id IS NOT NEW.category_id OR OLD.currency IS NOT NEW.currency OR OLD.amount_cents IS NOT NEW.amount_cents BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'budgets', NEW.id, 'update', json_object('id', OLD.id, 'category_id', OLD.category_id, 'currency', OLD.currency, 'amount_cents', OLD.amount_cents), json_object('id', NEW.id, 'category_id', NEW.category_id, 'currency', NEW.currency, 'amount_cents', NEW.amount_cents));
END;
CREATE TRIGGER log_budgets_delete AFTER DELETE ON budgets BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'budgets', OLD.id, 'delete', json_object('id', OLD.id, 'category_id', OLD.category_id, 'currency', OLD.currency, 'amount_cents', OLD.amount_cents), NULL);
END;
