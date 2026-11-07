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
from .import_rules import list_rules, matching_rule
from .money import PRECISE_UNIT
from .tags import parse_tags, set_transaction_tags
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


def _apply_rules(records, rules, category_id):
    """Dopisuje do rekordów kategorię, nazwę produktu i tagi z pierwszej pasującej reguły.

    Kategoria spoza reguły, wybrana w oknie importu, dotyczy rekordów bez reguły i reguł,
    które same kategorii nie ustawiają.
    """
    for record in records:
        cents = record["amount_cents"]
        kind = "income" if cents and cents > 0 else "expense"
        rule = matching_rule(rules, record["description"], kind) if not record["error"] else None
        record["rule"] = rule
        record["kind"] = kind
        rule_category = rule["category_id"] if rule else None
        record["category_id"] = rule_category if rule_category is not None else category_id
        record["product_name"] = (rule and rule["product_name"]) or record["description"]
        record["tags"] = parse_tags(rule["tags"])[0] if rule else []


def preview(db, wallet_id, rows, mapping, category_id=None):
    """Rekordy z oznaczonymi duplikatami i regułami oraz liczniki do podsumowania."""
    records = parse_records(rows, mapping)
    existing = _existing_hashes(db, wallet_id)
    for record in records:
        record["duplicate"] = record["hash"] in existing
    _apply_rules(records, list_rules(db), category_id)
    counts = {
        "new": sum(1 for r in records if r["hash"] and not r["duplicate"]),
        "duplicates": sum(1 for r in records if r["duplicate"]),
        "invalid": sum(1 for r in records if r["error"]),
        "matched": sum(
            1 for r in records if r["rule"] and r["hash"] and not r["duplicate"]
        ),
    }
    return records, counts


def import_rows(db, wallet_id, rows, mapping, category_id=None):
    """Zapisuje poprawne rekordy z regułami; zwraca liczniki imported/duplicates/invalid/matched."""
    _check_mapping(mapping)
    records = parse_records(rows, mapping)
    _apply_rules(records, list_rules(db), category_id)
    imported = duplicates = invalid = matched = 0
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
                    record["kind"],
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
                        "name": record["product_name"],
                        "category_id": record["category_id"],
                        "quantity_e5": PRECISE_UNIT,
                        "unit_price_e5": abs(cents) * 1000,
                        "total_e5": abs(cents) * 1000,
                        "total_cents": abs(cents),
                    }
                ],
            )
            if record["tags"]:
                set_transaction_tags(db, cursor.lastrowid, record["tags"])
            imported += 1
            matched += record["rule"] is not None
    return {
        "imported": imported,
        "duplicates": duplicates,
        "invalid": invalid,
        "matched": matched,
    }
