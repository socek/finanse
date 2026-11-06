"""Import wyciągu CSV: wybór kolumn, podgląd i zapis."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..bank_import import column_options, import_rows, preview, safe_rows
from ..categories import list_categories
from ..csv_import import DELIMITERS, detect_mapping
from ..errors import ValidationError
from ..money import format_money
from . import common

PREVIEW_ROWS = 20


class ImportDialog(QDialog):
    def __init__(self, db, wallet, content, delimiter, parent=None):
        super().__init__(parent)
        self.db = db
        self.wallet = wallet
        self.content = content
        self.rows = []
        self.result_counts = None
        self.setWindowTitle(f"Import CSV do portfela {wallet['name']}")

        self.delimiter = QComboBox()
        for value, label in DELIMITERS.items():
            self.delimiter.addItem(label, value)
        self.delimiter.setCurrentIndex(self.delimiter.findData(delimiter))
        self.start = QSpinBox()
        self.date_column = QComboBox()
        self.description_column = QComboBox()
        self.amount_column = QComboBox()
        self.category = QComboBox()
        self.category.addItem("Bez kategorii", None)
        for item in list_categories(db):
            self.category.addItem(item["name"], item["id"])

        form = QFormLayout()
        form.addRow("Separator", self.delimiter)
        form.addRow("Dane od wiersza", self.start)
        form.addRow("Kolumna daty", self.date_column)
        form.addRow("Kolumna opisu", self.description_column)
        form.addRow("Kolumna kwoty", self.amount_column)
        form.addRow("Kategoria dla wszystkich", self.category)

        self.counts = QLabel()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Wiersz", "Data", "Opis", "Kwota", "Status"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.hint = QLabel()

        buttons = QDialogButtonBox()
        self.import_button = buttons.addButton(
            "Importuj", QDialogButtonBox.ButtonRole.AcceptRole
        )
        buttons.addButton("Anuluj", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.counts)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.hint)
        layout.addWidget(buttons)
        self.resize(820, 640)

        self.delimiter.currentIndexChanged.connect(self._reload_rows)
        self.start.valueChanged.connect(self._start_changed)
        for combo in (self.date_column, self.description_column, self.amount_column):
            combo.currentIndexChanged.connect(self._refresh_preview)
        self._reload_rows()

    def _reload_rows(self):
        self.rows = safe_rows(self.content, self.delimiter.currentData())
        mapping = detect_mapping(self.rows)
        self.start.blockSignals(True)
        self.start.setRange(1, max(len(self.rows), 1))
        self.start.setValue(mapping["start"] + 1)
        self.start.blockSignals(False)
        self._fill_columns(mapping)
        self._refresh_preview()

    def _start_changed(self):
        self._fill_columns(self.mapping())
        self._refresh_preview()

    def _fill_columns(self, mapping):
        options = column_options(self.rows, self.start.value() - 1)
        for combo, key in (
            (self.date_column, "date"),
            (self.description_column, "description"),
            (self.amount_column, "amount"),
        ):
            combo.blockSignals(True)
            combo.clear()
            for option in options:
                combo.addItem(option["label"], option["index"])
            combo.setCurrentIndex(max(combo.findData(mapping[key]), 0))
            combo.blockSignals(False)

    def mapping(self):
        return {
            "start": self.start.value() - 1,
            "date": self.date_column.currentData(),
            "description": self.description_column.currentData(),
            "amount": self.amount_column.currentData(),
        }

    def _refresh_preview(self):
        mapping = self.mapping()
        if not self.rows or None in mapping.values():
            self.counts.setText("Przy tym separatorze plik jest pusty lub nieczytelny.")
            self.table.setRowCount(0)
            self.hint.clear()
            self.import_button.setEnabled(False)
            return
        records, counts = preview(self.db, self.wallet["id"], self.rows, mapping)
        self.counts.setText(
            f"Nowe: {counts['new']} · duplikaty: {counts['duplicates']}"
            f" · niepoprawne wiersze: {counts['invalid']}"
        )
        shown = records[:PREVIEW_ROWS]
        self.table.setRowCount(len(shown))
        for index, record in enumerate(shown):
            cents = record["amount_cents"]
            amount = "–" if cents is None else format_money(cents, self.wallet["currency"])
            if record["error"]:
                status = f"Pominięty: {record['error']}"
            elif record["duplicate"]:
                status = "Duplikat"
            else:
                status = "Nowy"
            cells = (
                str(record["line"]),
                record["occurred_on"] or "–",
                record["description"],
                amount,
                status,
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column in (0, 3):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(index, column, item)
        self.table.resizeColumnToContents(0)
        self.table.resizeColumnToContents(1)
        self.table.resizeColumnToContents(3)
        self.table.resizeColumnToContents(4)
        self.hint.setText(
            f"Pokazano pierwsze {len(shown)} z {len(records)} wierszy."
            if len(records) > len(shown)
            else ""
        )
        self.import_button.setEnabled(counts["new"] > 0)

    def accept(self):
        try:
            self.result_counts = import_rows(
                self.db,
                self.wallet["id"],
                self.rows,
                self.mapping(),
                self.category.currentData(),
            )
        except ValidationError as error:
            common.show_errors(self, error.errors)
            return
        super().accept()

    def summary(self):
        counts = self.result_counts
        lines = [f"Zaimportowano transakcje: {counts['imported']}."]
        if counts["duplicates"]:
            lines.append(f"Pominięte duplikaty: {counts['duplicates']}.")
        if counts["invalid"]:
            lines.append(f"Pominięte niepoprawne wiersze: {counts['invalid']}.")
        return "\n".join(lines)
