"""Lista produktów portfela, niezależna od tego, w jakim rachunku się znalazły."""

from .wallets import NO_CATEGORY, EntryFilters, add_to_totals


def _matches(product, filters):
    if filters.min_cents is not None and product["total_cents"] < filters.min_cents:
        return False
    if filters.max_cents is not None and product["total_cents"] > filters.max_cents:
        return False
    if (
        filters.category is not None
        and (product["category_id"] or NO_CATEGORY) != filters.category
    ):
        return False
    # casefold, bo LIKE w SQLite nie rozpoznaje wielkości polskich liter.
    text = filters.text.strip().casefold()
    return not text or text in product["name"].casefold()


def load_products(db, wallet_ids, date_from="", date_to="", filters=EntryFilters()):
    """Pasujące produkty z okresu, od najnowszych, z sumami osobno dla każdej waluty."""
    wallet_ids = list(wallet_ids)
    marks = ",".join("?" * len(wallet_ids))
    period = ""
    args = list(wallet_ids)
    if date_from:
        period += " AND t.occurred_on >= ?"
        args.append(date_from)
    if date_to:
        period += " AND t.occurred_on <= ?"
        args.append(date_to)
    rows = db.execute(
        f"""
        SELECT p.id, p.transaction_id, p.name, p.category_id, p.quantity_milli,
               p.unit_price_cents, p.total_cents,
               c.name AS category_name,
               t.kind, t.occurred_on, t.description,
               w.name AS wallet_name, w.currency
        FROM products p
        JOIN transactions t ON t.id = p.transaction_id
        JOIN wallets w ON w.id = t.wallet_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE t.wallet_id IN ({marks}) {period}
        ORDER BY t.occurred_on DESC, t.created_at DESC, t.id DESC, p.position
        """,
        args,
    ).fetchall()
    products = [row for row in rows if _matches(row, filters)]
    summary = {"income": {}, "expense": {}}
    for product in products:
        add_to_totals(summary[product["kind"]], product["currency"], product["total_cents"])
    return products, summary


def group_products_by_day(products):
    """Grupuje posortowane produkty po dniu i sumuje przychody oraz wydatki."""
    days = []
    for product in products:
        if not days or days[-1]["date"] != product["occurred_on"]:
            days.append(
                {
                    "date": product["occurred_on"],
                    "entries": [],
                    "income": {},
                    "expense": {},
                }
            )
        day = days[-1]
        day["entries"].append(product)
        add_to_totals(day[product["kind"]], product["currency"], product["total_cents"])
    return days
