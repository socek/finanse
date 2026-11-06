import pytest

from finanse.categories import (
    create_category,
    delete_category,
    list_categories,
    rename_category,
)
from finanse.errors import ValidationError
from finanse.reports import axis_scale, build_report
from finanse.transactions import (
    create_transaction,
    delete_transaction,
    get_transaction,
    update_transaction,
)
from finanse.transfers import create_transfer, delete_transfer, update_transfer
from finanse.wallets import (
    create_wallet,
    delete_wallet,
    get_wallet,
    list_wallets,
    load_entries,
    update_wallet,
)


def rows(*products):
    return [
        {"name": name, "quantity": quantity, "price": price, "category": category}
        for name, quantity, price, category in (
            (*product, None)[:4] for product in products
        )
    ]


def add(db, wallet, *products, kind="expense", on="2026-11-05"):
    return create_transaction(db, wallet, kind, on, "Zakupy", rows(*products))


def balance(db, wallet):
    return get_wallet(db, wallet)["balance_cents"]


def category_id(db, name):
    return db.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]


def test_many_wallets_with_unique_names(db):
    create_wallet(db, "Gotówka")
    create_wallet(db, "Konto", "eur", "12,50")
    assert [w["name"] for w in list_wallets(db)] == ["Gotówka", "Konto"]
    with pytest.raises(ValidationError, match="już portfel"):
        create_wallet(db, "gotówka")


@pytest.mark.parametrize(
    ("name", "currency", "initial", "message"),
    [
        ("", "PLN", "0", "nazwę"),
        ("A", "ZŁOTY", "0", "trzyliterowym"),
        ("A", "PLN", "abc", "saldo"),
    ],
)
def test_invalid_wallet(db, name, currency, initial, message):
    with pytest.raises(ValidationError, match=message):
        create_wallet(db, name, currency, initial)
    assert list_wallets(db) == []


def test_update_wallet(db):
    wallet = create_wallet(db, "A", "PLN", "1")
    update_wallet(db, wallet, "B", "EUR", "2,50")
    row = get_wallet(db, wallet)
    assert (row["name"], row["currency"], row["initial_balance_cents"]) == ("B", "EUR", 250)


def test_transaction_with_many_products_updates_balance(db):
    wallet = create_wallet(db, "A", "PLN", "100")
    add(db, wallet, ("Chleb", "2", "4,50"), ("Ser", "0,5", "39,99"), ("", "1", ""))
    assert db.execute(
        "SELECT name, quantity_milli, unit_price_cents, total_cents"
        " FROM products ORDER BY position"
    ).fetchall()[1][:] == ("Ser", 500, 3999, 2000)
    assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
    assert balance(db, wallet) == 7100
    add(db, wallet, ("Zwrot", "1", "10"), kind="income")
    assert balance(db, wallet) == 8100


@pytest.mark.parametrize(
    ("products", "message"),
    [
        ([("", "1", "")], "co najmniej jeden produkt"),
        ([("Chleb", "abc", "1")], "niepoprawna ilość"),
        ([("Chleb", "0", "1")], "niepoprawna ilość"),
        ([("Chleb", "1", "-5")], "niepoprawna cena"),
        ([("Chleb", "1", "")], "niepoprawna cena"),
        ([("", "1", "5")], "podaj nazwę"),
    ],
)
def test_invalid_products_save_nothing(db, products, message):
    wallet = create_wallet(db, "A")
    with pytest.raises(ValidationError, match=message):
        add(db, wallet, *products)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_invalid_date_and_category_are_rejected(db):
    wallet = create_wallet(db, "A")
    with pytest.raises(ValidationError, match="poprawną datę"):
        add(db, wallet, ("Chleb", "1", "1"), on="2026-13-45")
    with pytest.raises(ValidationError, match="niepoprawna kategoria"):
        add(db, wallet, ("Chleb", "1", "1", 99999))


def test_edit_replaces_products_and_keeps_import_hash(db):
    wallet = create_wallet(db, "A")
    food = category_id(db, "Jedzenie")
    transaction = add(db, wallet, ("Chleb", "1", "5", food), ("Ser", "1", "5"))
    db.execute("UPDATE transactions SET import_hash = 'h' WHERE id = ?", (transaction,))

    data = get_transaction(db, transaction)
    assert data["rows"][0] == {
        "name": "Chleb", "category": food, "quantity": "1", "price": "5,00",
    }  # fmt: skip

    update_transaction(
        db, transaction, "income", "2026-11-06", "Nowy", rows(("Mleko", "3", "2"))
    )
    data = get_transaction(db, transaction)
    assert (data["kind"], data["occurred_on"], data["description"]) == (
        "income", "2026-11-06", "Nowy",
    )  # fmt: skip
    assert [row["name"] for row in data["rows"]] == ["Mleko"]
    assert balance(db, wallet) == 600
    assert db.execute("SELECT import_hash FROM transactions").fetchone()[0] == "h"


def test_delete_transaction_and_wallet_cascade(db):
    wallet = create_wallet(db, "A", "PLN", "10")
    transaction = add(db, wallet, ("Chleb", "1", "5"))
    add(db, wallet, ("Ser", "1", "1"))
    delete_transaction(db, transaction)
    assert balance(db, wallet) == 900
    delete_wallet(db, wallet)
    assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0


def test_categories_create_rename_duplicate_delete(db):
    category = create_category(db, "Psy")
    with pytest.raises(ValidationError, match="już kategorię"):
        create_category(db, "psy")
    with pytest.raises(ValidationError, match="nazwę"):
        create_category(db, "  ")
    with pytest.raises(ValidationError, match="już kategorię"):
        rename_category(db, category, "Dom")
    rename_category(db, category, "Koty")
    assert "Koty" in [c["name"] for c in list_categories(db)]

    wallet = create_wallet(db, "A")
    add(db, wallet, ("Karma", "1", "5", category))
    assert next(c for c in list_categories(db) if c["name"] == "Koty")["product_count"] == 1
    delete_category(db, category)
    assert db.execute("SELECT category_id FROM products").fetchone()[0] is None


def test_date_filter_and_summary(db):
    wallet = create_wallet(db, "A")
    add(db, wallet, ("X", "1", "1"), on="2026-10-01")
    add(db, wallet, ("Y", "1", "2"), on="2026-11-01")
    add(db, wallet, ("Z", "1", "4"), kind="income", on="2026-11-02")
    entries, summary = load_entries(db, wallet, "2026-11-01", "2026-11-30")
    assert [e["item"]["occurred_on"] for e in entries] == ["2026-11-02", "2026-11-01"]
    assert summary == {"income": 400, "expense": 200}


def test_transfer_moves_money(db):
    source = create_wallet(db, "A", "PLN", "100")
    target = create_wallet(db, "B")
    transfer = create_transfer(db, source, target, "2026-11-05", "", "50")
    assert (balance(db, source), balance(db, target)) == (5000, 5000)
    assert load_entries(db, target)[0][0]["item"]["description"] == "Przelew"
    update_transfer(db, transfer, source, target, "2026-11-06", "Oszczędności", "30")
    assert balance(db, source) == 7000
    delete_transfer(db, transfer)
    assert balance(db, source) == 10000


def test_transfer_between_currencies_needs_both_amounts(db):
    source = create_wallet(db, "PLN", "PLN", "1000")
    target = create_wallet(db, "EUR", "EUR")
    with pytest.raises(ValidationError, match="różne waluty"):
        create_transfer(db, source, target, "2026-11-05", "", "430")
    create_transfer(db, source, target, "2026-11-05", "", "430", "100")
    assert (balance(db, source), balance(db, target)) == (57000, 10000)


@pytest.mark.parametrize(
    ("amount", "same", "message"),
    [
        ("0", False, "poprawną kwotę"),
        ("-5", False, "poprawną kwotę"),
        ("abc", False, "poprawną kwotę"),
        ("5", True, "muszą być różne"),
    ],
)
def test_invalid_transfers(db, amount, same, message):
    source = create_wallet(db, "A")
    target = source if same else create_wallet(db, "B")
    with pytest.raises(ValidationError, match=message):
        create_transfer(db, source, target, "2026-11-05", "", amount)


def test_wallet_with_transfers_cannot_be_deleted(db):
    source = create_wallet(db, "A", "PLN", "100")
    target = create_wallet(db, "B")
    transfer = create_transfer(db, source, target, "2026-11-05", "", "5")
    with pytest.raises(ValidationError, match="ma przelewy"):
        delete_wallet(db, target)
    delete_transfer(db, transfer)
    delete_wallet(db, target)
    assert len(list_wallets(db)) == 1


def test_report_totals_categories_and_month_boundaries(db):
    wallet = create_wallet(db, "A")
    food, home = category_id(db, "Jedzenie"), category_id(db, "Dom")
    add(db, wallet, ("Chleb", "1", "30", food), ("Mydło", "1", "10", home), ("I", "1", "60"),
        on="2026-11-30")  # fmt: skip
    add(db, wallet, ("Pensja", "1", "1000"), kind="income", on="2026-11-01")
    add(db, wallet, ("Poza", "1", "7"), on="2026-10-31")
    add(db, wallet, ("Poza", "1", "8"), on="2026-12-01")

    report = build_report(db, month="2026-11")
    assert report["month_title"] == "listopad 2026"
    assert (report["expense_total"], report["income_total"], report["net_total"]) == (
        10000, 100000, 90000,
    )  # fmt: skip
    assert report["expenses"][0]["name"] == "Bez kategorii"
    assert report["expenses"][0]["share"] == "60%"
    october = next(m for m in report["trend"]["months"] if m["key"] == "2026-10")
    assert october["expense"] == 700


def test_report_tiny_share_and_transfers(db):
    wallet = create_wallet(db, "A")
    other = create_wallet(db, "B")
    add(db, wallet, ("Dużo", "1", "1000"), ("Mało", "1", "1", category_id(db, "Dom")))
    create_transfer(db, wallet, other, "2026-11-05", "", "50")
    report = build_report(db, month="2026-11")
    assert report["expenses"][1]["share"] == "<1%"
    assert report["expense_total"] == 100100


def test_report_never_mixes_currencies(db):
    pln = create_wallet(db, "Złotówki")
    eur = create_wallet(db, "Euro", "EUR")
    add(db, pln, ("A", "1", "11"))
    add(db, eur, ("B", "1", "22"))
    report = build_report(db, "currency:PLN", "2026-11")
    assert (report["expense_total"], report["currency"]) == (1100, "PLN")
    report = build_report(db, f"wallet:{eur}", "2026-11")
    assert (report["expense_total"], report["currency"]) == (2200, "EUR")


@pytest.mark.parametrize(
    ("scope", "month"), [("", "abc"), ("", "2026-13"), ("zle", ""), ("wallet:999", "")]
)
def test_report_survives_bad_parameters(db, scope, month):
    create_wallet(db, "A")
    assert build_report(db, scope, month)["currency"] == "PLN"


def test_report_without_wallets(db):
    assert build_report(db) is None


@pytest.mark.parametrize(
    ("cents", "step", "maximum"),
    [
        (0, 1, 1),
        (50, 1, 1),
        (100_00, 20, 100),
        (1234_00, 500, 1500),
        (9_999_00, 2000, 10000),
        (123_456_00, 50000, 150000),
    ],
)
def test_axis_scale(cents, step, maximum):
    assert axis_scale(cents) == (step, maximum)
