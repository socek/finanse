"""Tekstowy widok dziennika zmian."""

import json
from collections import Counter
from datetime import datetime, timezone

from .money import format_money, format_precise_input, format_quantity_input

MAX_ROWS = 2000
ACTIONS = {"insert": "Dodano", "update": "Zmieniono", "delete": "Usunięto"}
NOUNS = {
    "wallets": "portfel",
    "categories": "kategorię",
    "transactions": "transakcję",
    "products": "produkt",
    "transfers": "przelew",
    "recurring_transactions": "transakcję cykliczną",
    "recurring_products": "produkt transakcji cyklicznej",
}
TITLE_FIELDS = {
    "wallets": "name",
    "categories": "name",
    "transactions": "description",
    "products": "name",
    "transfers": "description",
    "recurring_transactions": "description",
    "recurring_products": "name",
}
# Produkty usuwane i dodawane na nowo przy zapisie rachunku nie są prawdziwą zmianą.
REPLACED_ON_SAVE = ("products", "recurring_products")


def _money(value, _names):
    return format_money(value)


def _kind(value, _names):
    return {"income": "przychód", "expense": "wydatek"}.get(value, value)


def _precise(value, _names):
    return format_precise_input(value)


def _precise_quantity(value, _names):
    return format_quantity_input(value)


def _old_quantity(value, _names):
    """Starsze wpisy dziennika mają ilość w tysięcznych."""
    return format_quantity_input(value * 100)


def _wallet(value, names):
    return names["wallets"].get(value, f"nr {value}")


def _category(value, names):
    return names["categories"].get(value, f"nr {value}")


def _text(value, _names):
    return f"„{value}”"


def _plain(value, _names):
    return str(value)


def _vat_rate(value, _names):
    return f"{value}%"


def _wallet_type(value, _names):
    return {"vat": "z VAT", "plain": "zwykły"}.get(value, value)


_PRODUCT_FIELDS = (
    ("name", "nazwa", _text, "brak"),
    ("category_id", "kategoria", _category, "bez kategorii"),
    ("quantity_e5", "ilość", _precise_quantity, "brak"),
    ("quantity_milli", "ilość", _old_quantity, "brak"),
    ("unit_price_e5", "cena", _precise, "brak"),
    ("unit_price_cents", "cena", _money, "brak"),
    ("total_e5", "wartość", _precise, "brak"),
    ("total_cents", "wartość", _money, "brak"),
    ("vat_rate", "VAT", _vat_rate, "zw."),
    ("vat_cents", "kwota VAT", _money, "brak"),
)
FIELDS = {
    "wallets": (
        ("name", "nazwa", _text, "brak"),
        ("currency", "waluta", _plain, "brak"),
        ("initial_balance_cents", "saldo początkowe", _money, "brak"),
        ("wallet_type", "typ", _wallet_type, "zwykły"),
    ),
    "categories": (("name", "nazwa", _text, "brak"),),
    "transactions": (
        ("wallet_id", "portfel", _wallet, "brak"),
        ("kind", "rodzaj", _kind, "brak"),
        ("occurred_on", "data", _plain, "brak"),
        ("description", "opis", _text, "brak"),
    ),
    "products": _PRODUCT_FIELDS,
    "transfers": (
        ("from_wallet_id", "z portfela", _wallet, "brak"),
        ("to_wallet_id", "do portfela", _wallet, "brak"),
        ("occurred_on", "data", _plain, "brak"),
        ("description", "opis", _text, "brak"),
        ("amount_from_cents", "kwota", _money, "brak"),
        ("amount_to_cents", "kwota docelowa", _money, "brak"),
    ),
    "recurring_transactions": (
        ("wallet_id", "portfel", _wallet, "brak"),
        ("kind", "rodzaj", _kind, "brak"),
        ("description", "opis", _text, "brak"),
        ("amount_cents", "kwota", _money, "ustalana przy płatności"),
        ("category_id", "kategoria", _category, "bez kategorii"),
        ("remaining", "licznik", _plain, "bez limitu"),
        ("last_paid_on", "ostatnia płatność", _plain, "brak"),
    ),
    "recurring_products": _PRODUCT_FIELDS,
}


def _names(db):
    """Nazwy portfeli i kategorii, także już usuniętych, które zna dziennik."""
    names = {"wallets": {}, "categories": {}}
    for table, known in names.items():
        for row in db.execute(
            "SELECT row_id, COALESCE(new_values, old_values) AS row_values"
            " FROM change_log WHERE table_name = ? ORDER BY id",
            (table,),
        ):
            known[row["row_id"]] = json.loads(row["row_values"])["name"]
        for row in db.execute(f"SELECT id, name FROM {table}"):
            known[row["id"]] = row["name"]
    return names


def _value(field, values, names):
    key, _label, formatter, empty = field
    value = values.get(key)
    return empty if value is None else formatter(value, names)


def _fields(table, values):
    """Pola do opisania; wartość w groszach powtarzałaby tę dokładną."""
    return [
        field
        for field in FIELDS[table]
        if not (field[0] == "total_cents" and "total_e5" in values)
    ]


def _is_plain_default(field, values):
    """Opis pozycji bez VAT nie musi tego wyliczać."""
    if field[0] in ("vat_rate", "vat_cents"):
        return values.get("vat_rate") is None
    return field[0] == "wallet_type" and values.get("wallet_type") == "plain"


def _describe(row, names):
    """Jedna linia opisu albo None, gdy zmieniły się tylko pola techniczne."""
    table = row["table_name"]
    old = json.loads(row["old_values"]) if row["old_values"] else {}
    new = json.loads(row["new_values"]) if row["new_values"] else {}
    current = new or old
    title = f"{ACTIONS[row['action']]} {NOUNS[table]} „{current[TITLE_FIELDS[table]]}”"
    if row["action"] == "update":
        changes = [
            f"{field[1]}: {_value(field, old, names)} → {_value(field, new, names)}"
            for field in _fields(table, current)
            if old.get(field[0]) != new.get(field[0])
        ]
        return f"{title}: {', '.join(changes)}" if changes else None
    details = [
        f"{field[1]}: {_value(field, current, names)}"
        for field in _fields(table, current)
        # Starsze wpisy dziennika mają kolumny, których już nie ma, i na odwrót.
        if field[0] != TITLE_FIELDS[table]
        and field[0] in current
        and not _is_plain_default(field, current)
    ]
    return f"{title} ({', '.join(details)})"


def _without_replaced_rows(rows):
    """Pomija pary usunięcie i dodanie tych samych wartości w jednej operacji."""

    def fingerprint(row, column):
        values = json.loads(row[column])
        values.pop("id")
        return row["table_name"], json.dumps(values, sort_keys=True)

    deleted = Counter(
        fingerprint(row, "old_values")
        for row in rows
        if row["action"] == "delete" and row["table_name"] in REPLACED_ON_SAVE
    )
    inserted = Counter(
        fingerprint(row, "new_values")
        for row in rows
        if row["action"] == "insert" and row["table_name"] in REPLACED_ON_SAVE
    )
    skip = {"delete": deleted & inserted, "insert": deleted & inserted}
    result = []
    for row in rows:
        if row["action"] != "update" and row["table_name"] in REPLACED_ON_SAVE:
            column = "old_values" if row["action"] == "delete" else "new_values"
            key = fingerprint(row, column)
            if skip[row["action"]][key] > 0:
                skip[row["action"]][key] -= 1
                continue
        result.append(row)
    return result


def _local_time(text):
    moment = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def history_text(db, max_rows=MAX_ROWS):
    """Historia od najnowszych zmian, jako zwykły tekst."""
    total = db.execute("SELECT COUNT(*) FROM change_log").fetchone()[0]
    if total == 0:
        return "Historia jest pusta. Zapisywane są zmiany od włączenia dziennika."
    rows = db.execute(
        "SELECT * FROM change_log ORDER BY id DESC LIMIT ?", (max_rows,)
    ).fetchall()
    groups = {}
    for row in reversed(rows):
        key = row["operation_id"] or f"row-{row['id']}"
        groups.setdefault(key, []).append(row)

    names = _names(db)
    blocks = []
    if total > len(rows):
        blocks.append(f"Pokazano {len(rows)} najnowszych zmian z {total}.")
    for group in reversed(list(groups.values())):
        lines = [_describe(row, names) for row in _without_replaced_rows(group)]
        lines = [line for line in lines if line]
        if lines:
            header = _local_time(group[0]["changed_at"])
            if group[0]["operation_id"] is None:
                header += " (zmiana spoza aplikacji)"
            blocks.append("\n".join([header, *(f"  {line}" for line in lines)]))
    return "\n\n".join(blocks) if blocks else "Historia nie zawiera widocznych zmian."
