import pytest

from finanse.money import (
    format_money,
    format_money_input,
    format_precise_input,
    format_quantity,
    format_quantity_input,
    line_total,
    parse_money,
    parse_precise,
    parse_quantity,
    to_cents,
    unit_price,
)


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("12", 1200),
        ("12,5", 1250),
        ("12.50", 1250),
        ("1 234,56", 123456),
        ("1 234,56", 123456),
        ("-3,07", -307),
        ("0,29", 29),
    ],
)
def test_parse_money(text, cents):
    assert parse_money(text) == cents


@pytest.mark.parametrize(
    "text", ["", "abc", "1,234", "NaN", "Infinity", "1e5", "1,2,3", "9999999999"]
)
def test_parse_money_rejects(text):
    with pytest.raises(ValueError):
        parse_money(text)


@pytest.mark.parametrize(
    ("text", "value"),
    [("1", 100000), ("0,5", 50000), ("1.255", 125500), ("35,89123", 3589123), ("0,00001", 1)],
)
def test_parse_quantity(text, value):
    assert parse_quantity(text) == value


@pytest.mark.parametrize("text", ["0", "-1", "1,234567", "", "10000000", "0,00000"])
def test_parse_quantity_rejects(text):
    with pytest.raises(ValueError):
        parse_quantity(text)


@pytest.mark.parametrize(
    ("text", "value"),
    [("12", 1200000), ("6,19", 619000), ("6,19123", 619123), ("1 234,5", 123450000), ("-1,5", -150000)],
)
def test_parse_precise(text, value):
    assert parse_precise(text) == value


@pytest.mark.parametrize("text", ["", "abc", "1,123456", "9999999999"])
def test_parse_precise_rejects(text):
    with pytest.raises(ValueError):
        parse_precise(text)


def test_parse_money_still_allows_two_places_only():
    with pytest.raises(ValueError):
        parse_money("1,234")


def test_line_total_keeps_precision_and_rounds_half_up():
    assert line_total(150000, 333000) == 499500  # 4,995 zł
    assert line_total(100000, 199900) == 199900
    assert line_total(3589123, 619000) == 22216671  # 222,16671 zł
    assert line_total(1, 1) == 0
    assert line_total(50000, 1) == 1  # połowa w górę


@pytest.mark.parametrize(
    ("value", "cents"), [(0, 0), (499, 0), (500, 1), (499500, 500), (22216671, 22217), (100000, 100)]
)
def test_to_cents_rounds_half_up(value, cents):
    assert to_cents(value) == cents


def test_formatting():
    assert format_money(123456789, "PLN") == "1\xa0234\xa0567,89\xa0PLN"
    assert format_money(-5) == "-0,05"
    assert format_money_input(-123456) == "-1234,56"


@pytest.mark.parametrize(
    ("value", "text"),
    [(100000, "1"), (150000, "1,5"), (7238000, "72,38"), (125500, "1,26"), (124999, "1,25")],
)
def test_format_quantity_rounds_to_two_places(value, text):
    assert format_quantity(value) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [(100000, "1"), (150000, "1,5"), (125500, "1,255"), (3589123, "35,89123")],
)
def test_format_quantity_input_keeps_precision(value, text):
    assert format_quantity_input(value) == text


@pytest.mark.parametrize(
    ("value", "text"),
    [(0, "0,00"), (500000, "5,00"), (333000, "3,33"), (333333, "3,33333"), (125500, "1,255"), (-150000, "-1,50")],
)
def test_format_precise_input(value, text):
    assert format_precise_input(value) == text


@pytest.mark.parametrize(
    ("total", "quantity", "price"),
    [
        (1000000, 100000, 1000000),
        (1000000, 400000, 250000),
        (1000000, 300000, 333333),
        (2000000, 300000, 666667),
        (5, 200000, 3),  # połowa w górę
        (0, 100000, 0),
        (1000000, 50000, 2000000),  # pół sztuki
    ],
)
def test_unit_price(total, quantity, price):
    assert unit_price(total, quantity) == price
