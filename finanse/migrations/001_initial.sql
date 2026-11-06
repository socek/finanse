-- Kwoty są przechowywane w groszach, a ilości w tysięcznych części jednostki,
-- zawsze jako liczby całkowite.

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wallets (
    id                    INTEGER PRIMARY KEY,
    user_id               INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    name                  TEXT NOT NULL COLLATE NOCASE,
    currency              TEXT NOT NULL DEFAULT 'PLN',
    initial_balance_cents INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY,
    wallet_id   INTEGER NOT NULL REFERENCES wallets (id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    occurred_on TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_transactions_wallet
    ON transactions (wallet_id, occurred_on);

CREATE TABLE IF NOT EXISTS products (
    id               INTEGER PRIMARY KEY,
    transaction_id   INTEGER NOT NULL REFERENCES transactions (id) ON DELETE CASCADE,
    position         INTEGER NOT NULL,
    name             TEXT NOT NULL,
    quantity_milli   INTEGER NOT NULL CHECK (quantity_milli > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    total_cents      INTEGER NOT NULL CHECK (total_cents >= 0)
);

CREATE INDEX IF NOT EXISTS idx_products_transaction
    ON products (transaction_id, position);
