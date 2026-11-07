-- Tagi łączą transakcje niezależnie od kategorii, np. „Wakacje 2026” albo „Remont”.
-- Transakcja może mieć wiele tagów. Usunięcie tagu nie usuwa transakcji.
CREATE TABLE tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE transaction_tags (
    id             INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions (id) ON DELETE CASCADE,
    tag_id         INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    UNIQUE (transaction_id, tag_id)
);
CREATE INDEX idx_transaction_tags_tag ON transaction_tags (tag_id);

CREATE TRIGGER log_tags_insert AFTER INSERT ON tags BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'tags', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'name', NEW.name));
END;
CREATE TRIGGER log_tags_update AFTER UPDATE ON tags
WHEN OLD.id IS NOT NEW.id OR OLD.name IS NOT NEW.name BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'tags', NEW.id, 'update', json_object('id', OLD.id, 'name', OLD.name), json_object('id', NEW.id, 'name', NEW.name));
END;
CREATE TRIGGER log_tags_delete AFTER DELETE ON tags BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'tags', OLD.id, 'delete', json_object('id', OLD.id, 'name', OLD.name), NULL);
END;

CREATE TRIGGER log_transaction_tags_insert AFTER INSERT ON transaction_tags BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'transaction_tags', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'transaction_id', NEW.transaction_id, 'tag_id', NEW.tag_id));
END;
CREATE TRIGGER log_transaction_tags_update AFTER UPDATE ON transaction_tags
WHEN OLD.id IS NOT NEW.id OR OLD.transaction_id IS NOT NEW.transaction_id OR OLD.tag_id IS NOT NEW.tag_id BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'transaction_tags', NEW.id, 'update', json_object('id', OLD.id, 'transaction_id', OLD.transaction_id, 'tag_id', OLD.tag_id), json_object('id', NEW.id, 'transaction_id', NEW.transaction_id, 'tag_id', NEW.tag_id));
END;
CREATE TRIGGER log_transaction_tags_delete AFTER DELETE ON transaction_tags BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'transaction_tags', OLD.id, 'delete', json_object('id', OLD.id, 'transaction_id', OLD.transaction_id, 'tag_id', OLD.tag_id), NULL);
END;
