"""Ustawienia aplikacji w pliku obok bazy, oddzielnie od danych finansowych."""

import json
import os
from pathlib import Path

FILE_NAME = "settings.json"


def settings_path(database):
    return Path(database).parent / FILE_NAME


def load_settings(database):
    """Brakujący lub uszkodzony plik oznacza ustawienia domyślne."""
    try:
        settings = json.loads(settings_path(database).read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return settings if isinstance(settings, dict) else {}


def save_setting(database, name, value):
    """Zapisuje przez plik tymczasowy, żeby awaria nie zostawiła uciętego pliku."""
    settings = {**load_settings(database), name: value}
    path = settings_path(database)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2), "utf-8")
    os.replace(temporary, path)
