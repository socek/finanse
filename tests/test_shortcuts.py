import pytest
from PySide6.QtCore import QCoreApplication, QDate, QEvent, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QPushButton

from helpers import priced

from finanse.db import connect, init_db
from finanse.gui import common, shortcuts
from finanse.gui.dialogs import TransactionDialog
from finanse.gui.main_window import MainWindow
from finanse.recurring import create_recurring, get_recurring
from finanse.settings import load_settings
from finanse.transactions import create_transaction
from finanse.wallets import create_wallet, get_wallet, list_wallets

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier
NONE = Qt.KeyboardModifier.NoModifier


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    monkeypatch.setattr(common, "show_info", lambda _p, text: collected.append(text))
    monkeypatch.setattr(common, "confirm", lambda *_a, **_k: True)
    return collected


@pytest.fixture
def window(db, errors):
    main = MainWindow(db)
    main.show()
    assert QTest.qWaitForWindowActive(main)
    yield main
    main.close()
    main.deleteLater()
    QCoreApplication.sendPostedEvents(main, QEvent.Type.DeferredDelete)


def spend(db, wallet, on="2026-10-05", name="Chleb"):
    return create_transaction(db, wallet, "expense", on, "Zakupy", [
        {"name": name, "quantity": "1", "price": "5", "category": None},
    ])  # fmt: skip


def press(main, key, modifier=NONE):
    QTest.keyClick(main.tabs.currentWidget(), key, modifier)


def editor_set(main, key, text):
    editor = main.settings.editors[key]
    editor.setKeySequence(QKeySequence(text))
    editor.editingFinished.emit()


def test_default_shortcuts_are_valid_and_unique(qapp):
    keys = [action.key for action in shortcuts.ACTIONS]
    assert len(keys) == len(set(keys))
    for action in shortcuts.ACTIONS:
        assert shortcuts.validation_error(action.key, action.default) is None, action
        assert not QKeySequence(action.default).isEmpty(), action
    # Domyślne skróty okna głównego nie kolidują ze standardową edycją tekstu.
    for action in shortcuts.ACTIONS:
        if action.key not in ("delete_selected", "add_product", "save"):
            assert not shortcuts._is_reserved(action.default), action.default


def test_every_main_action_is_bound(window):
    expected = {
        action.key
        for action in shortcuts.ACTIONS
        if action.scope == shortcuts.MAIN and action.key != "delete_selected"
    }
    assert set(window.action_shortcuts) == expected
    for key, shortcut in window.action_shortcuts.items():
        assert shortcuts.text_of(shortcut.key()) == shortcuts.default_text(key)


@pytest.mark.parametrize("number", range(1, 10))
def test_ctrl_number_switches_tabs(window, number):
    key = getattr(Qt.Key, f"Key_{number}")
    press(window, key, CTRL)
    assert window.tabs.currentIndex() == number - 1


def test_wallet_tab_actions_use_real_keys(db, window):
    wallet = create_wallet(db, "A")
    other = create_wallet(db, "B")
    spend(db, wallet)
    press(window, Qt.Key.Key_F5)
    tab = window.wallets
    assert tab.tree.topLevelItemCount() == 1  # F5 odświeża

    press(window, Qt.Key.Key_F, CTRL)
    assert window.focusWidget() is tab.filter_bar.search
    tab.filter_bar.search.setText("nie ma takiego")
    press(window, Qt.Key.Key_F, CTRL | SHIFT)
    assert tab.filter_bar.search.text() == ""

    press(window, Qt.Key.Key_Up, CTRL | SHIFT)
    assert not tab.tree.topLevelItem(0).isExpanded()
    press(window, Qt.Key.Key_Down, CTRL | SHIFT)
    assert tab.tree.topLevelItem(0).isExpanded()

    press(window, Qt.Key.Key_D, CTRL | SHIFT)
    assert tab.wallet_list.checked_ids() == set()
    press(window, Qt.Key.Key_A, CTRL | SHIFT)
    assert tab.wallet_list.checked_ids() == {wallet, other}


def test_edit_and_delete_selected_transaction_with_keys(db, window, monkeypatch):
    wallet = create_wallet(db, "A")
    spend(db, wallet)
    window.wallets.refresh()
    tree = window.wallets.tree
    tree.setCurrentItem(tree.topLevelItem(0).child(0))
    opened = []
    monkeypatch.setattr(TransactionDialog, "exec", lambda d: opened.append(d) or 0)
    press(window, Qt.Key.Key_F2)
    assert len(opened) == 1 and opened[0].transaction_id is not None

    tree.setFocus()
    QTest.keyClick(tree, Qt.Key.Key_Delete)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_delete_key_in_search_field_only_edits_text(db, window):
    wallet = create_wallet(db, "A")
    spend(db, wallet)
    window.wallets.refresh()
    tree = window.wallets.tree
    tree.setCurrentItem(tree.topLevelItem(0).child(0))
    search = window.wallets.filter_bar.search
    search.setFocus()
    search.setText("ab")
    search.setCursorPosition(0)
    QTest.keyClick(search, Qt.Key.Key_Delete)
    assert search.text() == "b"
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_recurring_pay_edit_delete_keys(db, window, monkeypatch):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Czynsz", remaining="2", rows=priced("Czynsz", "10"))
    window.tabs.setCurrentWidget(window.recurring)
    table = window.recurring.table
    press(window, Qt.Key.Key_P, CTRL)  # nic nie jest zaznaczone
    assert get_recurring(db, recurring)["remaining"] == 2

    table.setCurrentCell(0, 0)
    monkeypatch.setattr(
        "finanse.gui.recurring_tab.PaymentDialog.exec",
        lambda d: (d.accept(), d.result())[1],
    )
    press(window, Qt.Key.Key_P, CTRL)
    assert get_recurring(db, recurring)["remaining"] == 1

    table.setCurrentCell(0, 0)
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Delete)
    assert table.rowCount() == 0


def test_report_month_keys(db, window):
    create_wallet(db, "A")
    window.tabs.setCurrentWidget(window.reports)
    window.reports.show_month("2026-10")
    press(window, Qt.Key.Key_Left, ALT)
    assert window.reports.report["month_key"] == "2026-09"
    press(window, Qt.Key.Key_Right, ALT)
    press(window, Qt.Key.Key_Right, ALT)
    assert window.reports.report["month_key"] == "2026-11"


def test_category_delete_key(db, window):
    window.tabs.setCurrentWidget(window.categories)
    table = window.categories.table
    rows = table.rowCount()
    table.setCurrentCell(0, 0)
    table.setFocus()
    QTest.keyClick(table, Qt.Key.Key_Delete)
    assert table.rowCount() == rows - 1


def test_actions_without_wallet_report_it(db, window, errors):
    for key in ("import_csv", "edit_wallet", "delete_wallet"):
        errors.clear()
        window.action_shortcuts[key].activated.emit()
        assert "Dodaj najpierw portfel" in errors[0]


def test_actions_on_unrelated_tab_do_nothing(db, window, errors):
    window.tabs.setCurrentWidget(window.history)
    for key in ("edit_selected", "pay_selected", "search", "expand_all", "next_month"):
        window.action_shortcuts[key].activated.emit()
    assert errors == []


def test_quit_key_closes_window(db, errors):
    main = MainWindow(db)
    main.show()
    assert QTest.qWaitForWindowActive(main)
    press(main, Qt.Key.Key_Q, CTRL)
    assert not main.isVisible()


def test_changing_shortcut_works_at_once_and_is_saved(db, window):
    create_wallet(db, "A")
    window.tabs.setCurrentWidget(window.settings)
    editor_set(window, "tab_1", "Ctrl+Shift+1")
    assert window.action_shortcuts["tab_1"].key().toString() == "Ctrl+Shift+1"
    path = str(window.settings.database)
    assert load_settings(path)["shortcuts"] == {"tab_1": "Ctrl+Shift+1"}

    editor_set(window, "new_transaction", "Ctrl+J")
    window.tabs.setCurrentWidget(window.wallets)
    assert "Ctrl+J" in window.wallets.new_transaction_button.text()
    assert shortcuts.saved_values() == {"tab_1": "Ctrl+Shift+1", "new_transaction": "Ctrl+J"}


def test_saved_shortcuts_are_loaded_in_new_window(tmp_path, errors):
    path = str(tmp_path / "x.db")
    init_db(path)
    db = connect(path)
    main = MainWindow(db)
    editor_set(main, "quit", "Ctrl+Shift+Q")
    shortcuts.forget()
    again = MainWindow(db)
    assert shortcuts.sequence_text("quit") == "Ctrl+Shift+Q"
    assert again.action_shortcuts["quit"].key().toString() == "Ctrl+Shift+Q"
    assert again.settings.editors["quit"].keySequence().toString() == "Ctrl+Shift+Q"
    db.close()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Ctrl+N", "już przypisany"),  # inne działanie
        ("Ctrl+C", "zajęty"),
        ("Ctrl+A", "zajęty"),
        ("Ctrl+E", "zajęty"),
        ("Ctrl+Y", "zajęty"),
        ("Esc", "zajęty"),
        ("Tab", "zajęty"),
        ("A", "blokowałby"),
        ("Shift+A", "blokowałby"),
        ("Return", "blokowałby"),
    ],
)
def test_bad_shortcut_is_rejected_and_old_one_stays(db, window, errors, text, message):
    editor_set(window, "quit", text)
    assert message in errors[0]
    assert shortcuts.sequence_text("quit") == "Ctrl+Q"
    assert window.settings.editors["quit"].keySequence().toString() == "Ctrl+Q"
    assert window.action_shortcuts["quit"].key().toString() == "Ctrl+Q"
    assert not load_settings(str(window.settings.database))


def test_function_key_and_alt_are_allowed(db, window, errors):
    editor_set(window, "quit", "F10")
    editor_set(window, "refresh", "Alt+R")
    assert errors == []
    assert shortcuts.sequence_text("quit") == "F10"


def test_dialog_and_window_scopes_may_share_a_key(db, window, errors):
    editor_set(window, "today", "Ctrl+N")
    assert errors == []
    assert shortcuts.sequence_text("today") == "Ctrl+N"


def test_shortcut_can_be_disabled_and_reset(db, window, errors):
    editor = window.settings.editors["refresh"]
    editor.clear()
    editor.editingFinished.emit()
    assert shortcuts.sequence_text("refresh") == ""
    assert window.action_shortcuts["refresh"].key().isEmpty()
    assert load_settings(str(window.settings.database))["shortcuts"] == {"refresh": ""}

    # Wolny skrót można przypisać innemu działaniu, ale wtedy reset zgłasza konflikt.
    editor_set(window, "quit", "F5")
    assert shortcuts.sequence_text("quit") == "F5"
    window.settings._reset("refresh")
    assert "już przypisany" in errors[0]
    assert shortcuts.sequence_text("refresh") == ""

    window.settings.reset_all()
    assert shortcuts.saved_values() == {}
    assert shortcuts.sequence_text("refresh") == "F5"
    assert shortcuts.sequence_text("quit") == "Ctrl+Q"
    assert window.action_shortcuts["quit"].key().toString() == "Ctrl+Q"
    assert window.settings.editors["refresh"].keySequence().toString() == "F5"
    assert load_settings(str(window.settings.database))["shortcuts"] == {}


@pytest.mark.parametrize(
    "saved",
    [
        None,
        "tekst",
        {"nie_ma": "Ctrl+J"},
        {"quit": 5},
        {"quit": "Ctrl+C"},
        {"quit": "Ctrl+N"},
    ],
)
def test_invalid_saved_shortcuts_are_ignored(qapp, saved):
    shortcuts.load(saved)
    assert shortcuts.saved_values() == {}
    assert shortcuts.sequence_text("quit") == "Ctrl+Q"


def _dialog(db):
    wallet = create_wallet(db, "A")
    dialog = TransactionDialog(db, get_wallet(db, wallet))
    dialog.show()
    dialog.table.cellWidget(0, dialog.NAME).setText("Kawa")
    dialog.table.cellWidget(0, dialog.PRICE).setText("3")
    return dialog


def test_dialog_labels_follow_settings(db, errors):
    dialog = _dialog(db)
    assert dialog.today_button.text() == "Dzisiaj (Ctrl+T)"
    texts = {button.text() for button in dialog.findChildren(QPushButton)}
    assert "Dodaj produkt (Enter)" in texts and "Zapisz (Shift+Enter)" in texts
    dialog.close()

    shortcuts.set_sequence("today", "Ctrl+Shift+T")
    shortcuts.set_sequence("save", "Ctrl+S")
    shortcuts.set_sequence("add_product", "")
    dialog = TransactionDialog(db, list_wallets(db)[0])
    assert dialog.today_button.text() == "Dzisiaj (Ctrl+Shift+T)"
    texts = {button.text() for button in dialog.findChildren(QPushButton)}
    assert "Dodaj produkt" in texts and "Zapisz (Ctrl+S)" in texts


def test_changed_save_and_add_keys_work_in_dialog(db, errors):
    shortcuts.set_sequence("save", "Ctrl+S")
    shortcuts.set_sequence("add_product", "Ctrl+J")
    dialog = _dialog(db)
    description = dialog.description

    QTest.keyClick(description, Qt.Key.Key_J, CTRL)
    assert dialog.table.rowCount() == 2

    # Enter nie ma już działania i nie zapisuje przez domyślny przycisk.
    QTest.keyClick(description, Qt.Key.Key_Return)
    QTest.keyClick(description, Qt.Key.Key_Return, SHIFT)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.isVisible()

    QTest.keyClick(description, Qt.Key.Key_S, CTRL)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_swapped_enter_keys_work_in_dialog(db, errors):
    shortcuts.set_sequence("add_product", "Ctrl+J")
    shortcuts.set_sequence("save", "Return")
    dialog = _dialog(db)
    QTest.keyClick(dialog.description, Qt.Key.Key_Return)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_keypad_enter_matches_return_setting(db, errors):
    dialog = _dialog(db)
    QTest.keyClick(dialog.description, Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier | SHIFT)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_changed_today_key_updates_open_dialog(db, errors):
    dialog = _dialog(db)
    assert QTest.qWaitForWindowActive(dialog)
    shortcuts.set_sequence("today", "Ctrl+J")
    dialog.occurred_on.setDate(QDate(2020, 1, 1))
    QTest.keyClick(dialog.description, Qt.Key.Key_J, CTRL)
    assert dialog.occurred_on.date() == QDate.currentDate()
    dialog.close()


def test_closed_dialog_shortcuts_are_pruned(db, errors):
    dialog = _dialog(db)
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(dialog, QEvent.Type.DeferredDelete)
    shortcuts.set_sequence("today", "Ctrl+J")  # nie może odwołać się do usuniętego okna
    assert shortcuts.sequence_text("today") == "Ctrl+J"
