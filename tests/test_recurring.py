from datetime import date

import pytest

from helpers import priced

from finanse.errors import ValidationError
from finanse.recurring import (
    advance_due,
    count_due,
    create_recurring,
    days_until_due,
    delete_recurring,
    due_text,
    get_recurring,
    list_recurring,
    pay_recurring,
    payment_draft,
    period_text,
    recurring_totals,
    set_suspended,
    skip_due,
    update_recurring,
)
from finanse.transactions import delete_transaction, get_transaction
from finanse.wallets import create_wallet, delete_wallet, get_wallet


def category_id(db, name):
    return db.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]


def product(name="Woda", quantity="2", price="5", category=None):
    return {"name": name, "quantity": quantity, "price": price, "category": category}


def pay_draft(db, recurring_id, on="2026-11-05"):
    draft = payment_draft(db, recurring_id)
    return pay_recurring(
        db, recurring_id, draft["kind"], on, draft["description"], draft["rows"]
    )


def test_recurring_needs_wallet_but_not_products(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", " Czynsz ")
    saved = get_recurring(db, recurring)
    assert saved["description"] == "Czynsz"
    assert saved["remaining"] is None and saved["rows"] == []
    assert list_recurring(db)[0]["total_cents"] is None
    with pytest.raises(ValidationError, match="Wybierz portfel"):
        create_recurring(db, 999, "expense", "Czynsz")
    with pytest.raises(ValidationError, match="Wybierz portfel"):
        create_recurring(db, None, "expense", "Czynsz")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"description": ""}, "Podaj opis"),
        ({"kind": "x"}, "rodzaj"),
        ({"remaining": "-1"}, "Licznik"),
        ({"remaining": "1,5"}, "Licznik"),
        ({"rows": [product(category=9999)]}, "kategoria"),
        ({"rows": [product(quantity="abc")]}, "niepoprawna ilość"),
    ],
)
def test_invalid_recurring_saves_nothing(db, kwargs, message):
    wallet = create_wallet(db, "A")
    values = {"kind": "expense", "description": "Czynsz", **kwargs}
    with pytest.raises(ValidationError, match=message):
        create_recurring(db, wallet, **values)
    assert list_recurring(db) == []


def test_products_set_amount_and_categories(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(
        db, wallet, "expense", "Media",
        rows=[product(), product("Prąd", "1", "30", category_id(db, "Rachunki"))],
    )  # fmt: skip
    assert len(get_recurring(db, recurring)["rows"]) == 2
    row = list_recurring(db)[0]
    assert (row["product_count"], row["total_cents"]) == (2, 4000)
    assert row["product_categories"] == "Rachunki"
    assert row["wallet_name"] == "A" and row["currency"] == "PLN"


def test_payment_without_products_needs_amount_and_category_from_form(db):
    wallet = create_wallet(db, "A", "PLN", "100")
    dom = category_id(db, "Dom")
    recurring = create_recurring(db, wallet, "expense", "Czynsz")
    draft = payment_draft(db, recurring)
    assert draft["rows"] == [
        {"name": "Czynsz", "category": None, "quantity": "1", "price": ""}
    ]
    rows = [{**draft["rows"][0], "price": "30", "category": dom}]
    transaction = pay_recurring(db, recurring, "expense", "2026-11-05", "Czynsz", rows)
    saved = get_transaction(db, transaction)
    assert (saved["wallet_id"], saved["kind"], saved["occurred_on"]) == (
        wallet, "expense", "2026-11-05",
    )  # fmt: skip
    assert saved["rows"] == [
        {"name": "Czynsz", "category": dom, "quantity": "1", "price": "30,00", "total": "30,00",
         "vat_rate": None}
    ]
    assert get_wallet(db, wallet)["balance_cents"] == 7000
    assert get_recurring(db, recurring)["last_paid_on"] == "2026-11-05"


def test_payment_copies_products_and_income_kind(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "income", "Najem", rows=[product("X", "2", "5")])
    saved = get_transaction(db, pay_draft(db, recurring))
    assert saved["kind"] == "income"
    assert saved["rows"][0]["name"] == "X" and saved["rows"][0]["quantity"] == "2"
    assert get_wallet(db, wallet)["balance_cents"] == 1000


def test_given_value_passes_from_template_to_payment(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Media", rows=[
        {"name": "Woda", "category": None, "quantity": "3", "price": "3,33", "total": "10"},
    ])  # fmt: skip
    assert list_recurring(db)[0]["total_cents"] == 1000
    assert get_recurring(db, recurring)["rows"][0]["total"] == "10,00"
    pay_draft(db, recurring)
    assert get_wallet(db, wallet)["balance_cents"] == -1000


def test_counter_decreases_and_blocks_at_zero(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Rata", remaining="2", rows=priced("Rata", "10"))
    pay_draft(db, recurring)
    assert get_recurring(db, recurring)["remaining"] == 1
    pay_draft(db, recurring)
    assert get_recurring(db, recurring)["remaining"] == 0
    with pytest.raises(ValidationError, match="zera"):
        pay_draft(db, recurring)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2

    # Edycja może wznowić zakończoną transakcję.
    update_recurring(
        db, recurring, wallet, "expense", "Rata", remaining="1", rows=priced("Rata", "10")
    )
    pay_draft(db, recurring)
    assert get_recurring(db, recurring)["remaining"] == 0


def test_no_counter_means_no_limit(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"))
    for _ in range(3):
        pay_draft(db, recurring)
    assert get_recurring(db, recurring)["remaining"] is None
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 3


def test_invalid_payment_keeps_counter(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Prąd", remaining="2")
    with pytest.raises(ValidationError, match="niepoprawna cena"):
        pay_draft(db, recurring)  # kwota nie została podana
    assert get_recurring(db, recurring)["remaining"] == 2
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_backdated_payment_keeps_latest_paid_date(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"))
    pay_draft(db, recurring, "2026-11-05")
    pay_draft(db, recurring, "2026-10-05")
    assert get_recurring(db, recurring)["last_paid_on"] == "2026-11-05"


def test_deleting_template_keeps_paid_transactions(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Czynsz", rows=[product()])
    pay_draft(db, recurring)
    delete_recurring(db, recurring)
    assert list_recurring(db) == []
    assert db.execute("SELECT COUNT(*) FROM recurring_products").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_deleting_paid_transaction_does_not_restore_counter(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Rata", remaining="2", rows=priced("Rata", "10"))
    delete_transaction(db, pay_draft(db, recurring))
    assert get_recurring(db, recurring)["remaining"] == 1


def test_wallet_and_category_deletion(db):
    wallet = create_wallet(db, "A")
    dom = category_id(db, "Dom")
    create_recurring(db, wallet, "expense", "Media", rows=[product(category=dom)])
    with db:  # z konsoli, bo aplikacja nie usunie używanej kategorii
        db.execute("DELETE FROM categories WHERE id = ?", (dom,))
    assert db.execute("SELECT category_id FROM recurring_products").fetchone()[0] is None
    delete_wallet(db, wallet)
    assert list_recurring(db) == []
    assert db.execute("SELECT COUNT(*) FROM recurring_products").fetchone()[0] == 0


def monthly(on="2026-11-10", count="1", unit="month"):
    return {"unit": unit, "count": count, "next_due_on": on}


@pytest.mark.parametrize(
    ("due_on", "unit", "count", "due_day", "expected"),
    [
        ("2026-11-10", "day", 3, None, "2026-11-13"),
        ("2026-12-30", "week", 1, None, "2027-01-06"),
        ("2026-11-10", "month", 1, 10, "2026-12-10"),
        ("2026-11-10", "month", 3, 10, "2027-02-10"),
        ("2027-01-31", "month", 1, 31, "2027-02-28"),
        ("2027-02-28", "month", 1, 31, "2027-03-31"),
        ("2028-02-29", "year", 1, 29, "2029-02-28"),
        ("2029-02-28", "year", 3, 29, "2032-02-29"),
    ],
)
def test_advance_due(due_on, unit, count, due_day, expected):
    assert advance_due(due_on, unit, count, due_day) == expected


@pytest.mark.parametrize(
    ("unit", "count", "text"),
    [
        (None, 1, "bez terminu"),
        ("month", 1, "co miesiąc"),
        ("month", 3, "co 3 miesiące"),
        ("month", 5, "co 5 miesięcy"),
        ("week", 2, "co 2 tygodnie"),
        ("day", 12, "co 12 dni"),
        ("year", 22, "co 22 lata"),
        ("year", 14, "co 14 lat"),
    ],
)
def test_period_text(unit, count, text):
    assert period_text(unit, count) == text


def test_due_text():
    assert due_text(-1) == "po terminie 1 dzień"
    assert due_text(-3) == "po terminie 3 dni"
    assert due_text(0) == "dzisiaj"
    assert due_text(1) == "jutro"
    assert due_text(5) == "za 5 dni"


def test_schedule_is_saved_and_optional(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Czynsz", schedule=monthly())
    saved = get_recurring(db, recurring)
    assert (saved["next_due_on"], saved["period_unit"], saved["period_count"]) == (
        "2026-11-10", "month", 1,
    )  # fmt: skip
    assert saved["due_day"] == 10

    update_recurring(db, recurring, wallet, "expense", "Czynsz")
    saved = get_recurring(db, recurring)
    assert saved["next_due_on"] is saved["period_unit"] is saved["due_day"] is None


@pytest.mark.parametrize(
    ("schedule", "message"),
    [
        (monthly(unit="hour"), "okres powtarzania"),
        (monthly(count="0"), "Okres musi"),
        (monthly(count="1000"), "Okres musi"),
        (monthly(count="x"), "Okres musi"),
        (monthly(on="2026-13-01"), "termin"),
        (monthly(on=""), "termin"),
    ],
)
def test_invalid_schedule_saves_nothing(db, schedule, message):
    wallet = create_wallet(db, "A")
    with pytest.raises(ValidationError, match=message):
        create_recurring(db, wallet, "expense", "Czynsz", schedule=schedule)
    assert list_recurring(db) == []


def test_payment_moves_due_date_from_previous_due_date(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(
        db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"),
        schedule=monthly("2027-01-31"),
    )  # fmt: skip
    # Spóźniona płatność nie przesuwa kolejnych terminów.
    pay_draft(db, recurring, on="2027-02-15")
    assert get_recurring(db, recurring)["next_due_on"] == "2027-02-28"
    pay_draft(db, recurring, on="2027-02-20")
    assert get_recurring(db, recurring)["next_due_on"] == "2027-03-31"


def test_payment_without_schedule_keeps_no_due_date(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"))
    pay_draft(db, recurring)
    assert get_recurring(db, recurring)["next_due_on"] is None


def test_editing_without_changing_due_date_keeps_due_day(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(
        db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"),
        schedule=monthly("2027-01-31"),
    )  # fmt: skip
    pay_draft(db, recurring)
    update_recurring(
        db, recurring, wallet, "expense", "Czynsz i media", rows=priced("Czynsz", "10"),
        schedule=monthly("2027-02-28"),
    )  # fmt: skip
    assert get_recurring(db, recurring)["due_day"] == 31
    update_recurring(
        db, recurring, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"),
        schedule=monthly("2027-02-27"),
    )  # fmt: skip
    assert get_recurring(db, recurring)["due_day"] == 27


def test_skip_moves_due_date_without_payment(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(
        db, wallet, "expense", "Czynsz", remaining="2", schedule=monthly()
    )
    skip_due(db, recurring)
    saved = get_recurring(db, recurring)
    assert (saved["next_due_on"], saved["remaining"], saved["last_paid_on"]) == (
        "2026-12-10", 2, None,
    )  # fmt: skip
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0

    plain = create_recurring(db, wallet, "expense", "Bez terminu")
    with pytest.raises(ValidationError, match="nie ma terminu"):
        skip_due(db, plain)
    finished = create_recurring(
        db, wallet, "expense", "Koniec", remaining="0", schedule=monthly()
    )
    with pytest.raises(ValidationError, match="zera"):
        skip_due(db, finished)
    with pytest.raises(ValidationError, match="nie istnieje"):
        skip_due(db, 999)


def test_due_days_count_and_list_order(db):
    wallet = create_wallet(db, "A")
    today = date(2026, 11, 10)
    create_recurring(db, wallet, "expense", "Bez terminu")
    create_recurring(db, wallet, "expense", "Później", schedule=monthly("2026-11-20"))
    create_recurring(db, wallet, "expense", "Zaległa", schedule=monthly("2026-11-01"))
    create_recurring(db, wallet, "expense", "Dzisiaj", schedule=monthly("2026-11-10"))
    create_recurring(
        db, wallet, "expense", "Zakończona", remaining="0", schedule=monthly("2026-10-01")
    )
    items = list_recurring(db)
    assert [item["description"] for item in items] == [
        "Zaległa", "Dzisiaj", "Później", "Bez terminu", "Zakończona",
    ]  # fmt: skip
    assert [days_until_due(item, today) for item in items] == [-9, 0, 10, None, None]
    assert count_due(db, today) == 2


def test_suspended_is_not_due_summed_or_skippable_until_resumed(db):
    wallet = create_wallet(db, "A")
    today = date(2026, 11, 10)
    active = create_recurring(
        db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"), schedule=monthly("2026-11-20")
    )
    held = create_recurring(
        db, wallet, "expense", "Siłownia", rows=priced("Karnet", "99"), schedule=monthly("2026-11-01")
    )
    assert count_due(db, today) == 1
    set_suspended(db, held, True)

    items = list_recurring(db)
    assert [item["description"] for item in items] == ["Czynsz", "Siłownia"]
    assert days_until_due(items[1], today) is None
    assert count_due(db, today) == 0
    assert recurring_totals(items)["expense"] == {"PLN": 1000}
    with pytest.raises(ValidationError):
        skip_due(db, held)

    # Edycja nie wznawia, a termin czeka niezmieniony.
    update_recurring(
        db, held, wallet, "expense", "Karnet", rows=priced("Karnet", "99"),
        schedule=monthly("2026-11-01"),
    )  # fmt: skip
    assert get_recurring(db, held)["suspended"] == 1
    set_suspended(db, held, False)
    assert get_recurring(db, held)["next_due_on"] == "2026-11-01"
    assert count_due(db, today) == 1
    assert recurring_totals(list_recurring(db))["expense"] == {"PLN": 10900}
    assert get_recurring(db, active)["suspended"] == 0
