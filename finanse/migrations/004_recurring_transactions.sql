-- Szablony transakcji cyklicznych. Kwota i kategoria dotyczą szablonu bez produktów,
-- a pusta kwota oznacza, że poznamy ją dopiero przy płatności.
-- Pusty licznik oznacza brak limitu płatności.
CREATE TABLE recurring_transactions (
    id           INTEGER PRIMARY KEY,
    wallet_id    INTEGER NOT NULL REFERENCES wallets (id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('expense', 'income')),
    description  TEXT NOT NULL,
    amount_cents INTEGER CHECK (amount_cents > 0),
    category_id  INTEGER REFERENCES categories (id) ON DELETE SET NULL,
    remaining    INTEGER CHECK (remaining >= 0),
    last_paid_on TEXT,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_recurring_wallet ON recurring_transactions (wallet_id);

CREATE TABLE recurring_products (
    id               INTEGER PRIMARY KEY,
    recurring_id     INTEGER NOT NULL
                     REFERENCES recurring_transactions (id) ON DELETE CASCADE,
    position         INTEGER NOT NULL,
    name             TEXT NOT NULL,
    category_id      INTEGER REFERENCES categories (id) ON DELETE SET NULL,
    quantity_milli   INTEGER NOT NULL CHECK (quantity_milli > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    total_cents      INTEGER NOT NULL CHECK (total_cents >= 0)
);
CREATE INDEX idx_recurring_products ON recurring_products (recurring_id, position);
