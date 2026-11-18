-- Pożyczka składa się z własnych pozycji: pożyczeń i spłat, np. 100 zł, potem kolejne 50 zł
-- i spłata 30 zł. Pozycja jest poza portfelami, z własną datą, kwotą i rolą, albo jest
-- powiązana z transakcją w portfelu i wtedy datę, kwotę i rolę bierze z niej: przy pożyczce
-- udzielonej wydatek to pożyczenie, a przychód spłata, przy zaciągniętej odwrotnie.
-- Usunięcie transakcji usuwa jej pozycję, a usunięcie pozycji zostawia transakcję.
CREATE TABLE loan_items (
    id             INTEGER PRIMARY KEY,
    loan_id        INTEGER NOT NULL REFERENCES loans (id) ON DELETE CASCADE,
    transaction_id INTEGER UNIQUE REFERENCES transactions (id) ON DELETE CASCADE,
    role           TEXT CHECK (role IN ('principal', 'repayment')),
    occurred_on    TEXT,
    amount_cents   INTEGER CHECK (amount_cents > 0),
    description    TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (transaction_id IS NOT NULL
           OR (role IS NOT NULL AND occurred_on IS NOT NULL AND amount_cents IS NOT NULL))
);
CREATE INDEX idx_loan_items_loan ON loan_items (loan_id);

-- Kwota spoza portfeli staje się pierwszą pozycją, a powiązania – pozycjami z transakcją.
INSERT INTO loan_items (loan_id, role, occurred_on, amount_cents, created_at)
SELECT id, 'principal', opened_on, initial_cents, created_at FROM loans WHERE initial_cents > 0;
INSERT INTO loan_items (loan_id, transaction_id)
SELECT loan_id, transaction_id FROM loan_transactions ORDER BY id;

DROP TRIGGER log_loan_transactions_insert;
DROP TRIGGER log_loan_transactions_update;
DROP TRIGGER log_loan_transactions_delete;
DROP TABLE loan_transactions;

-- Kwota pożyczki to teraz suma pozycji, więc kolumna initial_cents znika.
DROP TRIGGER log_loans_insert;
DROP TRIGGER log_loans_update;
DROP TRIGGER log_loans_delete;
CREATE TABLE new_loans (
    id          INTEGER PRIMARY KEY,
    direction   TEXT NOT NULL CHECK (direction IN ('lent', 'borrowed')),
    person      TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    currency    TEXT NOT NULL,
    opened_on   TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO new_loans (id, direction, person, description, currency, opened_on, created_at)
SELECT id, direction, person, description, currency, opened_on, created_at FROM loans;
DROP TABLE loans;
ALTER TABLE new_loans RENAME TO loans;

CREATE TRIGGER log_loans_insert AFTER INSERT ON loans BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loans', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'direction', NEW.direction, 'person', NEW.person, 'description', NEW.description, 'currency', NEW.currency, 'opened_on', NEW.opened_on, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_loans_update AFTER UPDATE ON loans
WHEN OLD.id IS NOT NEW.id OR OLD.direction IS NOT NEW.direction OR OLD.person IS NOT NEW.person OR OLD.description IS NOT NEW.description OR OLD.currency IS NOT NEW.currency OR OLD.opened_on IS NOT NEW.opened_on OR OLD.created_at IS NOT NEW.created_at BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loans', NEW.id, 'update', json_object('id', OLD.id, 'direction', OLD.direction, 'person', OLD.person, 'description', OLD.description, 'currency', OLD.currency, 'opened_on', OLD.opened_on, 'created_at', OLD.created_at), json_object('id', NEW.id, 'direction', NEW.direction, 'person', NEW.person, 'description', NEW.description, 'currency', NEW.currency, 'opened_on', NEW.opened_on, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_loans_delete AFTER DELETE ON loans BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loans', OLD.id, 'delete', json_object('id', OLD.id, 'direction', OLD.direction, 'person', OLD.person, 'description', OLD.description, 'currency', OLD.currency, 'opened_on', OLD.opened_on, 'created_at', OLD.created_at), NULL);
END;

CREATE TRIGGER log_loan_items_insert AFTER INSERT ON loan_items BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loan_items', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'loan_id', NEW.loan_id, 'transaction_id', NEW.transaction_id, 'role', NEW.role, 'occurred_on', NEW.occurred_on, 'amount_cents', NEW.amount_cents, 'description', NEW.description, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_loan_items_update AFTER UPDATE ON loan_items
WHEN OLD.id IS NOT NEW.id OR OLD.loan_id IS NOT NEW.loan_id OR OLD.transaction_id IS NOT NEW.transaction_id OR OLD.role IS NOT NEW.role OR OLD.occurred_on IS NOT NEW.occurred_on OR OLD.amount_cents IS NOT NEW.amount_cents OR OLD.description IS NOT NEW.description OR OLD.created_at IS NOT NEW.created_at BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loan_items', NEW.id, 'update', json_object('id', OLD.id, 'loan_id', OLD.loan_id, 'transaction_id', OLD.transaction_id, 'role', OLD.role, 'occurred_on', OLD.occurred_on, 'amount_cents', OLD.amount_cents, 'description', OLD.description, 'created_at', OLD.created_at), json_object('id', NEW.id, 'loan_id', NEW.loan_id, 'transaction_id', NEW.transaction_id, 'role', NEW.role, 'occurred_on', NEW.occurred_on, 'amount_cents', NEW.amount_cents, 'description', NEW.description, 'created_at', NEW.created_at));
END;
CREATE TRIGGER log_loan_items_delete AFTER DELETE ON loan_items BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'loan_items', OLD.id, 'delete', json_object('id', OLD.id, 'loan_id', OLD.loan_id, 'transaction_id', OLD.transaction_id, 'role', OLD.role, 'occurred_on', OLD.occurred_on, 'amount_cents', OLD.amount_cents, 'description', OLD.description, 'created_at', OLD.created_at), NULL);
END;
