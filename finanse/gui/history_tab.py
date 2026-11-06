from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from ..history import history_text


class HistoryTab(QWidget):
    """Historia zmian jako tekst do odczytu; odświeża się przy wejściu na zakładkę."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)
        self.refresh()

    def refresh(self):
        self.text.setPlainText(history_text(self.db))
