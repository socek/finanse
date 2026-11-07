"""Strona z plikami danych, ich rozmiarem i sumami."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..storage import data_files, database_path, format_size
from . import common

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
NAME, SIZE, MODIFIED = range(3)


class FilesTab(QWidget):
    """Odświeża się przy każdym otwarciu okna."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
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

        layout = QVBoxLayout(self)
        layout.addWidget(self.directory)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.total)
        self.refresh()

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
                item.addChild(child)
            self.tree.addTopLevelItem(item)
            item.setExpanded(True)
