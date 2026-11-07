"""Formularze: portfel, transakcja i przelew."""

from PySide6.QtCore import QDate, Qt
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
    format_precise_input,
    line_total,
    parse_precise,
    parse_quantity,
    to_cents,
    unit_price,
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
from . import common, shortcuts
from .category_combo import CategoryCombo


def _buttons(dialog, accept_text="Zapisz", shortcut=None):
    box = QDialogButtonBox()
    accept = box.addButton(accept_text, QDialogButtonBox.ButtonRole.AcceptRole)
    if shortcut:
        shortcuts.show_on(accept, shortcut)
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


MINUS_SIGNS = "-−–—"  # zwykły minus oraz znaki, które wklejają się np. z wyciągów


def _remove_minus(field):
    """Ilość, cena i wartość są dodatnie, a rodzaj transakcji wybiera się osobno."""
    text = field.text()
    if not any(sign in text for sign in MINUS_SIGNS):
        return
    cursor = field.cursorPosition()
    before_cursor = text[:cursor]
    for sign in MINUS_SIGNS:
        text = text.replace(sign, "")
        before_cursor = before_cursor.replace(sign, "")
    field.setText(text)
    field.setCursorPosition(len(before_cursor))


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
        shortcuts.show_on(add, "add_product")
        add.setAutoDefault(False)
        add.clicked.connect(self._next_product)
        bottom = QHBoxLayout()
        bottom.addWidget(add)
        bottom.addStretch()
        bottom.addWidget(self.total)
        return bottom

    def keyPressEvent(self, event):
        """Klawisze z ustawień: kolejny produkt i zapis całości."""
        if shortcuts.matches(event, "save"):
            self.accept()
        elif shortcuts.matches(event, "add_product"):
            self._next_product()
        elif event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            super().keyPressEvent(event)
        # Enter bez przypisanego działania nie może zapisywać przez domyślny przycisk.

    def _next_product(self):
        """Dodaje wiersz, a jeśli ostatni jest jeszcze pusty, tylko do niego przechodzi."""
        last = self.table.rowCount() - 1
        fields = [
            self.table.cellWidget(last, column).text().strip()
            for column in (self.NAME, self.PRICE, self.VALUE)
        ]
        quantity = self.table.cellWidget(last, self.QUANTITY).text().strip()
        if any(fields) or quantity not in ("", "1"):
            self._add_row(EMPTY_ROW, focus=True)
        else:
            self.table.cellWidget(last, self.NAME).setFocus()

    def _add_row(self, row, focus=False):
        index = self.table.rowCount()
        self.table.insertRow(index)
        name = QLineEdit(row["name"])
        name.setMaxLength(200)
        category = CategoryCombo()
        category.addItem("Bez kategorii", None)
        for item in self.categories:
            category.addItem(item["name"], item["id"])
        found = category.findData(row["category"])
        category.setCurrentIndex(max(found, 0))
        common.style_category_combo(category)
        quantity = QLineEdit(row["quantity"])
        price = QLineEdit(row["price"])
        value = QLineEdit()
        value.setAlignment(Qt.AlignmentFlag.AlignRight)
        computed = self._line_value(quantity.text(), price.text())
        stored = row.get("total", "")
        value.setText(stored or computed)
        value.setProperty("fixed", self._is_fixed_value(stored, computed, price.text()))
        remove = QToolButton()
        remove.setText("Usuń")
        remove.clicked.connect(lambda: self._remove_row(remove))

        for field in (quantity, price, value):
            field.textEdited.connect(lambda _text, edited=field: _remove_minus(edited))
        name.textChanged.connect(self._update_totals)
        quantity.textChanged.connect(lambda: self._quantity_edited(quantity, price, value))
        price.textChanged.connect(lambda: self._price_edited(quantity, price, value))
        value.textChanged.connect(lambda: self._value_edited(quantity, price, value))

        self.table.setCellWidget(index, self.NAME, name)
        self.table.setCellWidget(index, self.CATEGORY, category)
        self.table.setCellWidget(index, self.QUANTITY, quantity)
        self.table.setCellWidget(index, self.PRICE, price)
        self.table.setCellWidget(index, self.VALUE, value)
        self.table.setCellWidget(index, self.REMOVE, remove)
        if focus:
            name.setFocus()
            self._update_totals()

    @staticmethod
    def _is_fixed_value(stored, computed, price):
        """Czy wartość nie wynika z ilości i ceny, np. 10,00 przy 3 sztukach."""
        if not stored or stored == computed:
            return False
        if not computed:
            return True
        # Dane sprzed 5 miejsc po przecinku mają cenę i wartość zaokrąglone do groszy, więc
        # 72,38 x 8,57 = 620,2966 zapisane jako 620,30 nadal wynika z ilości i ceny.
        stored_e5, computed_e5 = parse_precise(stored), parse_precise(computed)
        rounded_legacy = (
            parse_precise(price) % 1000 == 0
            and stored_e5 % 1000 == 0
            and to_cents(computed_e5) * 1000 == stored_e5
        )
        return not rounded_legacy

    @staticmethod
    def _line_value(quantity, price):
        """Wartość z ilości i ceny jako tekst; pusty, gdy któreś pole jest niepoprawne."""
        try:
            price_e5 = parse_precise(price)
            if price_e5 < 0:
                return ""
            return format_precise_input(line_total(parse_quantity(quantity), price_e5))
        except ValueError:
            return ""

    @staticmethod
    def _set_quietly(field, text):
        """Ustawia wyliczone pole bez uruchamiania jego własnej obsługi zmiany."""
        field.blockSignals(True)
        field.setText(text)
        field.blockSignals(False)

    def _sync_value(self, quantity, price, value):
        self._set_quietly(value, self._line_value(quantity.text(), price.text()))

    def _sync_price(self, quantity, price, value):
        """Niepoprawne pole zostawia cenę bez zmian; błąd zgłosi dopiero zapis."""
        try:
            total_e5 = parse_precise(value.text())
            if total_e5 >= 0:
                quantity_e5 = parse_quantity(quantity.text())
                self._set_quietly(price, format_precise_input(unit_price(total_e5, quantity_e5)))
        except ValueError:
            pass

    def _quantity_edited(self, quantity, price, value):
        """Ilość przelicza to pole, które użytkownik zmienił jako ostatnie."""
        if value.property("fixed"):
            self._sync_price(quantity, price, value)
        else:
            self._sync_value(quantity, price, value)
        self._update_totals()

    def _price_edited(self, quantity, price, value):
        value.setProperty("fixed", False)
        self._sync_value(quantity, price, value)
        self._update_totals()

    def _value_edited(self, quantity, price, value):
        # Puste pole w trakcie pisania niczego nie nadpisuje.
        value.setProperty("fixed", bool(value.text().strip()))
        if value.property("fixed"):
            self._sync_price(quantity, price, value)
        self._update_totals()

    def _remove_row(self, button):
        if self.table.rowCount() == 1:
            self.table.cellWidget(0, self.NAME).clear()
            self.table.cellWidget(0, self.CATEGORY).setCurrentIndex(0)
            self.table.cellWidget(0, self.VALUE).clear()
            self.table.cellWidget(0, self.QUANTITY).setText("1")
            self.table.cellWidget(0, self.PRICE).clear()
        else:
            for index in range(self.table.rowCount()):
                if self.table.cellWidget(index, self.REMOVE) is button:
                    self.table.removeRow(index)
                    break
        self._update_totals()

    def _row_total(self, index):
        """Wartość do sumy; niepoprawne pole zgłosi dopiero zapis."""
        text = self.table.cellWidget(index, self.VALUE).text().strip()
        if not text:
            text = self._line_value(
                self.table.cellWidget(index, self.QUANTITY).text(),
                self.table.cellWidget(index, self.PRICE).text(),
            )
        try:
            return to_cents(max(parse_precise(text), 0))
        except ValueError:
            return 0

    def _update_totals(self):
        total = sum(self._row_total(index) for index in range(self.table.rowCount()))
        self.total.setText(f"Suma: {format_money(total, self._currency())}")

    def rows(self):
        rows = []
        for index in range(self.table.rowCount()):
            value = self.table.cellWidget(index, self.VALUE)
            rows.append(
                {
                    "name": self.table.cellWidget(index, self.NAME).text(),
                    "category": self.table.cellWidget(index, self.CATEGORY).selected_category(),
                    "quantity": self.table.cellWidget(index, self.QUANTITY).text(),
                    "price": self.table.cellWidget(index, self.PRICE).text(),
                    "total": value.text() if value.property("fixed") else "",
                }
            )
        return rows


def _kind_combo(selected):
    combo = QComboBox()
    combo.addItem("Wydatek", "expense")
    combo.addItem("Przychód", "income")
    combo.setCurrentIndex(combo.findData(selected))
    return combo


DESCRIPTION_HINT = "np. Zakupy spożywcze"


class TransactionDialog(_ProductRowsMixin, _SavingDialog):
    ACCEPT_TEXT = "Zapisz"
    # Data ostatnio dodanej transakcji; żyje tylko do zamknięcia aplikacji, żeby wygodnie
    # dopisywać kilka transakcji z przeszłości.
    remembered_date = None

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
        is_new = transaction_id is None and initial is None
        self.occurred_on = common.date_edit(
            TransactionDialog.remembered_date if is_new else data["occurred_on"]
        )
        self.today_button = QPushButton("Dzisiaj")
        shortcuts.show_on(self.today_button, "today")
        self.today_button.setAutoDefault(False)
        self.today_button.clicked.connect(self.set_today)
        self.today_shortcut = shortcuts.bind("today", self, self.set_today)
        date_row = QHBoxLayout()
        date_row.addWidget(self.occurred_on, 1)
        date_row.addWidget(self.today_button)
        self.description = QLineEdit(data["description"])
        self.description.setMaxLength(200)
        self.description.setPlaceholderText(DESCRIPTION_HINT)

        top = QFormLayout()
        # Portfel wybiera się tylko przy nowej transakcji; płatność ma go z szablonu.
        self.wallet_combo = None
        if is_new:
            self.wallet_combo = QComboBox()
            self.currencies = {}
            for item in list_wallets(db):
                self.wallet_combo.addItem(item["name"], item["id"])
                self.currencies[item["id"]] = item["currency"]
            if wallet is not None:
                self.wallet_combo.setCurrentIndex(
                    max(self.wallet_combo.findData(wallet["id"]), 0)
                )
            top.addRow("Portfel", self.wallet_combo)
        top.addRow("Rodzaj", self.kind)
        top.addRow("Data", date_row)
        top.addRow("Opis", self.description)

        bottom = self._product_section(data["rows"], list_categories(db))

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)
        layout.addWidget(_buttons(self, self.ACCEPT_TEXT, "save"))
        self.resize(760, 480)
        if self.wallet_combo is not None:
            self.wallet_combo.currentIndexChanged.connect(self._update_totals)
            self.table.cellWidget(0, self.NAME).setFocus()
        self._update_totals()

    def set_today(self):
        self.occurred_on.setDate(QDate.currentDate())

    def selected_wallet_id(self):
        if self.wallet_combo is not None:
            return self.wallet_combo.currentData()
        return self.wallet["id"]

    def _currency(self):
        if self.wallet_combo is not None:
            return self.currencies.get(self.wallet_combo.currentData(), "")
        return self.wallet["currency"]

    def suggested_description(self):
        """Nazwa jedynego produktu nowej transakcji; pusty tekst, gdy jej nie ma."""
        if self.wallet_combo is None:
            return ""
        filled = [
            row
            for row in self.rows()
            if row["name"].strip()
            or row["price"].strip()
            or row["total"].strip()
            or row["quantity"].strip() not in ("", "1")
        ]
        return filled[0]["name"].strip() if len(filled) == 1 else ""

    def _update_totals(self):
        super()._update_totals()
        self.description.setPlaceholderText(
            self.suggested_description() or DESCRIPTION_HINT
        )

    def values(self):
        return (
            self.kind.currentData(),
            common.iso_date(self.occurred_on),
            self.description.text().strip() or self.suggested_description(),
            self.rows(),
        )

    def save(self):
        if self.transaction_id is None:
            self.transaction_id = create_transaction(
                self.db, self.selected_wallet_id(), *self.values()
            )
            TransactionDialog.remembered_date = common.iso_date(self.occurred_on)
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
        self.remaining = QLineEdit(
            "" if data["remaining"] is None else str(data["remaining"])
        )
        self.remaining.setPlaceholderText("puste: bez limitu")

        top = QFormLayout()
        top.addRow("Portfel", self.wallet)
        top.addRow("Rodzaj", self.kind)
        top.addRow("Opis", self.description)
        top.addRow("Licznik płatności", self.remaining)

        bottom = self._product_section(data["rows"], categories)
        hint = QLabel(
            "Produkty są opcjonalne. Bez nich kwotę i kategorię podasz przy płatności."
        )

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(hint)
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)
        layout.addWidget(_buttons(self, "Zapisz", "save"))
        self.resize(760, 560)
        self.wallet.currentIndexChanged.connect(self._update_totals)
        self._update_totals()

    def _currency(self):
        return self.currencies.get(self.wallet.currentData(), "")

    def save(self):
        values = (
            self.wallet.currentData(),
            self.kind.currentData(),
            self.description.text(),
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
