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
    assert db.execute("PRAGMA user_version").fetchone()[0] == 3
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
