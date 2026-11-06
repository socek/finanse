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
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..money import format_money
from ..reports import build_report
from ..wallets import list_wallets
from . import common

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


class ReportsTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.currency = ""
        self.excluded = set()  # dzięki temu nowy portfel jest od razu w raporcie
        self.listed_wallets = None
        self.month = QDate.currentDate().toString("yyyy-MM")
        self.report = None

        self.currency_label = QLabel("Waluta")
        self.currency_combo = QComboBox()
        self.currency_combo.currentIndexChanged.connect(self._currency_changed)
        self.wallet_list = QListWidget()
        self.wallet_list.itemChanged.connect(self._wallet_toggled)
        self.select_all_button = QPushButton("Zaznacz wszystkie")
        self.select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_button = QPushButton("Odznacz wszystkie")
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

        self.previous_button = QPushButton("← Poprzedni")
        self.previous_button.clicked.connect(lambda: self.show_month(self.report["previous_month"]))
        self.month_edit = QDateEdit()
        self.month_edit.setDisplayFormat("yyyy-MM")
        self.month_edit.dateChanged.connect(self._month_edited)
        self.next_button = QPushButton("Następny →")
        self.next_button.clicked.connect(lambda: self.show_month(self.report["next_month"]))
        controls = QHBoxLayout()
        controls.addWidget(self.previous_button)
        controls.addWidget(self.month_edit)
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

        self.expenses_grid = QGridLayout()
        self.expenses_empty = QLabel("Brak wydatków w tym miesiącu.")
        self.incomes_title = _section_title("Przychody według kategorii")
        self.incomes_grid = QGridLayout()

        self.chart = TrendChart()
        self.chart.monthClicked.connect(self.show_month)
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
        body_layout.addWidget(_section_title("Wydatki według kategorii"))
        body_layout.addWidget(self.expenses_empty)
        body_layout.addLayout(self.expenses_grid)
        body_layout.addSpacing(12)
        body_layout.addWidget(self.incomes_title)
        body_layout.addLayout(self.incomes_grid)
        body_layout.addSpacing(12)
        body_layout.addWidget(_section_title("Ostatnie 12 miesięcy"))
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
            self.previous_button,
            self.month_edit,
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
        self.month = key
        self.refresh()

    def _month_edited(self, value):
        self.show_month(value.toString("yyyy-MM"))

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
        self.report = build_report(self.db, self.currency, wallet_ids, self.month)
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
        self.month = report["month_key"]
        self._fill_selection(report)
        self.month_edit.blockSignals(True)
        self.month_edit.setDate(QDate.fromString(self.month + "-01", "yyyy-MM-dd"))
        self.month_edit.blockSignals(False)

        currency = report["currency"]
        self.month_title.setText(report["month_title"])
        self._fill_wallet_totals(report)
        self.income_label.setText(format_money(report["income_total"], currency))
        self.expense_label.setText(format_money(report["expense_total"], currency))
        self.net_label.setText(format_money(report["net_total"], currency))

        self.expenses_empty.setVisible(not report["expenses"])
        self._fill_bars(self.expenses_grid, report["expenses"], common.expense_series(), currency)
        self.incomes_title.setVisible(bool(report["incomes"]))
        self._fill_bars(self.incomes_grid, report["incomes"], common.income_series(), currency)

        trend = report["trend"]
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

    @staticmethod
    def _fill_bars(grid, rows, color, currency):
        while grid.count():
            widget = grid.takeAt(0).widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
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
