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


def _swatch(color):
    swatch = QFrame()
    swatch.setFixedSize(12, 12)
    swatch.setStyleSheet(f"background: {color.name()}; border-radius: 3px;")
    return swatch


class ReportsTab(QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.scope = ""
        self.month = QDate.currentDate().toString("yyyy-MM")
        self.report = None

        self.scope_combo = QComboBox()
        self.scope_combo.setMinimumWidth(220)
        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        self.previous_button = QPushButton("← Poprzedni")
        self.previous_button.clicked.connect(lambda: self.show_month(self.report["previous_month"]))
        self.month_edit = QDateEdit()
        self.month_edit.setDisplayFormat("yyyy-MM")
        self.month_edit.dateChanged.connect(self._month_edited)
        self.next_button = QPushButton("Następny →")
        self.next_button.clicked.connect(lambda: self.show_month(self.report["next_month"]))
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Zakres"))
        controls.addWidget(self.scope_combo)
        controls.addSpacing(16)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.month_edit)
        controls.addWidget(self.next_button)
        controls.addStretch()

        self.no_wallets = QLabel("Dodaj portfel, aby zobaczyć raporty.")

        self.month_title = _section_title("")
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

        self.expenses_grid = QGridLayout()
        self.expenses_empty = QLabel("Brak wydatków w tym miesiącu.")
        self.incomes_title = _section_title("Przychody według kategorii")
        self.incomes_grid = QGridLayout()

        self.chart = TrendChart()
        self.chart.monthClicked.connect(self.show_month)
        self.trend_empty = QLabel("Brak transakcji w tym okresie.")
        legend = QHBoxLayout()
        self.legend_widgets = [
            _swatch(common.income_series()),
            QLabel("Przychody"),
            _swatch(common.expense_series()),
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
        body_layout.addLayout(stats)
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

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.no_wallets)
        layout.addWidget(self.scroll, 1)
        self.controls = (
            self.scope_combo,
            self.previous_button,
            self.month_edit,
            self.next_button,
        )
        self.refresh()

    def show_month(self, key):
        self.month = key
        self.refresh()

    def _month_edited(self, value):
        self.show_month(value.toString("yyyy-MM"))

    def _scope_changed(self):
        self.scope = self.scope_combo.currentData() or ""
        self.refresh()

    def _toggle_table(self, checked):
        self.trend_table.setVisible(checked)
        self.table_button.setText("Ukryj tabelę" if checked else "Pokaż jako tabelę")

    def refresh(self):
        self.report = build_report(self.db, self.scope, self.month)
        has_report = self.report is not None
        self.no_wallets.setVisible(not has_report)
        self.scroll.setVisible(has_report)
        for control in self.controls:
            control.setEnabled(has_report)
        if not has_report:
            return

        report = self.report
        self.scope = report["scope"]
        self.month = report["month_key"]
        self._fill_scope(report)
        self.month_edit.blockSignals(True)
        self.month_edit.setDate(QDate.fromString(self.month + "-01", "yyyy-MM-dd"))
        self.month_edit.blockSignals(False)

        currency = report["currency"]
        self.month_title.setText(report["month_title"])
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
        self.trend_table.setFixedHeight(
            self.trend_table.horizontalHeader().height()
            + sum(self.trend_table.rowHeight(row) for row in range(self.trend_table.rowCount()))
            + 4
        )

    def _fill_scope(self, report):
        self.scope_combo.blockSignals(True)
        self.scope_combo.clear()
        for code in report["currencies"]:
            self.scope_combo.addItem(f"Wszystkie w {code}", f"currency:{code}")
        for wallet in report["wallets"]:
            self.scope_combo.addItem(wallet["name"], f"wallet:{wallet['id']}")
        self.scope_combo.setCurrentIndex(max(self.scope_combo.findData(report["scope"]), 0))
        self.scope_combo.blockSignals(False)

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
            grid.addWidget(common.plain_label(row["name"]), index, 0)
            grid.addWidget(ShareBar(row["bar_pct"], color), index, 1)
            grid.addWidget(value, index, 2)
