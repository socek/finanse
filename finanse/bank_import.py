"""Import wyciągu: podgląd i zapis rekordów odczytanych przez csv_import."""

import csv
from pathlib import Path

from .csv_import import (
    cell,
    decode,
    detect_delimiter,
    parse_records,
    read_rows,
)
from .errors import ValidationError
from .transactions import insert_products


def load_file(path):
    """Treść pliku jako tekst oraz wykryty separator."""
    try:
        data = Path(path).read_bytes()
    except OSError as error:
        raise ValidationError(f"Nie udało się odczytać pliku: {error}") from None
    content = decode(data)
    return content, detect_delimiter(content)


def safe_rows(content, delimiter):
    try:
        return read_rows(content, delimiter)
    except csv.Error:
        return []


def column_options(rows, start):
    """Opcje wyboru kolumny: nazwa z nagłówka i przykładowa wartość."""
    data = rows[start:]
    width = max((len(row) for row in data), default=0)
    header = rows[start - 1] if 0 < start <= len(rows) else []
    example = data[0] if data else []
    options = []
    for index in range(width):
        name = cell(header, index) or f"Kolumna {index + 1}"
        sample = cell(example, index)[:30]
        options.append(
            {"index": index, "label": f"{name} ({sample})" if sample else name}
        )
    return options


def _existing_hashes(db, wallet_id):
    rows = db.execute(
        "SELECT import_hash FROM transactions"
        " WHERE wallet_id = ? AND import_hash IS NOT NULL",
        (wallet_id,),
    )
    return {row["import_hash"] for row in rows}


def _check_mapping(mapping):
    if len({mapping["date"], mapping["description"], mapping["amount"]}) < 3:
        raise ValidationError("Data, opis i kwota muszą pochodzić z różnych kolumn.")


def preview(db, wallet_id, rows, mapping):
    """Rekordy z oznaczonymi duplikatami oraz liczniki do podsumowania."""
    records = parse_records(rows, mapping)
    existing = _existing_hashes(db, wallet_id)
    for record in records:
        record["duplicate"] = record["hash"] in existing
    counts = {
        "new": sum(1 for r in records if r["hash"] and not r["duplicate"]),
        "duplicates": sum(1 for r in records if r["duplicate"]),
        "invalid": sum(1 for r in records if r["error"]),
    }
    return records, counts


def import_rows(db, wallet_id, rows, mapping, category_id=None):
    """Zapisuje poprawne rekordy; zwraca liczniki imported/duplicates/invalid."""
    _check_mapping(mapping)
    records = parse_records(rows, mapping)
    imported = duplicates = invalid = 0
    with db:
        for record in records:
            if record["error"]:
                invalid += 1
                continue
            cents = record["amount_cents"]
            cursor = db.execute(
                "INSERT OR IGNORE INTO transactions"
                " (wallet_id, kind, occurred_on, description, import_hash)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    wallet_id,
                    "income" if cents > 0 else "expense",
                    record["occurred_on"],
                    record["description"],
                    record["hash"],
                ),
            )
            if cursor.rowcount == 0:
                duplicates += 1
                continue
            insert_products(
                db,
                cursor.lastrowid,
                [
                    {
                        "name": record["description"],
                        "category_id": category_id,
                        "quantity_milli": 1000,
                        "unit_price_cents": abs(cents),
                        "total_cents": abs(cents),
                    }
                ],
            )
            imported += 1
    return {"imported": imported, "duplicates": duplicates, "invalid": invalid}
