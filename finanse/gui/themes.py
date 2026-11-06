"""Motywy kolorystyczne aplikacji."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

SYSTEM = "system"
ROLE = QPalette.ColorRole
THEMES = {
    "light": {
        "name": "Jasny",
        ROLE.Window: "#f5f6f8",
        ROLE.Base: "#ffffff",
        ROLE.AlternateBase: "#f0f2f5",
        ROLE.Text: "#1c2128",
        ROLE.WindowText: "#1c2128",
        ROLE.Button: "#e9ecf0",
        ROLE.ButtonText: "#1c2128",
        ROLE.Highlight: "#1f6f5c",
        ROLE.HighlightedText: "#ffffff",
        ROLE.ToolTipBase: "#ffffff",
        ROLE.ToolTipText: "#1c2128",
        ROLE.PlaceholderText: "#626c78",
        ROLE.Link: "#1f6f5c",
        "disabled": "#8c95a0",
        "expense": "#dd5c28",  # domyślny pomarańcz ma na tym tle za mały kontrast
    },
    "dark": {
        "name": "Ciemny",
        ROLE.Window: "#14171b",
        ROLE.Base: "#1e2227",
        ROLE.AlternateBase: "#262b31",
        ROLE.Text: "#e7eaee",
        ROLE.WindowText: "#e7eaee",
        ROLE.Button: "#2c3137",
        ROLE.ButtonText: "#e7eaee",
        ROLE.Highlight: "#4cb89d",
        ROLE.HighlightedText: "#0d1512",
        ROLE.ToolTipBase: "#2c3137",
        ROLE.ToolTipText: "#e7eaee",
        ROLE.PlaceholderText: "#9aa4af",
        ROLE.Link: "#4cb89d",
        "disabled": "#6c757f",
    },
    "sepia": {
        "name": "Sepia",
        ROLE.Window: "#efe6d2",
        ROLE.Base: "#f8f1e0",
        ROLE.AlternateBase: "#f1e8d3",
        ROLE.Text: "#2e2618",
        ROLE.WindowText: "#2e2618",
        ROLE.Button: "#e3d8bf",
        ROLE.ButtonText: "#2e2618",
        ROLE.Highlight: "#7a4f24",
        ROLE.HighlightedText: "#ffffff",
        ROLE.ToolTipBase: "#f8f1e0",
        ROLE.ToolTipText: "#2e2618",
        ROLE.PlaceholderText: "#6b5f49",
        ROLE.Link: "#7a4f24",
        "disabled": "#9a8e77",
        # Domyślne kolory jasnego motywu mają na tym tle za mały kontrast.
        "positive": "#12603f",
        "negative": "#a32a20",
        "income": "#1f66bd",
        "expense": "#b84a1c",
    },
    "colorful": {
        "name": "Kolorowy",
        ROLE.Window: "#ece4fb",
        ROLE.Base: "#fffdf7",
        ROLE.AlternateBase: "#e4f4fb",
        ROLE.Text: "#24143f",
        ROLE.WindowText: "#24143f",
        ROLE.Button: "#bde8e0",
        ROLE.ButtonText: "#0c3b36",
        ROLE.Highlight: "#b0125b",
        ROLE.HighlightedText: "#ffffff",
        ROLE.ToolTipBase: "#fff3c4",
        ROLE.ToolTipText: "#24143f",
        ROLE.PlaceholderText: "#5f5478",
        ROLE.Link: "#0b57a4",
        "disabled": "#8f86a6",
        "positive": "#0a6b45",
        "negative": "#b01c2e",
        "income": "#1565c0",
        "expense": "#d84315",
        # Paleta Qt nie obejmuje zakładek ani nagłówków tabel.
        "stylesheet": """
            QTabBar::tab {
                background: #6a45b8;
                color: #ffffff;
                padding: 6px 12px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background: #b0125b;
            }
            QHeaderView::section {
                background: #0b6e7f;
                color: #ffffff;
                padding: 3px 6px;
                border: none;
                border-right: 1px solid #fffdf7;
            }
        """,
    },
}
_DISABLED_ROLES = (ROLE.Text, ROLE.WindowText, ROLE.ButtonText)
_system_look = None  # styl i paleta sprzed pierwszego użycia motywu
_current = SYSTEM


def color_override(name):
    """Kolor znaczeniowy aktualnego motywu albo None, gdy motyw go nie zmienia."""
    return THEMES.get(_current, {}).get(name)


def theme_choices():
    return [(SYSTEM, "Systemowy"), *((key, theme["name"]) for key, theme in THEMES.items())]


def _palette(theme):
    palette = QPalette()
    for role, color in theme.items():
        if isinstance(role, ROLE):
            palette.setColor(role, QColor(color))
    for role in _DISABLED_ROLES:
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(theme["disabled"]))
    return palette


def apply_theme(key):
    """Ustawia motyw; nieznana nazwa, np. z ręcznie zmienionego pliku, to motyw systemowy."""
    global _system_look, _current
    app = QApplication.instance()
    key = key if key in THEMES else SYSTEM
    if key == _current:
        return key
    _current = key
    if _system_look is None:
        _system_look = (app.style().objectName(), QPalette(app.palette()))
    # Przy aktywnym arkuszu stylów otwarte okna nie przejmują nowej palety, dlatego
    # arkusz jest zdejmowany na czas zmiany i zakładany dopiero na końcu.
    app.setStyleSheet("")
    if key == SYSTEM:
        app.setStyle(_system_look[0])
        app.setPalette(_system_look[1])
        return SYSTEM
    # Fusion jako jedyny styl Qt wiernie stosuje paletę na każdej platformie.
    app.setStyle("Fusion")
    app.setPalette(_palette(THEMES[key]))
    app.setStyleSheet(THEMES[key].get("stylesheet", ""))
    return key
