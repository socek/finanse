from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..budgets import budget_currencies, list_budgets
from ..categories import (
    create_category,
    delete_category,
    deletion_block_reason,
    list_categories,
    rename_category,
)
from ..errors import ValidationError
from ..money import format_money
from . import common, shortcuts
from .dialogs import BudgetDialog

BUDGET = 3


class CategoriesTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

        self.new_name = QLineEdit()
        self.new_name.setMaxLength(50)
        self.new_name.setPlaceholderText("Nazwa nowej kategorii")
        self.new_name.returnPressed.connect(self.add)
        add = QPushButton("Dodaj")
        add.clicked.connect(self.add)
        top = QHBoxLayout()
        top.addWidget(self.new_name, 1)
        top.addWidget(add)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Kategoria", "Produkty", "W cyklicznych", "Budżet miesięczny"]
        )
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            BUDGET, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.itemDoubleClicked.connect(
            lambda item: self.edit_budget() if item.column() == BUDGET else self.rename()
        )
        self.table.currentCellChanged.connect(lambda *_: self._update_buttons())
        self.delete_shortcut = shortcuts.bind(
            "delete_selected", self.table, self.delete, Qt.ShortcutContext.WidgetShortcut
        )
        self.empty = QLabel("Nie masz jeszcze kategorii.")

        self.rename_button = QPushButton("Zmień nazwę")
        shortcuts.show_on(self.rename_button, "edit_selected")
        self.rename_button.clicked.connect(self.rename)
        self.delete_button = QPushButton("Usuń")
        self.delete_button.clicked.connect(self.delete)
        self.budget_button = QPushButton("Budżet")
        self.budget_button.setToolTip("Miesięczny limit wydatków w zaznaczonej kategorii.")
        self.budget_button.clicked.connect(self.edit_budget)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.budget_button)
        actions.addWidget(self.rename_button)
        actions.addWidget(self.delete_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.empty)
        layout.addWidget(self.table, 1)
        layout.addLayout(actions)
        self.refresh()

    def edit_selected(self):
        self.rename()

    def refresh(self):
        categories = list_categories(self.db)
        budgets = {}
        for budget in list_budgets(self.db):
            budgets.setdefault(budget["category_id"], []).append(
                format_money(budget["amount_cents"], budget["currency"])
            )
        self.table.setRowCount(len(categories))
        for row, category in enumerate(categories):
            name = QTableWidgetItem(category["name"])
            name.setData(Qt.ItemDataRole.UserRole, category["id"])
            self.table.setItem(row, 0, name)
            for column, key in ((1, "product_count"), (2, "recurring_count")):
                count = QTableWidgetItem(str(category[key]))
                count.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.table.setItem(row, column, count)
            budget = QTableWidgetItem(", ".join(budgets.get(category["id"], [])) or "–")
            budget.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, BUDGET, budget)
        self.table.setCurrentCell(-1, -1)
        self.empty.setVisible(not categories)
        self._update_buttons()

    def _selected(self):
        row = self.table.currentRow()
        if row < 0:
            return None, None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole), item.text()

    def _block_reason(self, row):
        return deletion_block_reason(
            int(self.table.item(row, 1).text()), int(self.table.item(row, 2).text())
        )

    def _update_buttons(self):
        row = self.table.currentRow()
        selected = row >= 0
        self.rename_button.setEnabled(selected)
        self.budget_button.setEnabled(selected)
        reason = self._block_reason(row) if selected else "Zaznacz kategorię."
        self.delete_button.setEnabled(not reason)
        self.delete_button.setToolTip(shortcuts.tooltip("delete_selected", reason))

    def add(self):
        try:
            create_category(self.db, self.new_name.text())
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        self.new_name.clear()
        self.refresh()

    def rename(self):
        category_id, current = self._selected()
        if category_id is None:
            return
        name, accepted = QInputDialog.getText(
            self, "Zmiana nazwy", "Nowa nazwa kategorii:", text=current
        )
        if not accepted:
            return
        try:
            rename_category(self.db, category_id, name)
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        self.refresh()

    def _delete_question(self, name):
        question = f"Usunąć pustą kategorię „{name}”?"
        if self.table.item(self.table.currentRow(), BUDGET).text() != "–":
            question += " Jej budżet też zostanie usunięty."
        return question

    def edit_budget(self):
        category_id, name = self._selected()
        if category_id is None:
            return
        if not budget_currencies(self.db):
            common.show_errors(self, ["Dodaj najpierw portfel, żeby wybrać walutę budżetu."])
            return
        if BudgetDialog(self.db, category_id, name, parent=self).exec():
            self.refresh()

    def delete(self):
        category_id, name = self._selected()
        if category_id is None:
            return
        # Klawisz działa też wtedy, gdy przycisk jest wyłączony, więc wyjaśniamy powód.
        reason = self._block_reason(self.table.currentRow())
        if reason:
            common.show_errors(self, [reason])
        elif common.confirm(self, self._delete_question(name)):
            delete_category(self.db, category_id)
            self.refresh()
