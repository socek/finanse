import pytest
from PySide6.QtGui import QColor, QPalette
from test_gui import _contrast

from finanse.db import connect, init_db
from finanse.gui import common
from finanse.gui.main_window import MainWindow
from finanse.gui.reports_tab import ReportsTab
from finanse.gui.themes import SYSTEM, THEMES, apply_theme, theme_choices
from finanse.gui.wallets_tab import WalletsTab
from finanse.settings import load_settings, save_setting, settings_path
from finanse.transactions import create_transaction
from finanse.wallets import create_wallet

ROLE = QPalette.ColorRole


def _spend(db, wallet, on="2026-10-05"):
    create_transaction(db, wallet, "expense", on, "Zakupy", [
        {"name": "X", "quantity": "1", "price": "5", "category": None},
    ])  # fmt: skip


def _database(tmp_path):
    return str(tmp_path / "test.db")


def _settings(db):
    return db.execute("PRAGMA database_list").fetchone()["file"]


def _select(window, key):
    combo = window.settings.theme
    combo.setCurrentIndex(combo.findData(key))


def test_there_is_a_choice_of_themes():
    keys = [key for key, _name in theme_choices()]
    assert keys[0] == SYSTEM
    assert len(THEMES) == 4 and set(THEMES) <= set(keys)


@pytest.mark.parametrize("key", list(THEMES))
def test_theme_colors_are_readable(qapp, key):  # kolory znaczeniowe także na tle motywu
    theme = THEMES[key]
    for text, background in (
        (ROLE.Text, ROLE.Base),
        (ROLE.Text, ROLE.AlternateBase),
        (ROLE.WindowText, ROLE.Window),
        (ROLE.ButtonText, ROLE.Button),
        (ROLE.HighlightedText, ROLE.Highlight),
        (ROLE.ToolTipText, ROLE.ToolTipBase),
    ):
        assert _contrast(QColor(theme[text]), QColor(theme[background])) >= 4.5, (text, background)
    assert _contrast(QColor(theme[ROLE.PlaceholderText]), QColor(theme[ROLE.Base])) >= 4.5

    apply_theme(key)
    for color in (common.positive_color(), common.negative_color()):
        for background in (ROLE.Base, ROLE.AlternateBase, ROLE.Window):
            assert _contrast(color, QColor(theme[background])) >= 4.5, (color.name(), background)
    for color in (common.income_series(), common.expense_series()):
        assert _contrast(color, QColor(theme[ROLE.Window])) >= 3, color.name()


def test_apply_theme_changes_application_palette_and_style(qapp):
    original = qapp.palette().color(ROLE.Window)
    assert apply_theme("dark") == "dark"
    assert qapp.palette().color(ROLE.Window) == QColor("#14171b")
    assert qapp.style().objectName().lower() == "fusion"
    assert qapp.palette().color(QPalette.ColorGroup.Disabled, ROLE.Text) == QColor("#6c757f")
    apply_theme("sepia")
    assert qapp.palette().color(ROLE.Window) == QColor("#efe6d2")
    assert apply_theme(SYSTEM) == SYSTEM
    assert qapp.palette().color(ROLE.Window) == original


def test_colorful_theme_uses_many_hues_and_readable_tabs(qapp):
    theme = THEMES["colorful"]
    hues = {
        QColor(theme[role]).hslHue() // 30
        for role in (ROLE.Window, ROLE.AlternateBase, ROLE.Button, ROLE.Highlight, ROLE.ToolTipBase)
    }
    assert len(hues) >= 4
    for background in ("#6a45b8", "#b0125b", "#0b6e7f"):
        assert background in theme["stylesheet"]
        assert _contrast(QColor("#ffffff"), QColor(background)) >= 4.5


def test_stylesheet_is_removed_with_colorful_theme(qapp):
    apply_theme("colorful")
    assert "QTabBar::tab" in qapp.styleSheet()
    apply_theme("dark")
    assert qapp.styleSheet() == ""
    apply_theme("colorful")
    apply_theme(SYSTEM)
    assert qapp.styleSheet() == ""


def test_colorful_theme_is_saved_like_others(tmp_path, qapp):
    path = _database(tmp_path)
    init_db(path)
    db = connect(path)
    window = MainWindow(db)
    _select(window, "colorful")
    assert load_settings(path)["theme"] == "colorful"
    assert qapp.palette().color(ROLE.Window) == QColor("#ece4fb")
    db.close()


@pytest.mark.parametrize(
    "steps",
    [
        ["colorful"],
        ["dark", "colorful"],
        ["colorful", "dark"],
        ["colorful", "sepia", "colorful"],
        ["colorful", SYSTEM, "light"],
    ],
)
def test_open_window_gets_theme_colors_when_switching_live(db, qapp, steps):
    window = MainWindow(db)
    window.show()
    for key in steps:
        _select(window, key)
        qapp.processEvents()
    theme = THEMES[steps[-1]]
    tree = window.wallets.tree
    for widget, role in (
        (window, ROLE.Window),
        (window.wallets, ROLE.Window),
        (tree, ROLE.Base),
        (tree, ROLE.Highlight),
        (window.wallets.new_transaction_button, ROLE.Button),
    ):
        assert widget.palette().color(role) == QColor(theme[role]), (widget, role)
    window.close()


@pytest.mark.parametrize("value", ["nie ma takiego", None, 5])
def test_unknown_theme_falls_back_to_system(qapp, value):
    original = qapp.palette().color(ROLE.Window)
    assert apply_theme(value) == SYSTEM
    assert qapp.palette().color(ROLE.Window) == original


def test_selected_theme_is_saved_and_applied_by_new_window(tmp_path, qapp):
    path = _database(tmp_path)
    init_db(path)
    db = connect(path)
    window = MainWindow(db)
    assert window.settings.theme.currentData() == SYSTEM
    assert not settings_path(path).exists()

    _select(window, "dark")
    assert qapp.palette().color(ROLE.Window) == QColor("#14171b")
    assert load_settings(path)["theme"] == "dark"

    # Nowe uruchomienie: zapisany motyw ustawia start aplikacji, a lista go pokazuje.
    apply_theme(SYSTEM)
    apply_theme(load_settings(path).get("theme"))
    assert qapp.palette().color(ROLE.Window) == QColor("#14171b")
    assert MainWindow(db).settings.theme.currentData() == "dark"
    db.close()


def test_theme_change_recolors_existing_views(db, qapp):
    wallet = create_wallet(db, "A")
    _spend(db, wallet)
    window = MainWindow(db)
    amount_column = 4
    row = window.wallets.tree.topLevelItem(0).child(0)
    assert row.foreground(amount_column).color() == common.negative_color()
    light_negative = QColor("#b3362b")

    apply_theme("light")
    window.refresh_all_tabs()
    row = window.wallets.tree.topLevelItem(0).child(0)
    assert row.foreground(amount_column).color() == light_negative

    window.settings.theme.setCurrentIndex(window.settings.theme.findData("dark"))
    row = window.wallets.tree.topLevelItem(0).child(0)
    assert row.foreground(amount_column).color() == QColor("#f0857a")
    assert QColor("#3987e5").name() in window.reports.income_swatch.styleSheet()
    assert isinstance(window.reports, ReportsTab)


def test_theme_change_keeps_collapsed_days_and_selection(db, qapp):
    wallet = create_wallet(db, "A")
    _spend(db, wallet, "2026-10-05")
    _spend(db, wallet, "2026-10-06")
    window = MainWindow(db)
    tree = window.wallets.tree
    tree.topLevelItem(1).setExpanded(False)
    tree.setCurrentItem(tree.topLevelItem(0).child(0))
    selected = window.wallets.selected_entry()
    _select(window, "sepia")
    assert not tree.topLevelItem(1).isExpanded()
    assert window.wallets.selected_entry() == selected


def test_failed_save_reports_error_but_keeps_theme(db, qapp, monkeypatch):
    errors = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: errors.extend(e))
    window = MainWindow(db)
    import finanse.gui.settings_tab as settings_tab

    def fail(*_args):
        raise OSError("brak miejsca")

    monkeypatch.setattr(settings_tab, "save_setting", fail)
    _select(window, "dark")
    assert "brak miejsca" in errors[0]
    assert qapp.palette().color(ROLE.Window) == QColor("#14171b")


@pytest.mark.parametrize("content", ["{nie json", "[1, 2]", ""])
def test_damaged_settings_file_means_defaults(tmp_path, content):
    database = tmp_path / "x.db"
    settings_path(database).write_text(content)
    assert load_settings(database) == {}
    save_setting(database, "theme", "dark")
    assert load_settings(database) == {"theme": "dark"}


def test_save_setting_keeps_other_values_and_leaves_no_temp_file(tmp_path):
    database = tmp_path / "x.db"
    assert load_settings(database) == {}
    save_setting(database, "inne", 1)
    save_setting(database, "theme", "sepia")
    assert load_settings(database) == {"inne": 1, "theme": "sepia"}
    assert sorted(path.name for path in tmp_path.iterdir()) == ["settings.json"]


def test_wallets_tab_balance_color_follows_theme(db, qapp):
    wallet = create_wallet(db, "A")
    _spend(db, wallet)
    tab = WalletsTab(db)
    apply_theme("dark")
    tab.refresh()
    assert QColor("#f0857a").name() in tab.balance.styleSheet()
    apply_theme("sepia")
    tab.refresh()
    assert QColor("#a32a20").name() in tab.balance.styleSheet()
