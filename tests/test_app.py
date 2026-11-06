import pytest
from helpers import CSRF, add_transaction, add_wallet, page, post, query, sign_up


def test_anonymous_user_is_redirected_to_login(app):
    response = app.test_client().get("/wallets")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_register_login_logout(app):
    client = app.test_client()
    sign_up(client)
    post(client, "/logout")
    assert client.get("/wallets").status_code == 302

    bad = post(client, "/login", username="anna", password="zle-haslo")
    assert "Niepoprawna nazwa" in bad.get_data(as_text=True)

    good = post(client, "/login", username="ANNA", password="tajne-haslo")
    assert good.status_code == 302
    assert client.get("/wallets").status_code == 200


def test_duplicate_username_and_short_password_are_rejected(app):
    first = app.test_client()
    sign_up(first)
    second = app.test_client()
    taken = post(second, "/register", username="Anna", password="tajne-haslo")
    assert "już zajęta" in taken.get_data(as_text=True)
    short = post(second, "/register", username="ola", password="krotkie")
    assert "co najmniej" in short.get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) FROM users") == [(1,)]


@pytest.mark.parametrize(
    "data", [{}, {"csrf_token": "zly"}, {"csrf_token": "zażółć"}]
)
def test_post_without_valid_csrf_token_is_rejected(client, data):
    with client.session_transaction() as session:
        session["csrf_token"] = CSRF
    response = client.post(
        "/wallets/new", data={"name": "X", "currency": "PLN", **data}
    )
    assert response.status_code == 400


def test_user_can_have_many_wallets(client):
    add_wallet(client, "Gotówka", "100,00")
    add_wallet(client, "Konto", "2 500,50", "EUR")
    html = page(client, "/wallets")
    assert "Gotówka" in html and "100,00 PLN" in html
    assert "Konto" in html and "2 500,50 EUR" in html


def test_wallet_name_must_be_unique_per_user(app, client):
    add_wallet(client, "Gotówka")
    duplicate = post(
        client, "/wallets/new", name="gotówka", currency="PLN", initial_balance="0"
    )
    assert "Masz już portfel" in duplicate.get_data(as_text=True)

    other = app.test_client()
    sign_up(other, "ola")
    add_wallet(other, "Gotówka")


def test_invalid_wallet_form_keeps_values(client):
    response = post(
        client, "/wallets/new", name="Konto", currency="ZŁ", initial_balance="abc"
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "trzyliterowym" in html and "Niepoprawne saldo" in html
    assert 'value="Konto"' in html


def test_transaction_with_many_products_updates_balance(app, client):
    wallet_id = add_wallet(client, initial_balance="100,00")
    response = add_transaction(
        client,
        wallet_id,
        products=[("Chleb", "2", "4,50"), ("Ser", "0,5", "39,99"), ("", "1", "")],
    )
    assert response.status_code == 302

    rows = query(
        app,
        "SELECT name, quantity_milli, unit_price_cents, total_cents"
        " FROM products ORDER BY position",
    )
    assert rows == [("Chleb", 2000, 450, 900), ("Ser", 500, 3999, 2000)]

    html = page(client, f"/wallets/{wallet_id}")
    assert "Chleb" in html and "Ser" in html
    assert "71,00 PLN" in html  # 100 - 9 - 20

    add_transaction(client, wallet_id, kind="income", products=[("Zwrot", "1", "10")])
    assert "81,00 PLN" in page(client, f"/wallets/{wallet_id}")


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
def test_invalid_products_save_nothing(app, client, products, message):
    wallet_id = add_wallet(client)
    response = add_transaction(client, wallet_id, products=products)
    assert response.status_code == 200
    assert message in response.get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(0,)]


def test_invalid_row_keeps_entered_values(client):
    wallet_id = add_wallet(client)
    response = add_transaction(
        client, wallet_id, products=[("Chleb", "2", "abc"), ("Ser", "1", "5")]
    )
    html = response.get_data(as_text=True)
    assert 'value="abc"' in html and 'value="Ser"' in html


def test_invalid_date_is_rejected(app, client):
    wallet_id = add_wallet(client)
    response = post(
        client,
        f"/wallets/{wallet_id}/transactions/new",
        kind="expense",
        occurred_on="2026-13-45",
        description="Zakupy",
        product_name="Chleb",
        product_quantity="1",
        product_price="1",
    )
    assert "poprawną datę" in response.get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(0,)]


def test_edit_transaction_replaces_products(app, client):
    wallet_id = add_wallet(client)
    add_transaction(client, wallet_id, products=[("Chleb", "1,5", "4,50"), ("Ser", "1", "20")])
    transaction_id = query(app, "SELECT id FROM transactions")[0][0]

    form = page(client, f"/transactions/{transaction_id}/edit")
    assert 'value="1,5"' in form and 'value="4,50"' in form

    response = post(
        client,
        f"/transactions/{transaction_id}/edit",
        kind="income",
        occurred_on="2026-11-01",
        description="Zwrot",
        product_name="Mleko",
        product_quantity="1",
        product_price="3",
    )
    assert response.status_code == 302
    assert query(app, "SELECT name FROM products") == [("Mleko",)]
    assert query(app, "SELECT kind, occurred_on, description FROM transactions") == [
        ("income", "2026-11-01", "Zwrot")
    ]
    assert "103,00 PLN" in page(client, f"/wallets/{wallet_id}")


def test_delete_transaction_restores_balance(app, client):
    wallet_id = add_wallet(client)
    add_transaction(client, wallet_id)
    transaction_id = query(app, "SELECT id FROM transactions")[0][0]
    post(client, f"/transactions/{transaction_id}/delete")
    assert query(app, "SELECT COUNT(*) FROM products") == [(0,)]
    assert "100,00 PLN" in page(client, f"/wallets/{wallet_id}")


def test_delete_wallet_removes_transactions_and_products(app, client):
    wallet_id = add_wallet(client)
    add_transaction(client, wallet_id)
    post(client, f"/wallets/{wallet_id}/delete")
    assert query(app, "SELECT COUNT(*) FROM wallets") == [(0,)]
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(0,)]
    assert query(app, "SELECT COUNT(*) FROM products") == [(0,)]


def test_user_cannot_touch_someone_elses_data(app, client):
    wallet_id = add_wallet(client)
    add_transaction(client, wallet_id)
    transaction_id = query(app, "SELECT id FROM transactions")[0][0]

    other = app.test_client()
    sign_up(other, "ola")

    assert other.get(f"/wallets/{wallet_id}").status_code == 404
    assert other.get(f"/wallets/{wallet_id}/edit").status_code == 404
    assert other.get(f"/wallets/{wallet_id}/transactions/new").status_code == 404
    assert other.get(f"/transactions/{transaction_id}/edit").status_code == 404
    assert post(other, f"/wallets/{wallet_id}/delete").status_code == 404
    assert post(other, f"/transactions/{transaction_id}/delete").status_code == 404
    assert add_transaction(other, wallet_id).status_code == 404

    assert query(app, "SELECT COUNT(*) FROM wallets") == [(1,)]
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(1,)]


def test_user_content_is_escaped(client):
    wallet_id = add_wallet(client, "<script>x</script>")
    assert "<script>x</script>" not in page(client, f"/wallets/{wallet_id}")
