import sqlite3

import pytest

from finanse import db as db_module
from finanse.__main__ import default_database
from finanse.db import (
    backup_on_startup,
    check_backup,
    connect,
    init_db,
    latest_version,
    restore_backup,
)
from finanse.errors import ValidationError
from finanse.wallets import create_wallet, list_wallets


def test_backup_on_startup_copies_database_and_prunes_only_its_files(tmp_path):
    path = tmp_path / "finanse.db"
    assert backup_on_startup(path) is None  # bazy jeszcze nie ma
    assert not (tmp_path / "backups").exists()

    init_db(str(path))
    db = connect(str(path))
    create_wallet(db, "A")
    db.close()

    directory = tmp_path / "backups"
    directory.mkdir()
    for day in range(1, 5):
        (directory / f"finanse-2026010{day}-120000.db").write_text("stara")
    foreign = directory / "moja-kopia.db"
    foreign.write_text("nie ruszać")

    target = backup_on_startup(path, keep=2)
    copy = connect(str(target))
    assert copy.execute("SELECT name FROM wallets").fetchone()[0] == "A"
    copy.close()
    names = sorted(file.name for file in directory.iterdir())
    assert names == sorted(["finanse-20260104-120000.db", target.name, "moja-kopia.db"])
    assert foreign.read_text() == "nie ruszać"
    assert not list(directory.glob("*.tmp"))


def test_default_database_is_in_home_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert default_database() == tmp_path / ".finanse" / "finanse.db"


def _names(db):
    return [wallet["name"] for wallet in list_wallets(db)]


def test_restore_backup_replaces_data_in_open_connection(tmp_path):
    path = tmp_path / "finanse.db"
    init_db(str(path))
    db = connect(str(path))
    create_wallet(db, "Stary")
    copy = backup_on_startup(path)
    create_wallet(db, "Nowy")

    safety = restore_backup(db, copy)

    assert _names(db) == ["Stary"]
    assert safety.parent == tmp_path
    assert safety.name.startswith("finanse.db.przed-przywroceniem-")
    saved = connect(str(safety))
    assert sorted(_names(saved)) == ["Nowy", "Stary"]
    saved.close()
    # Połączenie dalej działa i zapisuje do przywróconej bazy.
    create_wallet(db, "Po przywróceniu")
    db.close()
    db = connect(str(path))
    assert sorted(_names(db)) == ["Po przywróceniu", "Stary"]
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    db.close()


def test_restore_backup_migrates_older_copy(tmp_path):
    path = tmp_path / "finanse.db"
    init_db(str(path))
    db = connect(str(path))
    create_wallet(db, "Bieżący")
    # Kopia sprzed migracji tagów: baza w wersji 10.
    older = tmp_path / "v10.db"
    source = sqlite3.connect(older)
    for number, sql in db_module._migrations():
        if number > 10:
            break
        source.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};COMMIT;")
    source.execute("INSERT INTO wallets (name) VALUES ('Z kopii')")
    source.commit()
    source.close()

    assert check_backup(older) == 10
    restore_backup(db, older)
    assert _names(db) == ["Z kopii"]
    assert db.execute("PRAGMA user_version").fetchone()[0] == latest_version()
    assert db.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 0
    db.close()


def test_restore_backup_rejects_bad_files_without_changes(tmp_path):
    path = tmp_path / "finanse.db"
    init_db(str(path))
    db = connect(str(path))
    create_wallet(db, "A")

    text = tmp_path / "notatka.txt"
    text.write_text("to nie baza")
    other = tmp_path / "inna.db"
    sqlite3.connect(other).execute("CREATE TABLE x (y)").connection.commit()
    newer = tmp_path / "nowsza.db"
    connection = sqlite3.connect(newer)
    connection.executescript(
        f"CREATE TABLE wallets (id); PRAGMA user_version = {latest_version() + 1};"
    )
    connection.close()

    cases = {
        text: "nie jest bazą danych SQLite",
        other: "nie jest kopią bazy Finanse",
        newer: "nowszej wersji aplikacji",
        tmp_path / "brak.db": "Nie ma pliku",
        path: "plik otwartej bazy",
    }
    for source, message in cases.items():
        with pytest.raises(ValidationError) as error:
            restore_backup(db, source)
        assert message in error.value.errors[0]
    assert _names(db) == ["A"]
    assert not list(tmp_path.glob("*przed-przywroceniem*"))
    db.close()


def test_restore_backup_keeps_data_when_migration_fails(tmp_path):
    path = tmp_path / "finanse.db"
    init_db(str(path))
    db = connect(str(path))
    create_wallet(db, "Bieżący")
    # Kopia z dwoma kontami: migracja 3 jej nie przyjmie.
    older = tmp_path / "konta.db"
    source = sqlite3.connect(older)
    for number, sql in db_module._migrations()[:2]:
        source.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};COMMIT;")
    source.execute("INSERT INTO users (username, password_hash) VALUES ('a', 'x'), ('b', 'x')")
    source.commit()
    source.close()

    with pytest.raises(ValidationError) as error:
        restore_backup(db, older)
    assert "Dane zostały bez zmian" in error.value.errors[-1]
    assert _names(db) == ["Bieżący"]
    assert db.execute("PRAGMA user_version").fetchone()[0] == latest_version()
    db.close()
