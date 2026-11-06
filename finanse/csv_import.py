"""Odczyt wyciągów bankowych w CSV: kodowanie, separator, kolumny, kwoty i daty."""

import csv
import hashlib
import io
import re
from collections import Counter
from datetime import date

from .money import parse_money

DELIMITERS = {";": "średnik", ",": "przecinek", "\t": "tabulator", "|": "kreska"}
FALLBACK_DESCRIPTION = "Import z banku"
MAX_DESCRIPTION_LENGTH = 200

_AMOUNT_WORDS = ("kwota", "amount", "wartość", "wartosc")
_NOT_AMOUNT_WORDS = ("saldo", "balance", "waluta", "currency")
_DESCRIPTION_WORDS = (
    "opis", "tytuł", "tytul", "description", "title",
    "kontrahent", "odbiorca", "nazwa", "payee",
)  # fmt: skip


def decode(data):
    """Banki w Polsce używają głównie UTF-8 albo Windows-1250."""
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            return data.decode(encoding).replace("\0", "")
        except UnicodeDecodeError:
            continue
    return data.decode("iso-8859-2").replace("\0", "")


def read_rows(text, delimiter):
    """Niepuste wiersze pliku jako listy komórek bez skrajnych spacji."""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    rows = [[cell.strip() for cell in row] for row in reader]
    return [row for row in rows if any(row)]


def detect_delimiter(text):
    """Wybiera separator, przy którym najwięcej wierszy ma tyle samo kolumn."""
    best, best_score = ";", (-1, -1)
    for delimiter in DELIMITERS:
        try:
            counts = Counter(len(row) for row in read_rows(text, delimiter))
        except csv.Error:
            continue
        for columns, rows in counts.items():
            score = (rows, columns)
            if columns >= 2 and score > best_score:
                best, best_score = delimiter, score
    return best


def parse_date(text):
    """Zwraca datę ISO albo None. Przy zapisie liczbowym dzień jest przed miesiącem."""
    first = text.strip().split(" ")[0].split("T")[0]
    match = re.fullmatch(r"([0-9]{4})[-./]([0-9]{1,2})[-./]([0-9]{1,2})", first)
    if match:
        year, month, day = match.groups()
    else:
        match = re.fullmatch(r"([0-9]{1,2})[-./]([0-9]{1,2})[-./]([0-9]{4})", first)
        if not match:
            return None
        day, month, year = match.groups()
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def parse_amount(text):
    """Kwota ze znakiem w groszach, np. z "-1.234,56 PLN"; None, gdy niepoprawna."""
    cleaned = re.sub(r"\s", "", text).replace("−", "-")
    cleaned = re.sub(r"(?i)(zł|[a-z]{3})$", "", cleaned)
    match = re.fullmatch(
        r"([+-]?)"
        r"([0-9]{1,3}(?:([.,'])[0-9]{3})(?:\3[0-9]{3})*|[0-9]+)"
        r"(?:([.,])([0-9]{1,2}))?",
        cleaned,
    )
    if match is None:
        return None
    sign, whole, group_separator, decimal_separator, fraction = match.groups()
    if group_separator and group_separator == decimal_separator:
        return None
    whole = re.sub(r"[^0-9]", "", whole)
    try:
        cents = parse_money(f"{whole}.{fraction or '0'}")
    except ValueError:
        return None
    return -cents if sign == "-" else cents


def cell(row, index):
    return row[index] if 0 <= index < len(row) else ""


def _find_by_header(header, words, skip_words=(), exclude=()):
    for word in words:
        for index, name in enumerate(header):
            lowered = name.lower()
            if (
                index not in exclude
                and word in lowered
                and not any(skip in lowered for skip in skip_words)
            ):
                return index
    return None


def detect_mapping(rows):
    """Zgaduje pierwszy wiersz danych i kolumny; użytkownik może to poprawić."""
    start = 0
    for index, row in enumerate(rows):
        dates = [i for i, value in enumerate(row) if parse_date(value)]
        amounts = [
            i
            for i, value in enumerate(row)
            if i not in dates and parse_amount(value) is not None
        ]
        if dates and amounts:
            start = index
            break
    else:
        return {"start": 0, "date": 0, "description": 1, "amount": 2}

    first = rows[start]
    header = rows[start - 1] if start > 0 else []
    date_column = next(i for i, value in enumerate(first) if parse_date(value))

    amount_column = _find_by_header(
        header, _AMOUNT_WORDS, _NOT_AMOUNT_WORDS, exclude=(date_column,)
    )
    if amount_column is None or parse_amount(cell(first, amount_column)) is None:
        candidates = [
            i
            for i, value in enumerate(first)
            if not parse_date(value) and parse_amount(value) is not None
        ]
        with_fraction = [i for i in candidates if re.search(r"[.,]", first[i])]
        amount_column = (with_fraction or candidates)[0]

    description_column = _find_by_header(
        header, _DESCRIPTION_WORDS, exclude=(date_column, amount_column)
    )
    if description_column is None:
        others = [i for i in range(len(first)) if i not in (date_column, amount_column)]
        description_column = max(others, key=lambda i: len(first[i]), default=0)

    return {
        "start": start,
        "date": date_column,
        "description": description_column,
        "amount": amount_column,
    }


def parse_records(rows, mapping):
    """Zamienia wiersze na rekordy; niepoprawne mają ustawione pole `error`."""
    records = []
    seen = Counter()
    for number, row in enumerate(rows[mapping["start"] :], mapping["start"] + 1):
        occurred_on = parse_date(cell(row, mapping["date"]))
        amount = parse_amount(cell(row, mapping["amount"]))
        description = " ".join(cell(row, mapping["description"]).split())
        description = description[:MAX_DESCRIPTION_LENGTH] or FALLBACK_DESCRIPTION
        record = {
            "line": number,
            "occurred_on": occurred_on,
            "description": description,
            "amount_cents": amount,
            "error": None,
            "hash": None,
        }
        if occurred_on is None:
            record["error"] = "brak poprawnej daty"
        elif amount is None:
            record["error"] = "brak poprawnej kwoty"
        elif amount == 0:
            record["error"] = "kwota zerowa"
        else:
            # Dwa identyczne wiersze w pliku to dwie operacje, np. dwa takie same
            # bilety, więc odcisk uwzględnia numer powtórzenia.
            key = (occurred_on, amount, description)
            fingerprint = f"{occurred_on}|{amount}|{description}|{seen[key]}"
            seen[key] += 1
            record["hash"] = hashlib.sha256(fingerprint.encode()).hexdigest()
        records.append(record)
    return records
