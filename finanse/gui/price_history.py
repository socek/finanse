"""Okno historii ceny produktu: podsumowanie, wykres ceny, sklepy i lista zakupów."""

from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from ..money import format_money, format_quantity, to_cents
from ..price_history import price_history
from ..reports import axis_scale
from . import common

AXIS_WIDTH = 72
LABEL_HEIGHT = 24
TOP_MARGIN = 10
SIDE_MARGIN = 12
MARKER = 8
HIT_RADIUS = 12
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter


def _price(value_e5, currency=""):
    return format_money(to_cents(value_e5), currency)


def _change_text(percent):
    if percent is None:
        return "–"
    if abs(percent) < 0.05:
        return "bez zmian"
    sign = "+" if percent > 0 else "−"
    return f"{sign}{abs(percent):.1f}%".replace(".", ",")


class PriceChart(QWidget):
    """Cena jednostkowa w czasie; oś X zachowuje odstępy między datami zakupów."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.currency = ""
        self.hovered = None
        self.setMouseTracking(True)
        self.setMinimumHeight(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_entries(self, entries, currency):
        self.entries = entries
        self.currency = currency
        self.hovered = None
        self.update()

    def _scale(self):
        largest = max(to_cents(entry["unit_price_e5"]) for entry in self.entries)
        return axis_scale(largest)

    def _points(self):
        step, axis_max = self._scale()
        days = [date.fromisoformat(entry["occurred_on"]).toordinal() for entry in self.entries]
        first, span = days[0], max(days[-1] - days[0], 1)
        left, right = AXIS_WIDTH + SIDE_MARGIN, self.width() - SIDE_MARGIN
        bottom = self.height() - LABEL_HEIGHT
        height = bottom - TOP_MARGIN
        single_day = days[0] == days[-1]
        points = []
        for index, (day, entry) in enumerate(zip(days, self.entries)):
            if single_day:
                # Zakupy z jednego dnia rozkładają się równo, żeby się nie nakładały.
                x = left + (right - left) * (index + 0.5) / len(self.entries)
            else:
                x = left + (right - left) * (day - first) / span
            y = bottom - height * to_cents(entry["unit_price_e5"]) / (axis_max * 100)
            points.append(QPointF(x, y))
        return points

    def _nearest(self, position):
        best, best_distance = None, HIT_RADIUS
        for index, point in enumerate(self._points()):
            distance = abs(point.x() - position.x())
            if distance <= best_distance:
                best, best_distance = index, distance
        return best

    def mouseMoveEvent(self, event):
        if not self.entries:
            return
        index = self._nearest(event.position())
        if index != self.hovered:
            self.hovered = index
            self.update()
        if index is None:
            QToolTip.hideText()
            return
        entry = self.entries[index]
        QToolTip.showText(
            event.globalPosition().toPoint(),
            f"{entry['occurred_on']} · {entry['shop']}\n"
            f"Cena: {_price(entry['unit_price_e5'], self.currency)}"
            f" · ilość: {format_quantity(entry['quantity_e5'])}",
            self,
        )

    def leaveEvent(self, _event):
        self.hovered = None
        self.update()

    def paintEvent(self, _event):
        if not self.entries:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = self.palette().color(QPalette.ColorRole.WindowText)
        muted = QColor(text)
        muted.setAlpha(170)
        grid = QColor(text)
        grid.setAlpha(36)
        bottom = self.height() - LABEL_HEIGHT
        height = bottom - TOP_MARGIN

        step, axis_max = self._scale()
        for value in range(0, axis_max + 1, step):
            y = bottom - height * value / axis_max
            painter.setPen(grid)
            painter.drawLine(AXIS_WIDTH, round(y), self.width(), round(y))
            painter.setPen(muted)
            painter.drawText(
                QRectF(0, y - 10, AXIS_WIDTH - 8, 20),
                RIGHT,
                format_money(value * 100),
            )

        points = self._points()
        color = common.expense_series()
        if len(points) > 1:
            path = QPainterPath(points[0])
            for point in points[1:]:
                path.lineTo(point)
            painter.setPen(QPen(color, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

        surface = self.palette().color(QPalette.ColorRole.Window)
        for index, point in enumerate(points):
            size = MARKER + (4 if index == self.hovered else 0)
            # Obwódka w kolorze tła oddziela punkt od linii.
            painter.setPen(QPen(surface, 2))
            painter.setBrush(color)
            painter.drawEllipse(point, size / 2, size / 2)

        painter.setPen(muted)
        for index in sorted({0, len(points) - 1}):
            label = self.entries[index]["occurred_on"]
            align = Qt.AlignmentFlag.AlignLeft if index == 0 else Qt.AlignmentFlag.AlignRight
            x = points[index].x()
            rect = QRectF(x - 4, bottom + 4, 120, LABEL_HEIGHT - 4)
            if index:
                rect = QRectF(x - 116, bottom + 4, 120, LABEL_HEIGHT - 4)
            painter.drawText(rect, align | Qt.AlignmentFlag.AlignTop, label)
        painter.end()


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


def _fill(table, rows, right_columns):
    table.setRowCount(len(rows))
    for row, cells in enumerate(rows):
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            if column in right_columns:
                item.setTextAlignment(RIGHT)
            table.setItem(row, column, item)


def _bold(label):
    font = QFont(label.font())
    font.setBold(True)
    label.setFont(font)
    return label


class PriceHistoryDialog(QDialog):
    def __init__(self, db, name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Historia ceny: {name}")
        self.histories = price_history(db, name)

        self.currency = QComboBox()
        for history in self.histories:
            self.currency.addItem(history["currency"])
        self.currency.currentIndexChanged.connect(self._show)
        currency_row = QHBoxLayout()
        self.currency_label = QLabel("Waluta")
        currency_row.addWidget(self.currency_label)
        currency_row.addWidget(self.currency)
        currency_row.addStretch()
        several = len(self.histories) > 1
        self.currency_label.setVisible(several)
        self.currency.setVisible(several)

        self.empty = QLabel("Ten produkt nie występuje w żadnym wydatku.")
        self.stats = {}
        stats = QGridLayout()
        for column, (key, caption) in enumerate(
            (
                ("last", "Ostatnia cena"),
                ("cheapest", "Najniższa"),
                ("dearest", "Najwyższa"),
                ("average", "Średnia zapłacona"),
                ("change", "Zmiana od pierwszego zakupu"),
            )
        ):
            value = _bold(QLabel())
            detail = common.plain_label()
            detail.setWordWrap(True)
            stats.addWidget(QLabel(caption), 0, column)
            stats.addWidget(value, 1, column)
            stats.addWidget(detail, 2, column, Qt.AlignmentFlag.AlignTop)
            self.stats[key] = (value, detail)

        self.chart_title = _bold(QLabel("Cena za jednostkę"))
        self.chart = PriceChart()
        self.shops = _table(["Sklep (opis transakcji)", "Zakupy", "Najniższa", "Średnia", "Ostatnia"], 0)
        self.purchases = _table(["Data", "Sklep (opis transakcji)", "Portfel", "Ilość", "Cena", "Wartość"], 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Zamknij")
        buttons.rejected.connect(self.reject)

        self.content = QWidget()
        content = QVBoxLayout(self.content)
        content.setContentsMargins(0, 0, 0, 0)
        content.addLayout(currency_row)
        content.addLayout(stats)
        content.addSpacing(8)
        content.addWidget(self.chart_title)
        content.addWidget(self.chart)
        content.addWidget(_bold(QLabel("Według sklepów, od najtańszego")))
        content.addWidget(self.shops)
        content.addWidget(_bold(QLabel("Zakupy, od najnowszych")))
        content.addWidget(self.purchases, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.empty)
        layout.addWidget(self.content, 1)
        layout.addWidget(buttons)
        self.empty.setVisible(not self.histories)
        self.content.setVisible(bool(self.histories))
        self.resize(900, 760)
        self._show()

    def history(self):
        return self.histories[self.currency.currentIndex()] if self.histories else None

    def _show(self):
        history = self.history()
        if history is None:
            return
        currency = history["currency"]

        def set_stat(key, value, detail=""):
            self.stats[key][0].setText(value)
            self.stats[key][1].setText(detail)

        def at(entry):
            return f"{entry['occurred_on']}, {entry['shop']}"

        set_stat("last", _price(history["last"]["unit_price_e5"], currency), at(history["last"]))
        set_stat(
            "cheapest", _price(history["cheapest"]["unit_price_e5"], currency), at(history["cheapest"])
        )
        set_stat(
            "dearest", _price(history["dearest"]["unit_price_e5"], currency), at(history["dearest"])
        )
        count = len(history["entries"])
        set_stat("average", _price(history["average_e5"], currency), f"z {count} zakupów")
        set_stat(
            "change",
            _change_text(history["change_percent"]),
            f"od {history['first']['occurred_on']}",
        )

        self.chart_title.setText(f"Cena za jednostkę ({currency})")
        self.chart.set_entries(history["entries"], currency)
        cheapest_shop = history["shops"][0]["shop"]
        _fill(
            self.shops,
            [
                (
                    shop["shop"],
                    str(shop["count"]),
                    _price(shop["min_e5"], currency),
                    _price(shop["average_e5"], currency),
                    f"{_price(shop['last_e5'], currency)} ({shop['last_on']})",
                )
                for shop in history["shops"]
            ],
            {1, 2, 3, 4},
        )
        # Sklepów jest zwykle kilka; resztę miejsca dostaje lista zakupów.
        self.shops.setFixedHeight(
            self.shops.horizontalHeader().sizeHint().height()
            + sum(self.shops.rowHeight(row) for row in range(self.shops.rowCount()))
            + 2 * self.shops.frameWidth()
        )
        if len(history["shops"]) > 1:
            for column in range(self.shops.columnCount()):
                item = self.shops.item(0, column)
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)
            self.shops.item(0, 0).setToolTip(f"Najniższa średnia cena: {cheapest_shop}")
        _fill(
            self.purchases,
            [
                (
                    entry["occurred_on"],
                    entry["shop"],
                    entry["wallet_name"],
                    format_quantity(entry["quantity_e5"]),
                    _price(entry["unit_price_e5"], currency),
                    format_money(entry["total_cents"], currency),
                )
                for entry in reversed(history["entries"])
            ],
            {3, 4, 5},
        )
