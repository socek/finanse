"""Pole tagów po przecinku z podpowiedziami istniejących tagów dla właśnie pisanego tagu."""

from PySide6.QtCore import QStringListModel, Qt
from PySide6.QtWidgets import QCompleter, QLineEdit

from ..tags import SEPARATOR, format_tags, list_tags


class TagsEdit(QLineEdit):
    def __init__(self, db, names=(), parent=None):
        super().__init__(format_tags(names), parent)
        self.setPlaceholderText("np. Wakacje 2026, Remont")
        self.setToolTip("Tagi oddzielaj przecinkami. Nowy tag powstaje przy zapisie.")
        model = QStringListModel([tag["name"] for tag in list_tags(db)], self)
        self.tag_completer = QCompleter(model, self)
        self.tag_completer.setWidget(self)
        self.tag_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.tag_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.tag_completer.activated.connect(self._insert)
        self.textEdited.connect(self._suggest)

    def _current_part(self):
        """Początek i tekst tagu, w którym stoi kursor."""
        text = self.text()[: self.cursorPosition()]
        start = text.rfind(SEPARATOR) + 1
        return start, text[start:].strip()

    def _suggest(self):
        _start, part = self._current_part()
        if not part:
            self.tag_completer.popup().hide()
            return
        self.tag_completer.setCompletionPrefix(part)
        if self.tag_completer.completionCount():
            self.tag_completer.complete()
        else:
            self.tag_completer.popup().hide()

    def _insert(self, name):
        start, _part = self._current_part()
        end = self.text().find(SEPARATOR, self.cursorPosition())
        rest = "" if end < 0 else self.text()[end:]
        before = self.text()[:start]
        prefix = before + (" " if before else "")
        self.setText(f"{prefix}{name}{SEPARATOR} {rest.lstrip(SEPARATOR).lstrip()}".rstrip())
        self.setCursorPosition(len(prefix) + len(name) + 1)

    def keyPressEvent(self, event):
        # Enter na liście podpowiedzi wybiera tag, a nie zapisuje transakcji.
        popup = self.tag_completer.popup()
        if popup.isVisible() and event.key() in (
            Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape, Qt.Key.Key_Tab,
        ):  # fmt: skip
            event.ignore()
            return
        super().keyPressEvent(event)
