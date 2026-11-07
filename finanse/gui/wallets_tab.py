"""Zakładka portfeli: lista po lewej, operacje wybranego portfela po prawej."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..bank_import import load_file
from ..errors import ValidationError
from ..forecast import balance_forecast
from ..money import format_money, format_totals
from ..transactions import delete_transaction, get_transaction
from ..transfers import delete_transfer
from ..wallets import (
    VAT,
    delete_wallet,
    get_wallet,
    group_by_day,
    list_wallets,
    load_entries,
)
from . import common, shortcuts
from .day_list import (
    KEY_ROLE,
    RIGHT,
    DayTree,
    FilterBar,
    WalletList,
    last_transaction_text,
    selection_title,
    summary_text,
    title_row,
    wallet_panel,
)
from .dialogs import TransactionDialog, TransferDialog, WalletDialog
from .forecast_dialog import ForecastDialog
from .import_dialog import ImportDialog

ENTRY_ROLE = KEY_ROLE
DATE, DESCRIPTION, WALLET, CATEGORY, AMOUNT = range(5)
NET, VAT_AMOUNT = 7, 8  # za kolumnami sum dnia, a na ekranie przed kwotą


class WalletsTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

        self.wallet_list = WalletList()
        self.wallet_list.checked_changed.connect(self._selection_changed)
        self.wallet_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.wallet_list.customContextMenuRequested.connect(self._show_wallet_menu)
        new_wallet = QPushButton("Nowy portfel")
        shortcuts.show_on(new_wallet, "new_wallet")
        new_wallet.clicked.connect(self.create_wallet)
        left = wallet_panel(self.wallet_list, new_wallet)

        self.title = common.plain_label("")
        title_font = QFont(self.title.font())
        title_font.setPointSizeF(title_font.pointSizeF() * 1.5)
        title_font.setBold(True)
        self.title.setFont(title_font)
        self.last_transaction = QLabel()
        self.balance = QLabel()
        balance_font = QFont(self.balance.font())
        balance_font.setPointSizeF(balance_font.pointSizeF() * 1.2)
        self.balance.setFont(balance_font)
        self.forecast = common.plain_label()
        self.forecast.setToolTip(
            "Saldo dziś, operacje wpisane z późniejszą datą i płatności cykliczne"
            " z terminem do końca miesiąca, także zaległe."
        )

        self.new_transaction_button = QPushButton("Nowa transakcja")
        shortcuts.show_on(self.new_transaction_button, "new_transaction")
        self.new_transaction_button.clicked.connect(self.create_transaction)
        self.transfer_button = QPushButton("Przelew")
        shortcuts.show_on(self.transfer_button, "new_transfer")
        self.transfer_button.clicked.connect(self.create_transfer)
        self.forecast_button = QPushButton("Prognoza salda")
        self.forecast_button.setToolTip("Prognoza salda zaznaczonych portfeli na wybrany dzień.")
        self.forecast_button.clicked.connect(self.show_forecast)
        self.wallet_actions = [
            self.new_transaction_button, self.transfer_button, self.forecast_button,
        ]  # fmt: skip
        actions = QHBoxLayout()
        for button in self.wallet_actions:
            actions.addWidget(button)
        actions.addStretch()

        self.filter_bar = FilterBar(db)
        self.filter_bar.changed.connect(self._filters_changed)

        self.summary = common.plain_label()
        self.summary.setWordWrap(True)
        self.summary.hide()
        self.empty = QLabel()
        self.empty.hide()

        self.tree = DayTree(
            ["Data", "Opis", "Portfel", "Kategoria", "Kwota"],
            stretch_columns=(DESCRIPTION,),
            extra_headers=("Netto", "VAT"),
        )
        self.tree.currentItemChanged.connect(self._update_entry_buttons)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_entry())
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_entry_menu)
        self.delete_shortcut = shortcuts.bind(
            "delete_selected",
            self.tree,
            self.delete_entry,
            Qt.ShortcutContext.WidgetShortcut,
        )

        self.edit_entry_button = QPushButton("Edytuj operację")
        shortcuts.show_on(self.edit_entry_button, "edit_selected")
        self.edit_entry_button.clicked.connect(self.edit_entry)
        self.duplicate_button = QPushButton("Duplikuj")
        shortcuts.show_on(self.duplicate_button, "duplicate_selected")
        self.duplicate_button.clicked.connect(self.duplicate_transaction)
        self.delete_entry_button = QPushButton("Usuń operację")
        shortcuts.show_on(self.delete_entry_button, "delete_selected")
        self.delete_entry_button.clicked.connect(self.delete_entry)
        self.expand_all_button = QPushButton("Rozwiń wszystko")
        shortcuts.show_on(self.expand_all_button, "expand_all")
        self.expand_all_button.clicked.connect(self.tree.expandAll)
        self.collapse_all_button = QPushButton("Zwiń wszystko")
        shortcuts.show_on(self.collapse_all_button, "collapse_all")
        self.collapse_all_button.clicked.connect(self.tree.collapseAll)
        entry_actions = QHBoxLayout()
        entry_actions.addWidget(self.expand_all_button)
        entry_actions.addWidget(self.collapse_all_button)
        entry_actions.addStretch()
        entry_actions.addWidget(self.duplicate_button)
        entry_actions.addWidget(self.edit_entry_button)
        entry_actions.addWidget(self.delete_entry_button)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addLayout(title_row(self.title, self.last_transaction))
        right_layout.addWidget(self.balance)
        right_layout.addWidget(self.forecast)
        right_layout.addLayout(actions)
        right_layout.addWidget(self.filter_bar)
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
        """Portfel podświetlony na liście, którego dotyczą działania z menu."""
        return self.wallet_list.current_id()

    def _balance_date(self):
        """Salda odpowiadają końcowi filtrowanego okresu, czyli dacie „Do”."""
        return self.filter_bar.state()[1]

    @staticmethod
    def _wallet_label(wallet):
        balance = format_money(wallet["balance_cents"], wallet["currency"])
        return f"{wallet['name']}\n{balance}"

    def edit_selected(self):
        self.edit_entry()

    def focus_search(self):
        self.filter_bar.search.setFocus()
        self.filter_bar.search.selectAll()

    def clear_filters(self):
        self.filter_bar.clear()

    def expand_all(self):
        self.tree.expandAll()

    def collapse_all(self):
        self.tree.collapseAll()

    def check_all(self):
        self.wallet_list.set_all_checked(True)

    def uncheck_all(self):
        self.wallet_list.set_all_checked(False)

    def refresh(self, select=None):
        self.wallet_list.fill(
            list_wallets(self.db, self._balance_date()), self._wallet_label, select
        )
        self.filter_bar.refresh_categories()
        self._selection_changed()

    def _filters_changed(self):
        self.wallet_list.set_labels(
            list_wallets(self.db, self._balance_date()), self._wallet_label
        )
        self._selection_changed()

    def _selection_changed(self):
        self._update_header()
        self.refresh_entries()

    def _update_header(self):
        balance_date = self._balance_date()
        wallets = list_wallets(self.db, balance_date)
        checked = self.wallet_list.checked_ids()
        for button in self.wallet_actions:
            button.setEnabled(bool(wallets))
        self.title.setText(selection_title(wallets, checked))
        self.last_transaction.setText(last_transaction_text(self.db, checked))
        totals = {}
        for wallet in wallets:
            if wallet["id"] in checked:
                totals[wallet["currency"]] = (
                    totals.get(wallet["currency"], 0) + wallet["balance_cents"]
                )
        text = format_totals(totals)
        self.balance.setText(
            f"Saldo na {balance_date}: {text}" if text and balance_date else text
        )
        negative = len(totals) == 1 and next(iter(totals.values())) < 0
        self.balance.setStyleSheet(
            f"color: {common.negative_color().name()}" if negative else ""
        )
        self._update_forecast(checked)

    def _update_forecast(self, checked):
        if not checked:
            self.forecast.hide()
            return
        forecast = balance_forecast(self.db, wallet_ids=set(checked))
        totals = {
            currency: total["forecast"] for currency, total in forecast["totals"].items()
        }
        text = f"Prognoza na koniec miesiąca ({forecast['until']}): {format_totals(totals)}"
        if forecast["unknown"]:
            text += f" · płatności bez kwoty: {forecast['unknown']}"
        self.forecast.setText(text)
        negative = any(total < 0 for total in totals.values())
        self.forecast.setStyleSheet(
            f"color: {common.negative_color().name()}" if negative else ""
        )
        self.forecast.show()

    def show_forecast(self):
        checked = set(self.wallet_list.checked_ids())
        ForecastDialog(self.db, checked or None, parent=self).exec()

    def refresh_entries(self, *_):
        wallet_ids = self.wallet_list.checked_ids()
        self.tree.setColumnHidden(WALLET, len(wallet_ids) < 2)
        has_vat = any(
            wallet["id"] in wallet_ids and wallet["wallet_type"] == VAT
            for wallet in list_wallets(self.db)
        )
        self.tree.setColumnHidden(NET, not has_vat)
        self.tree.setColumnHidden(VAT_AMOUNT, not has_vat)
        date_from, date_to, filters, notes = self.filter_bar.state()
        entries, summary = load_entries(self.db, wallet_ids, date_from, date_to, filters)
        filtered = bool(date_from or date_to or filters.active)
        text = summary_text(notes, filtered and bool(wallet_ids), summary)
        self.summary.setText(text)
        self.summary.setVisible(bool(text))

        self.tree.fill(
            tuple(sorted(wallet_ids)),
            group_by_day(entries),
            lambda day: [self._entry_item(entry, wallet_ids) for entry in day["entries"]],
            "Operacje",
            filters.active,
        )
        if not wallet_ids:
            has_wallets = self.wallet_list.count() > 0
            self.empty.setText("Zaznacz co najmniej jeden portfel." if has_wallets else "")
        elif filtered:
            self.empty.setText("Brak operacji spełniających wybrane filtry.")
        else:
            self.empty.setText("Wybrane portfele nie mają jeszcze transakcji.")
        self.empty.setVisible(not entries and bool(self.empty.text()))
        self._update_entry_buttons()

    def _entry_item(self, entry, wallet_ids):
        if entry["type"] == "transaction":
            return self._transaction_item(entry)
        return self._transfer_item(entry["item"], wallet_ids)

    @staticmethod
    def _categories(products):
        names = dict.fromkeys(p["category_name"] or "Bez kategorii" for p in products)
        return ", ".join(names)

    def _transaction_item(self, entry):
        transaction = entry["item"]
        income = transaction["kind"] == "income"
        amount = format_money(transaction["total_cents"], transaction["currency"])
        item = QTreeWidgetItem(
            [
                "",
                transaction["description"],
                transaction["wallet_name"],
                self._categories(entry["products"]),
                f"{'+' if income else '−'}{amount}",
            ]
        )
        item.setData(DATE, ENTRY_ROLE, ("transaction", transaction["id"]))
        if transaction["wallet_type"] == VAT:
            net = transaction["total_cents"] - transaction["vat_cents"]
            item.setText(NET, format_money(net, transaction["currency"]))
            item.setText(VAT_AMOUNT, format_money(transaction["vat_cents"], transaction["currency"]))
            item.setTextAlignment(NET, RIGHT)
            item.setTextAlignment(VAT_AMOUNT, RIGHT)
        common.mark_row_kind(item, income, self.tree.columnCount())
        common.mark_no_category(item, CATEGORY)
        item.setTextAlignment(AMOUNT, RIGHT)
        item.setForeground(
            AMOUNT, common.positive_color() if income else common.negative_color()
        )
        return item

    def _transfer_item(self, transfer, wallet_ids):
        outgoing = format_money(transfer["amount_from_cents"], transfer["from_currency"])
        incoming = format_money(transfer["amount_to_cents"], transfer["to_currency"])
        route = f"{transfer['from_name']} → {transfer['to_name']}"
        if {transfer["from_wallet_id"], transfer["to_wallet_id"]} <= wallet_ids:
            # Oba portfele są wybrane, więc suma pieniędzy się nie zmienia.
            other = route
            amount = outgoing if outgoing == incoming else f"{outgoing} → {incoming}"
        elif transfer["from_wallet_id"] in wallet_ids:
            other = f"→ {transfer['to_name']}"
            amount = f"−{outgoing}"
        else:
            other = f"← {transfer['from_name']}"
            amount = f"+{incoming}"
        item = QTreeWidgetItem(
            ["", f"{transfer['description']} ({other})", route, "Przelew", amount]
        )
        item.setData(DATE, ENTRY_ROLE, ("transfer", transfer["id"]))
        item.setTextAlignment(AMOUNT, RIGHT)
        item.setToolTip(CATEGORY, "Przelew nie liczy się do przychodów ani wydatków.")
        return item

    def selected_entry(self):
        """Rachunek lub przelew z zaznaczonego wiersza; dzień nie jest operacją."""
        item = self.tree.currentItem()
        key = item.data(DATE, ENTRY_ROLE) if item else None
        return None if key is None or key[0] == "day" else key

    def _wallet_menu(self):
        """Menu portfela podświetlonego na liście."""
        if self.wallet_id() is None:
            return None
        menu = QMenu(self)
        menu.addAction("Nowa transakcja", self.create_transaction)
        menu.addAction("Import CSV", self.import_csv)
        menu.addAction("Edytuj portfel", self.edit_wallet)
        menu.addAction("Usuń portfel", self.delete_wallet)
        return menu

    def _show_wallet_menu(self, position):
        item = self.wallet_list.itemAt(position)
        if item is None:
            return
        self.wallet_list.setCurrentItem(item)
        self._wallet_menu().exec(self.wallet_list.viewport().mapToGlobal(position))

    def _show_wallets(self, *wallet_ids):
        """Portfel, do którego właśnie coś zapisano, ma być widoczny na liście."""
        self.wallet_list.excluded.difference_update(wallet_ids)

    def _entry_menu(self):
        """Menu rachunku lub przelewu; wiersz dnia nie ma żadnych działań."""
        if self.selected_entry() is None:
            return None
        menu = QMenu(self)
        menu.addAction("Edytuj", self.edit_entry)
        if self.selected_entry()[0] == "transaction":
            menu.addAction("Duplikuj", self.duplicate_transaction)
        menu.addAction("Usuń", self.delete_entry)
        return menu

    def _show_entry_menu(self, position):
        item = self.tree.itemAt(position)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        menu = self._entry_menu()
        if menu:
            menu.exec(self.tree.viewport().mapToGlobal(position))

    def _update_entry_buttons(self, *_):
        entry = self.selected_entry()
        self.edit_entry_button.setEnabled(entry is not None)
        self.delete_entry_button.setEnabled(entry is not None)
        self.duplicate_button.setEnabled(entry is not None and entry[0] == "transaction")

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
            self, f"Usunąć portfel „{wallet['name']}” razem ze wszystkimi transakcjami, "
            "także cyklicznymi?"
        ):
            return
        try:
            delete_wallet(self.db, wallet["id"])
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        self.refresh(select=-1)

    def create_transaction(self):
        """Zwraca identyfikator dodanej transakcji albo None."""
        if self.wallet_id() is None:
            common.show_errors(self, ["Dodaj najpierw portfel."])
            return None
        wallet = get_wallet(self.db, self.wallet_id())
        dialog = TransactionDialog(self.db, wallet, parent=self)
        if dialog.exec():
            self._show_wallets(dialog.selected_wallet_id())
            self.refresh()
            key = ("transaction", dialog.transaction_id)
            self.tree.flash(lambda candidate: candidate == key)
            return dialog.transaction_id
        return None

    def duplicate_selected(self):
        self.duplicate_transaction()

    def duplicate_transaction(self):
        """Zwraca identyfikator dodanej kopii albo None; przelewów nie kopiuje."""
        entry = self.selected_entry()
        if entry is None or entry[0] != "transaction":
            return None
        source = get_transaction(self.db, entry[1])
        wallet = get_wallet(self.db, source["wallet_id"])
        dialog = TransactionDialog(self.db, wallet, parent=self, copy_from=entry[1])
        if not dialog.exec():
            return None
        self._show_wallets(dialog.selected_wallet_id())
        self.refresh()
        key = ("transaction", dialog.transaction_id)
        self.tree.flash(lambda candidate: candidate == key)
        return dialog.transaction_id

    def create_transfer(self):
        if len(list_wallets(self.db)) < 2:
            common.show_errors(
                self, ["Do przelewu potrzebujesz co najmniej dwóch portfeli."]
            )
            return
        dialog = TransferDialog(self.db, from_wallet=self.wallet_id(), parent=self)
        if dialog.exec():
            self._show_wallets(dialog.source.currentData(), dialog.target.currentData())
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
            self._show_wallets(wallet["id"])
            self.refresh()

    def edit_entry(self):
        entry = self.selected_entry()
        if entry is None:
            return
        kind, entry_id = entry
        if kind == "transaction":
            wallet_id = get_transaction(self.db, entry_id)["wallet_id"]
            wallet = get_wallet(self.db, wallet_id)
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
            if common.confirm(
                self, f"Usunąć transakcję „{self.tree.currentItem().text(DESCRIPTION)}”?"
            ):
                delete_transaction(self.db, entry_id)
                self.refresh()
        elif common.confirm(self, "Usunąć ten przelew? Zmieni to saldo obu portfeli."):
            delete_transfer(self.db, entry_id)
            self.refresh()
