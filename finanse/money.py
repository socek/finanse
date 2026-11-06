"""Parsowanie i formatowanie kwot oraz ilości na liczbach całkowitych."""

import re

MAX_AMOUNT_CENTS = 10**11  # 1 mld w jednostkach waluty
MAX_QUANTITY_MILLI = 10**9  # milion sztuk
MAX_TRANSACTION_CENTS = 10**12

NBSP = " "


def _parse_fixed(text, places):
    """Zamienia tekst typu "1 234,5" na liczbę całkowitą z `places` miejscami."""
    cleaned = re.sub(r"\s", "", text).replace(",", ".")
    match = re.fullmatch(rf"(-?)([0-9]{{1,15}})(?:\.([0-9]{{1,{places}}}))?", cleaned)
    if match is None:
        raise ValueError(text)
    sign, whole, fraction = match.groups()
    value = int(whole) * 10**places + int((fraction or "").ljust(places, "0"))
    return -value if sign else value


def parse_money(text):
    cents = _parse_fixed(text, 2)
    if abs(cents) > MAX_AMOUNT_CENTS:
        raise ValueError(text)
    return cents


def parse_quantity(text):
    milli = _parse_fixed(text, 3)
    if not 0 < milli <= MAX_QUANTITY_MILLI:
        raise ValueError(text)
    return milli


def line_total(quantity_milli, unit_price_cents):
    """Wartość pozycji w groszach, zaokrąglona połowę w górę."""
    return (quantity_milli * unit_price_cents + 500) // 1000


def unit_price(total_cents, quantity_milli):
    """Cena jednostkowa w groszach dla podanej wartości, zaokrąglona połowę w górę."""
    return (2000 * total_cents + quantity_milli) // (2 * quantity_milli)


def format_money(cents, currency=""):
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    grouped = f"{whole:,}".replace(",", NBSP)
    text = f"{sign}{grouped},{fraction:02d}"
    return f"{text}{NBSP}{currency}" if currency else text


def format_totals(totals, sign=""):
    """Kwoty w wielu walutach, np. "10,00 PLN, 5,00 EUR"; walut nigdy nie sumujemy."""
    return ", ".join(
        f"{sign}{format_money(cents, currency)}"
        for currency, cents in sorted(totals.items())
    )


def format_money_input(cents):
    """Kwota do pola formularza, bez separatorów tysięcy."""
    sign = "-" if cents < 0 else ""
    whole, fraction = divmod(abs(cents), 100)
    return f"{sign}{whole},{fraction:02d}"


def format_quantity(milli):
    whole, fraction = divmod(milli, 1000)
    if fraction == 0:
        return str(whole)
    return f"{whole},{fraction:03d}".rstrip("0")
