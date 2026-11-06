"""Zakładka produktów: same pozycje rachunków wybranego portfela, według dni."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSplitter,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..money import format_money, format_quantity
from ..products import group_products_by_day, load_products
from ..wallets import get_wallet, list_wallets
from . import common
from .day_list import KEY_ROLE, RIGHT, DayTree, FilterBar, summary_text
from .dialogs import TransactionDialog

NAME, TRANSACTION, CATEGORY, QUANTITY, PRICE, VALUE = range(1, 7)


class ProductsTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

        self.wallet_list = QListWidget()
        self.wallet_list.currentItemChanged.connect(self._wallet_changed)

        self.title = common.plain_label()
        font = QFont(self.title.font())
        font.setPointSizeF(font.pointSizeF() * 1.5)
        font.setBold(True)
        self.title.setFont(font)

        self.filter_bar = FilterBar(db)
        self.filter_bar.changed.connect(self.refresh_products)
        self.summary = common.plain_label()
        self.summary.setWordWrap(True)
        self.summary.hide()
        self.empty = QLabel()
        self.empty.hide()

        self.tree = DayTree(
            ["Data", "Produkt", "Transakcja", "Kategoria", "Ilość", "Cena", "Wartość"],
            stretch_columns=(NAME, TRANSACTION),
        )
        self.tree.currentItemChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_transaction())
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_menu)

        self.expand_all_button = QPushButton("Rozwiń wszystko")
        self.expand_all_button.clicked.connect(self.tree.expandAll)
        self.collapse_all_button = QPushButton("Zwiń wszystko")
        self.collapse_all_button.clicked.connect(self.tree.collapseAll)
        self.edit_button = QPushButton("Edytuj transakcję")
        self.edit_button.clicked.connect(self.edit_transaction)
        actions = QHBoxLayout()
        actions.addWidget(self.expand_all_button)
        actions.addWidget(self.collapse_all_button)
        actions.addStretch()
        actions.addWidget(self.edit_button)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.title)
        right_layout.addWidget(self.filter_bar)
        right_layout.addWidget(self.summary)
        right_layout.addWidget(self.empty)
        right_layout.addWidget(self.tree, 1)
        right_layout.addLayout(actions)

        splitter = QSplitter()
        splitter.addWidget(self.wallet_list)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 860])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter)
        self.refresh()

    def wallet_id(self):
        item = self.wallet_list.currentItem()
        return item.data(KEY_ROLE) if item else None

    def refresh(self):
        selected = self.wallet_id()
        self.wallet_list.blockSignals(True)
        self.wallet_list.clear()
        current = None
        for wallet in list_wallets(self.db):
            item = QListWidgetItem(wallet["name"])
            item.setData(KEY_ROLE, wallet["id"])
            self.wallet_list.addItem(item)
            if wallet["id"] == selected or current is None:
                current = item
        if current:
            self.wallet_list.setCurrentItem(current)
        self.wallet_list.blockSignals(False)
        self.filter_bar.refresh_categories()
        self.refresh_products()

    def _wallet_changed(self, *_):
        self.refresh_products()

    def refresh_products(self):
        wallet_id = self.wallet_id()
        wallet = get_wallet(self.db, wallet_id) if wallet_id else None
        if wallet is None:
            self.title.setText("Dodaj pierwszy portfel")
            self.tree.clear()
            self.summary.hide()
            self.empty.hide()
            self._update_buttons()
            return
        self.title.setText(wallet["name"])

        date_from, date_to, filters, notes = self.filter_bar.state()
        products, summary = load_products(self.db, wallet_id, date_from, date_to, filters)
        filtered = bool(date_from or date_to or filters.active)
        currency = wallet["currency"]
        text = summary_text(notes, filtered, summary, currency)
        self.summary.setText(text)
        self.summary.setVisible(bool(text))

        self.tree.fill(
            wallet_id,
            group_products_by_day(products),
            lambda day: [self._product_item(p, currency) for p in day["entries"]],
            currency,
            "Produkty",
            filters.active,
        )
        self.empty.setText(
            "Brak produktów spełniających wybrane filtry."
            if filtered
            else "Ten portfel nie ma jeszcze produktów."
        )
        self.empty.setVisible(not products)
        self._update_buttons()

    @staticmethod
    def _product_item(product, currency):
        income = product["kind"] == "income"
        value = format_money(product["total_cents"], currency)
        item = QTreeWidgetItem(
            [
                "",
                product["name"],
                product["description"],
                product["category_name"] or "Bez kategorii",
                format_quantity(product["quantity_milli"]),
                format_money(product["unit_price_cents"]),
                f"{'+' if income else '−'}{value}",
            ]
        )
        item.setData(0, KEY_ROLE, ("product", product["id"], product["transaction_id"]))
        for column in (QUANTITY, PRICE, VALUE):
            item.setTextAlignment(column, RIGHT)
        item.setForeground(
            VALUE, common.positive_color() if income else common.negative_color()
        )
        return item

    def selected_transaction(self):
        """Rachunek zaznaczonego produktu; wiersz dnia żadnego nie wskazuje."""
        item = self.tree.currentItem()
        key = item.data(0, KEY_ROLE) if item else None
        return key[2] if key and key[0] == "product" else None

    def _update_buttons(self, *_):
        self.edit_button.setEnabled(self.selected_transaction() is not None)

    def _show_menu(self, position):
        item = self.tree.itemAt(position)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        if self.selected_transaction() is None:
            return
        menu = QMenu(self)
        menu.addAction("Edytuj transakcję", self.edit_transaction)
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def edit_transaction(self):
        transaction_id = self.selected_transaction()
        if transaction_id is None:
            return
        wallet = get_wallet(self.db, self.wallet_id())
        if TransactionDialog(self.db, wallet, transaction_id, parent=self).exec():
            self.refresh_products()
