import pytest
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox

from finanse.gui import common, title_bar
from finanse.gui.dialogs import BudgetDialog
from finanse.gui.main_window import MainWindow
from finanse.gui.settings_tab import SettingsTab
from finanse.settings import load_settings
from finanse.storage import database_path
from finanse.wallets import create_wallet


@pytest.fixture
def bars(qapp):
    title_bar.install(qapp, True)
    yield
    title_bar.set_enabled(False)


def shown(widget, qapp):
    widget.show()
    qapp.processEvents()
    return title_bar.bar_of(widget)


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({"XDG_CURRENT_DESKTOP": "Hyprland"}, True),
        ({"XDG_CURRENT_DESKTOP": "sway"}, True),
        ({"HYPRLAND_INSTANCE_SIGNATURE": "abc"}, True),
        ({"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, False),
        ({"XDG_CURRENT_DESKTOP": "KDE"}, False),
        ({}, False),
    ],
)
def test_default_follows_desktop(environ, expected):
    assert title_bar.default_enabled(environ) is expected


def test_main_window_and_dialogs_get_a_title_bar(db, qapp, bars):
    window = MainWindow(db)
    bar = shown(window, qapp)
    assert bar.isVisible() and bar.title.text() == "Finanse"
    assert bar.geometry().top() == 0 and bar.width() == window.width()
    assert window.contentsMargins().top() == title_bar.HEIGHT

    create_wallet(db, "A")
    dialog = BudgetDialog(db, 1, "Jedzenie")
    height = dialog.height()
    bar = shown(dialog, qapp)
    assert bar.title.text() == "Budżet: Jedzenie"
    assert dialog.height() == height + title_bar.HEIGHT
    dialog.setWindowTitle("Inny tytuł")
    qapp.processEvents()
    assert bar.title.text() == "Inny tytuł"
    window.close()
    dialog.close()


def test_close_button_rejects_dialog(db, qapp, bars):
    create_wallet(db, "A")
    dialog = BudgetDialog(db, 1, "Jedzenie")
    shown(dialog, qapp).close_button.click()
    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_message_and_input_boxes_get_a_title_bar(qapp, bars):
    box = common._message_box(None, QMessageBox.Icon.Question, "Na pewno?")
    assert shown(box, qapp).title.text() == "Finanse"
    box.close()
    question = QInputDialog()
    question.setWindowTitle("Zmiana nazwy")
    assert shown(question, qapp).title.text() == "Zmiana nazwy"
    question.close()


def test_disabled_bar_is_not_added(db, qapp):
    title_bar.set_enabled(False)
    window = MainWindow(db)
    assert shown(window, qapp) is None
    assert window.contentsMargins().top() == 0
    window.close()


def test_setting_toggles_open_windows_and_is_saved(db, qapp, bars):
    create_wallet(db, "A")
    dialog = BudgetDialog(db, 1, "Jedzenie")
    bar = shown(dialog, qapp)
    height = dialog.height()
    settings = SettingsTab(db)
    assert settings.title_bar.isChecked()

    settings.title_bar.setChecked(False)
    assert not bar.isVisible()
    assert dialog.contentsMargins().top() == 0
    assert dialog.height() == height - title_bar.HEIGHT
    assert load_settings(database_path(db))[title_bar.SETTING] is False

    settings.title_bar.setChecked(True)
    assert bar.isVisible() and dialog.height() == height
    assert load_settings(database_path(db))[title_bar.SETTING] is True
    dialog.close()
