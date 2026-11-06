"""Części wspólne list według dni: filtry oraz drzewo dni z pozycjami."""

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..categories import list_categories
from ..money import format_money, parse_money
from ..wallets import NO_CATEGORY, EntryFilters
from . import common

KEY_ROLE = Qt.ItemDataRole.UserRole
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


class FilterBar(QWidget):
    """Filtry listy: okres, szukanie po nazwie, kategoria i kwota."""

    changed = Signal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

        self.use_from = QCheckBox("Od")
        self.date_from = common.date_edit()
        self.date_from.setDate(QDate.currentDate().addMonths(-1))
        self.use_to = QCheckBox("Do")
        self.date_to = common.date_edit()
        self.date_from.setEnabled(False)
        self.date_to.setEnabled(False)
        self.use_from.toggled.connect(self.date_from.setEnabled)
        self.use_to.toggled.connect(self.date_to.setEnabled)
        clear = QPushButton("Wyczyść filtry")
        clear.clicked.connect(self.clear)
        dates = QHBoxLayout()
        for widget in (self.use_from, self.date_from, self.use_to, self.date_to):
            dates.addWidget(widget)
        dates.addStretch()
        dates.addWidget(clear)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Szukaj po nazwie")
        self.search.setClearButtonEnabled(True)
        self.category = QComboBox()
        self.category.setMinimumWidth(170)
        self.amount_from = QLineEdit()
        self.amount_from.setPlaceholderText("Kwota od")
        self.amount_from.setFixedWidth(90)
        self.amount_to = QLineEdit()
        self.amount_to.setPlaceholderText("Kwota do")
        self.amount_to.setFixedWidth(90)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.category)
        search_row.addWidget(self.amount_from)
        search_row.addWidget(self.amount_to)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(dates)
        layout.addLayout(search_row)

        for checkbox in (self.use_from, self.use_to):
            checkbox.toggled.connect(self.changed)
        for edit in (self.date_from, self.date_to):
            edit.dateChanged.connect(self.changed)
        for line in (self.search, self.amount_from, self.amount_to):
            line.textChanged.connect(self.changed)
        self.category.currentIndexChanged.connect(self.changed)
        self.refresh_categories()

    def refresh_categories(self):
        """Kategorie mogły się zmienić w innej zakładce; wybór zostaje, jeśli istnieje."""
        selected = self.category.currentData()
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("Wszystkie kategorie", None)
        self.category.addItem("Bez kategorii", NO_CATEGORY)
        for category in list_categories(self.db):
            self.category.addItem(category["name"], category["id"])
        self.category.setCurrentIndex(max(self.category.findData(selected), 0))
        self.category.blockSignals(False)

    def clear(self):
        self.use_from.setChecked(False)
        self.use_to.setChecked(False)
        self.search.clear()
        self.category.setCurrentIndex(0)
        self.amount_from.clear()
        self.amount_to.clear()

    @staticmethod
    def _amount(edit):
        """Zwraca (grosze albo None, czy tekst jest poprawny)."""
        text = edit.text().strip()
        if not text:
            return None, True
        try:
            cents = parse_money(text)
        except ValueError:
            return None, False
        return (cents, True) if cents >= 0 else (None, False)

    def state(self):
        """Zwraca (data od, data do, filtry, uwagi o błędnych wartościach)."""
        date_from = common.iso_date(self.date_from) if self.use_from.isChecked() else ""
        date_to = common.iso_date(self.date_to) if self.use_to.isChecked() else ""
        min_cents, min_valid = self._amount(self.amount_from)
        max_cents, max_valid = self._amount(self.amount_to)
        notes = []
        if not (min_valid and max_valid):
            notes.append("Niepoprawna kwota w filtrze została pominięta.")
        if date_from and date_to and date_from > date_to:
            notes.append("Data „Od” nie może być późniejsza niż „Do”.")
        filters = EntryFilters(
            self.search.text(), self.category.currentData(), min_cents, max_cents
        )
        return date_from, date_to, filters, notes


def summary_text(notes, filtered, summary, currency):
    parts = list(notes)
    if filtered:
        parts.append(
            f"Wybrane pozycje: przychody {format_money(summary['income'], currency)},"
            f" wydatki {format_money(summary['expense'], currency)}."
        )
    return " ".join(parts)


class DayTree(QTreeWidget):
    """Drzewo: dzień z sumami, a po rozwinięciu jego pozycje.

    Dwie ostatnie kolumny to sumy dnia. Dni są domyślnie rozwinięte, a przy odświeżaniu
    drzewo pamięta te zwinięte przez użytkownika oraz zaznaczenie. Przy aktywnych
    filtrach rozwija wszystkie dni, żeby wyniki były widoczne, a po ich wyczyszczeniu
    przywraca układ sprzed filtrowania.
    """

    def __init__(self, headers, stretch_columns, parent=None):
        super().__init__(parent)
        self.setHeaderLabels([*headers, "Przychody", "Wydatki"])
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        header = self.header()
        header.setStretchLastSection(False)
        for column in range(self.columnCount()):
            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.Stretch
                if column in stretch_columns
                else QHeaderView.ResizeMode.ResizeToContents,
            )
        self.scope = None
        self.collapsed_before_filtering = None

    def fill(self, scope, days, make_rows, currency, label, filtering):
        """Buduje listę; `make_rows(day)` zwraca wiersze pozycji danego dnia."""
        collapsed = {
            self.topLevelItem(index).data(0, KEY_ROLE)
            for index in range(self.topLevelItemCount())
            if not self.topLevelItem(index).isExpanded()
        }
        current = self.currentItem()
        selected = current.data(0, KEY_ROLE) if current else None
        if scope != self.scope:
            collapsed, selected = set(), None
            self.scope = scope
            self.collapsed_before_filtering = None
        if filtering and self.collapsed_before_filtering is None:
            self.collapsed_before_filtering = collapsed
        elif not filtering and self.collapsed_before_filtering is not None:
            collapsed = self.collapsed_before_filtering
            self.collapsed_before_filtering = None

        self.clear()
        for day in days:
            item = self._day_item(day, currency, label)
            item.addChildren(make_rows(day))
            self.addTopLevelItem(item)
            item.setExpanded(filtering or item.data(0, KEY_ROLE) not in collapsed)
            if item.data(0, KEY_ROLE) == selected:
                self.setCurrentItem(item)
            for index in range(item.childCount()):
                if item.child(index).data(0, KEY_ROLE) == selected:
                    self.setCurrentItem(item.child(index))

    def _day_item(self, day, currency, label):
        income_column, expense_column = self.columnCount() - 2, self.columnCount() - 1
        item = QTreeWidgetItem([day["date"], f"{label}: {len(day['entries'])}"])
        item.setData(0, KEY_ROLE, ("day", day["date"]))
        font = QFont(item.font(0))
        font.setBold(True)
        for column in range(self.columnCount()):
            item.setFont(column, font)
        if day["income"]:
            item.setText(income_column, f"+{format_money(day['income'], currency)}")
            item.setTextAlignment(income_column, RIGHT)
            item.setForeground(income_column, common.positive_color())
        if day["expense"]:
            item.setText(expense_column, f"−{format_money(day['expense'], currency)}")
            item.setTextAlignment(expense_column, RIGHT)
            item.setForeground(expense_column, common.negative_color())
        return item
