"""Pasek tytułowy rysowany przez aplikację, dla menedżerów okien bez dekoracji.

Na przykład Hyprland czy sway nie rysują pasków tytułowych, więc bez tego okna nie
mają nazw. Pasek dostaje każde okno aplikacji: główne, formularze, komunikaty
i zapytania. Leży nad zawartością okna, a margines okna robi mu miejsce, więc
działa przy każdym układzie, także w oknach tworzonych przez Qt.
"""

import os

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QToolButton,
    QWidget,
)

# Pulpity, które same nie rysują pasków tytułowych.
UNDECORATED_DESKTOPS = {"hyprland", "sway", "i3", "niri", "river", "qtile", "dwl", "bspwm"}
SETTING = "title_bar"
HEIGHT = 30

_enabled = False
_installer = None


def default_enabled(environ=None):
    """Domyślnie pasek jest tylko tam, gdzie pulpit go nie rysuje."""
    environ = os.environ if environ is None else environ
    desktops = environ.get("XDG_CURRENT_DESKTOP", "").lower().split(":")
    return bool(UNDECORATED_DESKTOPS.intersection(desktops)) or bool(
        environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    )


def is_enabled():
    return _enabled


class TitleBar(QWidget):
    """Tytuł okna i przycisk zamknięcia; przeciągnięcie przesuwa okno."""

    def __init__(self, window):
        super().__init__(window)
        self.window_widget = window
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(
            "#titleBar { background: palette(button);"
            " border-bottom: 1px solid palette(mid); }"
        )
        self.title = QLabel()
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        font = QFont(self.title.font())
        font.setBold(True)
        self.title.setFont(font)
        self.close_button = QToolButton()
        self.close_button.setText("✕")
        self.close_button.setToolTip("Zamknij okno")
        self.close_button.setAutoRaise(True)
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.clicked.connect(window.close)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 4, 0)
        layout.addWidget(self.title, 1)
        layout.addWidget(self.close_button)
        self.update_title()

    def update_title(self):
        self.title.setText(self.window_widget.windowTitle() or "Finanse")

    def place(self):
        self.setGeometry(0, 0, self.window_widget.width(), HEIGHT)
        self.raise_()

    def mousePressEvent(self, event):
        handle = self.window_widget.windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemMove()

    def mouseDoubleClickEvent(self, _event):
        window = self.window_widget
        if isinstance(window, QMainWindow):
            window.showNormal() if window.isMaximized() else window.showMaximized()


def _is_app_window(widget):
    return (
        isinstance(widget, (QDialog, QMainWindow))
        and widget.isWindow()
        and widget.windowType() in (Qt.WindowType.Window, Qt.WindowType.Dialog)
    )


def bar_of(window):
    return window.findChild(TitleBar, options=Qt.FindChildOption.FindDirectChildrenOnly)


def _show(window, visible):
    bar = bar_of(window)
    if bar is None:
        if not visible:
            return
        bar = TitleBar(window)
    margins = window.contentsMargins()
    top = HEIGHT if visible else 0
    if margins.top() != top:
        window.setContentsMargins(margins.left(), top, margins.right(), margins.bottom())
        # Okno dobrało rozmiar do treści, więc pasek nie może jej ścisnąć.
        if not isinstance(window, QMainWindow):
            window.resize(window.width(), window.height() + top - margins.top())
    bar.setVisible(visible)
    if visible:
        bar.place()


class _Installer(QObject):
    """Dokłada pasek każdemu oknu przy pokazaniu i pilnuje jego tytułu i szerokości."""

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.WindowTitleChange):
            if _is_app_window(watched):
                if kind == QEvent.Type.Show:
                    _show(watched, _enabled)
                bar = bar_of(watched)
                if bar is not None and bar.isVisible():
                    bar.update_title()
                    bar.place()
        return False


def install(app, enabled):
    global _installer
    if _installer is None:
        _installer = _Installer(app)
        app.installEventFilter(_installer)
    set_enabled(enabled)


def set_enabled(enabled):
    """Włącza lub wyłącza pasek, także w oknach, które są już otwarte."""
    global _enabled
    _enabled = bool(enabled)
    for widget in QApplication.topLevelWidgets():
        if _is_app_window(widget) and widget.isVisible():
            _show(widget, _enabled)
