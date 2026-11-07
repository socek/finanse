"""Parsowanie i formatowanie kwot oraz ilości na liczbach całkowitych."""

import re

MAX_AMOUNT_CENTS = 10**11  # 1 mld w jednostkach waluty
MAX_QUANTITY_E5 = 10**11  # milion sztuk
PRECISE_PLACES = 5
PRECISE_UNIT = 10**PRECISE_PLACES
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


def parse_precise(text):
    """Kwota w stutysięcznych, np. cena produktu z 5 miejscami po przecinku."""
    value = _parse_fixed(text, PRECISE_PLACES)
    if abs(value) > MAX_AMOUNT_CENTS * 1000:
        raise ValueError(text)
    return value


def parse_quantity(text):
    """Ilość w stutysięcznych, zawsze dodatnia."""
    value = _parse_fixed(text, PRECISE_PLACES)
    if not 0 < value <= MAX_QUANTITY_E5:
        raise ValueError(text)
    return value


def line_total(quantity_e5, unit_price_e5):
    """Wartość pozycji w stutysięcznych, zaokrąglona połowę w górę."""
    return (quantity_e5 * unit_price_e5 + PRECISE_UNIT // 2) // PRECISE_UNIT


def unit_price(total_e5, quantity_e5):
    """Cena jednostkowa w stutysięcznych dla podanej wartości, zaokrąglona połowę w górę."""
    return (2 * PRECISE_UNIT * total_e5 + quantity_e5) // (2 * quantity_e5)


def to_cents(value_e5):
    """Grosze, czyli to, co liczy się do sald; połowa grosza idzie w górę."""
    return (value_e5 + 500) // 1000


def gross_from_net(net, rate):
    """Brutto z netto przy stawce w procentach; pusta stawka to brak VAT."""
    if not rate:
        return net
    return (net * (100 + rate) + 50) // 100


def net_from_gross(gross, rate):
    """Netto z brutto, zaokrąglone połowę w górę; działa w każdej skali kwot."""
    if not rate:
        return gross
    return (2 * gross * 100 + 100 + rate) // (2 * (100 + rate))


def vat_from_gross(gross_cents, rate):
    """VAT w groszach taki, żeby netto i VAT zawsze sumowały się do brutto."""
    return gross_cents - net_from_gross(gross_cents, rate)


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


def _format_fixed(value, places, min_places):
    sign = "-" if value < 0 else ""
    whole, fraction = divmod(abs(value), 10**places)
    digits = f"{fraction:0{places}d}".rstrip("0").ljust(min_places, "0")
    return f"{sign}{whole},{digits}" if digits else f"{sign}{whole}"


def format_precise_input(value_e5):
    """Cena lub wartość do pola formularza: co najmniej 2 miejsca, bez utraty dokładności."""
    return _format_fixed(value_e5, PRECISE_PLACES, 2)


def format_quantity_input(quantity_e5):
    """Ilość do pola formularza, bez zbędnych zer."""
    return _format_fixed(quantity_e5, PRECISE_PLACES, 0)


def format_quantity(quantity_e5):
    """Ilość na listach, zaokrąglona do 2 miejsc."""
    return _format_fixed(to_cents(quantity_e5), 2, 0)
