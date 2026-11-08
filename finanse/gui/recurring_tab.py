"""Zakładka transakcji cyklicznych z przyciskiem płatności przy każdej z nich."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..money import format_money, format_totals
from ..errors import ValidationError
from ..recurring import (
    DUE_SOON_DAYS,
    count_due,
    days_until_due,
    delete_recurring,
    due_text,
    list_recurring,
    period_text,
    recurring_totals,
    set_suspended,
    skip_due,
)
from ..wallets import get_wallet, list_wallets
from . import common, shortcuts
from .dialogs import PaymentDialog, RecurringDialog

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
(
    DESCRIPTION, WALLET, CATEGORY, PRODUCTS, AMOUNT, PERIOD, DUE, REMAINING, LAST_PAID, PAY,
) = range(10)  # fmt: skip
OVERDUE_HINT = "Termin płatności minął."
DUE_SOON_HINT = f"Termin płatności przypada w ciągu {DUE_SOON_DAYS} dni."
SUSPENDED_HINT = "Zawieszona: nie liczy się do sum, prognozy ani płatności po terminie."


class RecurringTab(QWidget):
    # Liczba płatności po terminie lub na dzisiaj, do pokazania w nazwie zakładki.
    due_count_changed = Signal(int)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.skippable = set()
        self.suspended = set()

        new_button = QPushButton("Nowa transakcja cykliczna")
        shortcuts.show_on(new_button, "new_recurring")
        new_button.clicked.connect(self.create)
        top = QHBoxLayout()
        top.addWidget(new_button)
        top.addStretch()

        self.empty = QLabel("Nie masz jeszcze transakcji cyklicznych.")
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            [
                "Opis",
                "Portfel",
                "Kategoria",
                "Produkty",
                "Kwota",
                "Powtarzanie",
                "Termin",
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
        common.attach_row_menu(self.table, self._row_menu)
        self.delete_shortcut = shortcuts.bind(
            "delete_selected", self.table, self.delete, Qt.ShortcutContext.WidgetShortcut
        )

        self.skip_button = QPushButton("Pomiń termin")
        self.skip_button.setToolTip(
            "Przesuwa termin zaznaczonej transakcji o jeden okres bez płatności."
        )
        self.skip_button.clicked.connect(self.skip)
        self.suspend_button = QPushButton("Zawieś")
        self.suspend_button.setToolTip(
            "Zawieszona transakcja zostaje na liście, ale nie liczy się do sum ani prognozy."
        )
        self.suspend_button.clicked.connect(self.toggle_suspended)
        self.edit_button = QPushButton("Edytuj")
        shortcuts.show_on(self.edit_button, "edit_selected")
        self.edit_button.clicked.connect(self.edit)
        self.delete_button = QPushButton("Usuń")
        shortcuts.show_on(self.delete_button, "delete_selected")
        self.delete_button.clicked.connect(self.delete)
        self.summary = QLabel()
        self.summary.setToolTip(
            "Suma kwot z listy, bez przeliczania okresów powtarzania. Pomija transakcje "
            "zakończone, zawieszone i te z kwotą ustalaną przy płatności."
        )
        actions = QHBoxLayout()
        actions.addWidget(self.summary)
        actions.addStretch()
        actions.addWidget(self.suspend_button)
        actions.addWidget(self.skip_button)
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
        self.skippable = {
            item["id"] for item in items if days_until_due(item) is not None
        }
        self.suspended = {item["id"] for item in items if item["suspended"]}
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            self._fill_row(row, item)
            if item["id"] == selected:
                self.table.setCurrentCell(row, DESCRIPTION)
        if selected not in {item["id"] for item in items}:
            self.table.setCurrentCell(-1, -1)
        self.empty.setVisible(not items)
        self._update_summary(items)
        self._update_buttons()
        self.due_count_changed.emit(count_due(self.db))

    def _update_summary(self, items):
        totals = recurring_totals(items)
        parts = []
        if totals["expense"]:
            parts.append(f"Suma wydatków: {format_totals(totals['expense'], '−')}")
        if totals["income"]:
            parts.append(f"Suma przychodów: {format_totals(totals['income'], '+')}")
        self.summary.setText("   |   ".join(parts))
        self.summary.setVisible(bool(parts))

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
            PERIOD: period_text(item["period_unit"], item["period_count"]),
            DUE: self._due_cell_text(item),
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
        self._mark_due(self.table.item(row, DUE), days_until_due(item))
        if item["suspended"]:
            for column in (DESCRIPTION, DUE):
                self.table.item(row, column).setForeground(common.muted_text())
                self.table.item(row, column).setToolTip(SUSPENDED_HINT)
        if item["total_cents"] is not None:
            self.table.item(row, AMOUNT).setForeground(
                common.positive_color() if income else common.negative_color()
            )
        pay = QPushButton("Zapłać")
        pay.setToolTip(shortcuts.tooltip("pay_selected", "Dotyczy zaznaczonego wiersza."))
        pay.setEnabled(item["remaining"] != 0)
        pay.clicked.connect(lambda: self.pay(item["id"], item["wallet_id"]))
        self.table.setCellWidget(row, PAY, pay)

    @staticmethod
    def _due_cell_text(item):
        if item["suspended"]:
            return f"{item['next_due_on'] or ''} (zawieszona)".strip()
        if item["next_due_on"] is None:
            return "–"
        days = days_until_due(item)
        if days is None:
            return item["next_due_on"]
        return f"{item['next_due_on']} ({due_text(days)})"

    @staticmethod
    def _mark_due(cell, days):
        if days is None:
            return
        if days < 0:
            font = cell.font()
            font.setBold(True)
            cell.setFont(font)
            cell.setBackground(common.overdue_background())
            cell.setForeground(common.overdue_text())
            cell.setToolTip(OVERDUE_HINT)
        elif days <= DUE_SOON_DAYS:
            cell.setBackground(common.warning_background())
            cell.setForeground(common.warning_text())
            cell.setToolTip(DUE_SOON_HINT)

    def selected_id(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, DESCRIPTION) is None:
            return None
        return self.table.item(row, DESCRIPTION).data(Qt.ItemDataRole.UserRole)

    def _update_buttons(self):
        selected_id = self.selected_id()
        selected = selected_id is not None
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected)
        self.skip_button.setEnabled(selected_id in self.skippable)
        self.suspend_button.setEnabled(selected)
        self.suspend_button.setText("Wznów" if selected_id in self.suspended else "Zawieś")

    def _row_menu(self):
        """Menu zaznaczonej transakcji, tylko z działaniami możliwymi w jej stanie."""
        recurring_id = self.selected_id()
        menu = QMenu(self)
        if self.table.cellWidget(self.table.currentRow(), PAY).isEnabled():
            menu.addAction("Zapłać", self.pay_selected)
        if recurring_id in self.skippable:
            menu.addAction("Pomiń termin", self.skip)
        menu.addAction(
            "Wznów" if recurring_id in self.suspended else "Zawieś", self.toggle_suspended
        )
        menu.addAction("Edytuj", self.edit)
        menu.addAction("Usuń", self.delete)
        return menu

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

    def toggle_suspended(self):
        recurring_id = self.selected_id()
        if recurring_id is None:
            return
        set_suspended(self.db, recurring_id, recurring_id not in self.suspended)
        self.refresh()

    def skip(self):
        recurring_id = self.selected_id()
        if recurring_id is None:
            return
        row = self.table.currentRow()
        description = self.table.item(row, DESCRIPTION).text()
        if not common.confirm(
            self,
            f"Pominąć termin transakcji „{description}” bez płatności? "
            "Termin przesunie się o jeden okres, a licznik się nie zmieni.",
            "Pomiń",
        ):
            return
        try:
            skip_due(self.db, recurring_id)
        except ValidationError as error:
            common.show_errors(self, error.errors)
        self.refresh()

    def pay(self, recurring_id, wallet_id):
        wallet = get_wallet(self.db, wallet_id)
        if PaymentDialog(self.db, wallet, recurring_id, parent=self).exec():
            self.refresh()
