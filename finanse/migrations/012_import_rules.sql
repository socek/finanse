-- Reguły importu: gdy opis z wyciągu zawiera tekst, import nadaje kategorię, nazwę produktu
-- i tagi. Pierwsza pasująca reguła według pozycji wygrywa. Pusta nazwa produktu oznacza
-- opis z wyciągu, pusty rodzaj oznacza wydatki i przychody.
CREATE TABLE import_rules (
    id           INTEGER PRIMARY KEY,
    position     INTEGER NOT NULL,
    pattern      TEXT NOT NULL,
    kind         TEXT CHECK (kind IN ('expense', 'income')),
    category_id  INTEGER REFERENCES categories (id) ON DELETE SET NULL,
    product_name TEXT,
    tags         TEXT NOT NULL DEFAULT ''
);

CREATE TRIGGER log_import_rules_insert AFTER INSERT ON import_rules BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'import_rules', NEW.id, 'insert', NULL, json_object('id', NEW.id, 'position', NEW.position, 'pattern', NEW.pattern, 'kind', NEW.kind, 'category_id', NEW.category_id, 'product_name', NEW.product_name, 'tags', NEW.tags));
END;
CREATE TRIGGER log_import_rules_update AFTER UPDATE ON import_rules
WHEN OLD.id IS NOT NEW.id OR OLD.position IS NOT NEW.position OR OLD.pattern IS NOT NEW.pattern OR OLD.kind IS NOT NEW.kind OR OLD.category_id IS NOT NEW.category_id OR OLD.product_name IS NOT NEW.product_name OR OLD.tags IS NOT NEW.tags BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'import_rules', NEW.id, 'update', json_object('id', OLD.id, 'position', OLD.position, 'pattern', OLD.pattern, 'kind', OLD.kind, 'category_id', OLD.category_id, 'product_name', OLD.product_name, 'tags', OLD.tags), json_object('id', NEW.id, 'position', NEW.position, 'pattern', NEW.pattern, 'kind', NEW.kind, 'category_id', NEW.category_id, 'product_name', NEW.product_name, 'tags', NEW.tags));
END;
CREATE TRIGGER log_import_rules_delete AFTER DELETE ON import_rules BEGIN
    INSERT INTO change_log (operation_id, table_name, row_id, action, old_values, new_values)
    VALUES ((SELECT id FROM operations WHERE is_open = 1), 'import_rules', OLD.id, 'delete', json_object('id', OLD.id, 'position', OLD.position, 'pattern', OLD.pattern, 'kind', OLD.kind, 'category_id', OLD.category_id, 'product_name', OLD.product_name, 'tags', OLD.tags), NULL);
END;
