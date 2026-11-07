"""Tagi transakcji: projekty i okazje niezależne od kategorii, np. „Wakacje 2026”.

Nazwy tagów porównuje się bez wielkości liter, także polskich, więc „Łódź” i „łódź” to
ten sam tag. Tagi wpisuje się po przecinku.
"""

import re
import sqlite3

from .errors import ValidationError

MAX_TAG_LENGTH = 50
SEPARATOR = ","
# Polska litera ze znakiem trafia za swoją literą bazową, np. „ł” za wszystkie „l…”.
_POLISH_ORDER = str.maketrans(
    {"ą": "a~", "ć": "c~", "ę": "e~", "ł": "l~", "ń": "n~", "ó": "o~", "ś": "s~",
     "ź": "z~", "ż": "z~~"}
)  # fmt: skip


def sort_key(name):
    """Kolejność alfabetyczna z polskimi literami, bez względu na wielkość liter."""
    return name.casefold().translate(_POLISH_ORDER)


def _key(name):
    return re.sub(r"\s+", " ", name).strip().casefold()


def _clean(name):
    return re.sub(r"\s+", " ", name).strip()


def parse_tags(text):
    """Nazwy tagów z tekstu po przecinku, bez powtórzeń; zwraca (nazwy, błędy)."""
    names, seen, errors = [], set(), []
    for part in text.split(SEPARATOR):
        name = _clean(part)
        if not name or _key(name) in seen:
            continue
        if len(name) > MAX_TAG_LENGTH:
            errors.append(f"Tag „{name[:20]}…” jest za długi (do {MAX_TAG_LENGTH} znaków).")
            continue
        seen.add(_key(name))
        names.append(name)
    return names, errors


def format_tags(names):
    return f"{SEPARATOR} ".join(names)


def list_tags(db):
    """Tagi z liczbą transakcji, alfabetycznie bez względu na wielkość liter."""
    rows = db.execute(
        """
        SELECT t.id, t.name,
               (SELECT COUNT(*) FROM transaction_tags tt WHERE tt.tag_id = t.id)
                   AS transaction_count
        FROM tags t
        """
    ).fetchall()
    return sorted(rows, key=lambda row: sort_key(row["name"]))


def tags_of(db, transaction_id):
    return [
        row["name"]
        for row in db.execute(
            """
            SELECT t.name FROM transaction_tags tt JOIN tags t ON t.id = tt.tag_id
            WHERE tt.transaction_id = ?
            """,
            (transaction_id,),
        )
    ]


def tags_by_transaction(db, transaction_ids):
    """{transakcja: [(id tagu, nazwa), …]} dla podanych transakcji."""
    ids = list(transaction_ids)
    result = {transaction_id: [] for transaction_id in ids}
    for start in range(0, len(ids), 500):  # limit parametrów zapytania w SQLite
        chunk = ids[start : start + 500]
        marks = ",".join("?" * len(chunk))
        for row in db.execute(
            f"""
            SELECT tt.transaction_id, t.id, t.name
            FROM transaction_tags tt JOIN tags t ON t.id = tt.tag_id
            WHERE tt.transaction_id IN ({marks})
            """,
            chunk,
        ):
            result[row["transaction_id"]].append((row["id"], row["name"]))
    for tags in result.values():
        tags.sort(key=lambda tag: sort_key(tag[1]))
    return result


def set_transaction_tags(db, transaction_id, names):
    """Zastępuje tagi transakcji; brakujące tagi tworzy. Wywoływać wewnątrz `with db`."""
    existing = {_key(row["name"]): row["id"] for row in db.execute("SELECT id, name FROM tags")}
    tag_ids = []
    for name in names:
        tag_id = existing.get(_key(name))
        if tag_id is None:
            tag_id = db.execute("INSERT INTO tags (name) VALUES (?)", (name,)).lastrowid
            existing[_key(name)] = tag_id
        tag_ids.append(tag_id)
    current = {
        row["tag_id"]
        for row in db.execute(
            "SELECT tag_id FROM transaction_tags WHERE transaction_id = ?", (transaction_id,)
        )
    }
    # Bez zmian w niezmienionych tagach, żeby historia pokazywała tylko prawdziwe zmiany.
    for tag_id in current - set(tag_ids):
        db.execute(
            "DELETE FROM transaction_tags WHERE transaction_id = ? AND tag_id = ?",
            (transaction_id, tag_id),
        )
    for tag_id in tag_ids:
        if tag_id not in current:
            db.execute(
                "INSERT INTO transaction_tags (transaction_id, tag_id) VALUES (?, ?)",
                (transaction_id, tag_id),
            )


def rename_tag(db, tag_id, name):
    name = _clean(name)
    if not name or len(name) > MAX_TAG_LENGTH:
        raise ValidationError(f"Podaj nazwę tagu (do {MAX_TAG_LENGTH} znaków).")
    if SEPARATOR in name:
        raise ValidationError("Nazwa tagu nie może zawierać przecinka.")
    for row in db.execute("SELECT id, name FROM tags WHERE id != ?", (tag_id,)):
        if _key(row["name"]) == _key(name):
            raise ValidationError("Masz już tag o tej nazwie.")
    try:
        with db:
            db.execute("UPDATE tags SET name = ? WHERE id = ?", (name, tag_id))
    except sqlite3.IntegrityError:
        raise ValidationError("Masz już tag o tej nazwie.") from None


def delete_tag(db, tag_id):
    """Usuwa tag ze wszystkich transakcji; same transakcje zostają."""
    with db:
        db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))


def tag_totals(db, wallet_ids, start, end):
    """Przychody i wydatki każdego tagu w okresie [start, end) z wybranych portfeli."""
    marks = ",".join("?" * len(wallet_ids))
    rows = db.execute(
        f"""
        SELECT tg.id, tg.name, t.kind, SUM(p.total_cents) AS total,
               COUNT(DISTINCT t.id) AS transactions
        FROM transaction_tags tt
        JOIN tags tg ON tg.id = tt.tag_id
        JOIN transactions t ON t.id = tt.transaction_id
        JOIN products p ON p.transaction_id = t.id
        WHERE t.wallet_id IN ({marks}) AND t.occurred_on >= ? AND t.occurred_on < ?
        GROUP BY tg.id, t.kind
        """,
        (*wallet_ids, start, end),
    ).fetchall()
    by_tag = {}
    for row in rows:
        tag = by_tag.setdefault(
            row["id"], {"id": row["id"], "name": row["name"], "income": 0, "expense": 0,
                        "transactions": 0},
        )  # fmt: skip
        tag[row["kind"]] += row["total"]
        tag["transactions"] += row["transactions"]
    result = list(by_tag.values())
    for tag in result:
        tag["net"] = tag["income"] - tag["expense"]
    result.sort(key=lambda tag: (-(tag["income"] + tag["expense"]), sort_key(tag["name"])))
    return result
