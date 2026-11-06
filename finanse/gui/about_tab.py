from importlib import resources

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QTextBrowser, QVBoxLayout, QWidget

from .. import __version__


def changelog_text():
    return resources.files("finanse").joinpath("CHANGELOG.md").read_text("utf-8")


class AboutTab(QWidget):
    """Wersja aplikacji i historia zmian."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.title = QLabel("Finanse")
        font = QFont(self.title.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.5)
        self.title.setFont(font)
        self.version = QLabel(f"Wersja {__version__}")
        self.changelog = QTextBrowser()
        self.changelog.setMarkdown(changelog_text())

        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addWidget(self.version)
        layout.addWidget(self.changelog, 1)

    def refresh(self):
        """Treść jest stała, ale każda zakładka odświeża się przy wejściu."""
