import pytest

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
