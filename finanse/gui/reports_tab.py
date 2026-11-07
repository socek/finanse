"""Zakładka raportów: bilans miesiąca, kategorie i wykres z 12 miesięcy."""

from PySide6.QtCore import QDate, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..money import format_money
from ..reports import build_report
from ..wallets import list_wallets
from . import common, shortcuts

BAR_WIDTH = 12
BAR_GAP = 2
BAR_RADIUS = 4
AXIS_WIDTH = 64
LABEL_HEIGHT = 26
TOP_MARGIN = 10


def _top_rounded(rect):
    """Prostokąt zaokrąglony tylko u góry, oparty o linię bazową."""
    radius = min(BAR_RADIUS, rect.height(), rect.width() / 2)
    path = QPainterPath()
    path.moveTo(rect.left(), rect.bottom())
    path.lineTo(rect.left(), rect.top() + radius)
    path.quadTo(rect.left(), rect.top(), rect.left() + radius, rect.top())
    path.lineTo(rect.right() - radius, rect.top())
    path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + radius)
    path.lineTo(rect.right(), rect.bottom())
    path.closeSubpath()
    return path


class TrendChart(QWidget):
    """Przychody i wydatki z 12 miesięcy; kliknięcie wybiera miesiąc."""

    monthClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.trend = None
        self.hovered = None
        self.setMouseTracking(True)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_trend(self, trend):
        self.trend = trend
        self.hovered = None
        self.update()

    def _slot_width(self):
        return (self.width() - AXIS_WIDTH) / len(self.trend["months"])

    def _month_at(self, x):
        if not self.trend or x < AXIS_WIDTH:
            return None
        index = int((x - AXIS_WIDTH) / self._slot_width())
        return index if 0 <= index < len(self.trend["months"]) else None

    def mouseMoveEvent(self, event):
        index = self._month_at(event.position().x())
        if index != self.hovered:
            self.hovered = index
            self.update()
        if index is None:
            QToolTip.hideText()
        else:
            QToolTip.showText(
                event.globalPosition().toPoint(), self.trend["months"][index]["tip"], self
            )

    def leaveEvent(self, _event):
        self.hovered = None
        self.update()

    def mousePressEvent(self, event):
        index = self._month_at(event.position().x())
        if index is not None:
            self.monthClicked.emit(self.trend["months"][index]["key"])

    def paintEvent(self, _event):
        if not self.trend:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        text = palette.color(QPalette.ColorRole.WindowText)
        muted = QColor(text)
        muted.setAlpha(170)
        grid = QColor(text)
        grid.setAlpha(36)
        band = QColor(text)
        band.setAlpha(18)

        plot_bottom = self.height() - LABEL_HEIGHT
        plot_height = plot_bottom - TOP_MARGIN
        slot = self._slot_width()

        for index, month in enumerate(self.trend["months"]):
            if month["selected"] or index == self.hovered:
                painter.fillRect(
                    QRectF(AXIS_WIDTH + index * slot, TOP_MARGIN, slot, plot_height + LABEL_HEIGHT),
                    band,
                )

        for tick in self.trend["ticks"]:
            y = plot_bottom - plot_height * tick["pct"] / 100
            painter.setPen(grid)
            painter.drawLine(AXIS_WIDTH, round(y), self.width(), round(y))
            painter.setPen(muted)
            painter.drawText(
                QRectF(0, y - 10, AXIS_WIDTH - 8, 20),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                tick["label"],
            )

        income_color = common.income_series()
        expense_color = common.expense_series()
        bar_width = min(BAR_WIDTH, max(3.0, (slot - BAR_GAP - 6) / 2))
        painter.setPen(Qt.PenStyle.NoPen)
        for index, month in enumerate(self.trend["months"]):
            center = AXIS_WIDTH + (index + 0.5) * slot
            bars = (
                (month["income"], month["income_pct"], income_color, center - bar_width - BAR_GAP / 2),
                (month["expense"], month["expense_pct"], expense_color, center + BAR_GAP / 2),
            )
            for value, pct, color, left in bars:
                if value:
                    height = max(2.0, plot_height * pct / 100)
                    painter.setBrush(color)
                    painter.drawPath(
                        _top_rounded(QRectF(left, plot_bottom - height, bar_width, height))
                    )

        for index, month in enumerate(self.trend["months"]):
            font = QFont(self.font())
            font.setBold(month["selected"])
            painter.setFont(font)
            painter.setPen(text if month["selected"] else muted)
            painter.drawText(
                QRectF(AXIS_WIDTH + index * slot, plot_bottom, slot, LABEL_HEIGHT),
                Qt.AlignmentFlag.AlignCenter,
                month["short"],
            )
        painter.end()


class ShareBar(QWidget):
    """Pasek udziału kategorii, proporcjonalny do największej z nich."""

    def __init__(self, percent, color, parent=None):
        super().__init__(parent)
        self.percent = percent
        self.color = color
        self.setFixedHeight(16)
        self.setMinimumWidth(120)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        track = QColor(self.palette().color(QPalette.ColorRole.WindowText))
        track.setAlpha(24)
        rect = QRectF(0, 3, self.width(), 10)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, 4, 4)
        width = max(3.0, self.width() * self.percent / 100)
        painter.setBrush(self.color)
        painter.drawRoundedRect(QRectF(0, 3, width, 10), 4, 4)
        painter.end()


def _section_title(text):
    label = QLabel(text)
    font = QFont(label.font())
    font.setBold(True)
    font.setPointSizeF(font.pointSizeF() * 1.15)
    label.setFont(font)
    return label


def _color_swatch(swatch, color):
    swatch.setStyleSheet(f"background: {color.name()}; border-radius: 3px;")


def _swatch(color):
    swatch = QFrame()
    swatch.setFixedSize(12, 12)
    _color_swatch(swatch, color)
    return swatch


def _fit_height(table):
    """Tabela w przewijanym widoku nie potrzebuje własnego paska przewijania."""
    table.setFixedHeight(
        table.horizontalHeader().height()
        + sum(table.rowHeight(row) for row in range(table.rowCount()))
        + 4
    )


def _clear_grid(grid):
    while grid.count():
        widget = grid.takeAt(0).widget()
        if widget:
            widget.setParent(None)
            widget.deleteLater()


class ReportsTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.currency = ""
        self.excluded = set()  # dzięki temu nowy portfel jest od razu w raporcie
        self.listed_wallets = None
        today = QDate.currentDate()
        # Wybrany okres; pola pozostałych rodzajów pamiętają ostatnie wartości.
        self.period = {
            "period": "month",
            "month": today.toString("yyyy-MM"),
            "year": str(today.year()),
            "start": QDate(today.year(), today.month(), 1).toString(Qt.DateFormat.ISODate),
            "end": today.toString(Qt.DateFormat.ISODate),
        }
        self.report = None

        self.currency_label = QLabel("Waluta")
        self.currency_combo = QComboBox()
        self.currency_combo.currentIndexChanged.connect(self._currency_changed)
        self.wallet_list = QListWidget()
        self.wallet_list.itemChanged.connect(self._wallet_toggled)
        self.select_all_button = QPushButton("Zaznacz wszystkie")
        shortcuts.show_on(self.select_all_button, "check_all")
        self.select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_button = QPushButton("Odznacz wszystkie")
        shortcuts.show_on(self.select_none_button, "uncheck_all")
        self.select_none_button.clicked.connect(lambda: self._set_all_checked(False))
        side = QWidget()
        side.setFixedWidth(230)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.addWidget(_section_title("Portfele w raporcie"))
        side_layout.addWidget(self.currency_label)
        side_layout.addWidget(self.currency_combo)
        side_layout.addWidget(self.wallet_list, 1)
        side_layout.addWidget(self.select_all_button)
        side_layout.addWidget(self.select_none_button)

        self.period_combo = QComboBox()
        for key, name in (("month", "Miesiąc"), ("year", "Rok"), ("range", "Zakres dat")):
            self.period_combo.addItem(name, key)
        self.period_combo.currentIndexChanged.connect(self._period_kind_changed)
        self.previous_button = QPushButton("← Poprzedni")
        shortcuts.show_on(self.previous_button, "previous_month")
        self.previous_button.clicked.connect(lambda: self.show_period(self.report["previous"]))
        self.month_edit = QDateEdit()
        self.month_edit.setDisplayFormat("yyyy-MM")
        self.month_edit.dateChanged.connect(self._month_edited)
        self.year_edit = QSpinBox()
        self.year_edit.setRange(1900, 9999)
        self.year_edit.valueChanged.connect(lambda value: self.show_period({"year": str(value)}))
        self.range_start = common.date_edit()
        self.range_end = common.date_edit()
        for edit in (self.range_start, self.range_end):
            edit.dateChanged.connect(self._range_edited)
        range_widget = QWidget()
        range_layout = QHBoxLayout(range_widget)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.addWidget(QLabel("Od"))
        range_layout.addWidget(self.range_start)
        range_layout.addWidget(QLabel("Do"))
        range_layout.addWidget(self.range_end)
        self.period_inputs = QStackedWidget()
        self.period_inputs.addWidget(self.month_edit)
        self.period_inputs.addWidget(self.year_edit)
        self.period_inputs.addWidget(range_widget)
        self.period_inputs.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.next_button = QPushButton("Następny →")
        shortcuts.show_on(self.next_button, "next_month")
        self.next_button.clicked.connect(lambda: self.show_period(self.report["next"]))
        controls = QHBoxLayout()
        controls.addWidget(self.period_combo)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.period_inputs)
        controls.addWidget(self.next_button)
        controls.addStretch()

        self.no_wallets = QLabel("Dodaj portfel, aby zobaczyć raporty.")
        self.no_selection = QLabel("Zaznacz co najmniej jeden portfel.")

        self.month_title = _section_title("")
        self.selection_label = common.plain_label()
        self.selection_label.setWordWrap(True)
        self.income_label = QLabel()
        self.expense_label = QLabel()
        self.net_label = QLabel()
        stats = QHBoxLayout()
        for caption, value in (
            ("Przychody", self.income_label),
            ("Wydatki", self.expense_label),
            ("Bilans", self.net_label),
        ):
            font = QFont(value.font())
            font.setBold(True)
            font.setPointSizeF(font.pointSizeF() * 1.5)
            value.setFont(font)
            box = QVBoxLayout()
            box.addWidget(QLabel(caption))
            box.addWidget(value)
            stats.addLayout(box)
            stats.addSpacing(32)
        stats.addStretch()

        self.wallets_title = _section_title("Według portfeli")
        self.wallets_table = QTableWidget(0, 4)
        self.wallets_table.setHorizontalHeaderLabels(
            ["Portfel", "Przychody", "Wydatki", "Bilans"]
        )
        self.wallets_table.verticalHeader().hide()
        self.wallets_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.wallets_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        self.vat_title = _section_title("VAT")
        self.vat_table = QTableWidget(0, 5)
        self.vat_table.setHorizontalHeaderLabels(
            ["Stawka", "Sprzedaż netto", "VAT należny", "Zakupy netto", "VAT naliczony"]
        )
        self.vat_table.verticalHeader().hide()
        self.vat_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.vat_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.vat_balance = QLabel()

        self.budgets_grid = QGridLayout()
        self.budgets_empty = QLabel()
        self.budgets_hint = QLabel()
        self.budgets_hint.setWordWrap(True)

        self.tags_title = _section_title("Według tagów")
        self.tags_table = QTableWidget(0, 5)
        self.tags_table.setHorizontalHeaderLabels(
            ["Tag", "Transakcje", "Przychody", "Wydatki", "Bilans"]
        )
        self.tags_table.verticalHeader().hide()
        self.tags_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tags_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.expenses_grid = QGridLayout()
        self.expenses_empty = QLabel("Brak wydatków w tym okresie.")
        self.incomes_title = _section_title("Przychody według kategorii")
        self.incomes_grid = QGridLayout()

        self.chart = TrendChart()
        self.chart.monthClicked.connect(self._bar_clicked)
        self.trend_empty = QLabel("Brak transakcji w tym okresie.")
        legend = QHBoxLayout()
        self.income_swatch = _swatch(common.income_series())
        self.expense_swatch = _swatch(common.expense_series())
        self.legend_widgets = [
            self.income_swatch,
            QLabel("Przychody"),
            self.expense_swatch,
            QLabel("Wydatki"),
        ]
        for widget in self.legend_widgets:
            legend.addWidget(widget)
        legend.addStretch()
        self.table_button = QPushButton("Pokaż jako tabelę")
        self.table_button.setCheckable(True)
        self.table_button.toggled.connect(self._toggle_table)
        self.trend_table = QTableWidget(0, 3)
        self.trend_table.setHorizontalHeaderLabels(["Miesiąc", "Przychody", "Wydatki"])
        self.trend_table.verticalHeader().hide()
        self.trend_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.trend_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.trend_table.hide()

        hint = QLabel("Raporty nie uwzględniają przelewów między portfelami.")

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.addWidget(self.month_title)
        body_layout.addWidget(self.selection_label)
        body_layout.addLayout(stats)
        body_layout.addSpacing(12)
        body_layout.addWidget(self.wallets_title)
        body_layout.addWidget(self.wallets_table)
        body_layout.addSpacing(12)
        body_layout.addWidget(self.vat_title)
        body_layout.addWidget(self.vat_table)
        body_layout.addWidget(self.vat_balance)
        body_layout.addSpacing(12)
        body_layout.addWidget(_section_title("Budżety"))
        body_layout.addWidget(self.budgets_empty)
        body_layout.addLayout(self.budgets_grid)
        body_layout.addWidget(self.budgets_hint)
        body_layout.addSpacing(12)
        body_layout.addWidget(_section_title("Wydatki według kategorii"))
        body_layout.addWidget(self.expenses_empty)
        body_layout.addLayout(self.expenses_grid)
        body_layout.addSpacing(12)
        body_layout.addWidget(self.incomes_title)
        body_layout.addLayout(self.incomes_grid)
        body_layout.addSpacing(12)
        body_layout.addWidget(self.tags_title)
        body_layout.addWidget(self.tags_table)
        body_layout.addSpacing(12)
        self.trend_title = _section_title("")
        body_layout.addWidget(self.trend_title)
        body_layout.addWidget(self.trend_empty)
        body_layout.addLayout(legend)
        body_layout.addWidget(self.chart)
        table_row = QHBoxLayout()
        table_row.addWidget(self.table_button)
        table_row.addStretch()
        body_layout.addLayout(table_row)
        body_layout.addWidget(self.trend_table)
        body_layout.addWidget(hint)
        body_layout.addStretch()

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(body)

        main = QVBoxLayout()
        main.addLayout(controls)
        main.addWidget(self.no_wallets)
        main.addWidget(self.no_selection)
        main.addWidget(self.scroll, 1)
        layout = QHBoxLayout(self)
        layout.addWidget(side)
        layout.addLayout(main, 1)
        self.controls = (
            self.currency_combo,
            self.wallet_list,
            self.select_all_button,
            self.select_none_button,
            self.period_combo,
            self.previous_button,
            self.period_inputs,
            self.next_button,
        )
        self.refresh()

    def previous_month(self):
        self.previous_button.click()

    def next_month(self):
        self.next_button.click()

    def check_all(self):
        self.select_all_button.click()

    def uncheck_all(self):
        self.select_none_button.click()

    def show_month(self, key):
        self.show_period({"period": "month", "month": key})

    def show_period(self, changes):
        """Zmienia okres raportu; pominięte pola zostają, np. rok przy zmianie miesiąca."""
        self.period = {**self.period, **changes}
        self.refresh()

    def _period_kind_changed(self):
        kind = self.period_combo.currentData()
        if kind != self.period["period"]:
            self.show_period({"period": kind})

    def _month_edited(self, value):
        self.show_month(value.toString("yyyy-MM"))

    def _range_edited(self):
        self.show_period(
            {
                "start": common.iso_date(self.range_start),
                "end": common.iso_date(self.range_end),
            }
        )

    def _bar_clicked(self, key):
        """Słupek roku otwiera raport roczny, a słupek miesiąca miesięczny."""
        if len(key) == 4:
            self.show_period({"period": "year", "year": key})
        else:
            self.show_month(key)

    def _currency_changed(self):
        self.currency = self.currency_combo.currentData() or ""
        self.refresh()

    def _wallet_toggled(self, item):
        wallet_id = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self.excluded.discard(wallet_id)
        else:
            self.excluded.add(wallet_id)
        self.refresh()

    def _set_all_checked(self, checked):
        ids = {
            self.wallet_list.item(row).data(Qt.ItemDataRole.UserRole)
            for row in range(self.wallet_list.count())
        }
        self.excluded = self.excluded - ids if checked else self.excluded | ids
        self.refresh()

    def _toggle_table(self, checked):
        self.trend_table.setVisible(checked)
        self.table_button.setText("Ukryj tabelę" if checked else "Pokaż jako tabelę")

    def refresh(self):
        _color_swatch(self.income_swatch, common.income_series())
        _color_swatch(self.expense_swatch, common.expense_series())
        wallet_ids = {
            wallet["id"]
            for wallet in list_wallets(self.db)
            if wallet["id"] not in self.excluded
        }
        self.report = build_report(
            self.db,
            self.currency,
            wallet_ids,
            self.period["month"],
            self.period["period"],
            self.period["year"],
            self.period["start"],
            self.period["end"],
        )
        has_report = self.report is not None
        self.no_wallets.setVisible(not has_report)
        self.no_selection.setVisible(has_report and not self.report["selected_ids"])
        self.scroll.setVisible(has_report and bool(self.report["selected_ids"]))
        for control in self.controls:
            control.setEnabled(has_report)
        if not has_report:
            return

        report = self.report
        self.currency = report["currency"]
        self._remember_period(report)
        self._fill_selection(report)
        self._fill_period_inputs()

        currency = report["currency"]
        self.month_title.setText(report["title"])
        self._fill_wallet_totals(report)
        self._fill_vat(report)
        self.income_label.setText(format_money(report["income_total"], currency))
        self.expense_label.setText(format_money(report["expense_total"], currency))
        self.net_label.setText(format_money(report["net_total"], currency))

        self._fill_budgets(report)
        self._fill_tags(report)
        self.expenses_empty.setVisible(not report["expenses"])
        self._fill_bars(self.expenses_grid, report["expenses"], common.expense_series(), currency)
        self.incomes_title.setVisible(bool(report["incomes"]))
        self._fill_bars(self.incomes_grid, report["incomes"], common.income_series(), currency)

        trend = report["trend"]
        self.trend_title.setText(trend["title"])
        self.trend_table.horizontalHeaderItem(0).setText(
            "Rok" if trend["months"] and len(trend["months"][0]["key"]) == 4 else "Miesiąc"
        )
        has_data = trend["has_data"]
        self.trend_empty.setVisible(not has_data)
        self.chart.setVisible(has_data)
        self.chart.set_trend(trend)
        for widget in self.legend_widgets:
            widget.setVisible(has_data)
        self.table_button.setVisible(has_data)
        self.trend_table.setVisible(has_data and self.table_button.isChecked())
        self.trend_table.setRowCount(len(trend["months"]))
        for row, month in enumerate(trend["months"]):
            cells = (
                month["title"],
                format_money(month["income"], currency),
                format_money(month["expense"], currency),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.trend_table.setItem(row, column, item)
        _fit_height(self.trend_table)

    def _remember_period(self, report):
        """Okres po poprawkach, np. zamienione końce zakresu albo niepoprawny rok."""
        kind = report["period"]
        self.period["period"] = kind
        if kind == "month":
            self.period["month"] = report["month_key"]
        elif kind == "year":
            self.period["year"] = report["year"]
        else:
            self.period["start"], self.period["end"] = report["start"], report["end"]

    def _fill_period_inputs(self):
        period = self.period
        widgets = (
            self.period_combo, self.month_edit, self.year_edit, self.range_start, self.range_end,
        )  # fmt: skip
        for widget in widgets:
            widget.blockSignals(True)
        self.period_combo.setCurrentIndex(self.period_combo.findData(period["period"]))
        self.period_inputs.setCurrentIndex(("month", "year", "range").index(period["period"]))
        self.month_edit.setDate(QDate.fromString(period["month"] + "-01", "yyyy-MM-dd"))
        self.year_edit.setValue(int(period["year"]))
        self.range_start.setDate(QDate.fromString(period["start"], Qt.DateFormat.ISODate))
        self.range_end.setDate(QDate.fromString(period["end"], Qt.DateFormat.ISODate))
        for widget in widgets:
            widget.blockSignals(False)

    def _fill_selection(self, report):
        self.currency_combo.blockSignals(True)
        self.currency_combo.clear()
        for code in report["currencies"]:
            self.currency_combo.addItem(code, code)
        self.currency_combo.setCurrentIndex(
            max(self.currency_combo.findData(report["currency"]), 0)
        )
        self.currency_combo.blockSignals(False)
        several = len(report["currencies"]) > 1
        self.currency_label.setVisible(several)
        self.currency_combo.setVisible(several)

        wallets = [w for w in report["wallets"] if w["currency"] == report["currency"]]
        listed = [(wallet["id"], wallet["name"]) for wallet in wallets]
        self.wallet_list.blockSignals(True)
        # Przebudowa tylko po zmianie listy: odświeżenie bywa wywołane z sygnału
        # elementu listy, którego nie wolno wtedy usuwać.
        if listed != self.listed_wallets:
            self.listed_wallets = listed
            self.wallet_list.clear()
            for wallet_id, name in listed:
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, wallet_id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                self.wallet_list.addItem(item)
        for row in range(self.wallet_list.count()):
            item = self.wallet_list.item(row)
            included = item.data(Qt.ItemDataRole.UserRole) in report["selected_ids"]
            item.setCheckState(
                Qt.CheckState.Checked if included else Qt.CheckState.Unchecked
            )
        self.wallet_list.blockSignals(False)

        names = [row["name"] for row in report["wallet_totals"]]
        if len(names) == len(wallets) and len(names) > 1:
            self.selection_label.setText(f"Wszystkie portfele w {report['currency']}")
        else:
            self.selection_label.setText(", ".join(names))

    def _fill_vat(self, report):
        """Sekcja widoczna tylko przy wybranym portfelu z VAT."""
        vat = report["vat"]
        for widget in (self.vat_title, self.vat_table, self.vat_balance):
            widget.setVisible(vat is not None)
        if vat is None:
            return
        currency = report["currency"]
        rows = [*vat["by_rate"], {"label": "Razem", **vat}]
        self.vat_table.setRowCount(len(rows))
        for row, data in enumerate(rows):
            cells = (
                data["label"],
                format_money(data["sales_net"], currency),
                format_money(data["sales_vat"], currency),
                format_money(data["purchases_net"], currency),
                format_money(data["purchases_vat"], currency),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                if data is rows[-1]:
                    font = QFont(item.font())
                    font.setBold(True)
                    item.setFont(font)
                self.vat_table.setItem(row, column, item)
        _fit_height(self.vat_table)
        balance = vat["balance"]
        if balance >= 0:
            self.vat_balance.setText(f"VAT do zapłaty: {format_money(balance, currency)}")
        else:
            self.vat_balance.setText(f"Nadwyżka VAT naliczonego: {format_money(-balance, currency)}")

    def _fill_wallet_totals(self, report):
        """Rozbicie ma sens dopiero przy co najmniej dwóch portfelach."""
        totals = report["wallet_totals"]
        several = len(totals) > 1
        self.wallets_title.setVisible(several)
        self.wallets_table.setVisible(several)
        self.wallets_table.setRowCount(len(totals))
        currency = report["currency"]
        for row, wallet in enumerate(totals):
            cells = (
                wallet["name"],
                format_money(wallet["income"], currency),
                format_money(wallet["expense"], currency),
                format_money(wallet["net"], currency),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.wallets_table.setItem(row, column, item)
        _fit_height(self.wallets_table)

    def _fill_tags(self, report):
        """Sekcja widoczna tylko wtedy, gdy w okresie są otagowane transakcje."""
        tags = report["tags"]
        self.tags_title.setVisible(bool(tags))
        self.tags_table.setVisible(bool(tags))
        currency = report["currency"]
        self.tags_table.setRowCount(len(tags))
        for row, tag in enumerate(tags):
            cells = (
                tag["name"],
                str(tag["transactions"]),
                format_money(tag["income"], currency),
                format_money(tag["expense"], currency),
                format_money(tag["net"], currency),
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.tags_table.setItem(row, column, item)
        _fit_height(self.tags_table)

    def _fill_budgets(self, report):
        currency = report["currency"]
        budgets = report["budgets"]
        _clear_grid(self.budgets_grid)
        self.budgets_empty.setVisible(not budgets)
        self.budgets_empty.setText(f"Nie masz budżetów w {currency}.")
        hint = (
            "Budżety obejmują wydatki z portfeli wybranych w raporcie."
            " Ustawisz je w zakładce Kategorie."
        )
        if report["period"] != "month":
            months = f"{report['budget_months']:.2f}".rstrip("0").rstrip(".").replace(".", ",")
            hint += (
                f" Miesięczne limity są przeliczone na okres ({months} mies.),"
                " a niepełne miesiące liczą się według dni."
            )
        self.budgets_hint.setText(hint)
        self.budgets_grid.setColumnMinimumWidth(0, 140)
        self.budgets_grid.setColumnStretch(1, 1)
        self.budgets_grid.setColumnMinimumWidth(2, 190)
        for index, budget in enumerate(budgets):
            if budget["over"]:
                color = common.overdue_background()
                status = f"przekroczono o {format_money(-budget['left'], currency)}"
            else:
                color = (
                    common.warning_background()
                    if budget["nearly"]
                    else common.positive_color()
                )
                status = f"zostało {format_money(budget['left'], currency)}"
            usage = QLabel(
                f"{format_money(budget['spent'], currency)} z "
                f"{format_money(budget['limit'], currency)}  ({budget['percent']}%)"
            )
            usage.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            state = QLabel(status)
            if budget["over"]:
                font = QFont(state.font())
                font.setBold(True)
                state.setFont(font)
                state.setStyleSheet(
                    f"background: {common.overdue_background().name()};"
                    f" color: {common.overdue_text().name()};"
                    " padding: 1px 4px; border-radius: 3px;"
                )
            bar = ShareBar(min(budget["percent"], 100), color)
            bar.setToolTip(f"{budget['name']} · {usage.text()} · {status}")
            self.budgets_grid.addWidget(
                common.plain_label(budget["name"]), index, 0, Qt.AlignmentFlag.AlignLeft
            )
            self.budgets_grid.addWidget(bar, index, 1)
            self.budgets_grid.addWidget(usage, index, 2)
            self.budgets_grid.addWidget(state, index, 3, Qt.AlignmentFlag.AlignLeft)

    @staticmethod
    def _fill_bars(grid, rows, color, currency):
        _clear_grid(grid)
        # Stałe szerokości wyrównują paski wydatków i przychodów względem siebie.
        grid.setColumnMinimumWidth(0, 140)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(2, 190)
        for index, row in enumerate(rows):
            value = QLabel(f"{format_money(row['total'], currency)}  ({row['share']})")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            name = common.plain_label(row["name"])
            if row["name"] == common.NO_CATEGORY_NAME:
                common.mark_no_category_label(name)
            grid.addWidget(name, index, 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(ShareBar(row["bar_pct"], color), index, 1)
            grid.addWidget(value, index, 2)
