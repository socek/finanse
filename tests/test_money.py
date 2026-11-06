import pytest

from finanse.money import (
    format_money,
    format_money_input,
    format_quantity,
    line_total,
    parse_money,
    parse_quantity,
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
    ("text", "milli"), [("1", 1000), ("0,5", 500), ("1.255", 1255)]
)
def test_parse_quantity(text, milli):
    assert parse_quantity(text) == milli


@pytest.mark.parametrize("text", ["0", "-1", "1,2345", "", "10000000"])
def test_parse_quantity_rejects(text):
    with pytest.raises(ValueError):
        parse_quantity(text)


def test_line_total_rounds_half_up():
    assert line_total(1500, 333) == 500  # 4,995 zł
    assert line_total(1000, 1999) == 1999
    assert line_total(333, 100) == 33


def test_formatting():
    assert format_money(123456789, "PLN") == "1 234 567,89 PLN"
    assert format_money(-5) == "-0,05"
    assert format_money_input(-123456) == "-1234,56"
    assert format_quantity(1000) == "1"
    assert format_quantity(1500) == "1,5"
    assert format_quantity(1255) == "1,255"
