import io
import re

import pytest
from helpers import CSRF, add_wallet, page, post, query, sign_up

from finanse.csv_import import (
    decode,
    detect_delimiter,
    detect_mapping,
    parse_amount,
    parse_date,
    parse_records,
    read_rows,
)

# Układ podobny do polskich wyciągów: nagłówek z metadanymi, średnik, stopka.
BANK_CSV = """Wyciąg z rachunku;;;;
Numer;12 3456;;;

#Data operacji;#Opis operacji;#Rachunek;#Kwota;#Saldo po operacji;
2026-11-03;"Biedronka; Warszawa";Główny;-45,50 PLN;954,50 PLN;
04-11-2026;Wynagrodzenie;Główny;5 000,00 PLN;5 954,50 PLN;
05.11.2026;Bilet;Główny;-4,40;5 950,10;
05.11.2026;Bilet;Główny;-4,40;5 945,70;
Razem;;;;5 945,70 PLN;
"""


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("12,50", 1250),
        ("-12.50", -1250),
        ("+3", 300),
        ("−7,5", -750),
        ("1 234,56", 123456),
        ("1 234,56 zł", 123456),
        ("1.234,56", 123456),
        ("1,234.56", 123456),
        ("1,234", 123400),
        ("-1 234 567,89 PLN", -123456789),
        ("0,00", 0),
    ],
)
def test_parse_amount(text, cents):
    assert parse_amount(text) == cents


@pytest.mark.parametrize(
    "text",
    ["", "abc", "1.2.3", "12,345,6", "1,234,56", "1.234,567.00", "2026-11-05", "1e5"],
)
def test_parse_amount_rejects(text):
    assert parse_amount(text) is None


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("2026-11-05", "2026-11-05"),
        ("2026.11.05", "2026-11-05"),
        ("05.11.2026", "2026-11-05"),
        ("05-11-2026", "2026-11-05"),
        ("5/11/2026", "2026-11-05"),
        ("2026-11-05 13:45:00", "2026-11-05"),
        ("2026-11-05T13:45:00", "2026-11-05"),
    ],
)
def test_parse_date(text, iso):
    assert parse_date(text) == iso


@pytest.mark.parametrize("text", ["", "abc", "31.02.2026", "2026-13-01", "12,50"])
def test_parse_date_rejects(text):
    assert parse_date(text) is None


def test_decode_handles_polish_encodings():
    text = "Zażółć gęślą jaźń"
    assert decode(text.encode("utf-8")) == text
    assert decode(b"\xef\xbb\xbf" + text.encode("utf-8")) == text
    assert decode(text.encode("cp1250")) == text


@pytest.mark.parametrize(
    ("text", "delimiter"),
    [
        ("a;b;c\n1,5;2,5;3,5\n", ";"),
        ("a,b,c\n1,2,3\n", ","),
        ("a\tb\tc\n1\t2\t3\n", "\t"),
    ],
)
def test_detect_delimiter(text, delimiter):
    assert detect_delimiter(text) == delimiter


def test_detect_mapping_skips_preamble_and_ignores_balance():
    rows = read_rows(BANK_CSV, ";")
    mapping = detect_mapping(rows)
    assert rows[mapping["start"]][0] == "2026-11-03"
    assert mapping["date"] == 0
    assert mapping["description"] == 1
    assert mapping["amount"] == 3


def test_detect_mapping_without_header():
    rows = [["1001", "2026-11-05", "Sklep", "-12,50"]]
    mapping = detect_mapping(rows)
    assert (mapping["date"], mapping["description"], mapping["amount"]) == (1, 2, 3)


def test_parse_records_marks_invalid_rows_and_repeats():
    rows = read_rows(BANK_CSV, ";")
    records = parse_records(rows, detect_mapping(rows))
    assert [r["amount_cents"] for r in records[:4]] == [-4550, 500000, -440, -440]
    assert records[0]["description"] == "Biedronka; Warszawa"
    assert records[2]["hash"] != records[3]["hash"]
    assert records[4]["error"] == "brak poprawnej daty"


def upload(client, wallet_id, content=BANK_CSV, encoding="utf-8", filename="wyciag.csv"):
    with client.session_transaction() as session:
        session["csrf_token"] = CSRF
    return client.post(
        f"/wallets/{wallet_id}/import",
        data={
            "csrf_token": CSRF,
            "file": (io.BytesIO(content.encode(encoding)), filename),
        },
        content_type="multipart/form-data",
    )


def confirm(client, wallet_id, content=BANK_CSV, action="import", **overrides):
    rows = read_rows(content, ";")
    mapping = detect_mapping(rows)
    data = {
        "content": content,
        "delimiter": ";",
        "start": mapping["start"] + 1,
        "date_column": mapping["date"],
        "description_column": mapping["description"],
        "amount_column": mapping["amount"],
        "category": "",
        "action": action,
    }
    data.update(overrides)
    return post(client, f"/wallets/{wallet_id}/import/confirm", **data)


def test_upload_shows_preview_without_saving(app, client):
    wallet_id = add_wallet(client)
    response = upload(client, wallet_id)
    html = response.get_data(as_text=True).replace(" ", " ")
    assert response.status_code == 200
    assert "Biedronka; Warszawa" in html
    assert "-45,50 PLN" in html
    assert re.search(r"Nowe: <strong>4</strong>", html)
    assert re.search(r"niepoprawne wiersze: <strong>1</strong>", html)
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(0,)]


def test_upload_accepts_cp1250(client):
    wallet_id = add_wallet(client)
    content = "Data;Opis;Kwota\n2026-11-03;Żabka Łódź;-5,00\n"
    html = upload(client, wallet_id, content, "cp1250").get_data(as_text=True)
    assert "Żabka Łódź" in html


def test_import_creates_transactions_and_updates_balance(app, client):
    wallet_id = add_wallet(client, initial_balance="0")
    response = confirm(client, wallet_id)
    assert response.status_code == 302

    rows = query(
        app,
        "SELECT t.kind, t.occurred_on, t.description, p.name, p.quantity_milli,"
        " p.unit_price_cents, p.total_cents"
        " FROM transactions t JOIN products p ON p.transaction_id = t.id"
        " ORDER BY t.id",
    )
    assert len(rows) == 4
    assert rows[0] == (
        "expense", "2026-11-03", "Biedronka; Warszawa", "Biedronka; Warszawa",
        1000, 4550, 4550,
    )
    assert rows[1][0] == "income" and rows[1][1] == "2026-11-04"
    html = page(client, f"/wallets/{wallet_id}")
    assert "4 945,70 PLN" in html  # 5000 - 45,50 - 4,40 - 4,40
    assert "Zaimportowano transakcje: 4" in html
    assert "niepoprawne wiersze: 1" in html


def test_reimport_skips_duplicates_but_keeps_new_rows(app, client):
    wallet_id = add_wallet(client, initial_balance="0")
    confirm(client, wallet_id)
    confirm(client, wallet_id)
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(4,)]
    assert "Pominięte duplikaty: 4" in page(client, f"/wallets/{wallet_id}")

    html = upload(client, wallet_id).get_data(as_text=True)
    assert re.search(r"duplikaty: <strong>4</strong>", html)

    extended = BANK_CSV + "06.11.2026;Bilet;Główny;-4,40;0;\n"
    confirm(client, wallet_id, extended)
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(5,)]


def test_same_file_may_be_imported_into_another_wallet(app, client):
    first = add_wallet(client, "A")
    second = add_wallet(client, "B")
    confirm(client, first)
    confirm(client, second)
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(8,)]


def test_import_with_category(app, client):
    wallet_id = add_wallet(client)
    food = query(app, "SELECT id FROM categories WHERE name = 'Jedzenie'")[0][0]
    confirm(client, wallet_id, category=str(food))
    assert query(app, "SELECT DISTINCT category_id FROM products") == [(food,)]


def test_import_rejects_foreign_category_and_same_columns(app, client):
    wallet_id = add_wallet(client)
    other = app.test_client()
    sign_up(other, "ola")
    foreign = query(
        app,
        "SELECT c.id FROM categories c JOIN users u ON u.id = c.user_id"
        " WHERE u.username = 'ola' LIMIT 1",
    )[0][0]
    response = confirm(client, wallet_id, category=str(foreign))
    assert "Niepoprawna kategoria" in response.get_data(as_text=True)
    response = confirm(client, wallet_id, amount_column=0, date_column=0)
    assert "różnych kolumn" in response.get_data(as_text=True)
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(0,)]


def test_preview_action_does_not_save(app, client):
    wallet_id = add_wallet(client)
    response = confirm(client, wallet_id, action="preview")
    assert response.status_code == 200
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(0,)]


def test_import_escapes_file_content(client):
    wallet_id = add_wallet(client)
    content = "Data;Opis;Kwota\n2026-11-03;<script>x</script>;-5,00\n"
    html = upload(client, wallet_id, content).get_data(as_text=True)
    assert "<script>x</script>" not in html


def test_upload_rejects_too_large_and_missing_files(client):
    wallet_id = add_wallet(client)
    big = "a" * (2 * 1024 * 1024 + 1)
    assert "zbyt duży" in upload(client, wallet_id, big).get_data(as_text=True)
    response = post(client, f"/wallets/{wallet_id}/import")
    assert "Wybierz plik" in response.get_data(as_text=True)
    response = upload(client, wallet_id, "")
    assert "Nie udało się" in response.get_data(as_text=True)


def test_import_is_isolated_between_users(app, client):
    wallet_id = add_wallet(client)
    other = app.test_client()
    sign_up(other, "ola")
    assert other.get(f"/wallets/{wallet_id}/import").status_code == 404
    assert upload(other, wallet_id).status_code == 404
    assert confirm(other, wallet_id).status_code == 404
    assert query(app, "SELECT COUNT(*) FROM transactions") == [(0,)]
