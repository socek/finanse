import sqlite3

CSRF = "test-token"


def post(client, url, **data):
    with client.session_transaction() as session:
        session["csrf_token"] = CSRF
    return client.post(url, data={"csrf_token": CSRF, **data})


def sign_up(client, username="anna", password="tajne-haslo"):
    response = post(client, "/register", username=username, password=password)
    assert response.status_code == 200
    assert "Zapisz kod odzyskiwania" in response.get_data(as_text=True)
    return response


def add_wallet(client, name="Gotówka", initial_balance="100,00", currency="PLN"):
    response = post(
        client,
        "/wallets/new",
        name=name,
        currency=currency,
        initial_balance=initial_balance,
    )
    assert response.status_code == 302
    return int(response.headers["Location"].rsplit("/", 1)[1])


def add_transaction(
    client,
    wallet_id,
    kind="expense",
    products=(("Chleb", "2", "4,50"),),
    occurred_on="2026-11-05",
    **extra,
):
    return post(
        client,
        f"/wallets/{wallet_id}/transactions/new",
        kind=kind,
        occurred_on=occurred_on,
        description="Zakupy",
        product_name=[p[0] for p in products],
        product_quantity=[p[1] for p in products],
        product_price=[p[2] for p in products],
        **extra,
    )


def query(app, sql, *args):
    connection = sqlite3.connect(app.config["DATABASE"])
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        return connection.execute(sql, args).fetchall()
    finally:
        connection.close()


def page(client, url):
    response = client.get(url)
    assert response.status_code == 200
    return response.get_data(as_text=True).replace(" ", " ")
