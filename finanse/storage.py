"""Pliki z danymi aplikacji i zajmowane przez nie miejsce."""

import re
from datetime import datetime
from pathlib import Path

DATABASE, STARTUP_BACKUPS, OTHER_BACKUPS, OTHER_FILES = (
    "Baza danych",
    "Kopie przy starcie",
    "Kopie przed migracjami i ręczne",
    "Inne pliki",
)
GROUP_ORDER = (DATABASE, STARTUP_BACKUPS, OTHER_BACKUPS, OTHER_FILES)
_STARTUP_BACKUP = re.compile(r"finanse-[0-9]{8}-[0-9]{6}\.db")


def database_path(db):
    """Ścieżka pliku bazy otwartej w tym połączeniu."""
    return Path(db.execute("PRAGMA database_list").fetchone()["file"])


def format_size(size):
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < 1024:
            break
        value /= 1024
    else:
        unit = "GB"
    if unit == "B":
        return f"{size} B"
    return f"{value:.1f} {unit}".replace(".", ",")


def _group(path, database):
    if path.parent == database.parent:
        if path.name == database.name or path.name.startswith(f"{database.name}-"):
            return DATABASE  # razem z plikami pomocniczymi SQLite
        if path.name.startswith(f"{database.name}."):
            return OTHER_BACKUPS
        return OTHER_FILES
    return STARTUP_BACKUPS if _STARTUP_BACKUP.fullmatch(path.name) else OTHER_FILES


def data_files(database):
    """Grupy plików z katalogu bazy i podkatalogu backups, od najnowszych.

    Zwraca (grupy, liczba plików, łączny rozmiar). Puste grupy są pomijane.
    """
    database = Path(database)
    groups = {name: [] for name in GROUP_ORDER}
    directories = (database.parent, database.parent / "backups")
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            try:
                if not path.is_file():
                    continue
                stat = path.stat()
            except OSError:  # plik mógł zniknąć w trakcie odczytu
                continue
            groups[_group(path, database)].append(
                {
                    "path": path,
                    "name": str(path.relative_to(database.parent)),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime),
                }
            )
    result = []
    for name in GROUP_ORDER:
        files = sorted(
            groups[name], key=lambda file: (file["modified"], file["name"]), reverse=True
        )
        if files:
            result.append(
                {"name": name, "files": files, "size": sum(f["size"] for f in files)}
            )
    return (
        result,
        sum(len(group["files"]) for group in result),
        sum(group["size"] for group in result),
    )
