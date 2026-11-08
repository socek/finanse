-- Zawieszona transakcja cykliczna zostaje na liście, ale nie liczy się do sum, prognozy
-- ani liczby płatności po terminie.
ALTER TABLE recurring_transactions ADD COLUMN suspended INTEGER NOT NULL DEFAULT 0
    CHECK (suspended IN (0, 1));

DROP TRIGGER log_recurring_transactions_insert;
DROP TRIGGER log_recurring_transactions_update;
DROP TRIGGER log_recurring_transactions_delete;
CREATE TRIGGER log_recurring_transactions_insert AFTER INSERT ON recurring_transactions BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_transactions', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'wallet_id', NEW.wallet_id, 'kind', NEW.kind, 'description', NEW.description, 'remaining', NEW.remaining, 'last_paid_on', NEW.last_paid_on, 'created_at', NEW.created_at, 'next_due_on', NEW.next_due_on, 'period_unit', NEW.period_unit, 'period_count', NEW.period_count, 'due_day', NEW.due_day, 'suspended', NEW.suspended));
END;
CREATE TRIGGER log_recurring_transactions_update AFTER UPDATE ON recurring_transactions
WHEN OLD.id IS NOT NEW.id OR OLD.wallet_id IS NOT NEW.wallet_id OR OLD.kind IS NOT NEW.kind OR OLD.description IS NOT NEW.description OR OLD.remaining IS NOT NEW.remaining OR OLD.last_paid_on IS NOT NEW.last_paid_on OR OLD.created_at IS NOT NEW.created_at OR OLD.next_due_on IS NOT NEW.next_due_on OR OLD.period_unit IS NOT NEW.period_unit OR OLD.period_count IS NOT NEW.period_count OR OLD.due_day IS NOT NEW.due_day OR OLD.suspended IS NOT NEW.suspended BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_transactions', NEW.id, 'update', json_object('id', OLD.id, 'wallet_id', OLD.wallet_id, 'kind', OLD.kind, 'description', OLD.description, 'remaining', OLD.remaining, 'last_paid_on', OLD.last_paid_on, 'created_at', OLD.created_at, 'next_due_on', OLD.next_due_on, 'period_unit', OLD.period_unit, 'period_count', OLD.period_count, 'due_day', OLD.due_day, 'suspended', OLD.suspended), json_object('id', NEW.id, 'wallet_id', NEW.wallet_id, 'kind', NEW.kind, 'description', NEW.description, 'remaining', NEW.remaining, 'last_paid_on', NEW.last_paid_on, 'created_at', NEW.created_at, 'next_due_on', NEW.next_due_on, 'period_unit', NEW.period_unit, 'period_count', NEW.period_count, 'due_day', NEW.due_day, 'suspended', NEW.suspended));
END;
CREATE TRIGGER log_recurring_transactions_delete AFTER DELETE ON recurring_transactions BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'recurring_transactions', OLD.id, 'delete', json_object('id', OLD.id, 'wallet_id', OLD.wallet_id, 'kind', OLD.kind, 'description', OLD.description, 'remaining', OLD.remaining, 'last_paid_on', OLD.last_paid_on, 'created_at', OLD.created_at, 'next_due_on', OLD.next_due_on, 'period_unit', OLD.period_unit, 'period_count', OLD.period_count, 'due_day', OLD.due_day, 'suspended', OLD.suspended), NULL);
END;
