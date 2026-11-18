"""Zakładka pożyczek: lista z pozostałą kwotą i pozycje zaznaczonej pożyczki."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..loans import (
    BORROWED,
    DIRECTION_NAMES,
    LENT,
    PRINCIPAL,
    REPAYMENT,
    ROLE_NAMES,
    delete_loan,
    delete_loan_item,
    get_loan_item,
    list_loans,
    loan_items,
    loan_totals,
)
from ..money import format_money, format_totals
from ..transactions import get_transaction
from ..wallets import get_wallet
from . import common, shortcuts
from .dialogs import TransactionDialog
from .loan_dialogs import LinkTransactionDialog, LoanDialog, LoanItemDialog

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
PERSON, DIRECTION, DESCRIPTION, OPENED, PRINCIPAL_AMOUNT, REPAID, OUTSTANDING, PAY = range(8)
I_DATE, I_ROLE, I_AMOUNT, I_BALANCE, I_WALLET, I_DESCRIPTION = range(6)
OUTSIDE_WALLETS = "poza portfelami"
SETTLED_HINT = "Spłacona: nie liczy się do sum pod listą."


def _table(headers, stretch):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().hide()
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    common.multi_select(table)
    header = table.horizontalHeader()
    for column in range(len(headers)):
        header.setSectionResizeMode(
            column,
            QHeaderView.ResizeMode.Stretch
            if column == stretch
            else QHeaderView.ResizeMode.ResizeToContents,
        )
    return table


def _outstanding_text(cents, currency):
    if cents == 0:
        return "spłacona"
    if cents < 0:
        return f"nadpłata {format_money(-cents, currency)}"
    return format_money(cents, currency)


class LoansTab(QWidget):
    selection_changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.loans = {}

        new_button = QPushButton("Nowa pożyczka")
        shortcuts.show_on(new_button, "new_loan")
        new_button.clicked.connect(lambda: self.create())
        self.hide_settled = QCheckBox("Ukryj spłacone")
        self.hide_settled.toggled.connect(lambda _: self.refresh())
        top = QHBoxLayout()
        top.addWidget(new_button)
        top.addStretch()
        top.addWidget(self.hide_settled)

        self.empty = QLabel("Nie masz jeszcze pożyczek.")
        self.table = _table(
            ["Osoba", "Rodzaj", "Opis", "Data", "Pożyczono", "Spłacono", "Pozostało", ""],
            DESCRIPTION,
        )
        self.table.itemDoubleClicked.connect(lambda *_: self.edit())
        self.table.currentCellChanged.connect(lambda *_: self._current_changed())
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        common.attach_row_menu(self.table, self._row_menu)
        self.delete_shortcut = shortcuts.bind(
            "delete_selected", self.table, self.delete, Qt.ShortcutContext.WidgetShortcut
        )

        self.summary = common.plain_label()
        self.summary.setToolTip(
            "Kwoty, które zostały do spłaty, osobno dla każdej waluty; bez spłaconych pożyczek."
        )
        self.repay_button = QPushButton("Spłać…")
        self.repay_button.setToolTip(
            shortcuts.tooltip("pay_selected", "Spłata całości lub części zaznaczonej pożyczki.")
        )
        self.repay_button.clicked.connect(lambda: self.repay())
        self.lend_more_button = QPushButton("Pożycz więcej…")
        self.lend_more_button.setToolTip(
            "Kolejna kwota pożyczona tej samej osobie, jako nowa pozycja pożyczki."
        )
        self.lend_more_button.clicked.connect(lambda: self.lend_more())
        self.edit_button = QPushButton("Edytuj")
        shortcuts.show_on(self.edit_button, "edit_selected")
        self.edit_button.clicked.connect(self.edit)
        self.delete_button = QPushButton("Usuń")
        shortcuts.show_on(self.delete_button, "delete_selected")
        self.delete_button.clicked.connect(self.delete)
        actions = QHBoxLayout()
        actions.addWidget(self.summary)
        actions.addStretch()
        for button in (self.repay_button, self.lend_more_button, self.edit_button,
                       self.delete_button):  # fmt: skip
            actions.addWidget(button)

        top_part = QWidget()
        top_layout = QVBoxLayout(top_part)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addLayout(top)
        top_layout.addWidget(self.empty)
        top_layout.addWidget(self.table, 1)
        top_layout.addLayout(actions)

        self.details_title = common.plain_label()
        self.items = _table(
            ["Data", "Pozycja", "Kwota", "Pozostało po", "Portfel", "Opis"], I_DESCRIPTION
        )
        self.items.itemSelectionChanged.connect(self._update_buttons)
        self.items.itemDoubleClicked.connect(lambda *_: self.edit_item())
        common.attach_row_menu(self.items, self._item_menu)
        self.link_button = QPushButton("Połącz transakcje…")
        self.link_button.setToolTip(
            "Dodaje jako pozycje transakcje już zapisane w portfelach, np. z importu."
        )
        self.link_button.clicked.connect(self.link)
        self.edit_item_button = QPushButton("Edytuj pozycję")
        self.edit_item_button.setToolTip(
            "Pozycja z transakcją otwiera się jako transakcja z portfela."
        )
        self.edit_item_button.clicked.connect(self.edit_item)
        self.delete_item_button = QPushButton("Usuń pozycję")
        self.delete_item_button.setToolTip(
            "Transakcja z portfela zostaje w nim, tylko przestaje należeć do pożyczki."
        )
        self.delete_item_button.clicked.connect(self.delete_items)
        detail_actions = QHBoxLayout()
        detail_actions.addStretch()
        for button in (self.link_button, self.edit_item_button, self.delete_item_button):
            detail_actions.addWidget(button)
        bottom_part = QWidget()
        bottom_layout = QVBoxLayout(bottom_part)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(self.details_title)
        bottom_layout.addWidget(self.items, 1)
        bottom_layout.addLayout(detail_actions)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(top_part)
        splitter.addWidget(bottom_part)
        splitter.setSizes([400, 280])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        self.refresh()

    # Odświeżanie

    def refresh(self):
        selected = self.selected_id()
        loans = list_loans(self.db)
        self.loans = {loan["id"]: loan for loan in loans}
        visible = [
            loan for loan in loans
            if not (self.hide_settled.isChecked() and loan["outstanding_cents"] <= 0)
        ]  # fmt: skip
        self.table.setRowCount(len(visible))
        for row, loan in enumerate(visible):
            self._fill_row(row, loan)
            if loan["id"] == selected:
                self.table.setCurrentCell(row, PERSON)
        if selected not in {loan["id"] for loan in visible}:
            self.table.setCurrentCell(-1, -1)
        self.empty.setVisible(not visible)
        self.empty.setText(
            "Wszystkie pożyczki są spłacone." if loans else "Nie masz jeszcze pożyczek."
        )
        self._update_summary(loans)
        self._current_changed()

    def _update_summary(self, loans):
        totals = loan_totals(loans)
        parts = []
        if totals[LENT]:
            parts.append(f"Do oddania tobie: {format_totals(totals[LENT])}")
        if totals[BORROWED]:
            parts.append(f"Do oddania przez ciebie: {format_totals(totals[BORROWED])}")
        self.summary.setText("   |   ".join(parts))
        self.summary.setVisible(bool(parts))

    def _fill_row(self, row, loan):
        currency = loan["currency"]
        outstanding = loan["outstanding_cents"]
        cells = {
            PERSON: loan["person"],
            DIRECTION: DIRECTION_NAMES[loan["direction"]],
            DESCRIPTION: loan["description"],
            OPENED: loan["opened_on"],
            PRINCIPAL_AMOUNT: format_money(loan["principal_cents"], currency),
            REPAID: format_money(loan["repaid_cents"], currency),
            OUTSTANDING: _outstanding_text(outstanding, currency),
        }
        for column, text in cells.items():
            cell = QTableWidgetItem(text)
            if column in (PRINCIPAL_AMOUNT, REPAID, OUTSTANDING):
                cell.setTextAlignment(RIGHT)
            self.table.setItem(row, column, cell)
        first = self.table.item(row, PERSON)
        first.setData(Qt.ItemDataRole.UserRole, loan["id"])
        # Udzielona to pieniądze, które wrócą, a zaciągnięta to te, które trzeba oddać.
        lent = loan["direction"] == LENT
        if outstanding > 0:
            first.setData(common.SUM_ROLE, [(currency, outstanding if lent else -outstanding)])
            self.table.item(row, OUTSTANDING).setForeground(
                common.positive_color() if lent else common.negative_color()
            )
        else:
            for column in cells:
                self.table.item(row, column).setForeground(common.muted_text())
                self.table.item(row, column).setToolTip(SETTLED_HINT)
        pay = QPushButton("Spłać")
        pay.setToolTip(shortcuts.tooltip("pay_selected", "Dotyczy zaznaczonego wiersza."))
        pay.setEnabled(outstanding > 0)
        pay.clicked.connect(lambda: self.repay(loan["id"]))
        self.table.setCellWidget(row, PAY, pay)

    def _current_changed(self):
        self._fill_items()
        self._update_buttons()

    def _fill_items(self):
        loan = self.selected_loan()
        if loan is None:
            self.items.setRowCount(0)
            self.details_title.setText("Zaznacz pożyczkę, żeby zobaczyć jej pozycje.")
            return
        items = loan_items(self.db, loan["id"])
        self.details_title.setText(
            f"Pozycje pożyczki: {loan['person']}"
            + ("" if items else " · brak pozycji, dodaj je przyciskiem Pożycz więcej…")
        )
        self.items.setRowCount(len(items))
        for row, item in enumerate(items):
            principal = item["role"] == PRINCIPAL
            cells = (
                item["occurred_on"],
                ROLE_NAMES[item["role"]],
                f"{'+' if principal else '−'}{format_money(item['amount_cents'], loan['currency'])}",
                _outstanding_text(item["balance_cents"], loan["currency"]),
                item["wallet_name"] or OUTSIDE_WALLETS,
                item["description"],
            )
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if column in (I_AMOUNT, I_BALANCE):
                    cell.setTextAlignment(RIGHT)
                self.items.setItem(row, column, cell)
            self.items.item(row, I_DATE).setData(Qt.ItemDataRole.UserRole, item["id"])
            if item["wallet_name"] is None:
                self.items.item(row, I_WALLET).setForeground(common.muted_text())

    # Zaznaczenie

    def selected_id(self):
        row = self.table.currentRow()
        if row < 0 or self.table.item(row, PERSON) is None:
            return None
        return self.table.item(row, PERSON).data(Qt.ItemDataRole.UserRole)

    def selected_loan(self):
        return self.loans.get(self.selected_id())

    def _selected_ids(self):
        return [
            self.table.item(row, PERSON).data(Qt.ItemDataRole.UserRole)
            for row in common.selected_rows(self.table)
            if self.table.item(row, PERSON)
        ]

    def selected_item_id(self):
        row = self.items.currentRow()
        if row < 0 or self.items.item(row, I_DATE) is None:
            return None
        return self.items.item(row, I_DATE).data(Qt.ItemDataRole.UserRole)

    def _selected_item_ids(self):
        return [
            self.items.item(row, I_DATE).data(Qt.ItemDataRole.UserRole)
            for row in common.selected_rows(self.items)
            if self.items.item(row, I_DATE)
        ]

    def selection_summary(self):
        """Suma pozostałych kwot: udzielone na plus, zaciągnięte na minus."""
        rows = common.selected_rows(self.table)
        totals = {}
        for row in rows:
            common.add_amounts(totals, self.table.item(row, PERSON).data(common.SUM_ROLE))
        return common.selection_summary(len(rows), totals, "Pozostało")

    def can_repay(self):
        loan = self.selected_loan()
        return loan is not None and loan["outstanding_cents"] > 0

    def _delete_label(self):
        count = len(self._selected_ids())
        return f"Usuń zaznaczone ({count})" if count > 1 else "Usuń"

    def _delete_items_label(self):
        count = len(self._selected_item_ids())
        return f"Usuń pozycje ({count})" if count > 1 else "Usuń pozycję"

    def _update_buttons(self):
        selected = self.selected_loan() is not None
        self.repay_button.setEnabled(self.can_repay())
        self.lend_more_button.setEnabled(selected)
        self.edit_button.setEnabled(selected)
        self.delete_button.setEnabled(selected or bool(self._selected_ids()))
        self.delete_button.setText(self._delete_label())
        self.link_button.setEnabled(selected)
        self.edit_item_button.setEnabled(self.selected_item_id() is not None)
        self.delete_item_button.setEnabled(bool(self._selected_item_ids()))
        self.delete_item_button.setText(self._delete_items_label())

    def _row_menu(self):
        menu = QMenu(self)
        if self.can_repay():
            menu.addAction("Spłać…", self.repay)
        menu.addAction("Pożycz więcej…", self.lend_more)
        menu.addAction("Połącz transakcje…", self.link)
        menu.addAction("Edytuj", self.edit)
        menu.addAction(self._delete_label(), self.delete)
        return menu

    def _item_menu(self):
        menu = QMenu(self)
        menu.addAction("Edytuj pozycję", self.edit_item)
        menu.addAction(self._delete_items_label(), self.delete_items)
        return menu

    # Pożyczki

    def edit_selected(self):
        self.edit()

    def pay_selected(self):
        self.repay()

    def create(self, wallet_id=None):
        dialog = LoanDialog(self.db, wallet_id=wallet_id, parent=self)
        if dialog.exec():
            self.refresh()
            self._select(dialog.loan_id)
            return dialog.loan_id
        return None

    def _select(self, loan_id):
        for row in range(self.table.rowCount()):
            if self.table.item(row, PERSON).data(Qt.ItemDataRole.UserRole) == loan_id:
                self.table.setCurrentCell(row, PERSON)
                return

    def edit(self):
        loan_id = self.selected_id()
        if loan_id is None:
            return
        if LoanDialog(self.db, loan_id, parent=self).exec():
            self.refresh()

    def delete(self):
        ids = self._selected_ids()
        if len(ids) > 1:
            question = (
                f"Usunąć zaznaczone pożyczki ({len(ids)}) razem z pozycjami? "
                "Ich transakcje zostaną w portfelach i wrócą do raportów."
            )
        else:
            loan = self.selected_loan()
            if loan is None:
                return
            ids = [loan["id"]]
            question = (
                f"Usunąć pożyczkę „{loan['person']}” razem z pozycjami? "
                "Jej transakcje zostaną w portfelach i wrócą do raportów."
            )
        if common.confirm(self, question):
            for loan_id in ids:
                delete_loan(self.db, loan_id)
            self.refresh()

    # Pozycje

    def _add_item(self, role, loan_id=None):
        """Nowa pozycja; zwraca jej identyfikator albo None."""
        loan = self.loans.get(loan_id) if loan_id else self.selected_loan()
        if loan is None:
            return None
        dialog = LoanItemDialog(self.db, loan["id"], role, parent=self)
        if dialog.exec():
            self.refresh()
            return dialog.item_id
        return None

    def repay(self, loan_id=None):
        """Spłata całości albo części jako nowa pozycja pożyczki."""
        return self._add_item(REPAYMENT, loan_id)

    def lend_more(self, loan_id=None):
        """Kolejna pożyczona kwota jako nowa pozycja pożyczki."""
        return self._add_item(PRINCIPAL, loan_id)

    def edit_item(self):
        item = get_loan_item(self.db, self.selected_item_id())
        if item is None:
            return
        if item["transaction_id"] is None:
            dialog = LoanItemDialog(self.db, item["loan_id"], item_id=item["id"], parent=self)
        else:
            wallet_id = get_transaction(self.db, item["transaction_id"])["wallet_id"]
            dialog = TransactionDialog(
                self.db, get_wallet(self.db, wallet_id), item["transaction_id"], parent=self
            )
        if dialog.exec():
            self.refresh()

    def delete_items(self):
        ids = self._selected_item_ids()
        if not ids:
            return
        items = [get_loan_item(self.db, item_id) for item_id in ids]
        question = (
            f"Usunąć zaznaczone pozycje ({len(ids)})?" if len(ids) > 1 else "Usunąć tę pozycję?"
        )
        if any(item["transaction_id"] is not None for item in items):
            question += " Transakcje z portfeli zostaną w nich i wrócą do raportów."
        if common.confirm(self, question):
            for item_id in ids:
                delete_loan_item(self.db, item_id)
            self.refresh()

    def link(self):
        loan = self.selected_loan()
        if loan is None:
            return
        if LinkTransactionDialog(self.db, loan["id"], parent=self).exec():
            self.refresh()
