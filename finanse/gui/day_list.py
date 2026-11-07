"""Części wspólne list według dni: filtry oraz drzewo dni z pozycjami."""

from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..categories import list_categories
from ..money import format_totals, parse_money
from ..wallets import NO_CATEGORY, EntryFilters, last_transaction_date
from . import common, shortcuts

KEY_ROLE = Qt.ItemDataRole.UserRole
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
FLASH_DURATION_MS = 2000
FLASH_INTERVAL_MS = 250


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
        shortcuts.show_on(clear, "clear_filters")
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
        common.color_no_category_item(self.category)
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


def summary_text(notes, filtered, summary):
    parts = list(notes)
    if filtered:
        income = format_totals(summary["income"]) or "0,00"
        expense = format_totals(summary["expense"]) or "0,00"
        parts.append(f"Wybrane pozycje: przychody {income}, wydatki {expense}.")
    return " ".join(parts)


class WalletList(QListWidget):
    """Lista portfeli do zaznaczania. Nowy portfel jest od razu zaznaczony."""

    checked_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.excluded = set()
        self.itemChanged.connect(self._item_changed)

    def fill(self, wallets, label, select=None):
        """Przebudowuje listę; `label(wallet)` daje tekst pozycji."""
        select = select if select is not None else self.current_id()
        self.blockSignals(True)
        self.clear()
        current = None
        for wallet in wallets:
            item = QListWidgetItem(label(wallet))
            item.setData(KEY_ROLE, wallet["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Unchecked
                if wallet["id"] in self.excluded
                else Qt.CheckState.Checked
            )
            self.addItem(item)
            if wallet["id"] == select or current is None:
                current = item
        if current:
            self.setCurrentItem(current)
        self.blockSignals(False)

    def set_labels(self, wallets, label):
        """Zmienia same teksty, bez przebudowy listy i bez sygnału zaznaczenia."""
        labels = {wallet["id"]: label(wallet) for wallet in wallets}
        self.blockSignals(True)
        for row in range(self.count()):
            item = self.item(row)
            item.setText(labels.get(item.data(KEY_ROLE), item.text()))
        self.blockSignals(False)

    def current_id(self):
        item = self.currentItem()
        return item.data(KEY_ROLE) if item else None

    def checked_ids(self):
        return {
            self.item(row).data(KEY_ROLE)
            for row in range(self.count())
            if self.item(row).checkState() == Qt.CheckState.Checked
        }

    def set_all_checked(self, checked):
        self.blockSignals(True)
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.count()):
            item = self.item(row)
            item.setCheckState(state)
            if checked:
                self.excluded.discard(item.data(KEY_ROLE))
            else:
                self.excluded.add(item.data(KEY_ROLE))
        self.blockSignals(False)
        self.checked_changed.emit()

    def _item_changed(self, item):
        if item.checkState() == Qt.CheckState.Checked:
            self.excluded.discard(item.data(KEY_ROLE))
        else:
            self.excluded.add(item.data(KEY_ROLE))
        self.checked_changed.emit()


def wallet_panel(wallet_list, *extra_widgets):
    """Lewy panel: lista portfeli i przyciski zaznaczania."""
    select_all = QPushButton("Zaznacz wszystkie")
    shortcuts.show_on(select_all, "check_all")
    select_all.clicked.connect(lambda: wallet_list.set_all_checked(True))
    select_none = QPushButton("Odznacz wszystkie")
    shortcuts.show_on(select_none, "uncheck_all")
    select_none.clicked.connect(lambda: wallet_list.set_all_checked(False))
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(wallet_list)
    layout.addWidget(select_all)
    layout.addWidget(select_none)
    for widget in extra_widgets:
        layout.addWidget(widget)
    return panel


def selection_title(wallets, checked):
    """Nagłówek listy zależny od liczby zaznaczonych portfeli."""
    if not wallets:
        return "Dodaj pierwszy portfel"
    selected = [wallet for wallet in wallets if wallet["id"] in checked]
    if not selected:
        return "Nie wybrano portfela"
    if len(selected) == 1:
        return selected[0]["name"]
    return f"Wybrane portfele: {len(selected)}"


def title_row(title, last_transaction):
    """Nagłówek listy, a na prawo od niego data ostatniej transakcji."""
    row = QHBoxLayout()
    row.addWidget(title, 0, Qt.AlignmentFlag.AlignBaseline)
    row.addSpacing(16)
    row.addWidget(last_transaction, 0, Qt.AlignmentFlag.AlignBaseline)
    row.addStretch()
    return row


def last_transaction_text(db, wallet_ids):
    if not wallet_ids:
        return ""
    date = last_transaction_date(db, wallet_ids)
    return f"Najnowsza transakcja: {date}" if date else "Brak transakcji"


class _FlashDelegate(QStyledItemDelegate):
    """Maluje migający wiersz, nie zmieniając kolorów zapisanych w elementach drzewa."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        tree = self.parent()
        key = index.siblingAtColumn(0).data(KEY_ROLE)
        if tree.flash_visible and key is not None and tree.flash_match(key):
            palette = tree.palette()
            option.backgroundBrush = palette.brush(QPalette.ColorRole.Highlight)
            option.palette.setBrush(
                QPalette.ColorRole.Text, palette.brush(QPalette.ColorRole.HighlightedText)
            )


class DayTree(QTreeWidget):
    """Drzewo: dzień z sumami, a po rozwinięciu jego pozycje.

    Dwie ostatnie kolumny to sumy dnia. Dni są domyślnie rozwinięte, a przy odświeżaniu
    drzewo pamięta te zwinięte przez użytkownika oraz zaznaczenie. Przy aktywnych
    filtrach rozwija wszystkie dni, żeby wyniki były widoczne, a po ich wyczyszczeniu
    przywraca układ sprzed filtrowania.
    """

    def __init__(self, headers, stretch_columns, extra_headers=(), parent=None):
        """Dodatkowe kolumny, np. VAT, są za sumami, ale widać je przed ostatnią z `headers`."""
        super().__init__(parent)
        self.income_column = len(headers)
        self.expense_column = len(headers) + 1
        self.setHeaderLabels([*headers, "Przychody", "Wydatki", *extra_headers])
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
        for offset in range(len(extra_headers)):
            header.moveSection(self.expense_column + 1 + offset, len(headers) - 1 + offset)
        self.scope = None
        self.collapsed_before_filtering = None
        self.flash_match = lambda _key: False
        self.flash_visible = False
        self.flash_ticks_left = 0
        self.flash_timer = QTimer(self)
        self.flash_timer.timeout.connect(self._flash_tick)
        self.setItemDelegate(_FlashDelegate(self))

    def drawBranches(self, painter, rect, index):
        """Pole wcięcia należy do wiersza, więc dostaje jego tło."""
        key = index.siblingAtColumn(0).data(KEY_ROLE)
        if self.flash_visible and key is not None and self.flash_match(key):
            painter.fillRect(rect, self.palette().brush(QPalette.ColorRole.Highlight))
        else:
            background = index.siblingAtColumn(0).data(Qt.ItemDataRole.BackgroundRole)
            if background is not None:
                painter.fillRect(rect, background)
        super().drawBranches(painter, rect, index)

    def flash(self, match, duration=FLASH_DURATION_MS, interval=FLASH_INTERVAL_MS):
        """Miga wierszami o pasującym kluczu i pokazuje pierwszy z nich.

        Sprawdzany jest klucz, a nie element, bo odświeżenie listy tworzy elementy na nowo.
        Wiersz ukryty przez filtry nie miga.
        """
        for day_index in range(self.topLevelItemCount()):
            day = self.topLevelItem(day_index)
            for index in range(day.childCount()):
                if match(day.child(index).data(0, KEY_ROLE)):
                    day.setExpanded(True)
                    self.scrollToItem(day.child(index))
                    self.flash_match = match
                    self.flash_visible = True
                    self.flash_ticks_left = max(duration // interval - 1, 0)
                    self.flash_timer.start(interval)
                    self.viewport().update()
                    return

    def _flash_tick(self):
        if self.flash_ticks_left <= 0:
            self.flash_timer.stop()
            self.flash_visible = False
        else:
            self.flash_ticks_left -= 1
            self.flash_visible = not self.flash_visible
        self.viewport().update()

    def fill(self, scope, days, make_rows, label, filtering):
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
            item = self._day_item(day, label)
            item.addChildren(make_rows(day))
            self.addTopLevelItem(item)
            item.setExpanded(filtering or item.data(0, KEY_ROLE) not in collapsed)
            if item.data(0, KEY_ROLE) == selected:
                self.setCurrentItem(item)
            for index in range(item.childCount()):
                if item.child(index).data(0, KEY_ROLE) == selected:
                    self.setCurrentItem(item.child(index))

    def _day_item(self, day, label):
        income_column, expense_column = self.income_column, self.expense_column
        item = QTreeWidgetItem([day["date"], f"{label}: {len(day['entries'])}"])
        item.setData(0, KEY_ROLE, ("day", day["date"]))
        font = QFont(item.font(0))
        font.setBold(True)
        for column in range(self.columnCount()):
            item.setFont(column, font)
        if day["income"]:
            item.setText(income_column, format_totals(day["income"], "+"))
            item.setTextAlignment(income_column, RIGHT)
            item.setForeground(income_column, common.positive_color())
        if day["expense"]:
            item.setText(expense_column, format_totals(day["expense"], "−"))
            item.setTextAlignment(expense_column, RIGHT)
            item.setForeground(expense_column, common.negative_color())
        return item
