import sqlite3
from importlib import resources
from pathlib import Path

from flask import current_app, g

DEFAULT_CATEGORIES = (
    "Jedzenie",
    "Dom",
    "Rachunki",
    "Transport",
    "Zdrowie",
    "Ubrania",
    "Rozrywka",
    "Wynagrodzenie",
    "Inne",
)


def _connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_db():
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exception=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def seed_default_categories(db, user_id):
    db.executemany(
        "INSERT INTO categories (user_id, name) VALUES (?, ?)",
        [(user_id, name) for name in DEFAULT_CATEGORIES],
    )


def _migrations():
    """Zwraca posortowane pary (numer, SQL) z plików migrations/NNN_nazwa.sql."""
    directory = resources.files(__package__).joinpath("migrations")
    files = [file for file in directory.iterdir() if file.name.endswith(".sql")]
    return sorted((int(file.name[:3]), file.read_text("utf-8")) for file in files)


def _backup(connection, path, version):
    """Kopia przed migracją; istniejącej starszej kopii nie nadpisuje."""
    backup_path = Path(f"{path}.backup-v{version}")
    if backup_path.exists():
        return
    target = sqlite3.connect(backup_path)
    try:
        connection.backup(target)
    finally:
        target.close()


def init_db(path):
    connection = _connect(path)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        pending = [item for item in _migrations() if item[0] > version]
        has_tables = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1"
        ).fetchone()
        if pending and has_tables:
            _backup(connection, path, version)
        for number, sql in pending:
            try:
                connection.executescript(
                    f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;"
                )
            except sqlite3.Error:
                connection.rollback()
                raise
    finally:
        connection.close()
