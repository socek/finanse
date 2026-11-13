from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..budgets import list_budgets
from ..categories import (
    create_category,
    delete_category,
    deletion_block_reason,
    list_categories,
)
from ..errors import ValidationError
from ..money import format_money, format_totals
from . import common, shortcuts
from .dialogs import CategoryDialog
from .tags_panel import TagsPanel

BUDGET = 3


class CategoriesTab(QWidget):
    selection_changed = Signal()

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
        common.multi_select(self.table)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            BUDGET, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.itemDoubleClicked.connect(
            lambda item: self.edit(focus_budget=item.column() == BUDGET)
        )
        self.table.currentCellChanged.connect(lambda *_: self._update_buttons())
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        common.attach_row_menu(self.table, self._row_menu)
        self.delete_shortcut = shortcuts.bind(
            "delete_selected", self.table, self.delete, Qt.ShortcutContext.WidgetShortcut
        )
        self.empty = QLabel("Nie masz jeszcze kategorii.")

        self.edit_button = QPushButton("Edytuj")
        shortcuts.show_on(self.edit_button, "edit_selected")
        self.edit_button.clicked.connect(lambda: self.edit())
        self.delete_button = QPushButton("Usuń")
        self.delete_button.clicked.connect(self.delete)
        self.summary = QLabel()
        actions = QHBoxLayout()
        actions.addWidget(self.summary)
        actions.addStretch()
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)

        self.tags = TagsPanel(db)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.empty)
        layout.addWidget(self.table, 2)
        layout.addLayout(actions)
        layout.addSpacing(12)
        layout.addWidget(self.tags, 1)
        self.refresh()

    def edit_selected(self):
        self.edit()

    def refresh(self):
        categories = list_categories(self.db)
        budgets = {}
        totals = {}
        amounts = {}
        for budget in list_budgets(self.db):
            budgets.setdefault(budget["category_id"], []).append(
                format_money(budget["amount_cents"], budget["currency"])
            )
            amounts.setdefault(budget["category_id"], []).append(
                (budget["currency"], budget["amount_cents"])
            )
            totals[budget["currency"]] = (
                totals.get(budget["currency"], 0) + budget["amount_cents"]
            )
        self.summary.setText(f"Suma budżetów: {format_totals(totals)}")
        self.summary.setVisible(bool(totals))
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
            budget.setData(common.SUM_ROLE, amounts.get(category["id"], []))
            self.table.setItem(row, BUDGET, budget)
        self.table.setCurrentCell(-1, -1)
        self.empty.setVisible(not categories)
        if hasattr(self, "tags"):
            self.tags.refresh()
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

    def selection_summary(self):
        rows = common.selected_rows(self.table)
        totals = {}
        for row in rows:
            common.add_amounts(totals, self.table.item(row, BUDGET).data(common.SUM_ROLE))
        return common.selection_summary(len(rows), totals, "Suma budżetów")

    def _delete_rows(self):
        """Wiersze do usunięcia: kilka zaznaczonych albo bieżący."""
        rows = common.selected_rows(self.table)
        if len(rows) > 1:
            return rows
        current = self.table.currentRow()
        return [current] if current >= 0 else []

    def _rows_block_reason(self, rows):
        if len(rows) == 1:
            return self._block_reason(rows[0])
        blocked = [self.table.item(row, 0).text() for row in rows if self._block_reason(row)]
        if blocked:
            return "Usunąć można tylko puste kategorie. Niepuste: " + ", ".join(blocked) + "."
        return ""

    def _update_buttons(self):
        row = self.table.currentRow()
        selected = row >= 0
        self.edit_button.setEnabled(selected)
        rows = self._delete_rows()
        reason = self._rows_block_reason(rows) if rows else "Zaznacz kategorię."
        self.delete_button.setEnabled(not reason)
        self.delete_button.setText(f"Usuń zaznaczone ({len(rows)})" if len(rows) > 1 else "Usuń")
        self.delete_button.setToolTip(shortcuts.tooltip("delete_selected", reason))

    def _row_menu(self):
        """Menu zaznaczonej kategorii; niepustej nie da się usunąć."""
        menu = QMenu(self)
        menu.addAction("Edytuj", self.edit)
        rows = self._delete_rows()
        if not self._rows_block_reason(rows):
            menu.addAction(f"Usuń zaznaczone ({len(rows)})" if len(rows) > 1 else "Usuń",
                           self.delete)  # fmt: skip
        return menu

    def add(self):
        try:
            create_category(self.db, self.new_name.text())
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        self.new_name.clear()
        self.refresh()

    def edit(self, focus_budget=False):
        """Nazwa i budżety w jednym oknie; dwuklik w kolumnę budżetu zaczyna od kwoty."""
        category_id, name = self._selected()
        if category_id is None:
            return
        if CategoryDialog(self.db, category_id, name, focus_budget, parent=self).exec():
            self.refresh()

    def _delete_question(self, name):
        question = f"Usunąć pustą kategorię „{name}”?"
        if self.table.item(self.table.currentRow(), BUDGET).text() != "–":
            question += " Jej budżet też zostanie usunięty."
        return question

    def delete(self):
        rows = self._delete_rows()
        if len(rows) > 1:
            self._delete_many(rows)
            return
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

    def _delete_many(self, rows):
        reason = self._rows_block_reason(rows)
        if reason:
            common.show_errors(self, [reason])
            return
        question = f"Usunąć zaznaczone puste kategorie ({len(rows)})?"
        if any(self.table.item(row, BUDGET).text() != "–" for row in rows):
            question += " Ich budżety też zostaną usunięte."
        if common.confirm(self, question):
            for row in rows:
                delete_category(self.db, self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            self.refresh()
