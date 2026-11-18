"""Formularze pożyczek: pożyczka, jej pozycje (pożyczenia i spłaty) i łączenie z transakcjami."""

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..errors import ValidationError
from ..loans import (
    BORROWED,
    LENT,
    REPAYMENT,
    ROLE_NAMES,
    add_loan_item,
    create_loan,
    get_loan,
    get_loan_item,
    link_transaction,
    linkable_transactions,
    list_loans,
    loan_items,
    role_of,
    update_loan,
    update_loan_item,
)
from ..money import format_money, format_money_input, parse_money
from ..wallets import list_wallets
from . import common
from .dialogs import _buttons, _remove_minus, _SavingDialog

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
OUTSIDE_WALLETS = "Poza portfelami (bez transakcji)"


def loan_label(loan):
    """Krótki opis pożyczki na listach wyboru."""
    direction = "dla" if loan["direction"] == LENT else "od"
    text = f"{loan['person']} ({direction}, {loan['opened_on']})"
    if loan["description"]:
        text += f" – {loan['description']}"
    outstanding = format_money(loan["outstanding_cents"], loan["currency"])
    return f"{text} · pozostało {outstanding}"


def _today_row(edit):
    button = QPushButton("Dzisiaj")
    button.setAutoDefault(False)
    button.clicked.connect(lambda: edit.setDate(QDate.currentDate()))
    row = QHBoxLayout()
    row.addWidget(edit, 1)
    row.addWidget(button)
    return row


class LoanDialog(_SavingDialog):
    """Nowa pożyczka z pierwszą pozycją w portfelu albo poza nim; edycja zmienia tylko opis."""

    def __init__(self, db, loan_id=None, wallet_id=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.loan_id = loan_id
        loan = get_loan(db, loan_id) if loan_id else None
        self.setWindowTitle("Edycja pożyczki" if loan else "Nowa pożyczka")

        self.direction = QComboBox()
        self.direction.addItem("Pożyczam komuś (udzielona)", LENT)
        self.direction.addItem("Pożyczam od kogoś (zaciągnięta)", BORROWED)
        if loan:
            self.direction.setCurrentIndex(self.direction.findData(loan["direction"]))
            self.direction.setEnabled(False)
            self.direction.setToolTip("Rodzaju nie da się zmienić po utworzeniu pożyczki.")
        self.person = QLineEdit(loan["person"] if loan else "")
        self.person.setMaxLength(200)
        self.person.setPlaceholderText("np. Jan Kowalski albo bank")
        self.description = QLineEdit(loan["description"] if loan else "")
        self.description.setMaxLength(200)
        self.description.setPlaceholderText("opcjonalnie, np. na remont")
        self.opened_on = common.date_edit(loan["opened_on"] if loan else None)

        form = QFormLayout()
        form.addRow("Rodzaj", self.direction)
        form.addRow("Osoba", self.person)
        form.addRow("Opis", self.description)
        form.addRow("Data", _today_row(self.opened_on))

        self.wallet = None
        self.currency = None
        if loan is None:
            self.amount = QLineEdit()
            self.amount.setPlaceholderText("0,00")
            self.amount.textEdited.connect(lambda _text: _remove_minus(self.amount))
            self.wallet = _wallet_combo(list_wallets(db), wallet_id)
            self.wallet.setToolTip(
                "Z portfelem kwota pożyczki staje się w nim transakcją i zmienia saldo."
            )
            self.currency = QLineEdit("PLN")
            self.currency.setMaxLength(3)
            form.addRow("Kwota", self.amount)
            form.addRow("Portfel", self.wallet)
            form.addRow("Waluta", self.currency)
            self.wallet.currentIndexChanged.connect(self._update_currency)
            self._update_currency()
            hint = common.plain_label(
                "To pierwsza pozycja pożyczki. Kolejne kwoty i spłaty dodasz w zakładce"
                " Pożyczki przyciskami Pożycz więcej… i Spłać…."
            )
            hint.setWordWrap(True)
            form.addRow(hint)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, "Zapisz", "save"))
        self.setMinimumWidth(480)
        self.person.setFocus()

    def _update_currency(self):
        """Waluta wynika z portfela; wpisuje się ją tylko dla kwoty spoza portfeli."""
        self.currency.setEnabled(self.wallet.currentData() is None)

    def save(self):
        if self.loan_id is None:
            self.loan_id = create_loan(
                self.db,
                self.direction.currentData(),
                self.person.text(),
                self.description.text(),
                common.iso_date(self.opened_on),
                self.amount.text(),
                self.wallet.currentData(),
                self.currency.text(),
            )
        else:
            update_loan(
                self.db,
                self.loan_id,
                self.person.text(),
                self.description.text(),
                common.iso_date(self.opened_on),
            )


def _wallet_combo(wallets, selected):
    """Portfele z saldem i na końcu pozycja poza portfelami (dane None)."""
    combo = QComboBox()
    for wallet in wallets:
        balance = format_money(wallet["balance_cents"], wallet["currency"])
        combo.addItem(f"{wallet['name']} ({balance})", wallet["id"])
    combo.addItem(OUTSIDE_WALLETS, None)
    combo.setCurrentIndex(max(combo.findData(selected), 0))
    return combo


class LoanItemDialog(_SavingDialog):
    """Pozycja pożyczki: spłata z doborem kwoty albo kolejne pożyczenie.

    Nowa pozycja z portfelem staje się w nim transakcją. Edytować można tylko pozycje
    poza portfelami; pozycję z transakcją zmienia się w portfelu.
    """

    SHARES = (25, 50, 75, 100)

    def __init__(self, db, loan_id, role=REPAYMENT, item_id=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.loan = get_loan(db, loan_id)
        self.item_id = item_id
        item = get_loan_item(db, item_id) if item_id else None
        self.role = item["role"] if item else role
        repayment = self.role == REPAYMENT
        currency = self.loan["currency"]
        # Pozostała kwota bez edytowanej pozycji, od której liczy się część i wynik.
        self.base = self.loan["outstanding_cents"]
        if item:
            self.base += item["amount_cents"] if repayment else -item["amount_cents"]
        self.available = max(self.base, 0)
        person = self.loan["person"]
        if item:
            title = "Edycja spłaty" if repayment else "Edycja pożyczenia"
        else:
            title = "Spłata pożyczki" if repayment else "Kolejne pożyczenie"
        self.setWindowTitle(f"{title}: {person}")

        self.wallet = None
        if item is None:
            # Domyślnie tak jak ostatnia pozycja: ten sam portfel albo poza portfelami.
            items = loan_items(db, loan_id)
            wallets = [w for w in list_wallets(db) if w["currency"] == currency]
            selected = items[-1]["wallet_id"] if items else (wallets[0]["id"] if wallets else None)
            self.wallet = _wallet_combo(wallets, selected)
        self.occurred_on = common.date_edit(item["occurred_on"] if item else None)
        self.description = QLineEdit(item["description"] if item else "")
        self.description.setMaxLength(200)
        self.description.setPlaceholderText("opcjonalnie")

        if item:
            amount = format_money_input(item["amount_cents"])
        else:
            amount = format_money_input(self.available) if repayment else ""
        self.amount = QLineEdit(amount)
        self.amount.setPlaceholderText("0,00")
        self.amount.textEdited.connect(self._amount_edited)

        form = QFormLayout()
        if repayment:
            form.addRow(
                "Pozostało do spłaty", common.plain_label(format_money(self.available, currency))
            )
        if self.wallet is not None:
            form.addRow("Portfel", self.wallet)
        form.addRow("Data", _today_row(self.occurred_on))
        form.addRow(f"Kwota ({currency})", self.amount)

        self.slider = None
        if repayment and self.available > 0:
            # Suwak w procentach, bo kwota w groszach nie zmieści się w zakresie suwaka.
            self.slider = QSlider(Qt.Orientation.Horizontal)
            self.slider.setRange(0, 100)
            self.slider.valueChanged.connect(self.set_share)
            self.share_label = common.plain_label()
            self.share_label.setMinimumWidth(48)
            slider_row = QHBoxLayout()
            slider_row.addWidget(self.slider, 1)
            slider_row.addWidget(self.share_label)
            form.addRow("Część", slider_row)
            shares = QHBoxLayout()
            for share in self.SHARES:
                button = QPushButton("Całość" if share == 100 else f"{share}%")
                button.setAutoDefault(False)
                button.clicked.connect(lambda _=False, s=share: self.set_share(s))
                shares.addWidget(button)
            shares.addStretch()
            form.addRow("", shares)
        self.after = common.plain_label()
        form.addRow("Po zapisie zostanie", self.after)
        form.addRow("Opis", self.description)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        accept = "Spłać" if repayment and item is None else "Zapisz"
        layout.addWidget(_buttons(self, accept, "save"))
        self.setMinimumWidth(520)
        self.amount.setFocus()
        self.amount.selectAll()
        self._amount_edited(self.amount.text())

    def _cents(self):
        try:
            return parse_money(self.amount.text().strip())
        except ValueError:
            return None

    def _set_slider(self, percent):
        if self.slider is not None:
            self.slider.blockSignals(True)
            self.slider.setValue(percent)
            self.slider.blockSignals(False)
            self.share_label.setText(f"{percent}%")

    def set_share(self, percent):
        """Kwota jako część pozostałej do spłaty; całość jest zawsze dokładna."""
        cents = self.available if percent == 100 else (self.available * percent + 50) // 100
        self.amount.setText(format_money_input(cents))
        self._set_slider(percent)
        self._update_after()

    def _amount_edited(self, _text):
        _remove_minus(self.amount)
        cents = self._cents()
        if cents is not None and self.available:
            self._set_slider(max(0, min(100, round(cents * 100 / self.available))))
        self._update_after()

    def _update_after(self):
        cents = self._cents() or 0
        sign = -1 if self.role == REPAYMENT else 1
        remaining = self.base + sign * cents
        text = format_money(remaining, self.loan["currency"])
        if remaining == 0:
            text += " (spłacona)"
        elif remaining < 0:
            text += " (więcej niż pozostało)"
        self.after.setText(text)

    def save(self):
        values = (
            common.iso_date(self.occurred_on),
            self.amount.text(),
            self.description.text(),
        )
        if self.item_id is None:
            self.item_id = add_loan_item(
                self.db, self.loan["id"], self.role, *values, self.wallet.currentData()
            )
        else:
            update_loan_item(self.db, self.item_id, self.role, *values)


class LinkLoanDialog(_SavingDialog):
    """Wybór pożyczki dla istniejącej transakcji z portfela."""

    def __init__(self, db, transaction, parent=None):
        super().__init__(parent)
        self.db = db
        self.transaction = transaction
        self.setWindowTitle("Połącz z pożyczką")
        self.loans = [
            loan for loan in list_loans(db) if loan["currency"] == transaction["currency"]
        ]
        self.loan = QComboBox()
        for loan in self.loans:
            self.loan.addItem(loan_label(loan), loan["id"])
        self.role = common.plain_label()
        self.loan.currentIndexChanged.connect(self._update_role)
        amount = format_money(transaction["total_cents"], transaction["currency"])
        form = QFormLayout()
        form.addRow("Transakcja", common.plain_label(
            f"{transaction['occurred_on']} · {transaction['description']} · {amount}"
        ))  # fmt: skip
        form.addRow("Pożyczka", self.loan)
        form.addRow("Transakcja to", self.role)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, "Połącz"))
        self.setMinimumWidth(560)
        self._update_role()

    def _update_role(self):
        loan_id = self.loan.currentData()
        loan = next((loan for loan in self.loans if loan["id"] == loan_id), None)
        if loan is None:
            self.role.setText("")
            return
        role = role_of(loan["direction"], self.transaction["kind"])
        self.role.setText(
            "spłata pożyczki" if role == REPAYMENT else "pożyczenie (zwiększa pożyczkę)"
        )

    def save(self):
        if self.loan.currentData() is None:
            raise ValidationError("Wybierz pożyczkę.")
        link_transaction(self.db, self.loan.currentData(), self.transaction["id"])


class LinkTransactionDialog(QDialog):
    """Wybór istniejących transakcji, które należą do pożyczki."""

    DATE, WALLET, DESCRIPTION, ROLE, AMOUNT = range(5)

    def __init__(self, db, loan_id, parent=None):
        super().__init__(parent)
        self.db = db
        self.loan_id = loan_id
        loan = get_loan(db, loan_id)
        self.setWindowTitle(f"Połącz transakcje z pożyczką: {loan['person']}")
        self.items = linkable_transactions(db, loan_id)
        self.linked = 0

        self.search = QLineEdit()
        self.search.setPlaceholderText("Szukaj po opisie lub portfelu")
        self.search.textChanged.connect(self._filter)
        self.table = QTableWidget(len(self.items), 5)
        self.table.setHorizontalHeaderLabels(["Data", "Portfel", "Opis", "Rola", "Kwota"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        common.multi_select(self.table)
        header = self.table.horizontalHeader()
        for column in range(5):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Stretch
                if column == self.DESCRIPTION
                else QHeaderView.ResizeMode.ResizeToContents,
            )
        for row, item in enumerate(self.items):
            income = item["kind"] == "income"
            sign = "+" if income else "−"
            cells = (
                item["occurred_on"],
                item["wallet_name"],
                item["description"],
                ROLE_NAMES[item["role"]],
                f"{sign}{format_money(item['total_cents'], item['currency'])}",
            )
            for column, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if column == self.AMOUNT:
                    cell.setTextAlignment(RIGHT)
                    cell.setForeground(
                        common.positive_color() if income else common.negative_color()
                    )
                self.table.setItem(row, column, cell)
            self.table.item(row, self.DATE).setData(Qt.ItemDataRole.UserRole, item["id"])
        self.table.itemDoubleClicked.connect(lambda *_: self.accept())

        hint = common.plain_label(
            "Transakcje w walucie pożyczki, jeszcze niepowiązane z żadną pożyczką. "
            "Rolę wyznacza rodzaj transakcji. Zaznacz kilka z Ctrl lub Shift."
        )
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.search)
        layout.addWidget(self.table, 1)
        layout.addWidget(_buttons(self, "Połącz"))
        self.resize(760, 520)
        self.search.setFocus()

    def _filter(self, text):
        needle = text.strip().casefold()
        for row, item in enumerate(self.items):
            haystack = f"{item['description']} {item['wallet_name']}".casefold()
            self.table.setRowHidden(row, bool(needle) and needle not in haystack)

    def selected_ids(self):
        return [
            self.table.item(row, self.DATE).data(Qt.ItemDataRole.UserRole)
            for row in common.selected_rows(self.table)
            if not self.table.isRowHidden(row)
        ]

    def accept(self):
        ids = self.selected_ids()
        if not ids:
            common.show_errors(self, ["Zaznacz co najmniej jedną transakcję."])
            return
        try:
            for transaction_id in ids:
                link_transaction(self.db, self.loan_id, transaction_id)
                self.linked += 1
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        super().accept()

