import os
import re
import sqlite3
from datetime import datetime
from importlib import resources
from pathlib import Path

STARTUP_BACKUPS_KEPT = 30
_STARTUP_BACKUP_NAME = re.compile(r"finanse-[0-9]{8}-[0-9]{6}\.db")


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


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
    connection = connect(path)
    try:
        # Migracje przebudowują tabele, a DROP TABLE przy włączonych kluczach obcych
        # skasowałby kaskadowo wiersze zależne. Spójność sprawdzamy przed COMMIT.
        connection.execute("PRAGMA foreign_keys = OFF")
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
                    f"BEGIN;\n{sql}\nPRAGMA user_version = {number};"
                )
                if connection.execute("PRAGMA foreign_key_check").fetchone():
                    raise sqlite3.IntegrityError(
                        f"Migracja {number} naruszyła klucze obce."
                    )
                connection.commit()
            except sqlite3.Error:
                connection.rollback()
                raise
    finally:
        connection.close()


def backup_on_startup(path, keep=STARTUP_BACKUPS_KEPT):
    """Kopia całej bazy w katalogu backups obok niej; zostawia `keep` najnowszych.

    Zwraca ścieżkę kopii albo None, gdy bazy jeszcze nie ma.
    """
    path = Path(path).resolve()
    if not path.exists():
        return None
    directory = path.parent / "backups"
    directory.mkdir(exist_ok=True)
    target = directory / f"finanse-{datetime.now():%Y%m%d-%H%M%S}.db"
    temporary = target.with_suffix(".tmp")
    source = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        # Kopia pojawia się pod właściwą nazwą dopiero, gdy jest kompletna.
        copy = sqlite3.connect(temporary)
        try:
            source.backup(copy)
        finally:
            copy.close()
        os.replace(temporary, target)
    finally:
        source.close()
        temporary.unlink(missing_ok=True)

    backups = sorted(
        file for file in directory.iterdir() if _STARTUP_BACKUP_NAME.fullmatch(file.name)
    )
    for old in backups[:-keep]:
        old.unlink()
    return target
