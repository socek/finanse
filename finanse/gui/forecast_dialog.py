"""Okno prognozy salda: portfele na wybrany dzień i płatności, które się do niej liczą."""

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..forecast import balance_forecast, end_of_month
from ..money import format_money
from ..recurring import due_text
from . import common

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
UNKNOWN_HINT = "Kwota ustalana przy płatności, więc nie zmienia prognozy."


def _signed(cents, currency):
    if cents == 0:
        return "–"
    sign = "+" if cents > 0 else "−"
    return f"{sign}{format_money(abs(cents), currency)}"


def _table(headers, stretch):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().hide()
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    header = table.horizontalHeader()
    for column in range(len(headers)):
        header.setSectionResizeMode(
            column,
            QHeaderView.ResizeMode.Stretch
            if column == stretch
            else QHeaderView.ResizeMode.ResizeToContents,
        )
    return table


def _item(text, right=False, bold=False):
    item = QTableWidgetItem(text)
    if right:
        item.setTextAlignment(RIGHT)
    if bold:
        font = QFont(item.font())
        font.setBold(True)
        item.setFont(font)
    return item


def _mark_negative(item):
    """Ujemne saldo w prognozie to ostrzeżenie, więc wyróżnia się jak zaległość."""
    item.setBackground(common.overdue_background())
    item.setForeground(common.overdue_text())
    item.setToolTip("Prognozowane saldo jest ujemne.")


class ForecastDialog(QDialog):
    def __init__(self, db, wallet_ids=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.wallet_ids = wallet_ids
        self.setWindowTitle("Prognoza salda")

        today = date.today()
        self.until = common.date_edit(end_of_month(today).isoformat())
        self.until.setMinimumDate(QDate(today.year, today.month, today.day))
        self.until.dateChanged.connect(self.refresh)
        end_button = QPushButton("Koniec miesiąca")
        end_button.setAutoDefault(False)
        end_button.clicked.connect(
            lambda: self.until.setDate(
                QDate.fromString(end_of_month(today).isoformat(), Qt.DateFormat.ISODate)
            )
        )
        top = QHBoxLayout()
        top.addWidget(QLabel("Prognoza na koniec dnia"))
        top.addWidget(self.until)
        top.addWidget(end_button)
        top.addStretch()

        self.wallets = _table(
            ["Portfel", "Saldo dziś", "Wpisane na później", "Cykliczne przychody",
             "Cykliczne wydatki", "Prognoza"],
            0,
        )  # fmt: skip
        self.payments_title = QLabel()
        font = QFont(self.payments_title.font())
        font.setBold(True)
        self.payments_title.setFont(font)
        self.payments = _table(["Termin", "Opis", "Portfel", "Kwota"], 1)
        self.no_payments = QLabel("Do tego dnia nie ma zaplanowanych płatności cyklicznych.")
        self.unknown_note = QLabel()
        self.unknown_note.setWordWrap(True)
        hint = QLabel(
            "Prognoza to saldo dziś, operacje wpisane już z późniejszą datą oraz płatności"
            " cykliczne z terminem do wybranego dnia, także zaległe."
        )
        hint.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Zamknij")
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.wallets)
        layout.addWidget(self.payments_title)
        layout.addWidget(self.no_payments)
        layout.addWidget(self.payments, 1)
        layout.addWidget(self.unknown_note)
        layout.addWidget(hint)
        layout.addWidget(buttons)
        self.resize(900, 620)
        self.refresh()

    def refresh(self):
        until = date.fromisoformat(common.iso_date(self.until))
        self.forecast = balance_forecast(self.db, until, wallet_ids=self.wallet_ids)
        self._fill_wallets()
        self._fill_payments()

    def _fill_wallets(self):
        forecast = self.forecast
        rows = len(forecast["wallets"])
        several = len(forecast["wallets"]) > 1
        totals = forecast["totals"] if several else {}
        self.wallets.setRowCount(rows + len(totals))
        for row, wallet in enumerate(forecast["wallets"]):
            currency = wallet["currency"]
            unknown = wallet["unknown"]
            cells = (
                _item(wallet["name"]),
                _item(format_money(wallet["balance"], currency), right=True),
                _item(_signed(wallet["planned"], currency), right=True),
                _item(_signed(wallet["recurring_income"], currency), right=True),
                _item(_signed(-wallet["recurring_expense"], currency), right=True),
                _item(
                    format_money(wallet["forecast"], currency) + (" *" if unknown else ""),
                    right=True,
                    bold=True,
                ),
            )
            if unknown:
                cells[5].setToolTip(f"Płatności bez kwoty: {unknown}. {UNKNOWN_HINT}")
            if wallet["forecast"] < 0:
                _mark_negative(cells[5])
            for column, cell in enumerate(cells):
                self.wallets.setItem(row, column, cell)
        for offset, (currency, total) in enumerate(sorted(totals.items())):
            row = rows + offset
            cells = {
                0: _item(f"Razem {currency}", bold=True),
                1: _item(format_money(total["balance"], currency), right=True, bold=True),
                5: _item(format_money(total["forecast"], currency), right=True, bold=True),
            }
            if total["forecast"] < 0:
                _mark_negative(cells[5])
            for column in range(self.wallets.columnCount()):
                self.wallets.setItem(row, column, cells.get(column, _item("")))
        self.wallets.setFixedHeight(
            self.wallets.horizontalHeader().sizeHint().height()
            + sum(self.wallets.rowHeight(row) for row in range(self.wallets.rowCount()))
            + 2 * self.wallets.frameWidth()
        )

    def _fill_payments(self):
        forecast = self.forecast
        payments = forecast["payments"]
        today = date.fromisoformat(forecast["today"])
        self.payments_title.setText(f"Płatności cykliczne do {forecast['until']}")
        self.no_payments.setVisible(not payments)
        self.payments.setVisible(bool(payments))
        self.payments.setRowCount(len(payments))
        for row, payment in enumerate(payments):
            days = (date.fromisoformat(payment["due_on"]) - today).days
            due = _item(f"{payment['due_on']} ({due_text(days)})")
            if payment["overdue"]:
                due.setBackground(common.overdue_background())
                due.setForeground(common.overdue_text())
                due.setToolTip("Termin płatności minął.")
            if payment["amount_cents"] is None:
                amount = _item("ustalana przy płatności", right=True)
                amount.setToolTip(UNKNOWN_HINT)
            else:
                sign = 1 if payment["kind"] == "income" else -1
                amount = _item(
                    _signed(sign * payment["amount_cents"], payment["currency"]), right=True
                )
                amount.setForeground(
                    common.positive_color() if sign > 0 else common.negative_color()
                )
            for column, cell in enumerate(
                (due, _item(payment["description"]), _item(payment["wallet_name"]), amount)
            ):
                self.payments.setItem(row, column, cell)
        unknown = forecast["unknown"]
        self.unknown_note.setVisible(bool(unknown))
        self.unknown_note.setText(
            f"* Płatności bez kwoty: {unknown}. Nie zmieniają prognozy, bo ich kwotę"
            " poznasz dopiero przy płatności."
        )
