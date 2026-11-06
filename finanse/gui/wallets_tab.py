"""Zakładka portfeli: lista po lewej, operacje wybranego portfela po prawej."""

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..bank_import import load_file
from ..errors import ValidationError
from ..money import format_money, format_quantity
from ..transactions import delete_transaction
from ..transfers import delete_transfer
from ..wallets import delete_wallet, get_wallet, list_wallets, load_entries
from . import common
from .dialogs import TransactionDialog, TransferDialog, WalletDialog
from .import_dialog import ImportDialog

ENTRY_ROLE = Qt.ItemDataRole.UserRole
DATE, DESCRIPTION, CATEGORY, QUANTITY, PRICE, AMOUNT = range(6)
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class WalletsTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

        self.wallet_list = QListWidget()
        self.wallet_list.currentItemChanged.connect(self._load_wallet)
        new_wallet = QPushButton("Nowy portfel")
        new_wallet.clicked.connect(self.create_wallet)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.wallet_list)
        left_layout.addWidget(new_wallet)

        self.title = common.plain_label("")
        title_font = QFont(self.title.font())
        title_font.setPointSizeF(title_font.pointSizeF() * 1.5)
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.balance = QLabel()
        balance_font = QFont(self.balance.font())
        balance_font.setPointSizeF(balance_font.pointSizeF() * 1.2)
        self.balance.setFont(balance_font)

        self.new_transaction_button = QPushButton("Nowa transakcja")
        self.new_transaction_button.clicked.connect(self.create_transaction)
        self.transfer_button = QPushButton("Przelew")
        self.transfer_button.clicked.connect(self.create_transfer)
        self.import_button = QPushButton("Import CSV")
        self.import_button.clicked.connect(self.import_csv)
        self.edit_wallet_button = QPushButton("Edytuj portfel")
        self.edit_wallet_button.clicked.connect(self.edit_wallet)
        self.delete_wallet_button = QPushButton("Usuń portfel")
        self.delete_wallet_button.clicked.connect(self.delete_wallet)
        self.wallet_actions = [
            self.new_transaction_button,
            self.transfer_button,
            self.import_button,
            self.edit_wallet_button,
            self.delete_wallet_button,
        ]
        actions = QHBoxLayout()
        for button in self.wallet_actions:
            actions.addWidget(button)
        actions.addStretch()

        self.use_from = QCheckBox("Od")
        self.date_from = common.date_edit()
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.use_to = QCheckBox("Do")
        self.date_to = common.date_edit()
        filters = QHBoxLayout()
        for widget in (self.use_from, self.date_from, self.use_to, self.date_to):
            filters.addWidget(widget)
        filters.addStretch()
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)
        self.use_from.toggled.connect(self.date_from.setEnabled)
        self.use_to.toggled.connect(self.date_to.setEnabled)
        for checkbox in (self.use_from, self.use_to):
            checkbox.toggled.connect(self.refresh_entries)
        for edit in (self.date_from, self.date_to):
            edit.dateChanged.connect(self.refresh_entries)

        self.summary = QLabel()
        self.summary.hide()
        self.empty = QLabel()
        self.empty.hide()

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Data", "Opis", "Kategoria", "Ilość", "Cena", "Kwota"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(DESCRIPTION, QHeaderView.ResizeMode.Stretch)
        for column in (DATE, CATEGORY, QUANTITY, PRICE, AMOUNT):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(self._update_entry_buttons)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_entry())

        self.edit_entry_button = QPushButton("Edytuj operację")
        self.edit_entry_button.clicked.connect(self.edit_entry)
        self.delete_entry_button = QPushButton("Usuń operację")
        self.delete_entry_button.clicked.connect(self.delete_entry)
        entry_actions = QHBoxLayout()
        entry_actions.addStretch()
        entry_actions.addWidget(self.edit_entry_button)
        entry_actions.addWidget(self.delete_entry_button)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.title)
        right_layout.addWidget(self.balance)
        right_layout.addLayout(actions)
        right_layout.addLayout(filters)
        right_layout.addWidget(self.summary)
        right_layout.addWidget(self.empty)
        right_layout.addWidget(self.tree, 1)
        right_layout.addLayout(entry_actions)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 860])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        self.refresh()

    # Odświeżanie

    def wallet_id(self):
        item = self.wallet_list.currentItem()
        return item.data(ENTRY_ROLE) if item else None

    def refresh(self, select=None):
        select = select if select is not None else self.wallet_id()
        self.wallet_list.blockSignals(True)
        self.wallet_list.clear()
        current = None
        for wallet in list_wallets(self.db):
            balance = format_money(wallet["balance_cents"], wallet["currency"])
            item = QListWidgetItem(f"{wallet['name']}\n{balance}")
            item.setData(ENTRY_ROLE, wallet["id"])
            self.wallet_list.addItem(item)
            if wallet["id"] == select or current is None:
                current = item
        if current:
            self.wallet_list.setCurrentItem(current)
        self.wallet_list.blockSignals(False)
        self._load_wallet()

    def _load_wallet(self, *_):
        wallet_id = self.wallet_id()
        wallet = get_wallet(self.db, wallet_id) if wallet_id else None
        for button in self.wallet_actions:
            button.setEnabled(wallet is not None)
        if wallet is None:
            self.title.setText("Dodaj pierwszy portfel")
            self.balance.clear()
        else:
            self.title.setText(wallet["name"])
            self.balance.setText(format_money(wallet["balance_cents"], wallet["currency"]))
            color = common.negative_color().name() if wallet["balance_cents"] < 0 else ""
            self.balance.setStyleSheet(f"color: {color}" if color else "")
        self.refresh_entries()

    def _period(self):
        date_from = common.iso_date(self.date_from) if self.use_from.isChecked() else ""
        date_to = common.iso_date(self.date_to) if self.use_to.isChecked() else ""
        return date_from, date_to

    def refresh_entries(self, *_):
        self.tree.clear()
        wallet_id = self.wallet_id()
        wallet = get_wallet(self.db, wallet_id) if wallet_id else None
        if wallet is None:
            self.summary.hide()
            self.empty.hide()
            self._update_entry_buttons()
            return
        date_from, date_to = self._period()
        entries, summary = load_entries(self.db, wallet_id, date_from, date_to)
        filtered = bool(date_from or date_to)

        if date_from and date_to and date_from > date_to:
            self.summary.setText("Data „Od” nie może być późniejsza niż „Do”.")
        else:
            currency = wallet["currency"]
            self.summary.setText(
                f"W tym okresie: przychody {format_money(summary['income'], currency)},"
                f" wydatki {format_money(summary['expense'], currency)}."
            )
        self.summary.setVisible(filtered)

        for entry in entries:
            if entry["type"] == "transaction":
                self.tree.addTopLevelItem(self._transaction_item(entry, wallet))
            else:
                self.tree.addTopLevelItem(self._transfer_item(entry["item"], wallet))
        self.empty.setText(
            "Brak operacji w wybranym okresie."
            if filtered
            else "Ten portfel nie ma jeszcze transakcji."
        )
        self.empty.setVisible(not entries)
        self._update_entry_buttons()

    def _transaction_item(self, entry, wallet):
        transaction = entry["item"]
        income = transaction["kind"] == "income"
        amount = format_money(transaction["total_cents"], wallet["currency"])
        item = QTreeWidgetItem(
            [
                transaction["occurred_on"],
                transaction["description"],
                "",
                "",
                "",
                f"{'+' if income else '−'}{amount}",
            ]
        )
        item.setData(DATE, ENTRY_ROLE, ("transaction", transaction["id"]))
        item.setTextAlignment(AMOUNT, RIGHT)
        item.setForeground(
            AMOUNT, common.positive_color() if income else common.negative_color()
        )
        if len(entry["products"]) == 1:
            product = entry["products"][0]
            item.setText(CATEGORY, product["category_name"] or "Bez kategorii")
        for product in entry["products"]:
            child = QTreeWidgetItem(
                [
                    "",
                    product["name"],
                    product["category_name"] or "Bez kategorii",
                    format_quantity(product["quantity_milli"]),
                    format_money(product["unit_price_cents"]),
                    format_money(product["total_cents"]),
                ]
            )
            for column in (QUANTITY, PRICE, AMOUNT):
                child.setTextAlignment(column, RIGHT)
            item.addChild(child)
        return item

    def _transfer_item(self, transfer, wallet):
        outgoing = transfer["from_wallet_id"] == wallet["id"]
        if outgoing:
            other = f"→ {transfer['to_name']}"
            amount = "−" + format_money(
                transfer["amount_from_cents"], transfer["from_currency"]
            )
        else:
            other = f"← {transfer['from_name']}"
            amount = "+" + format_money(
                transfer["amount_to_cents"], transfer["to_currency"]
            )
        item = QTreeWidgetItem(
            [
                transfer["occurred_on"],
                f"{transfer['description']} ({other})",
                "Przelew",
                "",
                "",
                amount,
            ]
        )
        item.setData(DATE, ENTRY_ROLE, ("transfer", transfer["id"]))
        item.setTextAlignment(AMOUNT, RIGHT)
        item.setToolTip(CATEGORY, "Przelew nie liczy się do przychodów ani wydatków.")
        return item

    def selected_entry(self):
        item = self.tree.currentItem()
        if item is None:
            return None
        if item.parent():
            item = item.parent()
        return item.data(DATE, ENTRY_ROLE)

    def _update_entry_buttons(self, *_):
        selected = self.selected_entry() is not None
        self.edit_entry_button.setEnabled(selected)
        self.delete_entry_button.setEnabled(selected)

    # Działania

    def create_wallet(self):
        dialog = WalletDialog(self.db, parent=self)
        if dialog.exec():
            self.refresh(select=dialog.wallet_id)

    def edit_wallet(self):
        wallet = get_wallet(self.db, self.wallet_id())
        if WalletDialog(self.db, wallet, parent=self).exec():
            self.refresh()

    def delete_wallet(self):
        wallet = get_wallet(self.db, self.wallet_id())
        if not common.confirm(
            self, f"Usunąć portfel „{wallet['name']}” razem ze wszystkimi transakcjami?"
        ):
            return
        try:
            delete_wallet(self.db, wallet["id"])
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        self.refresh(select=-1)

    def create_transaction(self):
        wallet = get_wallet(self.db, self.wallet_id())
        if TransactionDialog(self.db, wallet, parent=self).exec():
            self.refresh()

    def create_transfer(self):
        if len(list_wallets(self.db)) < 2:
            common.show_errors(
                self, ["Do przelewu potrzebujesz co najmniej dwóch portfeli."]
            )
            return
        if TransferDialog(self.db, from_wallet=self.wallet_id(), parent=self).exec():
            self.refresh()

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Wybierz plik CSV z banku", "", "Pliki CSV (*.csv *.txt);;Wszystkie pliki (*)"
        )
        if path:
            self.import_file(path)

    def import_file(self, path):
        try:
            content, delimiter = load_file(path)
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        wallet = get_wallet(self.db, self.wallet_id())
        dialog = ImportDialog(self.db, wallet, content, delimiter, parent=self)
        if dialog.exec():
            common.show_info(self, dialog.summary())
            self.refresh()

    def edit_entry(self):
        entry = self.selected_entry()
        if entry is None:
            return
        kind, entry_id = entry
        if kind == "transaction":
            wallet = get_wallet(self.db, self.wallet_id())
            dialog = TransactionDialog(self.db, wallet, entry_id, parent=self)
        else:
            dialog = TransferDialog(self.db, transfer_id=entry_id, parent=self)
        if dialog.exec():
            self.refresh()

    def delete_entry(self):
        entry = self.selected_entry()
        if entry is None:
            return
        kind, entry_id = entry
        if kind == "transaction":
            if common.confirm(self, "Usunąć tę transakcję?"):
                delete_transaction(self.db, entry_id)
                self.refresh()
        elif common.confirm(self, "Usunąć ten przelew? Zmieni to saldo obu portfeli."):
            delete_transfer(self.db, entry_id)
            self.refresh()
