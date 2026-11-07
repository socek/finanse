from datetime import date, timedelta

import pytest
from helpers import priced
from PySide6.QtCore import QDate

from finanse.forecast import balance_forecast, end_of_month, scheduled_payments
from finanse.gui import common
from finanse.gui.forecast_dialog import ForecastDialog
from finanse.gui.wallets_tab import WalletsTab
from finanse.recurring import create_recurring
from finanse.transactions import create_transaction
from finanse.transfers import create_transfer
from finanse.wallets import create_wallet

TODAY = date(2026, 11, 10)


def schedule(on, unit="month", count=1):
    return {"unit": unit, "count": count, "next_due_on": on}


def spend(db, wallet, on, price, kind="expense"):
    create_transaction(db, wallet, kind, on, "X", priced("X", price))


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    return collected


def test_end_of_month():
    assert end_of_month(date(2026, 2, 3)) == date(2026, 2, 28)
    assert end_of_month(date(2028, 2, 29)) == date(2028, 2, 29)


def test_payments_repeat_until_the_day_and_respect_counter(db):
    wallet = create_wallet(db, "A")
    create_recurring(db, wallet, "expense", "Basen", rows=priced("Basen", "20"),
                     schedule=schedule("2026-11-03", "week"))
    create_recurring(db, wallet, "expense", "Rata", remaining="2", rows=priced("Rata", "100"),
                     schedule=schedule("2026-11-12", "week"))
    create_recurring(db, wallet, "expense", "Grudzień", rows=priced("G", "1"),
                     schedule=schedule("2026-12-01"))
    create_recurring(db, wallet, "expense", "Bez terminu", rows=priced("B", "1"))
    create_recurring(db, wallet, "expense", "Koniec", remaining="0", rows=priced("K", "1"),
                     schedule=schedule("2026-11-01"))
    payments = scheduled_payments(db, date(2026, 11, 30), TODAY)
    assert [(p["description"], p["due_on"], p["overdue"]) for p in payments] == [
        ("Basen", "2026-11-03", True),
        ("Basen", "2026-11-10", False),
        ("Rata", "2026-11-12", False),
        ("Basen", "2026-11-17", False),
        ("Rata", "2026-11-19", False),
        ("Basen", "2026-11-24", False),
    ]


def test_forecast_adds_future_entries_and_recurring(db):
    home = create_wallet(db, "Dom", "PLN", "1000")
    savings = create_wallet(db, "Oszczędności", "PLN", "500")
    euro = create_wallet(db, "Euro", "EUR", "10")
    spend(db, home, "2026-11-05", "100")
    spend(db, home, "2026-11-20", "50")  # już wpisana z późniejszą datą
    spend(db, home, "2026-12-05", "999")  # po dniu prognozy
    create_transfer(db, home, savings, "2026-11-25", "", "200")
    create_recurring(db, home, "income", "Pensja", rows=priced("Pensja", "3000"),
                     schedule=schedule("2026-11-28"))
    create_recurring(db, home, "expense", "Czynsz", rows=priced("Czynsz", "1500"),
                     schedule=schedule("2026-11-01"))  # zaległy
    create_recurring(db, home, "expense", "Prąd", schedule=schedule("2026-11-15"))

    forecast = balance_forecast(db, date(2026, 11, 30), TODAY)
    wallets = {w["name"]: w for w in forecast["wallets"]}
    dom = wallets["Dom"]
    assert dom["balance"] == 90000
    assert dom["planned"] == -25000
    assert (dom["recurring_income"], dom["recurring_expense"]) == (300000, 150000)
    assert dom["unknown"] == 1
    assert dom["forecast"] == 90000 - 25000 + 300000 - 150000
    assert wallets["Oszczędności"]["forecast"] == 70000
    assert forecast["totals"]["PLN"] == {"balance": 140000, "forecast": 285000}
    assert forecast["totals"]["EUR"]["forecast"] == 1000
    assert forecast["unknown"] == 1

    only_savings = balance_forecast(db, date(2026, 11, 30), TODAY, wallet_ids={savings})
    assert [w["name"] for w in only_savings["wallets"]] == ["Oszczędności"]
    assert only_savings["payments"] == [] and only_savings["unknown"] == 0
    assert euro in {w["id"] for w in forecast["wallets"]}


def test_forecast_defaults_to_end_of_month_and_never_looks_back(db):
    create_wallet(db, "A")
    assert balance_forecast(db, today=TODAY)["until"] == "2026-11-30"
    assert balance_forecast(db, date(2026, 1, 1), TODAY)["until"] == "2026-11-10"


def test_forecast_dialog(db, errors):
    today = date.today()
    wallet = create_wallet(db, "A", "PLN", "100")
    other = create_wallet(db, "B", "PLN", "5")
    create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "500"),
                     schedule=schedule((today - timedelta(days=1)).isoformat()))
    create_recurring(db, wallet, "expense", "Prąd", schedule=schedule(today.isoformat()))
    dialog = ForecastDialog(db)
    assert common.iso_date(dialog.until) == end_of_month(today).isoformat()
    assert dialog.wallets.rowCount() == 3  # dwa portfele i suma PLN
    forecast_cell = dialog.wallets.item(0, 5)
    assert forecast_cell.text().replace("\xa0", " ") == "-400,00 PLN *"
    assert forecast_cell.background().color() == common.overdue_background()
    assert dialog.wallets.item(2, 0).text() == "Razem PLN"
    assert dialog.payments.rowCount() == 2
    assert "po terminie 1 dzień" in dialog.payments.item(0, 0).text()
    assert dialog.payments.item(1, 3).text() == "ustalana przy płatności"
    assert dialog.unknown_note.isVisibleTo(dialog)

    dialog.until.setDate(QDate(today.year, today.month, today.day))
    assert dialog.forecast["until"] == today.isoformat()

    only_b = ForecastDialog(db, {other})
    assert only_b.wallets.rowCount() == 1
    assert only_b.no_payments.isVisibleTo(only_b)


def test_wallets_tab_shows_forecast_of_checked_wallets(db, errors, monkeypatch):
    today = date.today()
    wallet = create_wallet(db, "A", "PLN", "100")
    create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "30"),
                     schedule=schedule(today.isoformat()))
    tab = WalletsTab(db)
    text = tab.forecast.text().replace("\xa0", " ")
    assert text == f"Prognoza na koniec miesiąca ({end_of_month(today)}): 70,00 PLN"

    opened = []
    monkeypatch.setattr(ForecastDialog, "exec", lambda dialog: opened.append(dialog) or 0)
    tab.forecast_button.click()
    assert opened[0].wallet_ids == {wallet}

    tab.wallet_list.set_all_checked(False)
    assert not tab.forecast.isVisibleTo(tab)
