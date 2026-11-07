"""Strona z plikami danych, ich rozmiarem i sumami oraz przywracaniem kopii."""

import sqlite3
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..db import restore_backup
from ..errors import ValidationError
from ..storage import DATABASE, data_files, database_path, format_size
from . import common

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
NAME, SIZE, MODIFIED = range(3)
PATH = Qt.ItemDataRole.UserRole


class FilesTab(QWidget):
    """Odświeża się przy każdym otwarciu okna.

    `on_restored` wywołuje się po przywróceniu kopii, żeby widoki pokazały nowe dane.
    """

    def __init__(self, db, on_restored=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.on_restored = on_restored
        self.directory = common.plain_label()
        self.directory.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Plik", "Rozmiar", "Zmodyfikowano"])
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(SIZE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(MODIFIED, QHeaderView.ResizeMode.ResizeToContents)
        self.total = QLabel()
        font = QFont(self.total.font())
        font.setBold(True)
        self.total.setFont(font)
        self.restore_button = QPushButton("Przywróć zaznaczoną kopię…")
        self.restore_button.clicked.connect(self.restore_selected)
        self.restore_file_button = QPushButton("Przywróć z pliku…")
        self.restore_file_button.clicked.connect(self.restore_from_file)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda *_: self.restore_selected())

        buttons = QHBoxLayout()
        buttons.addWidget(self.total, 1)
        buttons.addWidget(self.restore_button)
        buttons.addWidget(self.restore_file_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.directory)
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)
        self.refresh()

    def selected_path(self):
        """Zaznaczona kopia; pliki samej bazy i nagłówki grup się nie liczą."""
        item = self.tree.currentItem()
        if item is None or not item.isSelected():
            return None
        return item.data(NAME, PATH)

    def _update_buttons(self):
        self.restore_button.setEnabled(self.selected_path() is not None)

    def restore_selected(self):
        path = self.selected_path()
        if path is not None:
            self.restore(path)

    def restore_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Wybierz kopię bazy",
            str(database_path(self.db).parent),
            "Kopie bazy (*.db *.db.* *.sqlite);;Wszystkie pliki (*)",
        )
        if path:
            self.restore(path)

    def restore(self, path):
        """Pyta o zgodę i zastępuje dane kopią; zwraca True po przywróceniu."""
        path = Path(path)
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError as error:
            common.show_errors(self, [f"Nie da się odczytać pliku {path}: {error}"])
            return False
        question = (
            f"Przywrócić kopię „{path.name}” z {modified:%Y-%m-%d %H:%M}?\n\n"
            "Wszystkie obecne dane zostaną zastąpione danymi z kopii. Przed tym aplikacja"
            " zapisze obecną bazę obok niej, więc przywrócenie da się cofnąć."
        )
        if not common.confirm(self, question, "Przywróć"):
            return False
        try:
            safety = restore_backup(self.db, path)
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return False
        except (OSError, sqlite3.Error) as error:
            common.show_errors(self, [f"Nie udało się przywrócić kopii: {error}"])
            return False
        self.refresh()
        if self.on_restored:
            self.on_restored()
        common.show_info(
            self,
            f"Przywrócono kopię „{path.name}”.\n\n"
            f"Poprzednie dane są w pliku „{safety.name}”. Aby do nich wrócić,"
            " przywróć ten plik.",
        )
        return True

    def refresh(self):
        database = database_path(self.db)
        groups, count, size = data_files(database)
        self.directory.setText(f"Katalog: {database.parent}")
        self.total.setText(f"Razem: {format_size(size)}, plików: {count}")
        self.tree.clear()
        for group in groups:
            item = QTreeWidgetItem(
                [
                    f"{group['name']} (plików: {len(group['files'])})",
                    format_size(group["size"]),
                    "",
                ]
            )
            font = QFont(item.font(NAME))
            font.setBold(True)
            for column in range(self.tree.columnCount()):
                item.setFont(column, font)
            item.setTextAlignment(SIZE, RIGHT)
            for file in group["files"]:
                child = QTreeWidgetItem(
                    [
                        file["name"],
                        format_size(file["size"]),
                        file["modified"].strftime("%Y-%m-%d %H:%M:%S"),
                    ]
                )
                child.setTextAlignment(SIZE, RIGHT)
                child.setToolTip(NAME, str(file["path"]))
                if group["name"] != DATABASE:
                    child.setData(NAME, PATH, str(file["path"]))
                item.addChild(child)
            self.tree.addTopLevelItem(item)
            item.setExpanded(True)
        self._update_buttons()
