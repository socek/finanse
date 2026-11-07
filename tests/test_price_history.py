import pytest
from PySide6.QtCore import QPointF

from finanse.gui import common
from finanse.gui.price_history import PriceHistoryDialog, _change_text
from finanse.gui.products_tab import NAME, ProductsTab
from finanse.price_history import normalize_name, price_history
from finanse.transactions import create_transaction
from finanse.wallets import create_wallet


def buy(db, wallet, on, shop, price, quantity="1", name="Masło", kind="expense"):
    create_transaction(db, wallet, kind, on, shop, [
        {"name": name, "quantity": quantity, "price": price, "category": None},
    ])  # fmt: skip


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    return collected


def test_normalize_name():
    assert normalize_name("  MASŁO   Extra ") == normalize_name("masło extra")


def test_history_matches_name_and_summarizes(db):
    wallet = create_wallet(db, "A")
    buy(db, wallet, "2026-01-05", "Biedronka", "6", quantity="2")
    buy(db, wallet, "2026-02-03", "Lidl", "5", name="masło ")
    buy(db, wallet, "2026-03-10", "Biedronka", "7,5")
    buy(db, wallet, "2026-03-11", "Lidl", "9", name="Masło roślinne")
    buy(db, wallet, "2026-03-12", "Zwrot", "1", kind="income")

    [history] = price_history(db, "MASŁO")
    assert history["currency"] == "PLN"
    assert [e["occurred_on"] for e in history["entries"]] == [
        "2026-01-05", "2026-02-03", "2026-03-10",
    ]  # fmt: skip
    assert history["cheapest"]["shop"] == "Lidl"
    assert history["dearest"]["unit_price_e5"] == 750000
    assert history["last"]["occurred_on"] == "2026-03-10"
    # Średnia zapłacona: (12 + 5 + 7,5) / 4 sztuki.
    assert history["average_e5"] == 612500
    assert history["change_percent"] == pytest.approx(25)
    assert [(s["shop"], s["count"], s["average_e5"]) for s in history["shops"]] == [
        ("Lidl", 1, 500000), ("Biedronka", 2, 650000),
    ]  # fmt: skip
    assert history["shops"][1]["min_e5"] == 600000
    assert history["shops"][1]["last_on"] == "2026-03-10"


def test_currencies_are_separate_and_most_used_first(db):
    pln = create_wallet(db, "Złotówki")
    eur = create_wallet(db, "Euro", "EUR")
    buy(db, pln, "2026-01-01", "A", "6")
    buy(db, eur, "2026-01-02", "B", "2")
    buy(db, eur, "2026-01-03", "B", "3")
    histories = price_history(db, "Masło")
    assert [h["currency"] for h in histories] == ["EUR", "PLN"]
    assert [len(h["entries"]) for h in histories] == [2, 1]


def test_unknown_product_has_no_history(db):
    create_wallet(db, "A")
    assert price_history(db, "Nic") == []


def test_change_text():
    assert _change_text(None) == "–"
    assert _change_text(0.01) == "bez zmian"
    assert _change_text(23.08) == "+23,1%"
    assert _change_text(-5) == "−5,0%"


def test_dialog_shows_history_and_switches_currency(db, errors):
    pln = create_wallet(db, "Złotówki")
    eur = create_wallet(db, "Euro", "EUR")
    buy(db, pln, "2026-01-05", "Biedronka", "6")
    buy(db, pln, "2026-02-05", "Lidl", "5")
    buy(db, eur, "2026-01-02", "Aldi", "2")
    dialog = PriceHistoryDialog(db, "masło")
    assert dialog.windowTitle() == "Historia ceny: masło"
    assert dialog.currency.currentText() == "PLN"
    assert dialog.stats["cheapest"][0].text().replace("\xa0", " ") == "5,00 PLN"
    assert dialog.stats["cheapest"][1].text() == "2026-02-05, Lidl"
    assert dialog.stats["change"][0].text() == "−16,7%"
    assert dialog.shops.item(0, 0).text() == "Lidl" and dialog.shops.item(0, 0).font().bold()
    assert dialog.purchases.item(0, 0).text() == "2026-02-05"

    dialog.chart.resize(600, 220)
    assert not dialog.chart.grab().isNull()
    points = dialog.chart._points()
    assert points[0].x() < points[1].x() and points[0].y() < points[1].y()
    assert dialog.chart._nearest(points[1] + QPointF(5, 40)) == 1
    assert dialog.chart._nearest(QPointF(-100, 0)) is None

    dialog.currency.setCurrentIndex(1)
    assert dialog.purchases.rowCount() == 1
    assert "EUR" in dialog.stats["last"][0].text()
    assert dialog.stats["change"][0].text() == "bez zmian"


def test_dialog_for_unknown_product(db, errors):
    dialog = PriceHistoryDialog(db, "Nic")
    assert dialog.empty.isVisibleTo(dialog) and not dialog.content.isVisibleTo(dialog)


def test_products_tab_opens_history_of_selected_product(db, errors, monkeypatch):
    wallet = create_wallet(db, "A")
    buy(db, wallet, "2026-01-05", "Biedronka", "6")
    opened = []
    monkeypatch.setattr(PriceHistoryDialog, "exec", lambda dialog: opened.append(dialog) or 0)
    tab = ProductsTab(db)
    assert not tab.price_button.isEnabled()
    product = tab.tree.topLevelItem(0).child(0)
    tab.tree.setCurrentItem(product)
    assert tab.price_button.isEnabled()
    assert product.text(NAME) == "Masło"
    tab.price_button.click()
    assert opened[0].windowTitle() == "Historia ceny: Masło"
