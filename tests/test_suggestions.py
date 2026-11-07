import pytest

from finanse.gui import common
from finanse.gui.dialogs import RecurringDialog, TransactionDialog
from finanse.suggestions import last_purchase, product_names
from finanse.transactions import create_transaction
from finanse.wallets import VAT, create_wallet, get_wallet


def category_id(db, name):
    return db.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]


def buy(db, wallet, on, name, price, category=None, vat_rate=None, kind="expense"):
    row = {"name": name, "quantity": "1", "price": price, "category": category}
    if vat_rate is not None:
        row["vat_rate"] = vat_rate
    create_transaction(db, wallet, kind, on, "Zakupy", [row])


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    return collected


def test_names_by_frequency_then_recency_in_latest_spelling(db):
    wallet = create_wallet(db, "A")
    buy(db, wallet, "2026-01-01", "masło", "6")
    buy(db, wallet, "2026-01-02", "Chleb", "4")
    buy(db, wallet, "2026-01-03", "Masło ", "7")
    buy(db, wallet, "2026-01-04", "Mleko", "3")
    buy(db, wallet, "2026-01-05", "Pensja", "100", kind="income")
    assert product_names(db) == ["Masło", "Pensja", "Mleko", "Chleb"]


def test_last_purchase_uses_matching_currency_and_vat_wallet(db):
    pln = create_wallet(db, "Złotówki")
    eur = create_wallet(db, "Euro", "EUR")
    firm = create_wallet(db, "Firma", wallet_type=VAT)
    food, home = category_id(db, "Jedzenie"), category_id(db, "Dom")
    buy(db, firm, "2026-01-01", "Kawa", "40", food, vat_rate=8)
    buy(db, pln, "2026-01-02", "kawa", "30", home)
    buy(db, eur, "2026-01-03", "KAWA", "9")

    found = last_purchase(db, "Kawa", "PLN")
    assert found == {
        "category_id": None, "unit_price_e5": 3000000, "has_vat_rate": True, "vat_rate": 8,
    }  # fmt: skip
    assert last_purchase(db, "kawa", "EUR")["unit_price_e5"] == 900000
    assert last_purchase(db, "kawa", "USD")["unit_price_e5"] is None
    assert last_purchase(db, "Herbata", "PLN") is None


def test_no_vat_rate_without_vat_purchase(db):
    wallet = create_wallet(db, "A")
    buy(db, wallet, "2026-01-01", "Kawa", "30")
    assert last_purchase(db, "Kawa", "PLN")["has_vat_rate"] is False


def _row(dialog, index=0):
    return {
        column: dialog.table.cellWidget(index, column)
        for column in (dialog.NAME, dialog.CATEGORY, dialog.PRICE, dialog.VALUE, dialog.VAT_RATE)
    }


def test_choosing_a_name_fills_empty_fields(db, errors):
    wallet = create_wallet(db, "A")
    food = category_id(db, "Jedzenie")
    buy(db, wallet, "2026-01-01", "Masło", "6,49", food)
    dialog = TransactionDialog(db, get_wallet(db, wallet))
    row = _row(dialog)
    completer = row[dialog.NAME].completer()
    completer.setCompletionPrefix("sło")
    assert completer.currentCompletion() == "Masło"

    row[dialog.NAME].setText("Masło")
    completer.activated.emit("Masło")
    assert row[dialog.CATEGORY].selected_category() == food
    assert row[dialog.PRICE].text() == "6,49"
    assert row[dialog.VALUE].text() == "6,49"
    assert "6,49" in dialog.total.text()


def test_suggestion_never_overwrites_typed_values(db, errors):
    wallet = create_wallet(db, "A")
    food, home = category_id(db, "Jedzenie"), category_id(db, "Dom")
    buy(db, wallet, "2026-01-01", "Masło", "6,49", food)
    dialog = TransactionDialog(db, get_wallet(db, wallet))
    row = _row(dialog)
    row[dialog.CATEGORY].setCurrentIndex(row[dialog.CATEGORY].findData(home))
    row[dialog.PRICE].setText("8")
    row[dialog.NAME].setText("masło")
    row[dialog.NAME].editingFinished.emit()
    assert row[dialog.CATEGORY].selected_category() == home
    assert row[dialog.PRICE].text() == "8"

    row[dialog.NAME].setText("Nieznany")
    row[dialog.NAME].editingFinished.emit()
    assert row[dialog.PRICE].text() == "8"


def test_vat_rate_is_suggested_in_vat_wallet(db, errors):
    firm = create_wallet(db, "Firma", wallet_type=VAT)
    buy(db, firm, "2026-01-01", "Kawa", "40", vat_rate=8)
    dialog = TransactionDialog(db, get_wallet(db, firm))
    row = _row(dialog)
    row[dialog.NAME].setText("Kawa")
    row[dialog.NAME].editingFinished.emit()
    assert row[dialog.VAT_RATE].currentData() == 8
    assert row[dialog.PRICE].text() == "40,00"


def test_recurring_dialog_gets_suggestions_too(db, errors):
    wallet = create_wallet(db, "A")
    buy(db, wallet, "2026-01-01", "Czynsz", "2100", category_id(db, "Dom"))
    dialog = RecurringDialog(db)
    row = _row(dialog)
    assert dialog.product_names.stringList() == ["Czynsz"]
    row[dialog.NAME].setText("czynsz")
    row[dialog.NAME].editingFinished.emit()
    assert row[dialog.PRICE].text() == "2100,00"
