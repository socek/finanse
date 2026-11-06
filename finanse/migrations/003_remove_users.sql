-- Aplikacja okienkowa nie ma kont: portfele i kategorie nie należą już do nikogo.
-- Dane kilku kont nie dają się bezpiecznie scalić (nazwy są unikalne), dlatego
-- przy więcej niż jednym koncie migracja przerywa się i niczego nie zmienia.
CREATE TEMP TABLE _one_account (accounts INTEGER NOT NULL CHECK (accounts <= 1));
INSERT INTO _one_account SELECT COUNT(*) FROM users;
DROP TABLE _one_account;

CREATE TABLE new_wallets (
    id                    INTEGER PRIMARY KEY,
    name                  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    currency              TEXT NOT NULL DEFAULT 'PLN',
    initial_balance_cents INTEGER NOT NULL DEFAULT 0,
    created_at            TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO new_wallets (id, name, currency, initial_balance_cents, created_at)
SELECT id, name, currency, initial_balance_cents, created_at FROM wallets;
DROP TABLE wallets;
ALTER TABLE new_wallets RENAME TO wallets;

CREATE TABLE new_categories (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
INSERT INTO new_categories (id, name) SELECT id, name FROM categories;
DROP TABLE categories;
ALTER TABLE new_categories RENAME TO categories;

-- Nowa baza nie ma konta, przy którego zakładaniu powstawały kategorie startowe.
INSERT INTO categories (name)
SELECT defaults.name
FROM (
    SELECT 'Jedzenie' AS name
    UNION ALL SELECT 'Dom'
    UNION ALL SELECT 'Rachunki'
    UNION ALL SELECT 'Transport'
    UNION ALL SELECT 'Zdrowie'
    UNION ALL SELECT 'Ubrania'
    UNION ALL SELECT 'Rozrywka'
    UNION ALL SELECT 'Wynagrodzenie'
    UNION ALL SELECT 'Inne'
) AS defaults
WHERE NOT EXISTS (SELECT 1 FROM users);

DROP TABLE users;
