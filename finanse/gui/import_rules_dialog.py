"""Reguły importu: lista z kolejnością oraz formularz jednej reguły."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..categories import list_categories
from ..errors import ValidationError
from ..import_rules import (
    MAX_PATTERN_LENGTH,
    MAX_PRODUCT_NAME_LENGTH,
    create_rule,
    delete_rule,
    kind_label,
    list_rules,
    move_rule,
    update_rule,
)
from . import common
from .tags_edit import TagsEdit

KEEP_CATEGORY = "Bez zmiany"


class RuleDialog(QDialog):
    """Nowa reguła albo edycja istniejącej; `pattern` wypełnia tekst nowej reguły."""

    def __init__(self, db, rule=None, pattern="", kind=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.rule_id = rule["id"] if rule else None
        self.setWindowTitle("Edycja reguły importu" if rule else "Nowa reguła importu")

        self.pattern = QLineEdit(rule["pattern"] if rule else pattern)
        self.pattern.setMaxLength(MAX_PATTERN_LENGTH)
        self.pattern.setPlaceholderText("np. BIEDRONKA")
        self.kind = QComboBox()
        for value in (None, "expense", "income"):
            self.kind.addItem(kind_label(value).capitalize(), value)
        self.kind.setCurrentIndex(max(self.kind.findData(rule["kind"] if rule else kind), 0))
        self.category = QComboBox()
        self.category.addItem(KEEP_CATEGORY, None)
        for category in list_categories(db):
            self.category.addItem(category["name"], category["id"])
        if rule:
            self.category.setCurrentIndex(max(self.category.findData(rule["category_id"]), 0))
        self.product_name = QLineEdit((rule["product_name"] or "") if rule else "")
        self.product_name.setMaxLength(MAX_PRODUCT_NAME_LENGTH)
        self.product_name.setPlaceholderText("puste: opis z wyciągu")
        self.tags = TagsEdit(db)
        if rule:
            self.tags.setText(rule["tags"])

        form = QFormLayout()
        form.addRow("Opis zawiera", self.pattern)
        form.addRow("Dotyczy", self.kind)
        form.addRow("Kategoria", self.category)
        form.addRow("Nazwa produktu", self.product_name)
        form.addRow("Tagi", self.tags)
        hint = QLabel(
            "Wielkość liter i polskie znaki nie mają znaczenia: „Żabka” pasuje do"
            " „ZABKA 1234 KRAKOW”. Wygrywa pierwsza pasująca reguła z listy."
        )
        hint.setWordWrap(True)
        buttons = QDialogButtonBox()
        buttons.addButton("Zapisz", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Anuluj", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.resize(520, self.sizeHint().height())

    def accept(self):
        values = (
            self.pattern.text(),
            self.kind.currentData(),
            self.category.currentData(),
            self.product_name.text(),
            self.tags.text(),
        )
        try:
            if self.rule_id is None:
                self.rule_id = create_rule(self.db, *values)
            else:
                update_rule(self.db, self.rule_id, *values)
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        super().accept()


class RulesDialog(QDialog):
    PATTERN, KIND, CATEGORY, NAME, TAGS = range(5)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("Reguły importu")
        intro = QLabel(
            "Gdy opis z wyciągu zawiera tekst reguły, import nadaje transakcji kategorię,"
            " nazwę produktu i tagi z reguły. Wiersz bez reguły dostaje kategorię wybraną"
            " w oknie importu."
        )
        intro.setWordWrap(True)
        self.empty = QLabel("Nie masz jeszcze reguł importu.")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Opis zawiera", "Dotyczy", "Kategoria", "Nazwa produktu", "Tagi"]
        )
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        for column in range(5):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Stretch
                if column in (self.PATTERN, self.NAME)
                else QHeaderView.ResizeMode.ResizeToContents,
            )
        self.table.itemDoubleClicked.connect(lambda *_: self.edit())
        self.table.currentCellChanged.connect(lambda *_: self._update_buttons())

        self.add_button = QPushButton("Dodaj")
        self.add_button.clicked.connect(self.add)
        self.edit_button = QPushButton("Edytuj")
        self.edit_button.clicked.connect(self.edit)
        self.delete_button = QPushButton("Usuń")
        self.delete_button.clicked.connect(self.delete)
        self.up_button = QPushButton("W górę")
        self.up_button.clicked.connect(lambda: self.move(-1))
        self.down_button = QPushButton("W dół")
        self.down_button.clicked.connect(lambda: self.move(1))
        actions = QHBoxLayout()
        actions.addWidget(self.add_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch()
        actions.addWidget(self.up_button)
        actions.addWidget(self.down_button)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Zamknij")
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.empty)
        layout.addWidget(self.table, 1)
        layout.addLayout(actions)
        layout.addWidget(buttons)
        self.resize(860, 520)
        self.refresh()

    def refresh(self, select=None):
        rules = list_rules(self.db)
        self.table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            cells = (
                rule["pattern"],
                kind_label(rule["kind"]),
                rule["category_name"] or KEEP_CATEGORY,
                rule["product_name"] or "opis z wyciągu",
                rule["tags"] or "–",
            )
            for column, text in enumerate(cells):
                self.table.setItem(row, column, QTableWidgetItem(text))
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, rule["id"])
            if rule["id"] == select:
                self.table.setCurrentCell(row, 0)
        if select is None:
            self.table.setCurrentCell(-1, -1)
        self.empty.setVisible(not rules)
        self._update_buttons()

    def selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _update_buttons(self):
        row = self.table.currentRow()
        selected = row >= 0
        for button in (self.edit_button, self.delete_button):
            button.setEnabled(selected)
        self.up_button.setEnabled(selected and row > 0)
        self.down_button.setEnabled(selected and row < self.table.rowCount() - 1)

    def add(self):
        dialog = RuleDialog(self.db, parent=self)
        if dialog.exec():
            self.refresh(dialog.rule_id)

    def edit(self):
        rule_id = self.selected_id()
        if rule_id is None:
            return
        rule = next(rule for rule in list_rules(self.db) if rule["id"] == rule_id)
        if RuleDialog(self.db, rule, parent=self).exec():
            self.refresh(rule_id)

    def delete(self):
        rule_id = self.selected_id()
        if rule_id is None:
            return
        pattern = self.table.item(self.table.currentRow(), 0).text()
        if common.confirm(self, f"Usunąć regułę „{pattern}”?"):
            delete_rule(self.db, rule_id)
            self.refresh()

    def move(self, offset):
        rule_id = self.selected_id()
        if rule_id is not None:
            move_rule(self.db, rule_id, offset)
            self.refresh(rule_id)
