"""Zakładka transakcji cyklicznych z przyciskiem płatności przy każdej z nich."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..money import format_money
from ..recurring import delete_recurring, list_recurring
from ..wallets import get_wallet, list_wallets
from . import common, shortcuts
from .dialogs import PaymentDialog, RecurringDialog

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
DESCRIPTION, WALLET, CATEGORY, PRODUCTS, AMOUNT, REMAINING, LAST_PAID, PAY = range(8)


class RecurringTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

        new_button = QPushButton("Nowa transakcja cykliczna")
        new_button.clicked.connect(self.create)
        top = QHBoxLayout()
        top.addWidget(new_button)
        top.addStretch()

        self.empty = QLabel("Nie masz jeszcze transakcji cyklicznych.")
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                "Opis",
                "Portfel",
                "Kategoria",
                "Produkty",
                "Kwota",
                "Pozostało płatności",
                "Ostatnia płatność",
                "",
            ]
        )
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        for column in range(self.table.columnCount()):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Stretch
                if column == DESCRIPTION
                else QHeaderView.ResizeMode.ResizeToContents,
            )
        self.table.itemDoubleClicked.connect(lambda *_: self.edit())
        self.table.currentCellChanged.connect(lambda *_: self._update_buttons())
        self.delete_shortcut = shortcuts.bind(
            "delete_selected", self.table, self.delete, Qt.ShortcutContext.WidgetShortcut
        )

        self.edit_button = QPushButton("Edytuj")
        self.edit_button.clicked.connect(self.edit)
        self.delete_button = QPushButton("Usuń")
        self.delete_button.clicked.connect(self.delete)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.empty)
        layout.addWidget(self.table, 1)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        selected = self.selected_id()
        items = list_recurring(self.db)
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._fill_row(row, item)
            if item["id"] == selected:
                self.table.setCurrentCell(row, DESCRIPTION)
        if selected not in {item["id"] for item in items}:
            self.table.setCurrentCell(-1, -1)
        self.empty.setVisible(not items)
        self._update_buttons()

    def _fill_row(self, row, item):
        income = item["kind"] == "income"
        if item["total_cents"] is None:
            amount = "ustalana przy płatności"
        else:
            sign = "+" if income else "−"
            amount = f"{sign}{format_money(item['total_cents'], item['currency'])}"
        if item["remaining"] is None:
            remaining = "bez limitu"
        elif item["remaining"] == 0:
            remaining = "0 (zakończona)"
        else:
            remaining = str(item["remaining"])
        categories = (
            item["product_categories"] or "Bez kategorii"
            if item["product_count"]
            else "–"
        )
        cells = {
            DESCRIPTION: item["description"],
            WALLET: item["wallet_name"],
            CATEGORY: categories,
            PRODUCTS: str(item["product_count"]) if item["product_count"] else "–",
            AMOUNT: amount,
            REMAINING: remaining,
            LAST_PAID: item["last_paid_on"] or "–",
        }
        for column, text in cells.items():
            cell = QTableWidgetItem(text)
            if column in (PRODUCTS, AMOUNT, REMAINING):
                cell.setTextAlignment(RIGHT)
            self.table.setItem(row, column, cell)
        self.table.item(row, DESCRIPTION).setData(Qt.ItemDataRole.UserRole, item["id"])
        if categories == common.NO_CATEGORY_NAME:
            common.mark_no_category_cell(self.table.item(row, CATEGORY))
        if item["total_cents"] is not None:
            self.table.item(row, AMOUNT).setForeground(
                common.positive_color() if income else common.negative_color()
            )
        pay = QPushButton("Zapłać")
        pay.setEnabled(item["remaining"] != 0)
        pay.clicked.connect(lambda: self.pay(item["id"], item["wallet_id"]))
        self.table.setCellWidget(row, PAY, pay)

    def selected_id(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, DESCRIPTION) is None:
            return None
        return self.table.item(row, DESCRIPTION).data(Qt.ItemDataRole.UserRole)

    def _update_buttons(self):
        selected = self.selected_id() is not None
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)

    def edit_selected(self):
        self.edit()

    def pay_selected(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.cellWidget(row, PAY).click()

    def create(self):
        if not list_wallets(self.db):
            common.show_errors(self, ["Dodaj najpierw portfel."])
            return
        if RecurringDialog(self.db, parent=self).exec():
            self.refresh()

    def edit(self):
        recurring_id = self.selected_id()
        if recurring_id is None:
            return
        if RecurringDialog(self.db, recurring_id, parent=self).exec():
            self.refresh()

    def delete(self):
        recurring_id = self.selected_id()
        if recurring_id is None:
            return
        description = self.table.item(self.table.currentRow(), DESCRIPTION).text()
        if common.confirm(
            self,
            f"Usunąć transakcję cykliczną „{description}”? "
            "Zapłacone już transakcje zostaną w portfelu.",
        ):
            delete_recurring(self.db, recurring_id)
            self.refresh()

    def pay(self, recurring_id, wallet_id):
        wallet = get_wallet(self.db, wallet_id)
        if PaymentDialog(self.db, wallet, recurring_id, parent=self).exec():
            self.refresh()
