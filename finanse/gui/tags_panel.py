"""Lista tagów z liczbą transakcji, zmianą nazwy i usuwaniem; część zakładki Kategorie."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..errors import ValidationError
from ..tags import delete_tag, list_tags, rename_tag
from . import common, shortcuts


class TagsPanel(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        title = QLabel("Tagi")
        font = QFont(title.font())
        font.setBold(True)
        title.setFont(font)
        hint = QLabel(
            "Tagi dodajesz w oknie transakcji, po przecinku. Łączą transakcje niezależnie"
            " od kategorii, np. wydatki na wakacje. Raport pokazuje ich podsumowanie."
        )
        hint.setWordWrap(True)
        self.empty = QLabel("Nie masz jeszcze tagów.")

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Tag", "Transakcje"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemDoubleClicked.connect(lambda *_: self.rename())
        self.table.currentCellChanged.connect(lambda *_: self._update_buttons())
        common.attach_row_menu(self.table, self._row_menu)
        self.delete_shortcut = shortcuts.bind(
            "delete_selected", self.table, self.delete, Qt.ShortcutContext.WidgetShortcut
        )

        self.rename_button = QPushButton("Zmień nazwę tagu")
        self.rename_button.clicked.connect(self.rename)
        self.delete_button = QPushButton("Usuń tag")
        self.delete_button.clicked.connect(self.delete)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.rename_button)
        actions.addWidget(self.delete_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self.empty)
        layout.addWidget(self.table, 1)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        tags = list_tags(self.db)
        self.table.setRowCount(len(tags))
        for row, tag in enumerate(tags):
            name = QTableWidgetItem(tag["name"])
            name.setData(Qt.ItemDataRole.UserRole, tag["id"])
            count = QTableWidgetItem(str(tag["transaction_count"]))
            count.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, count)
        self.table.setCurrentCell(-1, -1)
        self.empty.setVisible(not tags)
        self.table.setVisible(bool(tags))
        self._update_buttons()

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None, None, 0
        item = self.table.item(row, 0)
        count = int(self.table.item(row, 1).text())
        return item.data(Qt.ItemDataRole.UserRole), item.text(), count

    def _update_buttons(self):
        selected = self.table.currentRow() >= 0
        self.rename_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    def _row_menu(self):
        menu = QMenu(self)
        menu.addAction("Zmień nazwę", self.rename)
        menu.addAction("Usuń", self.delete)
        return menu

    def rename(self):
        tag_id, current, _count = self._selected()
        if tag_id is None:
            return
        name, accepted = QInputDialog.getText(
            self, "Zmiana nazwy tagu", "Nowa nazwa tagu:", text=current
        )
        if not accepted:
            return
        try:
            rename_tag(self.db, tag_id, name)
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        self.refresh()

    def delete(self):
        tag_id, name, count = self._selected()
        if tag_id is None:
            return
        question = f"Usunąć tag „{name}”?"
        if count:
            question += f" Zniknie z transakcji ({count}), ale same transakcje zostaną."
        if common.confirm(self, question):
            delete_tag(self.db, tag_id)
            self.refresh()
