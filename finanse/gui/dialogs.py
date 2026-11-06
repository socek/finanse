"""Formularze: portfel, transakcja i przelew."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QToolButton,
    QVBoxLayout,
)

from ..categories import list_categories
from ..errors import ValidationError
from ..money import (
    format_money,
    format_money_input,
    line_total,
    parse_money,
    parse_quantity,
)
from ..recurring import (
    create_recurring,
    get_recurring,
    pay_recurring,
    payment_draft,
    update_recurring,
)
from ..transactions import (
    EMPTY_ROW,
    create_transaction,
    get_transaction,
    update_transaction,
)
from ..transfers import create_transfer, get_transfer, update_transfer
from ..wallets import create_wallet, list_wallets, update_wallet
from . import common


def _buttons(dialog, accept_text="Zapisz"):
    box = QDialogButtonBox()
    box.addButton(accept_text, QDialogButtonBox.ButtonRole.AcceptRole)
    box.addButton("Anuluj", QDialogButtonBox.ButtonRole.RejectRole)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class _SavingDialog(QDialog):
    """Okno, które zamyka się dopiero po udanym zapisie."""

    def save(self):
        raise NotImplementedError

    def accept(self):
        try:
            self.save()
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        super().accept()


class WalletDialog(_SavingDialog):
    def __init__(self, db, wallet=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.wallet = wallet
        self.wallet_id = wallet["id"] if wallet else None
        self.setWindowTitle("Edycja portfela" if wallet else "Nowy portfel")

        self.name = QLineEdit(wallet["name"] if wallet else "")
        self.name.setMaxLength(100)
        self.currency = QLineEdit(wallet["currency"] if wallet else "PLN")
        self.currency.setMaxLength(3)
        self.initial_balance = QLineEdit(
            format_money_input(wallet["initial_balance_cents"]) if wallet else "0,00"
        )

        form = QFormLayout(self)
        form.addRow("Nazwa", self.name)
        form.addRow("Waluta", self.currency)
        form.addRow("Saldo początkowe", self.initial_balance)
        form.addRow(_buttons(self))
        self.setMinimumWidth(380)

    def save(self):
        values = (
            self.name.text(),
            self.currency.text(),
            self.initial_balance.text(),
        )
        if self.wallet_id is None:
            self.wallet_id = create_wallet(self.db, *values)
        else:
            update_wallet(self.db, self.wallet_id, *values)


class _ProductRowsMixin:
    """Tabela produktów z sumą, wspólna dla transakcji i transakcji cyklicznych."""

    NAME, CATEGORY, QUANTITY, PRICE, VALUE, REMOVE = range(6)

    def _product_section(self, rows, categories):
        self.categories = categories
        self.total = QLabel()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Produkt", "Kategoria", "Ilość", "Cena", "Wartość", ""]
        )
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().hide()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.NAME, QHeaderView.ResizeMode.Stretch)
        for column, width in (
            (self.CATEGORY, 150),
            (self.QUANTITY, 80),
            (self.PRICE, 90),
            (self.VALUE, 90),
            (self.REMOVE, 60),
        ):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(column, width)
        for row in rows or [EMPTY_ROW]:
            self._add_row(row)

        add = QPushButton("Dodaj produkt")
        add.clicked.connect(lambda: self._add_row(EMPTY_ROW, focus=True))
        bottom = QHBoxLayout()
        bottom.addWidget(add)
        bottom.addStretch()
        bottom.addWidget(self.total)
        return bottom

    def _add_row(self, row, focus=False):
        index = self.table.rowCount()
        self.table.insertRow(index)
        name = QLineEdit(row["name"])
        name.setMaxLength(200)
        category = QComboBox()
        category.addItem("Bez kategorii", None)
        for item in self.categories:
            category.addItem(item["name"], item["id"])
        found = category.findData(row["category"])
        category.setCurrentIndex(max(found, 0))
        quantity = QLineEdit(row["quantity"])
        price = QLineEdit(row["price"])
        remove = QToolButton()
        remove.setText("Usuń")
        remove.clicked.connect(lambda: self._remove_row(remove))
        name.textChanged.connect(self._update_totals)
        quantity.textChanged.connect(self._update_totals)
        price.textChanged.connect(self._update_totals)

        self.table.setCellWidget(index, self.NAME, name)
        self.table.setCellWidget(index, self.CATEGORY, category)
        self.table.setCellWidget(index, self.QUANTITY, quantity)
        self.table.setCellWidget(index, self.PRICE, price)
        value = QTableWidgetItem("")
        value.setFlags(value.flags() & ~Qt.ItemFlag.ItemIsEditable)
        value.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.setItem(index, self.VALUE, value)
        self.table.setCellWidget(index, self.REMOVE, remove)
        if focus:
            name.setFocus()
            self._update_totals()

    def _remove_row(self, button):
        if self.table.rowCount() == 1:
            self.table.cellWidget(0, self.NAME).clear()
            self.table.cellWidget(0, self.CATEGORY).setCurrentIndex(0)
            self.table.cellWidget(0, self.QUANTITY).setText("1")
            self.table.cellWidget(0, self.PRICE).clear()
        else:
            for index in range(self.table.rowCount()):
                if self.table.cellWidget(index, self.REMOVE) is button:
                    self.table.removeRow(index)
                    break
        self._update_totals()

    @staticmethod
    def _row_total(quantity, price):
        """Wartość do podglądu; niepoprawne pole zgłosi dopiero zapis."""
        try:
            return line_total(parse_quantity(quantity), max(parse_money(price), 0))
        except ValueError:
            return 0

    def _update_totals(self):
        total = 0
        for index in range(self.table.rowCount()):
            cents = self._row_total(
                self.table.cellWidget(index, self.QUANTITY).text(),
                self.table.cellWidget(index, self.PRICE).text(),
            )
            total += cents
            self.table.item(index, self.VALUE).setText(format_money(cents))
        self.total.setText(f"Suma: {format_money(total, self._currency())}")

    def rows(self):
        return [
            {
                "name": self.table.cellWidget(index, self.NAME).text(),
                "category": self.table.cellWidget(index, self.CATEGORY).currentData(),
                "quantity": self.table.cellWidget(index, self.QUANTITY).text(),
                "price": self.table.cellWidget(index, self.PRICE).text(),
            }
            for index in range(self.table.rowCount())
        ]


def _kind_combo(selected):
    combo = QComboBox()
    combo.addItem("Wydatek", "expense")
    combo.addItem("Przychód", "income")
    combo.setCurrentIndex(combo.findData(selected))
    return combo


class TransactionDialog(_ProductRowsMixin, _SavingDialog):
    ACCEPT_TEXT = "Zapisz"

    def __init__(self, db, wallet, transaction_id=None, parent=None, initial=None):
        super().__init__(parent)
        self.db = db
        self.wallet = wallet
        self.transaction_id = transaction_id
        self.setWindowTitle("Edycja transakcji" if transaction_id else "Nowa transakcja")

        data = initial or (
            get_transaction(db, transaction_id)
            if transaction_id
            else {"kind": "expense", "occurred_on": None, "description": "", "rows": []}
        )

        self.kind = _kind_combo(data["kind"])
        self.occurred_on = common.date_edit(data["occurred_on"])
        self.description = QLineEdit(data["description"])
        self.description.setMaxLength(200)
        self.description.setPlaceholderText("np. Zakupy spożywcze")

        top = QFormLayout()
        top.addRow("Rodzaj", self.kind)
        top.addRow("Data", self.occurred_on)
        top.addRow("Opis", self.description)

        bottom = self._product_section(data["rows"], list_categories(db))

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)
        layout.addWidget(_buttons(self, self.ACCEPT_TEXT))
        self.resize(760, 480)
        self._update_totals()

    def _currency(self):
        return self.wallet["currency"]

    def values(self):
        return (
            self.kind.currentData(),
            common.iso_date(self.occurred_on),
            self.description.text(),
            self.rows(),
        )

    def save(self):
        if self.transaction_id is None:
            self.transaction_id = create_transaction(
                self.db, self.wallet["id"], *self.values()
            )
        else:
            update_transaction(self.db, self.transaction_id, *self.values())


class PaymentDialog(TransactionDialog):
    """Zwykła transakcja wypełniona z szablonu; zapis zmniejsza też licznik."""

    ACCEPT_TEXT = "Zapłać"

    def __init__(self, db, wallet, recurring_id, parent=None):
        self.recurring_id = recurring_id
        super().__init__(db, wallet, parent=parent, initial=payment_draft(db, recurring_id))
        self.setWindowTitle(f"Płatność: {self.description.text()}")

    def save(self):
        self.transaction_id = pay_recurring(self.db, self.recurring_id, *self.values())


class RecurringDialog(_ProductRowsMixin, _SavingDialog):
    def __init__(self, db, recurring_id=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.recurring_id = recurring_id
        self.setWindowTitle(
            "Edycja transakcji cyklicznej" if recurring_id else "Nowa transakcja cykliczna"
        )
        data = (
            get_recurring(db, recurring_id)
            if recurring_id
            else {
                "wallet_id": None,
                "kind": "expense",
                "description": "",
                "amount_cents": None,
                "category_id": None,
                "remaining": None,
                "rows": [],
            }
        )
        categories = list_categories(db)

        self.wallet = QComboBox()
        self.currencies = {}
        for wallet in list_wallets(db):
            self.wallet.addItem(wallet["name"], wallet["id"])
            self.currencies[wallet["id"]] = wallet["currency"]
        self.wallet.setCurrentIndex(max(self.wallet.findData(data["wallet_id"]), 0))
        self.kind = _kind_combo(data["kind"])
        self.description = QLineEdit(data["description"])
        self.description.setMaxLength(200)
        self.description.setPlaceholderText("np. Czynsz")
        self.amount = QLineEdit(
            format_money_input(data["amount_cents"])
            if data["amount_cents"] is not None
            else ""
        )
        self.amount.setPlaceholderText("puste: ustalana przy płatności")
        self.category = QComboBox()
        self.category.addItem("Bez kategorii", None)
        for item in categories:
            self.category.addItem(item["name"], item["id"])
        self.category.setCurrentIndex(max(self.category.findData(data["category_id"]), 0))
        self.remaining = QLineEdit(
            "" if data["remaining"] is None else str(data["remaining"])
        )
        self.remaining.setPlaceholderText("puste: bez limitu")

        top = QFormLayout()
        top.addRow("Portfel", self.wallet)
        top.addRow("Rodzaj", self.kind)
        top.addRow("Opis", self.description)
        top.addRow("Kwota", self.amount)
        top.addRow("Kategoria", self.category)
        top.addRow("Licznik płatności", self.remaining)

        bottom = self._product_section(data["rows"], categories)
        hint = QLabel(
            "Produkty są opcjonalne. Jeśli je dodasz, to one wyznaczą kwotę i kategorie."
        )

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(hint)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)
        layout.addWidget(_buttons(self))
        self.resize(760, 560)
        self.wallet.currentIndexChanged.connect(self._update_totals)
        self._update_totals()

    def _currency(self):
        return self.currencies.get(self.wallet.currentData(), "")

    def _has_products(self):
        return any(
            row["name"].strip() or row["price"].strip() for row in self.rows()
        )

    def _update_totals(self):
        super()._update_totals()
        has_products = self._has_products()
        self.amount.setEnabled(not has_products)
        self.category.setEnabled(not has_products)

    def save(self):
        values = (
            self.wallet.currentData(),
            self.kind.currentData(),
            self.description.text(),
            self.amount.text(),
            self.category.currentData(),
            self.remaining.text(),
            self.rows(),
        )
        if self.recurring_id is None:
            self.recurring_id = create_recurring(self.db, *values)
        else:
            update_recurring(self.db, self.recurring_id, *values)


class TransferDialog(_SavingDialog):
    def __init__(self, db, from_wallet=None, transfer_id=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.transfer_id = transfer_id
        self.wallets = list_wallets(db)
        self.setWindowTitle("Edycja przelewu" if transfer_id else "Nowy przelew")
        transfer = get_transfer(db, transfer_id) if transfer_id else None

        self.source = self._wallet_combo(
            transfer["from_wallet_id"] if transfer else from_wallet
        )
        self.target = self._wallet_combo(transfer["to_wallet_id"] if transfer else None)
        self.occurred_on = common.date_edit(transfer["occurred_on"] if transfer else None)
        self.description = QLineEdit(transfer["description"] if transfer else "")
        self.description.setMaxLength(200)
        self.amount_from = QLineEdit(
            format_money_input(transfer["amount_from_cents"]) if transfer else ""
        )
        self.amount_to = QLineEdit(
            format_money_input(transfer["amount_to_cents"]) if transfer else ""
        )

        form = QFormLayout(self)
        form.addRow("Z portfela", self.source)
        form.addRow("Do portfela", self.target)
        form.addRow("Data", self.occurred_on)
        form.addRow("Opis (opcjonalnie)", self.description)
        form.addRow("Kwota", self.amount_from)
        form.addRow("Kwota w walucie docelowej", self.amount_to)
        form.addRow(_buttons(self))
        self.setMinimumWidth(460)

        self.source.currentIndexChanged.connect(self._update_amount_to)
        self.target.currentIndexChanged.connect(self._update_amount_to)
        self._update_amount_to()

    def _wallet_combo(self, selected):
        combo = QComboBox()
        combo.addItem("Wybierz…", None)
        for wallet in self.wallets:
            balance = format_money(wallet["balance_cents"], wallet["currency"])
            combo.addItem(f"{wallet['name']} ({balance})", wallet["id"])
        combo.setCurrentIndex(max(combo.findData(selected), 0))
        return combo

    def _update_amount_to(self):
        """Druga kwota ma sens tylko przy różnych walutach."""
        currencies = {wallet["id"]: wallet["currency"] for wallet in self.wallets}
        source = currencies.get(self.source.currentData())
        target = currencies.get(self.target.currentData())
        self.amount_to.setEnabled(bool(source and target and source != target))

    def save(self):
        values = (
            self.source.currentData(),
            self.target.currentData(),
            common.iso_date(self.occurred_on),
            self.description.text(),
            self.amount_from.text(),
            self.amount_to.text(),
        )
        if self.transfer_id is None:
            self.transfer_id = create_transfer(self.db, *values)
        else:
            update_transfer(self.db, self.transfer_id, *values)
