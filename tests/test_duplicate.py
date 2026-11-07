import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest

from finanse.gui import common
from finanse.gui.dialogs import TransactionDialog
from finanse.gui.main_window import MainWindow
from finanse.gui.products_tab import ProductsTab
from finanse.gui.wallets_tab import WalletsTab
from finanse.transactions import create_transaction, get_transaction
from finanse.transfers import create_transfer
from finanse.wallets import VAT, create_wallet


def category_id(db, name):
    return db.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    return collected


def _accept_on_exec(monkeypatch, before=None):
    opened = []

    def fake_exec(dialog):
        opened.append(dialog)
        if before:
            before(dialog)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(TransactionDialog, "exec", fake_exec)
    return opened


def _source(db):
    wallet = create_wallet(db, "Firma", wallet_type=VAT)
    create_wallet(db, "Dom")
    food = category_id(db, "Jedzenie")
    transaction = create_transaction(db, wallet, "expense", "2026-10-05", "Hurtownia", [
        {"name": "Kawa", "quantity": "2", "price": "40", "category": food, "vat_rate": 8},
        {"name": "Mleko", "quantity": "3", "price": "1", "total": "2,50", "category": None,
         "vat_rate": 5},
    ])  # fmt: skip
    return wallet, transaction


def test_copy_dialog_is_a_new_prefilled_transaction(db, errors):
    wallet, transaction = _source(db)
    dialog = TransactionDialog(db, None, copy_from=transaction)
    assert dialog.windowTitle() == "Kopia transakcji"
    assert dialog.transaction_id is None
    assert dialog.wallet_combo.currentData() == wallet
    assert dialog.description.text() == "Hurtownia"
    assert common.iso_date(dialog.occurred_on) == QDate.currentDate().toString(Qt.DateFormat.ISODate)
    assert [row["name"] for row in dialog.rows()] == ["Kawa", "Mleko"]

    dialog.occurred_on.setDate(QDate(2026, 11, 7))
    dialog.accept()
    copy = get_transaction(db, dialog.transaction_id)
    original = get_transaction(db, transaction)
    assert dialog.transaction_id != transaction
    assert copy["occurred_on"] == "2026-11-07"
    assert copy["rows"] == original["rows"]
    assert original["occurred_on"] == "2026-10-05"


def test_copy_can_go_to_another_wallet(db, errors):
    _wallet, transaction = _source(db)
    dialog = TransactionDialog(db, None, copy_from=transaction)
    dialog.wallet_combo.setCurrentIndex(dialog.wallet_combo.findText("Dom"))
    dialog.accept()
    assert get_transaction(db, dialog.transaction_id)["wallet_id"] != get_transaction(db, transaction)["wallet_id"]


def test_wallets_tab_duplicates_transactions_but_not_transfers(db, errors, monkeypatch):
    wallet, transaction = _source(db)
    other = create_wallet(db, "Inny")
    create_transfer(db, wallet, other, "2026-10-06", "", "5")
    opened = _accept_on_exec(monkeypatch)
    tab = WalletsTab(db)
    day = tab.tree.topLevelItem(0)  # 2026-10-06: przelew
    tab.tree.setCurrentItem(day.child(0))
    assert not tab.duplicate_button.isEnabled()
    assert "Duplikuj" not in [action.text() for action in tab._entry_menu().actions()]
    assert tab.duplicate_transaction() is None

    tab.tree.setCurrentItem(tab.tree.topLevelItem(1).child(0))
    assert tab.duplicate_button.isEnabled()
    new_id = tab.duplicate_transaction()
    assert opened[0].windowTitle() == "Kopia transakcji"
    assert new_id is not None and new_id != transaction
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_products_tab_duplicates_transaction_of_selected_product(db, errors, monkeypatch):
    _wallet, transaction = _source(db)
    opened = _accept_on_exec(monkeypatch)
    tab = ProductsTab(db)
    assert not tab.duplicate_button.isEnabled()
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(1))
    assert tab.duplicate_button.isEnabled()
    tab.duplicate_button.click()
    assert len(opened[0].rows()) == 2
    assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 4


def test_shortcut_duplicates_on_current_tab(db, errors, monkeypatch):
    _wallet, _transaction = _source(db)
    opened = _accept_on_exec(monkeypatch)
    window = MainWindow(db)
    window.show()
    assert QTest.qWaitForWindowActive(window)
    tab = window.wallets
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))
    QTest.keyClick(tab, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    assert len(opened) == 1
    window.close()
