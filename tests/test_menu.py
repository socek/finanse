import pytest
from helpers import priced

from finanse.gui import common, shortcuts, title_bar
from finanse.gui.main_window import MainWindow, ShortcutsDialog
from finanse.gui.themes import current_theme
from finanse.recurring import create_recurring
from finanse.settings import load_settings
from finanse.storage import database_path
from finanse.transactions import create_transaction
from finanse.transfers import create_transfer
from finanse.wallets import create_wallet


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    monkeypatch.setattr(common, "confirm", lambda *_a, **_k: True)
    return collected


@pytest.fixture
def window(db, errors):
    main = MainWindow(db)
    yield main
    title_bar.set_enabled(False)


def menus(window):
    return {action.text().replace("&", ""): action.menu() for action in window.menuBar().actions()}


def item(window, menu, label):
    window.update_menus()
    for action in menus(window)[menu].actions():
        if action.text().split("\t")[0] == label:
            return action
    raise AssertionError(f"Brak „{label}” w menu {menu}")


def test_menu_bar_order_and_five_tabs(window):
    assert list(menus(window)) == [
        "Plik", "Edycja", "Widok", "Portfel", "Transakcja", "Raport", "Pomoc",
    ]  # fmt: skip
    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == [
        "Portfele", "Produkty", "Cykliczne", "Raporty", "Kategorie i tagi",
    ]  # fmt: skip


def test_menu_shows_current_shortcuts(window):
    assert item(window, "Plik", "Nowa transakcja…").text() == "Nowa transakcja…\tCtrl+N"
    assert item(window, "Edycja", "Ustawienia…").text() == "Ustawienia…\tCtrl+,"
    assert item(window, "Plik", "Kopie i pliki danych…").text() == "Kopie i pliki danych…"
    shortcuts.set_sequence("new_transaction", "Ctrl+J")
    window.refresh_all_tabs()
    assert item(window, "Plik", "Nowa transakcja…").text() == "Nowa transakcja…\tCtrl+J"


def test_edit_items_follow_selection(db, window):
    wallet = create_wallet(db, "A")
    other = create_wallet(db, "B")
    create_transaction(db, wallet, "expense", "2026-11-05", "Zakupy", priced("X", "5"))
    create_transfer(db, wallet, other, "2026-11-06", "", "1")
    window.wallets.refresh()
    assert not item(window, "Edycja", "Edytuj zaznaczone").isEnabled()

    tree = window.wallets.tree
    tree.setCurrentItem(tree.topLevelItem(0).child(0))  # przelew
    assert item(window, "Edycja", "Edytuj zaznaczone").isEnabled()
    assert not item(window, "Edycja", "Duplikuj transakcję").isEnabled()
    tree.setCurrentItem(tree.topLevelItem(1).child(0))  # transakcja
    assert item(window, "Edycja", "Duplikuj transakcję").isEnabled()

    item(window, "Edycja", "Usuń zaznaczone").trigger()
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_view_menu_switches_tabs(window):
    item(window, "Widok", "Raporty").trigger()
    assert window.tabs.currentWidget() is window.reports
    assert item(window, "Widok", "Raporty").isChecked()
    assert not item(window, "Widok", "Portfele").isChecked()
    assert item(window, "Raport", "Następny okres").isEnabled()
    assert not item(window, "Widok", "Rozwiń wszystko").isEnabled()
    item(window, "Widok", "Portfele").trigger()
    assert not item(window, "Raport", "Następny okres").isEnabled()
    assert item(window, "Widok", "Rozwiń wszystko").isEnabled()


def test_theme_and_title_bar_from_view_menu(window, db):
    view = menus(window)["Widok"]
    theme_menu = next(a.menu() for a in view.actions() if a.text() == "Motyw")
    dark = next(a for a in theme_menu.actions() if a.text() == "Ciemny")
    dark.trigger()
    assert current_theme() == "dark"
    assert load_settings(database_path(db))["theme"] == "dark"
    window.update_menus()
    assert dark.isChecked()

    window.title_bar_action.trigger()
    assert title_bar.is_enabled() is True
    assert window.settings.title_bar.isChecked()
    window.title_bar_action.trigger()
    assert title_bar.is_enabled() is False


def test_pages_open_in_their_own_windows(db, window):
    create_wallet(db, "A")
    item(window, "Pomoc", "Historia zmian danych…").trigger()
    assert window.history_dialog.isVisible()
    assert "Dodano portfel „A”" in window.history.text.toPlainText()
    item(window, "Plik", "Kopie i pliki danych…").trigger()
    assert window.files_dialog.isVisible()
    item(window, "Edycja", "Ustawienia…").trigger()
    assert window.settings_dialog.isVisible()
    item(window, "Pomoc", "O programie…").trigger()
    assert window.about_dialog.windowTitle() == "O programie"
    window.commands["open_settings"]()
    assert window.settings_dialog.isVisible()


def test_shortcuts_dialog_lists_actions(qapp):
    dialog = ShortcutsDialog()
    labels = [dialog.table.item(row, 0).text() for row in range(dialog.table.rowCount())]
    assert "Okno ustawień" in labels
    row = labels.index("Nowa transakcja")
    assert dialog.table.item(row, 1).text() == "Ctrl+N"


def test_transaction_menu_needs_the_right_tab(db, window, monkeypatch):
    wallet = create_wallet(db, "A")
    create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"))
    assert not item(window, "Transakcja", "Zapłać transakcję cykliczną").isEnabled()
    window.tabs.setCurrentWidget(window.recurring)
    window.recurring.table.setCurrentCell(0, 0)
    assert item(window, "Transakcja", "Zapłać transakcję cykliczną").isEnabled()
    assert not item(window, "Transakcja", "Pomiń termin transakcji cyklicznej").isEnabled()
    assert not item(window, "Transakcja", "Historia ceny produktu…").isEnabled()


def test_report_period_from_menu(db, window):
    create_wallet(db, "A")
    window.tabs.setCurrentWidget(window.reports)
    report = menus(window)["Raport"]
    period_menu = next(a.menu() for a in report.actions() if a.text() == "Okres")
    year = next(a for a in period_menu.actions() if a.text() == "Rok")
    window.update_menus()  # menu odświeża się przy otwarciu
    assert year.isEnabled()
    year.trigger()
    assert window.reports.report["period"] == "year"
    window.update_menus()
    assert year.isChecked()


def test_wallet_menu_needs_a_wallet(db, window):
    assert not item(window, "Portfel", "Edytuj portfel…").isEnabled()
    create_wallet(db, "A")
    window.wallets.refresh()
    assert item(window, "Portfel", "Prognoza salda…").isEnabled()
