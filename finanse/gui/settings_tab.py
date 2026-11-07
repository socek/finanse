from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..settings import load_settings, save_setting
from ..storage import database_path
from . import common, shortcuts, title_bar
from .themes import SYSTEM, apply_theme, theme_choices

ACTION, SHORTCUT, RESET = range(3)


class SettingsTab(QWidget):
    """`on_changed` odświeża widoki, które pokazują kolory motywu i podpisy skrótów."""

    def __init__(self, db, on_changed=None, parent=None):
        super().__init__(parent)
        self.database = database_path(db)
        self.on_changed = on_changed
        self.theme = QComboBox()
        for key, name in theme_choices():
            self.theme.addItem(name, key)
        saved = load_settings(self.database).get("theme", SYSTEM)
        self.theme.setCurrentIndex(max(self.theme.findData(saved), 0))
        self.theme.currentIndexChanged.connect(self._theme_selected)
        self.title_bar = QCheckBox("Pokazuj pasek tytułowy w oknach aplikacji")
        self.title_bar.setToolTip(
            "Dla menedżerów okien, które same nie rysują pasków, np. Hyprland."
            " Przeciągnięcie paska przesuwa okno."
        )
        self.title_bar.setChecked(title_bar.is_enabled())
        self.title_bar.toggled.connect(self._title_bar_toggled)
        form = QFormLayout()
        form.addRow("Motyw", self.theme)
        form.addRow("Okna", self.title_bar)

        self.editors = {}
        self.table = QTableWidget(len(shortcuts.ACTIONS), 3)
        self.table.setHorizontalHeaderLabels(["Działanie", "Skrót", ""])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(ACTION, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(SHORTCUT, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(RESET, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(SHORTCUT, 220)
        for row, action in enumerate(shortcuts.ACTIONS):
            self.table.setItem(row, ACTION, QTableWidgetItem(action.label))
            editor = QKeySequenceEdit()
            editor.setMaximumSequenceLength(1)
            editor.setClearButtonEnabled(True)
            editor.editingFinished.connect(lambda key=action.key: self._edited(key))
            self.editors[action.key] = editor
            self.table.setCellWidget(row, SHORTCUT, editor)
            reset = QPushButton("Domyślny")
            reset.setAutoDefault(False)
            reset.clicked.connect(lambda _=False, key=action.key: self._reset(key))
            self.table.setCellWidget(row, RESET, reset)
            self.table.setRowHeight(row, 30)
        self._show_sequences()

        self.reset_all_button = QPushButton("Przywróć wszystkie domyślne")
        self.reset_all_button.clicked.connect(self.reset_all)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(self.reset_all_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Skróty klawiszowe"))
        layout.addWidget(self.table, 1)
        layout.addLayout(bottom)

    def _show_sequences(self):
        for key, editor in self.editors.items():
            editor.blockSignals(True)
            editor.setKeySequence(QKeySequence(shortcuts.sequence_text(key)))
            editor.blockSignals(False)

    def _theme_selected(self):
        key = self.theme.currentData()
        apply_theme(key)
        self._notify()
        self._save("theme", key, "motywu")

    def _title_bar_toggled(self, checked):
        title_bar.set_enabled(checked)
        self._save(title_bar.SETTING, checked, "paska tytułowego")

    def _notify(self):
        if self.on_changed:
            self.on_changed()

    def _save(self, name, value, description):
        try:
            save_setting(self.database, name, value)
        except OSError as error:
            common.show_errors(self, [f"Nie udało się zapisać {description}: {error}"])

    def _shortcuts_changed(self):
        self._show_sequences()
        self._notify()
        self._save("shortcuts", shortcuts.saved_values(), "skrótów")

    def _edited(self, key):
        text = shortcuts.text_of(self.editors[key].keySequence())
        if text == shortcuts.sequence_text(key):
            return
        error = shortcuts.validation_error(key, text)
        if error:
            self._show_sequences()
            common.show_errors(self, [error])
            return
        shortcuts.set_sequence(key, text)
        self._shortcuts_changed()

    def _reset(self, key):
        default = shortcuts.default_text(key)
        error = shortcuts.validation_error(key, default)
        if error:
            common.show_errors(self, [error])
            return
        shortcuts.set_sequence(key, default)
        self._shortcuts_changed()

    def reset_all(self):
        shortcuts.reset_all()
        self._shortcuts_changed()

    def refresh(self):
        """Ustawienia nie zależą od danych, ale okno odświeża stronę przy każdym otwarciu."""
