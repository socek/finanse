"""Podpowiedzi nazw produktów z historii i wartości z ich ostatniego zakupu."""

from .price_history import normalize_name


def product_names(db):
    """Znane nazwy produktów, od najczęstszych; każda w pisowni z ostatniego użycia."""
    names = {}
    rows = db.execute(
        """
        SELECT p.name
        FROM products p
        JOIN transactions t ON t.id = p.transaction_id
        ORDER BY t.occurred_on, t.created_at, t.id, p.position
        """
    )
    for position, row in enumerate(rows):
        key = normalize_name(row["name"])
        if key:
            count = names.get(key, (0,))[0]
            names[key] = (count + 1, row["name"].strip(), position)
    # Przy równej liczbie wyżej jest nazwa użyta niedawno.
    ranked = sorted(names.values(), key=lambda item: (-item[0], -item[2]))
    return [spelling for _count, spelling, _order in ranked]


def last_purchase(db, name, currency=""):
    """Kategoria, cena i stawka VAT z ostatniego użycia nazwy albo None, gdy jej nie ma.

    Cena pochodzi z ostatniego zakupu w podanej walucie, a stawka z ostatniego użycia
    w portfelu z VAT, bo w zwykłym portfelu stawki nie ma. Brak takiego zakupu daje None.
    """
    wanted = normalize_name(name)
    rows = [
        row
        for row in db.execute(
            """
            SELECT p.name, p.category_id, p.unit_price_e5, p.vat_rate,
                   w.currency, w.wallet_type
            FROM products p
            JOIN transactions t ON t.id = p.transaction_id
            JOIN wallets w ON w.id = t.wallet_id
            ORDER BY t.occurred_on DESC, t.created_at DESC, t.id DESC, p.position DESC
            """
        )
        if normalize_name(row["name"]) == wanted
    ]
    if not rows:
        return None
    priced = next((row for row in rows if row["currency"] == currency), None)
    taxed = next((row for row in rows if row["wallet_type"] == "vat"), None)
    return {
        "category_id": rows[0]["category_id"],
        "unit_price_e5": priced["unit_price_e5"] if priced else None,
        "has_vat_rate": taxed is not None,
        "vat_rate": taxed["vat_rate"] if taxed else None,
    }
