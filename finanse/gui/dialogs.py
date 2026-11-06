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


class TransactionDialog(_SavingDialog):
    NAME, CATEGORY, QUANTITY, PRICE, VALUE, REMOVE = range(6)

    def __init__(self, db, wallet, transaction_id=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.wallet = wallet
        self.transaction_id = transaction_id
        self.categories = list_categories(db)
        self.setWindowTitle("Edycja transakcji" if transaction_id else "Nowa transakcja")

        data = (
            get_transaction(db, transaction_id)
            if transaction_id
            else {"kind": "expense", "occurred_on": None, "description": "", "rows": []}
        )

        self.kind = QComboBox()
        self.kind.addItem("Wydatek", "expense")
        self.kind.addItem("Przychód", "income")
        self.kind.setCurrentIndex(self.kind.findData(data["kind"]))
        self.occurred_on = common.date_edit(data["occurred_on"])
        self.description = QLineEdit(data["description"])
        self.description.setMaxLength(200)
        self.description.setPlaceholderText("np. Zakupy spożywcze")

        top = QFormLayout()
        top.addRow("Rodzaj", self.kind)
        top.addRow("Data", self.occurred_on)
        top.addRow("Opis", self.description)

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

        for row in data["rows"] or [EMPTY_ROW]:
            self._add_row(row)

        add = QPushButton("Dodaj produkt")
        add.clicked.connect(lambda: self._add_row(EMPTY_ROW, focus=True))
        self.total = QLabel()
        bottom = QHBoxLayout()
        bottom.addWidget(add)
        bottom.addStretch()
        bottom.addWidget(self.total)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)
        layout.addWidget(_buttons(self))
        self.resize(760, 480)
        self._update_totals()

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
        self.total.setText(f"Suma: {format_money(total, self.wallet['currency'])}")

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

    def save(self):
        values = (
            self.kind.currentData(),
            common.iso_date(self.occurred_on),
            self.description.text(),
            self.rows(),
        )
        if self.transaction_id is None:
            self.transaction_id = create_transaction(self.db, self.wallet["id"], *values)
        else:
            update_transaction(self.db, self.transaction_id, *values)


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
