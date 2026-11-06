ALTER TABLE users ADD COLUMN recovery_code_hash TEXT;
-- Zwiększany przy zmianie hasła, co unieważnia sesje na innych urządzeniach.
ALTER TABLE users ADD COLUMN session_epoch INTEGER NOT NULL DEFAULT 0;

CREATE TABLE categories (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name    TEXT NOT NULL COLLATE NOCASE,
    UNIQUE (user_id, name)
);

-- Istniejące konta dostają te same kategorie startowe co nowe.
INSERT INTO categories (user_id, name)
SELECT users.id, defaults.name
FROM users
CROSS JOIN (
    SELECT 'Jedzenie' AS name
    UNION ALL SELECT 'Dom'
    UNION ALL SELECT 'Rachunki'
    UNION ALL SELECT 'Transport'
    UNION ALL SELECT 'Zdrowie'
    UNION ALL SELECT 'Ubrania'
    UNION ALL SELECT 'Rozrywka'
    UNION ALL SELECT 'Wynagrodzenie'
    UNION ALL SELECT 'Inne'
) AS defaults;

ALTER TABLE products
    ADD COLUMN category_id INTEGER REFERENCES categories (id) ON DELETE SET NULL;
CREATE INDEX idx_products_category ON products (category_id);

-- Odcisk wiersza z wyciągu bankowego; chroni przed ponownym importem.
ALTER TABLE transactions ADD COLUMN import_hash TEXT;
CREATE UNIQUE INDEX idx_transactions_import_hash
    ON transactions (wallet_id, import_hash)
    WHERE import_hash IS NOT NULL;

-- Przelew nie jest ani przychodem, ani wydatkiem. Kwoty są dwie, bo portfele
-- mogą mieć różne waluty. RESTRICT: usunięcie portfela nie może po cichu zmienić
-- salda drugiego portfela.
CREATE TABLE transfers (
    id                INTEGER PRIMARY KEY,
    from_wallet_id    INTEGER NOT NULL REFERENCES wallets (id) ON DELETE RESTRICT,
    to_wallet_id      INTEGER NOT NULL REFERENCES wallets (id) ON DELETE RESTRICT,
    occurred_on       TEXT NOT NULL,
    description       TEXT NOT NULL,
    amount_from_cents INTEGER NOT NULL CHECK (amount_from_cents > 0),
    amount_to_cents   INTEGER NOT NULL CHECK (amount_to_cents > 0),
    created_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (from_wallet_id <> to_wallet_id)
);
CREATE INDEX idx_transfers_from ON transfers (from_wallet_id, occurred_on);
CREATE INDEX idx_transfers_to ON transfers (to_wallet_id, occurred_on);
