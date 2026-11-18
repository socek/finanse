-- Pożyczki udzielone innym (lent) i zaciągnięte (borrowed). Kwotę pożyczki i spłaty tworzą
-- powiązane transakcje: przy udzielonej wydatek zwiększa pożyczkę, a przychód ją spłaca,
-- przy zaciągniętej odwrotnie. initial_cents to kwota spoza portfeli, np. sprzed aplikacji.
-- Usunięcie pożyczki zostawia transakcje w portfelu, a usunięcie transakcji usuwa powiązanie.
CREATE TABLE loans (
    id            INTEGER PRIMARY KEY,
    direction     TEXT NOT NULL CHECK (direction IN ('lent', 'borrowed')),
    person        TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    currency      TEXT NOT NULL,
    opened_on     TEXT NOT NULL,
    initial_cents INTEGER NOT NULL DEFAULT 0 CHECK (initial_cents >= 0),
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE loan_transactions (
    id             INTEGER PRIMARY KEY,
    loan_id        INTEGER NOT NULL REFERENCES loans (id) ON DELETE CASCADE,
    transaction_id INTEGER NOT NULL UNIQUE REFERENCES transactions (id) ON DELETE CASCADE
);
CREATE INDEX idx_loan_transactions_loan ON loan_transactions (loan_id);

CREATE TRIGGER log_loans_insert AFTER INSERT ON loans BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loans', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'direction', NEW.direction, 'person', NEW.person, 'description', NEW.description, 'currency', NEW.currency, 'opened_on', NEW.opened_on, 'initial_cents', NEW.initial_cents, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_loans_update AFTER UPDATE ON loans
WHEN OLD.id IS NOT NEW.id OR OLD.direction IS NOT NEW.direction OR OLD.person IS NOT NEW.person OR OLD.description IS NOT NEW.description OR OLD.currency IS NOT NEW.currency OR OLD.opened_on IS NOT NEW.opened_on OR OLD.initial_cents IS NOT NEW.initial_cents OR OLD.created_at IS NOT NEW.created_at BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loans', NEW.id, 'update', json_object('id', OLD.id, 'direction', OLD.direction, 'person', OLD.person, 'description', OLD.description, 'currency', OLD.currency, 'opened_on', OLD.opened_on, 'initial_cents', OLD.initial_cents, 'created_at', OLD.created_at), json_object('id', NEW.id, 'direction', NEW.direction, 'person', NEW.person, 'description', NEW.description, 'currency', NEW.currency, 'opened_on', NEW.opened_on, 'initial_cents', NEW.initial_cents, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_loans_delete AFTER DELETE ON loans BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loans', OLD.id, 'delete', json_object('id', OLD.id, 'direction', OLD.direction, 'person', OLD.person, 'description', OLD.description, 'currency', OLD.currency, 'opened_on', OLD.opened_on, 'initial_cents', OLD.initial_cents, 'created_at', OLD.created_at), NULL);
END;

CREATE TRIGGER log_loan_transactions_insert AFTER INSERT ON loan_transactions BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loan_transactions', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'loan_id', NEW.loan_id, 'transaction_id', NEW.transaction_id));
END;
CREATE TRIGGER log_loan_transactions_update AFTER UPDATE ON loan_transactions
WHEN OLD.id IS NOT NEW.id OR OLD.loan_id IS NOT NEW.loan_id OR OLD.transaction_id IS NOT NEW.transaction_id BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loan_transactions', NEW.id, 'update', json_object('id', OLD.id, 'loan_id', OLD.loan_id, 'transaction_id', OLD.transaction_id), json_object('id', NEW.id, 'loan_id', NEW.loan_id, 'transaction_id', NEW.transaction_id));
END;
CREATE TRIGGER log_loan_transactions_delete AFTER DELETE ON loan_transactions BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loan_transactions', OLD.id, 'delete', json_object('id', OLD.id, 'loan_id', OLD.loan_id, 'transaction_id', OLD.transaction_id), NULL);
END;
