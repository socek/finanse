"""Historia ceny produktu: wszystkie zakupy o tej samej nazwie, z podziałem na sklepy.

Sklepem jest opis transakcji, bo to w nim zwykle zapisuje się, gdzie był zakup. Nazwy
porównuje się bez wielkości liter i nadmiarowych spacji. Ceny w różnych walutach nigdy
się nie mieszają, więc każda waluta ma osobne zestawienie.
"""

import re

from .money import PRECISE_UNIT


def normalize_name(name):
    # casefold, bo LOWER w SQLite nie rozpoznaje wielkości polskich liter.
    return re.sub(r"\s+", " ", name).strip().casefold()


def _average_e5(entries):
    """Średnia cena zapłacona za jednostkę: suma wartości przez sumę ilości."""
    quantity = sum(entry["quantity_e5"] for entry in entries)
    total = sum(entry["total_e5"] for entry in entries)
    return round(total * PRECISE_UNIT / quantity) if quantity else 0


def _shops(entries):
    by_shop = {}
    for entry in entries:
        by_shop.setdefault(entry["shop"], []).append(entry)
    shops = [
        {
            "shop": shop,
            "count": len(items),
            "min_e5": min(item["unit_price_e5"] for item in items),
            "average_e5": _average_e5(items),
            "last_e5": items[-1]["unit_price_e5"],
            "last_on": items[-1]["occurred_on"],
        }
        for shop, items in by_shop.items()
    ]
    shops.sort(key=lambda shop: (shop["average_e5"], shop["shop"].casefold()))
    return shops


def _summary(currency, entries):
    first, last = entries[0], entries[-1]
    cheapest = min(entries, key=lambda entry: entry["unit_price_e5"])
    dearest = max(entries, key=lambda entry: entry["unit_price_e5"])
    change = None
    if first["unit_price_e5"]:
        change = (last["unit_price_e5"] - first["unit_price_e5"]) / first["unit_price_e5"] * 100
    return {
        "currency": currency,
        "entries": entries,
        "first": first,
        "last": last,
        "cheapest": cheapest,
        "dearest": dearest,
        "average_e5": _average_e5(entries),
        "change_percent": change,
        "shops": _shops(entries),
    }


def price_history(db, name):
    """Zakupy produktu od najstarszych, osobno dla każdej waluty, od najczęstszej waluty.

    Zwraca pustą listę, gdy produktu nigdy nie kupiono.
    """
    wanted = normalize_name(name)
    rows = db.execute(
        """
        SELECT p.id, p.transaction_id, p.name, p.quantity_e5, p.unit_price_e5, p.total_e5,
               p.total_cents, t.occurred_on, t.description AS shop,
               w.name AS wallet_name, w.currency
        FROM products p
        JOIN transactions t ON t.id = p.transaction_id
        JOIN wallets w ON w.id = t.wallet_id
        WHERE t.kind = 'expense'
        ORDER BY t.occurred_on, t.created_at, t.id, p.position
        """
    ).fetchall()
    by_currency = {}
    for row in rows:
        if normalize_name(row["name"]) == wanted:
            by_currency.setdefault(row["currency"], []).append(dict(row))
    ordered = sorted(by_currency.items(), key=lambda item: (-len(item[1]), item[0]))
    return [_summary(currency, entries) for currency, entries in ordered]
