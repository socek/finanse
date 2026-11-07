"""Uruchomienie: python -m finanse [ścieżka do bazy]."""

import sqlite3
import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

from .db import backup_on_startup, connect, init_db
from .gui import title_bar
from .gui.main_window import MainWindow
from .gui.themes import apply_theme
from .settings import load_settings


def default_database():
    """Baza w osobnym katalogu, bo obok niej powstają kopie."""
    return Path.home() / ".finanse" / "finanse.db"


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("finanse")
    app.setDesktopFileName("finanse")  # app_id okna na Waylandzie

    QLocale.setDefault(QLocale(QLocale.Language.Polish, QLocale.Country.Poland))
    translator = QTranslator(app)
    if translator.load(
        "qtbase_pl", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    ):
        app.installTranslator(translator)

    path = Path(argv[1]) if len(argv) > 1 else default_database()
    try:
        # Tryb 700 dotyczy tylko nowego katalogu: dane nie są szyfrowane.
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError as error:
        QMessageBox.critical(
            None, "Finanse", f"Nie udało się otworzyć bazy {path}:\n{error}"
        )
        return 1
    try:
        backup_on_startup(path)
    except (OSError, sqlite3.Error) as error:
        QMessageBox.warning(
            None,
            "Finanse",
            f"Nie udało się zrobić kopii bazy przy starcie:\n{error}\n\n"
            "Aplikacja uruchomi się bez tej kopii.",
        )
    try:
        init_db(str(path))
        db = connect(str(path))
    except (OSError, sqlite3.Error) as error:
        QMessageBox.critical(
            None, "Finanse", f"Nie udało się otworzyć bazy {path}:\n{error}"
        )
        return 1

    settings = load_settings(path)
    apply_theme(settings.get("theme"))
    title_bar.install(app, settings.get(title_bar.SETTING, title_bar.default_enabled()))
    window = MainWindow(db)
    window.show()
    try:
        return app.exec()
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
