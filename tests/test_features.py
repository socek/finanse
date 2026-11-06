import re
import sqlite3
from importlib import resources

import pytest
from helpers import add_transaction, add_wallet, page, post, query, sign_up

from finanse import create_app
from finanse.db import DEFAULT_CATEGORIES
from finanse.reports import axis_scale


def category_id(app, name):
    return query(app, "SELECT id FROM categories WHERE name = ?", name)[0][0]


def recovery_code(response):
    html = response.get_data(as_text=True)
    return re.search(r"<code>([0-9A-F-]+)</code>", html).group(1)


# Migracje


def test_migration_keeps_existing_data_and_backs_it_up(tmp_path):
    path = tmp_path / "old.db"
    schema = (
        resources.files("finanse").joinpath("migrations/001_initial.sql").read_text()
    )
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.executescript(
        """
        INSERT INTO users (id, username, password_hash) VALUES (1, 'stary', 'x');
        INSERT INTO wallets (id, user_id, name, initial_balance_cents)
            VALUES (1, 1, 'Portfel', 1000);
        INSERT INTO transactions (id, wallet_id, kind, occurred_on, description)
            VALUES (1, 1, 'expense', '2026-11-01', 'Zakupy');
        INSERT INTO products
            (transaction_id, position, name, quantity_milli,
             unit_price_cents, total_cents)
            VALUES (1, 0, 'Chleb', 1000, 300, 300);
        """
    )
    connection.close()

    config = {"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(path)}
    app = create_app(config)
    create_app(config)  # drugie uruchomienie niczego nie zmienia

    assert query(app, "PRAGMA user_version") == [(2,)]
    assert query(app, "SELECT name, category_id FROM products") == [("Chleb", None)]
    assert query(app, "SELECT recovery_code_hash, session_epoch FROM users") == [
        (None, 0)
    ]
    migrated = query(app, "SELECT name FROM categories WHERE user_id = 1")
    assert sorted(name for (name,) in migrated) == sorted(DEFAULT_CATEGORIES)

    backup = sqlite3.connect(tmp_path / "old.db.backup-v0")
    assert backup.execute("SELECT COUNT(*) FROM products").fetchone() == (1,)
    assert backup.execute("PRAGMA user_version").fetchone() == (0,)
    backup.close()


def test_fresh_database_has_no_backup(tmp_path):
    create_app(
        {"TESTING": True, "SECRET_KEY": "t", "DATABASE": str(tmp_path / "new.db")}
    )
    assert [file.name for file in tmp_path.iterdir()] == ["new.db"]


# Kategorie


def test_new_user_gets_default_categories(app, client):
    rows = query(app, "SELECT name FROM categories ORDER BY name")
    assert sorted(name for (name,) in rows) == sorted(DEFAULT_CATEGORIES)


def test_category_create_rename_duplicate_delete(app, client):
    post(client, "/categories", name="Hobby")
    identifier = category_id(app, "Hobby")

    duplicate = client.post(
        "/categories", data={"csrf_token": "test-token", "name": "hobby"},
        follow_redirects=True,
    )
    assert "Masz już kategorię" in duplicate.get_data(as_text=True)

    post(client, f"/categories/{identifier}/rename", name="Pasje")
    assert query(app, "SELECT name FROM categories WHERE id = ?", identifier) == [
        ("Pasje",)
    ]


def test_deleting_category_keeps_products(app, client):
    wallet_id = add_wallet(client)
    food = category_id(app, "Jedzenie")
    add_transaction(client, wallet_id, product_category=[str(food)])
    assert query(app, "SELECT category_id FROM products") == [(food,)]

    post(client, f"/categories/{food}/delete")
    assert query(app, "SELECT name, category_id FROM products") == [("Chleb", None)]
    assert "Bez kategorii" in page(client, f"/wallets/{wallet_id}")


def test_products_in_one_transaction_can_have_different_categories(app, client):
    wallet_id = add_wallet(client)
    food, home = category_id(app, "Jedzenie"), category_id(app, "Dom")
    add_transaction(
        client,
        wallet_id,
        products=[("Chleb", "1", "4"), ("Mydło", "1", "6")],
        product_category=[str(food), str(home)],
    )
    assert query(app, "SELECT category_id FROM products ORDER BY position") == [
        (food,),
        (home,),
    ]
    transaction_id = query(app, "SELECT id FROM transactions")[0][0]
    form = page(client, f"/transactions/{transaction_id}/edit")
    assert f'<option value="{home}" selected>' in form


def test_someone_elses_category_is_rejected(app, client):
    other = app.test_client()
    sign_up(other, "ola")
    foreign = query(
        app,
        "SELECT c.id FROM categories c JOIN users u ON u.id = c.user_id"
        " WHERE u.username = 'ola' LIMIT 1",
    )[0][0]
    wallet_id = add_wallet(client)
    response = add_transaction(client, wallet_id, product_category=[str(foreign)])
    assert "niepoprawna kategoria" in response.get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(0,)]
    assert post(client, f"/categories/{foreign}/delete").status_code == 404
    assert post(client, f"/categories/{foreign}/rename", name="X").status_code == 404


# Filtr dat


def test_wallet_date_filter(client):
    wallet_id = add_wallet(client)
    add_transaction(client, wallet_id, products=[("Stary", "1", "1")], occurred_on="2026-01-15")
    add_transaction(client, wallet_id, products=[("Nowy", "1", "2")], occurred_on="2026-03-15")

    html = page(client, f"/wallets/{wallet_id}?date_from=2026-02-01&date_to=2026-03-31")
    assert "Nowy" in html and "Stary" not in html
    assert "wydatki 2,00 PLN" in html
    assert "97,00 PLN" in html  # saldo portfela pozostaje całkowite

    html = page(client, f"/wallets/{wallet_id}?date_to=2026-01-15")
    assert "Stary" in html and "Nowy" not in html


def test_wallet_invalid_date_filter_is_reported_and_ignored(client):
    wallet_id = add_wallet(client)
    add_transaction(client, wallet_id)
    html = page(client, f"/wallets/{wallet_id}?date_from=nonsens")
    assert "Niepoprawna data" in html and "Chleb" in html


# Przelewy


def transfer(client, source, target, amount="50", amount_to="", occurred_on="2026-11-05"):
    return post(
        client,
        "/transfers/new",
        from_wallet=source,
        to_wallet=target,
        occurred_on=occurred_on,
        description="",
        amount_from=amount,
        amount_to=amount_to,
    )


def test_transfer_moves_money_between_wallets(app, client):
    source = add_wallet(client, "A", "100")
    target = add_wallet(client, "B", "0")
    assert transfer(client, source, target).status_code == 302
    assert "50,00 PLN" in page(client, f"/wallets/{source}")
    assert "+50,00 PLN" in page(client, f"/wallets/{target}")
    assert "Przelew" in page(client, f"/wallets/{target}")


def test_transfer_between_currencies_needs_both_amounts(app, client):
    source = add_wallet(client, "PLN", "1000")
    target = add_wallet(client, "EUR", "0", "EUR")
    missing = transfer(client, source, target, "430")
    assert "różne waluty" in missing.get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) FROM transfers") == [(0,)]

    transfer(client, source, target, "430", "100")
    assert "570,00 PLN" in page(client, f"/wallets/{source}")
    assert "100,00 EUR" in page(client, f"/wallets/{target}")


@pytest.mark.parametrize(
    ("amount", "same_wallet", "message"),
    [
        ("0", False, "poprawną kwotę"),
        ("-5", False, "poprawną kwotę"),
        ("abc", False, "poprawną kwotę"),
        ("5", True, "muszą być różne"),
    ],
)
def test_invalid_transfers_are_rejected(app, client, amount, same_wallet, message):
    source = add_wallet(client, "A")
    target = source if same_wallet else add_wallet(client, "B")
    response = transfer(client, source, target, amount)
    assert message in response.get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) FROM transfers") == [(0,)]


def test_transfer_edit_and_delete(app, client):
    source = add_wallet(client, "A", "100")
    target = add_wallet(client, "B", "0")
    transfer(client, source, target, "50")
    transfer_id = query(app, "SELECT id FROM transfers")[0][0]

    post(
        client,
        f"/transfers/{transfer_id}/edit",
        from_wallet=source,
        to_wallet=target,
        occurred_on="2026-11-06",
        description="Oszczędności",
        amount_from="30",
        amount_to="",
    )
    assert query(app, "SELECT amount_from_cents, amount_to_cents FROM transfers") == [
        (3000, 3000)
    ]
    assert "70,00 PLN" in page(client, f"/wallets/{source}")

    post(client, f"/transfers/{transfer_id}/delete")
    assert "100,00 PLN" in page(client, f"/wallets/{source}")


def test_wallet_with_transfers_cannot_be_deleted(app, client):
    source = add_wallet(client, "A", "100")
    target = add_wallet(client, "B", "0")
    transfer(client, source, target)
    response = post(client, f"/wallets/{target}/delete")
    assert response.status_code == 302
    assert query(app, "SELECT COUNT(*) FROM wallets") == [(2,)]
    assert "ma przelewy" in page(client, f"/wallets/{target}")

    transfer_id = query(app, "SELECT id FROM transfers")[0][0]
    post(client, f"/transfers/{transfer_id}/delete")
    post(client, f"/wallets/{target}/delete")
    assert query(app, "SELECT COUNT(*) FROM wallets") == [(1,)]


def test_transfers_are_isolated_between_users(app, client):
    source = add_wallet(client, "A")
    target = add_wallet(client, "B")
    transfer(client, source, target)
    transfer_id = query(app, "SELECT id FROM transfers")[0][0]

    other = app.test_client()
    sign_up(other, "ola")
    own = add_wallet(other, "Moje")
    assert other.get(f"/transfers/{transfer_id}/edit").status_code == 404
    assert post(other, f"/transfers/{transfer_id}/delete").status_code == 404

    # Nie można też wyprowadzić pieniędzy z cudzego portfela.
    response = transfer(other, source, own)
    assert "Wybierz portfel" in response.get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) FROM transfers") == [(1,)]


# Raporty


def test_report_totals_categories_and_month_boundaries(app, client):
    wallet_id = add_wallet(client)
    food, home = category_id(app, "Jedzenie"), category_id(app, "Dom")
    add_transaction(
        client,
        wallet_id,
        products=[("Chleb", "1", "30"), ("Mydło", "1", "10"), ("Inne", "1", "60")],
        product_category=[str(food), str(home), ""],
        occurred_on="2026-11-30",
    )
    add_transaction(
        client, wallet_id, kind="income", products=[("Pensja", "1", "1000")],
        occurred_on="2026-11-01",
    )
    add_transaction(
        client, wallet_id, products=[("Poza", "1", "7")], occurred_on="2026-10-31"
    )
    add_transaction(
        client, wallet_id, products=[("Poza", "1", "8")], occurred_on="2026-12-01"
    )

    html = page(client, "/reports?month=2026-11")
    assert "listopad 2026" in html
    assert "100,00 PLN" in html  # wydatki
    assert "1 000,00 PLN" in html  # przychody
    assert "900,00 PLN" in html  # bilans
    assert "Bez kategorii" in html and "60%" in html
    assert "30,00 PLN" in html and "10,00 PLN" in html

    tips = re.findall(r'data-tip="(październik 2026[^"]*)"', html)
    assert tips and "Wydatki: 7,00 PLN" in tips[0].replace(" ", " ")


def test_report_shows_tiny_share_as_less_than_one_percent(app, client):
    wallet_id = add_wallet(client)
    food = category_id(app, "Jedzenie")
    add_transaction(
        client,
        wallet_id,
        products=[("Dużo", "1", "1000"), ("Mało", "1", "1")],
        product_category=["", str(food)],
    )
    html = page(client, "/reports?month=2026-11")
    assert "&lt;1%" in html and ">0%<" not in html


def test_report_excludes_transfers(app, client):
    source = add_wallet(client, "A", "100")
    target = add_wallet(client, "B", "0")
    transfer(client, source, target, "50", occurred_on="2026-11-05")
    html = page(client, "/reports?month=2026-11")
    assert "Brak wydatków" in html and "Brak transakcji" in html


def test_report_never_mixes_currencies(client):
    pln = add_wallet(client, "Złotówki")
    eur = add_wallet(client, "Euro", "0", "EUR")
    add_transaction(client, pln, products=[("A", "1", "11")])
    add_transaction(client, eur, products=[("B", "1", "22")])

    html = page(client, "/reports?month=2026-11&scope=currency:PLN")
    assert "11,00 PLN" in html and "22,00" not in html
    html = page(client, f"/reports?month=2026-11&scope=wallet:{eur}")
    assert "22,00 EUR" in html and "11,00" not in html


def test_report_rejects_someone_elses_wallet_scope(app, client):
    wallet_id = add_wallet(client)
    add_transaction(client, wallet_id, products=[("Tajne", "1", "123")])
    other = app.test_client()
    sign_up(other, "ola")
    add_wallet(other, "Moje", "0")
    html = page(other, f"/reports?month=2026-11&scope=wallet:{wallet_id}")
    assert "123,00" not in html


@pytest.mark.parametrize("params", ["month=abc", "month=2026-13", "scope=zle", ""])
def test_report_survives_bad_parameters(client, params):
    add_wallet(client)
    assert client.get(f"/reports?{params}").status_code == 200


def test_report_without_wallets(client):
    assert "Dodaj portfel" in page(client, "/reports")


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


# Konto i reset hasła


def login(client, password, username="anna"):
    return post(client, "/login", username=username, password=password)


def test_recovery_code_resets_password_once(app):
    client = app.test_client()
    code = recovery_code(sign_up(client))
    post(client, "/logout")

    response = post(
        client, "/reset-password", username="anna", code=code, password="nowe-haslo-1"
    )
    new_code = recovery_code(response)
    assert new_code != code
    assert client.get("/wallets").status_code == 200

    post(client, "/logout")
    assert login(client, "tajne-haslo").status_code == 200  # stare hasło nie działa
    assert login(client, "nowe-haslo-1").status_code == 302

    post(client, "/logout")
    again = post(
        client, "/reset-password", username="anna", code=code, password="kolejne-haslo"
    )
    assert "Niepoprawna nazwa" in again.get_data(as_text=True)


def test_recovery_code_ignores_formatting(app):
    client = app.test_client()
    code = recovery_code(sign_up(client))
    post(client, "/logout")
    sloppy = code.replace("-", " ").lower()
    response = post(
        client, "/reset-password", username="anna", code=sloppy, password="nowe-haslo-1"
    )
    assert "Zapisz kod odzyskiwania" in response.get_data(as_text=True)


@pytest.mark.parametrize(
    ("username", "code"),
    [("anna", "ZLYKOD"), ("nikt", "ZLYKOD"), ("anna", "")],
)
def test_reset_with_bad_data_gives_same_error(app, username, code):
    sign_up(app.test_client())
    client = app.test_client()
    response = post(
        client, "/reset-password", username=username, code=code, password="nowe-haslo-1"
    )
    assert "Niepoprawna nazwa użytkownika lub kod" in response.get_data(as_text=True)
    assert login(client, "tajne-haslo").status_code == 302


def test_account_without_code_cannot_use_reset(app):
    sign_up(app.test_client())
    connection = sqlite3.connect(app.config["DATABASE"])
    with connection:
        connection.execute("UPDATE users SET recovery_code_hash = NULL")
    connection.close()
    client = app.test_client()
    response = post(
        client, "/reset-password", username="anna", code="", password="nowe-haslo-1"
    )
    assert "Niepoprawna nazwa" in response.get_data(as_text=True)


def test_change_password_logs_out_other_sessions(app):
    first = app.test_client()
    sign_up(first)
    second = app.test_client()
    login(second, "tajne-haslo")
    assert second.get("/wallets").status_code == 200

    wrong = post(
        first, "/account/password", current_password="zle", new_password="nowe-haslo-1"
    )
    assert wrong.status_code == 302
    assert login(app.test_client(), "tajne-haslo").status_code == 302

    post(
        first,
        "/account/password",
        current_password="tajne-haslo",
        new_password="nowe-haslo-1",
    )
    assert first.get("/wallets").status_code == 200
    assert second.get("/wallets").status_code == 302
    assert login(app.test_client(), "nowe-haslo-1").status_code == 302


def test_regenerate_code_requires_password_and_invalidates_old(app):
    client = app.test_client()
    old = recovery_code(sign_up(client))
    rejected = post(client, "/account/recovery-code", current_password="zle")
    assert rejected.status_code == 302

    new = recovery_code(
        post(client, "/account/recovery-code", current_password="tajne-haslo")
    )
    assert new != old
    post(client, "/logout")
    response = post(
        client, "/reset-password", username="anna", code=old, password="nowe-haslo-1"
    )
    assert "Niepoprawna nazwa" in response.get_data(as_text=True)


def test_recovery_code_is_stored_hashed(app):
    code = recovery_code(sign_up(app.test_client()))
    stored = query(app, "SELECT recovery_code_hash FROM users")[0][0]
    assert code.replace("-", "") not in stored


def test_cli_reset_password(app):
    sign_up(app.test_client())
    runner = app.test_cli_runner()
    result = runner.invoke(
        args=["reset-password", "anna", "--password", "z-konsoli-123"]
    )
    assert result.exit_code == 0, result.output
    assert login(app.test_client(), "z-konsoli-123").status_code == 302

    assert runner.invoke(args=["reset-password", "nikt", "--password", "z-konsoli-123"]).exit_code != 0
    assert runner.invoke(args=["reset-password", "anna", "--password", "krotkie"]).exit_code != 0
