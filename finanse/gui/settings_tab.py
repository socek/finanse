from PySide6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QWidget

from ..settings import load_settings, save_setting
from ..storage import database_path
from . import common
from .themes import SYSTEM, apply_theme, theme_choices


class SettingsTab(QWidget):
    """`on_theme_changed` odświeża widoki, których kolory są zapisane w elementach."""

    def __init__(self, db, on_theme_changed=None, parent=None):
        super().__init__(parent)
        self.database = database_path(db)
        self.on_theme_changed = on_theme_changed
        self.theme = QComboBox()
        for key, name in theme_choices():
            self.theme.addItem(name, key)
        saved = load_settings(self.database).get("theme", SYSTEM)
        self.theme.setCurrentIndex(max(self.theme.findData(saved), 0))
        self.theme.currentIndexChanged.connect(self._theme_selected)

        form = QFormLayout()
        form.addRow("Motyw", self.theme)
        layout = QHBoxLayout(self)
        layout.addLayout(form)
        layout.addStretch()
        layout.setContentsMargins(16, 16, 16, 16)

    def _theme_selected(self):
        key = self.theme.currentData()
        apply_theme(key)
        if self.on_theme_changed:
            self.on_theme_changed()
        try:
            save_setting(self.database, "theme", key)
        except OSError as error:
            common.show_errors(self, [f"Nie udało się zapisać motywu: {error}"])

    def refresh(self):
        """Ustawienia nie zależą od danych, ale każda zakładka odświeża się przy wejściu."""
