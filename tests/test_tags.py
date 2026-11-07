import pytest
from helpers import priced
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from finanse.errors import ValidationError
from finanse.gui import common
from finanse.gui.categories_tab import CategoriesTab
from finanse.gui.dialogs import PaymentDialog, TransactionDialog
from finanse.gui.products_tab import ProductsTab
from finanse.gui.reports_tab import ReportsTab
from finanse.gui.tags_edit import TagsEdit
from finanse.gui.wallets_tab import DESCRIPTION, WalletsTab
from finanse.history import history_text
from finanse.products import load_products
from finanse.recurring import create_recurring, pay_recurring, payment_draft
from finanse.reports import build_report
from finanse.tags import delete_tag, list_tags, parse_tags, rename_tag, sort_key
from finanse.transactions import create_transaction, get_transaction, update_transaction
from finanse.transfers import create_transfer
from finanse.wallets import EntryFilters, create_wallet, get_wallet, load_entries


def add(db, wallet, description="Zakupy", price="10", tags=None, kind="expense", on="2026-11-05"):
    return create_transaction(db, wallet, kind, on, description, priced("X", price), tags)


def tag_id(db, name):
    return next(tag["id"] for tag in list_tags(db) if tag["name"] == name)


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    monkeypatch.setattr(common, "confirm", lambda *_a, **_k: True)
    return collected


def test_parse_tags():
    assert parse_tags(" Wakacje 2026 ,remont,, wakacje  2026, Łódź") == (
        ["Wakacje 2026", "remont", "Łódź"], [],
    )  # fmt: skip
    names, errors = parse_tags("x" * 51)
    assert names == [] and "za długi" in errors[0]


def test_tags_are_shared_case_insensitively_and_replaced(db):
    wallet = create_wallet(db, "A")
    first = add(db, wallet, tags="Wakacje, Łódź")
    second = add(db, wallet, tags=["wakacje", "ŁÓDŹ ", "Rodzice"])
    assert [(t["name"], t["transaction_count"]) for t in list_tags(db)] == [
        ("Łódź", 2), ("Rodzice", 1), ("Wakacje", 2),
    ]  # fmt: skip
    assert [sort_key(n) < sort_key(m) for n, m in (("Lz", "Ła"), ("ła", "Ma"), ("ź", "ż"))] == [
        True, True, True,
    ]  # fmt: skip
    assert sorted(get_transaction(db, second)["tags"]) == ["Rodzice", "Wakacje", "Łódź"]

    update_transaction(db, first, "expense", "2026-11-05", "Zakupy", priced("X", "10"), "Remont")
    assert get_transaction(db, first)["tags"] == ["Remont"]
    update_transaction(db, first, "expense", "2026-11-05", "Inne", priced("X", "10"))
    assert get_transaction(db, first)["tags"] == ["Remont"]  # None zostawia tagi
    update_transaction(db, first, "expense", "2026-11-05", "Inne", priced("X", "10"), "")
    assert get_transaction(db, first)["tags"] == []


def test_invalid_tag_saves_nothing(db):
    wallet = create_wallet(db, "A")
    with pytest.raises(ValidationError, match="za długi"):
        add(db, wallet, tags="x" * 60)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_rename_and_delete_tag(db):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet, tags="Wakacje, Remont")
    rename_tag(db, tag_id(db, "Wakacje"), " Wakacje  2026 ")
    assert sorted(get_transaction(db, transaction)["tags"]) == ["Remont", "Wakacje 2026"]
    with pytest.raises(ValidationError, match="już tag"):
        rename_tag(db, tag_id(db, "Remont"), "wakacje 2026")
    with pytest.raises(ValidationError, match="przecinka"):
        rename_tag(db, tag_id(db, "Remont"), "a, b")
    delete_tag(db, tag_id(db, "Remont"))
    assert get_transaction(db, transaction)["tags"] == ["Wakacje 2026"]
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_payment_can_be_tagged(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"))
    draft = payment_draft(db, recurring)
    transaction = pay_recurring(db, recurring, "expense", "2026-11-05", "Czynsz", draft["rows"], "Dom")
    assert get_transaction(db, transaction)["tags"] == ["Dom"]


def test_filters_and_search_by_tag(db):
    wallet = create_wallet(db, "A")
    other = create_wallet(db, "B")
    add(db, wallet, "Hotel", tags="Wakacje")
    add(db, wallet, "Chleb")
    create_transfer(db, wallet, other, "2026-11-05", "", "5")
    wakacje = tag_id(db, "Wakacje")
    entries, summary = load_entries(db, {wallet}, filters=EntryFilters(tag=wakacje))
    assert [e["item"]["description"] for e in entries] == ["Hotel"]
    assert summary["expense"] == {"PLN": 1000}
    found, _ = load_entries(db, {wallet}, filters=EntryFilters(text="wakac"))
    assert [e["item"]["description"] for e in found] == ["Hotel"]
    products, _ = load_products(db, {wallet}, filters=EntryFilters(tag=wakacje))
    assert len(products) == 1


def test_report_sums_tags_in_period(db):
    wallet = create_wallet(db, "A")
    add(db, wallet, price="100", tags="Wakacje, Rodzice")
    add(db, wallet, price="40", tags="Wakacje")
    add(db, wallet, price="25", tags="Wakacje", kind="income")
    add(db, wallet, price="999", tags="Wakacje", on="2026-10-31")
    tags = build_report(db, month="2026-11")["tags"]
    assert [(t["name"], t["transactions"], t["income"], t["expense"], t["net"]) for t in tags] == [
        ("Wakacje", 3, 2500, 14000, -11500),
        ("Rodzice", 1, 0, 10000, -10000),
    ]  # fmt: skip
    assert build_report(db, month="2026-12")["tags"] == []


def test_history_names_tags_and_transactions(db):
    wallet = create_wallet(db, "A")
    add(db, wallet, "Hotel", tags="Wakacje")
    text = history_text(db)
    assert "Dodano tag „Wakacje”" in text
    assert "Dodano tag transakcji „Wakacje” (transakcja: „Hotel”)" in text


def test_dialog_saves_and_copies_tags(db, errors):
    wallet = create_wallet(db, "A")
    dialog = TransactionDialog(db, get_wallet(db, wallet))
    dialog.table.cellWidget(0, dialog.NAME).setText("Hotel")
    dialog.table.cellWidget(0, dialog.PRICE).setText("300")
    dialog.tags.setText("Wakacje 2026, Rodzice")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert sorted(get_transaction(db, dialog.transaction_id)["tags"]) == ["Rodzice", "Wakacje 2026"]

    edit = TransactionDialog(db, get_wallet(db, wallet), dialog.transaction_id)
    assert edit.tags.text() in ("Wakacje 2026, Rodzice", "Rodzice, Wakacje 2026")
    copy = TransactionDialog(db, None, copy_from=dialog.transaction_id)
    assert copy.tags.text() == edit.tags.text()


def test_payment_dialog_has_tags_field(db, errors):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"))
    dialog = PaymentDialog(db, get_wallet(db, wallet), recurring)
    dialog.tags.setText("Dom")
    dialog.accept()
    assert get_transaction(db, dialog.transaction_id)["tags"] == ["Dom"]


def test_tags_edit_completes_current_tag(db, qapp):
    wallet = create_wallet(db, "A")
    add(db, wallet, tags="Wakacje 2026, Remont")
    edit = TagsEdit(db)
    edit.setText("Rodzice, wak")
    edit.setCursorPosition(len(edit.text()))
    assert edit._current_part() == (8, "wak")
    edit._suggest()
    assert edit.tag_completer.currentCompletion() == "Wakacje 2026"
    edit._insert("Wakacje 2026")
    assert edit.text() == "Rodzice, Wakacje 2026,"
    edit.setText("rem, Rodzice")
    edit.setCursorPosition(3)
    edit._insert("Remont")
    assert edit.text() == "Remont, Rodzice"


def test_lists_show_and_filter_tags(db, errors):
    wallet = create_wallet(db, "A")
    add(db, wallet, "Hotel", tags="Wakacje")
    add(db, wallet, "Chleb", on="2026-11-04")
    tab = WalletsTab(db)
    hotel = tab.tree.topLevelItem(0).child(0)
    assert hotel.text(DESCRIPTION) == "Hotel  · Wakacje"
    assert tab.filter_bar.tag.isVisibleTo(tab)
    tab.filter_bar.tag.setCurrentIndex(tab.filter_bar.tag.findText("Wakacje"))
    assert tab.tree.topLevelItemCount() == 1
    tab.filter_bar.clear()
    assert tab.tree.topLevelItemCount() == 2

    products = ProductsTab(db)
    products.filter_bar.tag.setCurrentIndex(products.filter_bar.tag.findText("Wakacje"))
    assert products.tree.topLevelItemCount() == 1


def test_tag_filter_is_hidden_without_tags(db, errors):
    create_wallet(db, "A")
    assert not WalletsTab(db).filter_bar.tag.isVisibleTo(None)


def test_reports_tab_shows_tag_section(db, errors):
    wallet = create_wallet(db, "A")
    tab = ReportsTab(db)
    tab.show_month("2026-11")
    assert not tab.tags_table.isVisibleTo(tab)
    add(db, wallet, tags="Wakacje")
    tab.refresh()
    assert tab.tags_table.isVisibleTo(tab)
    assert tab.tags_table.item(0, 0).text() == "Wakacje"


def test_categories_tab_manages_tags(db, errors, monkeypatch):
    wallet = create_wallet(db, "A")
    add(db, wallet, tags="Wakacje")
    tab = CategoriesTab(db)
    panel = tab.tags
    assert panel.table.rowCount() == 1 and panel.table.item(0, 1).text() == "1"
    assert not panel.rename_button.isEnabled()
    panel.table.setCurrentCell(0, 0)
    monkeypatch.setattr(
        "finanse.gui.tags_panel.QInputDialog.getText", lambda *_a, **_k: ("Urlop", True)
    )
    panel.rename()
    assert panel.table.item(0, 0).text() == "Urlop"
    panel.table.setCurrentCell(0, 0)
    panel.delete()
    assert panel.table.rowCount() == 0 and panel.empty.isVisibleTo(panel)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
