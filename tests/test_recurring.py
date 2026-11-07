import pytest

from helpers import priced

from finanse.categories import delete_category
from finanse.errors import ValidationError
from finanse.recurring import (
    create_recurring,
    delete_recurring,
    get_recurring,
    list_recurring,
    pay_recurring,
    payment_draft,
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
        {"name": "Czynsz", "category": dom, "quantity": "1", "price": "30,00", "total": "30,00"}
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
    delete_category(db, dom)
    assert db.execute("SELECT category_id FROM recurring_products").fetchone()[0] is None
    delete_wallet(db, wallet)
    assert list_recurring(db) == []
    assert db.execute("SELECT COUNT(*) FROM recurring_products").fetchone()[0] == 0
