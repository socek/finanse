import sqlite3
from importlib import resources

import pytest

from finanse.db import connect, init_db


def _script(name):
    return resources.files("finanse").joinpath(f"migrations/{name}").read_text("utf-8")


def _database_with_accounts(path, accounts=1):
    """Baza w wersji 2, czyli sprzed usunięcia kont."""
    connection = sqlite3.connect(path)
    connection.executescript(_script("001_initial.sql"))
    connection.executescript(
        "INSERT INTO users (id, username, password_hash) VALUES (1, 'stary', 'x');"
    )
    connection.executescript(_script("002_categories_transfers_import_recovery.sql"))
    connection.executescript(
        """
        INSERT INTO wallets (id, user_id, name, initial_balance_cents)
            VALUES (1, 1, 'Portfel', 1000), (2, 1, 'Drugi', 0);
        INSERT INTO transactions (id, wallet_id, kind, occurred_on, description)
            VALUES (1, 1, 'expense', '2026-11-01', 'Zakupy');
        INSERT INTO products
            (transaction_id, position, name, category_id, quantity_milli,
             unit_price_cents, total_cents)
            VALUES (1, 0, 'Chleb',
                    (SELECT id FROM categories WHERE name = 'Dom'), 1000, 300, 300);
        INSERT INTO transfers (from_wallet_id, to_wallet_id, occurred_on, description,
                               amount_from_cents, amount_to_cents)
            VALUES (1, 2, '2026-11-02', 'Przelew', 100, 100);
        PRAGMA user_version = 2;
        """
    )
    for number in range(2, accounts + 1):
        connection.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (?, ?, 'x')",
            (number, f"konto{number}"),
        )
    connection.commit()
    connection.close()


def test_migration_removes_accounts_and_keeps_data(tmp_path):
    path = str(tmp_path / "old.db")
    _database_with_accounts(path)
    init_db(path)
    init_db(path)  # drugie uruchomienie niczego nie zmienia

    db = connect(path)
    tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master")}
    assert "users" not in tables
    assert db.execute("PRAGMA user_version").fetchone()[0] >= 3
    columns = {row["name"] for row in db.execute("PRAGMA table_info(wallets)")}
    assert "user_id" not in columns
    assert db.execute(
        "SELECT p.name, c.name FROM products p JOIN categories c ON c.id = p.category_id"
    ).fetchall()[0][:] == ("Chleb", "Dom")
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM transfers").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM wallets").fetchone()[0] == 2
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    # Klucze obce nadal działają na przebudowanych tabelach.
    with db:
        db.execute("DELETE FROM transfers")
        db.execute("DELETE FROM wallets WHERE id = 1")
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    db.close()

    backup = sqlite3.connect(f"{path}.backup-v2")
    assert backup.execute("SELECT COUNT(*) FROM users").fetchone() == (1,)
    assert backup.execute("PRAGMA user_version").fetchone() == (2,)
    backup.close()


def test_migration_with_many_accounts_changes_nothing(tmp_path):
    path = str(tmp_path / "many.db")
    _database_with_accounts(path, accounts=2)
    with pytest.raises(sqlite3.IntegrityError):
        init_db(path)

    db = sqlite3.connect(path)
    assert db.execute("PRAGMA user_version").fetchone() == (2,)
    assert db.execute("SELECT COUNT(*) FROM users").fetchone() == (2,)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone() == (1,)
    db.close()


def test_fresh_database_has_default_categories_and_no_backup(tmp_path):
    path = tmp_path / "fresh.db"
    init_db(str(path))
    db = connect(str(path))
    names = {row["name"] for row in db.execute("SELECT name FROM categories")}
    assert {"Jedzenie", "Wynagrodzenie", "Inne"} <= names and len(names) == 9
    db.close()
    assert not list(tmp_path.glob("*.backup-*"))


def _database_with_old_recurring(path):
    """Baza w wersji 5, gdy transakcje cykliczne miały własną kwotę i kategorię."""
    connection = sqlite3.connect(path)
    names = sorted(
        file.name
        for file in resources.files("finanse").joinpath("migrations").iterdir()
        if file.name.endswith(".sql") and int(file.name[:3]) <= 5
    )
    for name in names:
        connection.executescript(_script(name))
    connection.executescript(
        """
        INSERT INTO wallets (id, name) VALUES (1, 'A');
        INSERT INTO categories (id, name) VALUES (100, 'Psy');
        INSERT INTO recurring_transactions
            (id, wallet_id, kind, description, amount_cents, category_id, remaining)
        VALUES
            (1, 1, 'expense', 'Z kwotą', 5000, 100, 3),
            (2, 1, 'income', 'Bez kwoty', NULL, 100, NULL),
            (3, 1, 'expense', 'Z produktem', 999, 100, NULL);
        INSERT INTO recurring_products
            (recurring_id, position, name, quantity_milli, unit_price_cents, total_cents)
        VALUES (3, 0, 'Woda', 1000, 700, 700);
        PRAGMA user_version = 5;
        """
    )
    connection.commit()
    connection.close()


def test_recurring_amount_becomes_a_product(tmp_path):
    path = str(tmp_path / "old.db")
    _database_with_old_recurring(path)
    init_db(path)

    db = connect(path)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(recurring_transactions)")}
    assert "amount_cents" not in columns and "category_id" not in columns
    rows = db.execute(
        "SELECT recurring_id, name, category_id, quantity_e5, unit_price_e5, total_e5, total_cents"
        " FROM recurring_products ORDER BY recurring_id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (1, "Z kwotą", 100, 100000, 5000000, 5000000, 5000),
        (3, "Woda", None, 100000, 700000, 700000, 700),  # produkty mają pierwszeństwo
    ]
    remaining = db.execute(
        "SELECT id, remaining FROM recurring_transactions ORDER BY id"
    ).fetchall()
    assert [tuple(row) for row in remaining] == [(1, 3), (2, None), (3, None)]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    # Klucze obce i dziennik działają na przebudowanej tabeli.
    before = db.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
    with db:
        db.execute("UPDATE recurring_transactions SET remaining = 2 WHERE id = 1")
        db.execute("DELETE FROM wallets WHERE id = 1")
    assert db.execute("SELECT COUNT(*) FROM recurring_products").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM change_log").fetchone()[0] > before
    db.close()

    backup = sqlite3.connect(f"{path}.backup-v5")
    assert backup.execute("SELECT amount_cents FROM recurring_transactions WHERE id = 1").fetchone() == (5000,)
    backup.close()


def test_five_decimal_migration_keeps_every_product(tmp_path):
    path = str(tmp_path / "old.db")
    connection = sqlite3.connect(path)
    names = sorted(
        file.name
        for file in resources.files("finanse").joinpath("migrations").iterdir()
        if file.name.endswith(".sql") and int(file.name[:3]) <= 6
    )
    for name in names:
        connection.executescript(_script(name))
    connection.executescript(
        """
        INSERT INTO wallets (id, name, initial_balance_cents) VALUES (1, 'A', 10000);
        INSERT INTO categories (id, name) VALUES (100, 'Psy');
        INSERT INTO transactions (id, wallet_id, kind, occurred_on, description)
            VALUES (1, 1, 'expense', '2026-11-01', 'Zakupy');
        INSERT INTO products
            (id, transaction_id, position, name, category_id, quantity_milli,
             unit_price_cents, total_cents)
        VALUES
            (7, 1, 0, 'Eksploatacja', 100, 72380, 857, 62030),
            (8, 1, 1, 'Ser', NULL, 3000, 333, 1000),
            (9, 1, 2, 'Pół', NULL, 1255, 100, 126);
        INSERT INTO recurring_transactions (id, wallet_id, kind, description)
            VALUES (1, 1, 'expense', 'Media');
        INSERT INTO recurring_products
            (id, recurring_id, position, name, quantity_milli, unit_price_cents, total_cents)
            VALUES (5, 1, 0, 'Woda', 2500, 400, 1000);
        PRAGMA user_version = 6;
        """
    )
    connection.commit()
    connection.close()
    init_db(path)

    db = connect(path)
    rows = db.execute(
        "SELECT id, position, name, category_id, quantity_e5, unit_price_e5, total_e5, total_cents"
        " FROM products ORDER BY id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (7, 0, "Eksploatacja", 100, 7238000, 857000, 62030000, 62030),
        (8, 1, "Ser", None, 300000, 333000, 1000000, 1000),
        (9, 2, "Pół", None, 125500, 100000, 126000, 126),
    ]
    recurring = db.execute(
        "SELECT id, quantity_e5, unit_price_e5, total_e5, total_cents FROM recurring_products"
    ).fetchone()
    assert tuple(recurring) == (5, 250000, 400000, 1000000, 1000)
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    indexes = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"idx_products_transaction", "idx_products_category", "idx_recurring_products"} <= indexes

    # Klucze obce działają na przebudowanych tabelach.
    with db:
        db.execute("DELETE FROM categories WHERE id = 100")
    assert db.execute("SELECT category_id FROM products WHERE id = 7").fetchone()[0] is None
    with db:
        db.execute("DELETE FROM transactions WHERE id = 1")
    assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
    db.close()
