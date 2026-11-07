import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from .errors import ValidationError
from .money import parse_money
from .tags import tags_by_transaction

MAX_NAME_LENGTH = 100
PLAIN, VAT = "plain", "vat"

_WALLET_WITH_BALANCE = """
    SELECT w.*,
           w.initial_balance_cents
           + COALESCE((
               SELECT SUM(CASE t.kind WHEN 'income' THEN p.total_cents
                                      ELSE -p.total_cents END)
               FROM transactions t
               JOIN products p ON p.transaction_id = t.id
               WHERE t.wallet_id = w.id
                 AND (:as_of IS NULL OR t.occurred_on <= :as_of)
           ), 0)
           + COALESCE((
               SELECT SUM(amount_to_cents) FROM transfers
               WHERE to_wallet_id = w.id
                 AND (:as_of IS NULL OR occurred_on <= :as_of)
           ), 0)
           - COALESCE((
               SELECT SUM(amount_from_cents) FROM transfers
               WHERE from_wallet_id = w.id
                 AND (:as_of IS NULL OR occurred_on <= :as_of)
           ), 0) AS balance_cents
    FROM wallets w
"""


NO_CATEGORY = 0  # identyfikatory kategorii zaczynają się od 1


@dataclass(frozen=True)
class EntryFilters:
    """Zawężenie listy operacji; domyślne wartości niczego nie filtrują."""

    text: str = ""
    category: int | None = None  # None: wszystkie, NO_CATEGORY: bez kategorii
    min_cents: int | None = None
    max_cents: int | None = None
    tag: int | None = None  # None: wszystkie, inaczej identyfikator tagu

    @property
    def active(self):
        return self != EntryFilters()


def add_to_totals(totals, currency, cents):
    """Dolicza kwotę do sumy danej waluty; zero nie tworzy wpisu."""
    if cents:
        totals[currency] = totals.get(currency, 0) + cents


def _entry_amount(entry, wallet_ids):
    item = entry["item"]
    if entry["type"] == "transaction":
        return item["total_cents"]
    if item["from_wallet_id"] in wallet_ids:
        return item["amount_from_cents"]
    return item["amount_to_cents"]


def _entry_names(entry):
    item = entry["item"]
    if entry["type"] == "transaction":
        return [
            item["description"],
            *(p["name"] for p in entry["products"]),
            *(name for _id, name in entry["tags"]),
        ]
    return [item["description"], item["from_name"], item["to_name"]]


def _matches(entry, wallet_ids, filters):
    amount = _entry_amount(entry, wallet_ids)
    if filters.min_cents is not None and amount < filters.min_cents:
        return False
    if filters.max_cents is not None and amount > filters.max_cents:
        return False
    if filters.tag is not None:
        # Przelew nie ma tagów.
        if entry["type"] != "transaction":
            return False
        if filters.tag not in {tag_id for tag_id, _name in entry["tags"]}:
            return False
    if filters.category is not None:
        # Przelew nie ma kategorii, a rachunek pasuje, gdy pasuje choć jeden produkt.
        if entry["type"] != "transaction":
            return False
        categories = {p["category_id"] or NO_CATEGORY for p in entry["products"]}
        if filters.category not in categories:
            return False
    # casefold, bo LIKE w SQLite nie rozpoznaje wielkości polskich liter.
    text = filters.text.strip().casefold()
    return not text or any(text in name.casefold() for name in _entry_names(entry))


def get_wallet(db, wallet_id):
    return db.execute(
        _WALLET_WITH_BALANCE + " WHERE w.id = :id", {"id": wallet_id, "as_of": None}
    ).fetchone()


def list_wallets(db, as_of=None):
    """Portfele z saldem na koniec podanego dnia; bez daty uwzględnia wszystkie wpisy."""
    return db.execute(
        _WALLET_WITH_BALANCE + " ORDER BY w.name", {"as_of": as_of or None}
    ).fetchall()


def _parse(name, currency, initial_balance):
    name = name.strip()
    currency = currency.strip().upper()
    errors = []
    if not name or len(name) > MAX_NAME_LENGTH:
        errors.append(f"Podaj nazwę portfela (do {MAX_NAME_LENGTH} znaków).")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        errors.append("Waluta musi być trzyliterowym kodem, np. PLN.")
    initial_cents = 0
    try:
        initial_cents = parse_money(initial_balance.strip() or "0")
    except ValueError:
        errors.append("Niepoprawne saldo początkowe.")
    if errors:
        raise ValidationError(errors)
    return name, currency, initial_cents


def _check_type(wallet_type):
    if wallet_type not in (PLAIN, VAT):
        raise ValidationError("Wybierz typ portfela.")


def wallet_has_vat(db, wallet_id):
    row = db.execute("SELECT wallet_type FROM wallets WHERE id = ?", (wallet_id,)).fetchone()
    return row is not None and row["wallet_type"] == VAT


def create_wallet(db, name, currency="PLN", initial_balance="0", wallet_type=PLAIN):
    _check_type(wallet_type)
    values = _parse(name, currency, initial_balance)
    try:
        with db:
            return db.execute(
                "INSERT INTO wallets (name, currency, initial_balance_cents, wallet_type)"
                " VALUES (?, ?, ?, ?)",
                (*values, wallet_type),
            ).lastrowid
    except sqlite3.IntegrityError:
        raise ValidationError("Masz już portfel o tej nazwie.") from None


def update_wallet(db, wallet_id, name, currency, initial_balance, wallet_type=None):
    """Bez podanego typu portfel go zachowuje. Stawki VAT produktów pozostają zapisane."""
    if wallet_type is not None:
        _check_type(wallet_type)
    values = _parse(name, currency, initial_balance)
    try:
        with db:
            db.execute(
                "UPDATE wallets SET name = ?, currency = ?, initial_balance_cents = ?,"
                " wallet_type = COALESCE(?, wallet_type) WHERE id = ?",
                (*values, wallet_type, wallet_id),
            )
    except sqlite3.IntegrityError:
        raise ValidationError("Masz już portfel o tej nazwie.") from None


def delete_wallet(db, wallet_id):
    has_transfers = db.execute(
        "SELECT 1 FROM transfers WHERE from_wallet_id = ? OR to_wallet_id = ? LIMIT 1",
        (wallet_id, wallet_id),
    ).fetchone()
    if has_transfers:
        raise ValidationError(
            "Ten portfel ma przelewy. Usuń je najpierw, bo wpływają na saldo "
            "drugiego portfela."
        )
    with db:
        db.execute("DELETE FROM wallets WHERE id = ?", (wallet_id,))


def load_entries(db, wallet_ids, date_from="", date_to="", filters=EntryFilters()):
    """Pasujące transakcje i przelewy portfeli z okresu, od najnowszych, z sumami.

    Sumy są osobne dla każdej waluty. Przelew między wybranymi portfelami pojawia się
    raz i nie liczy się do sum.
    """
    wallet_ids = set(wallet_ids)
    marks = ",".join("?" * len(wallet_ids))
    period = ""
    period_args = []
    if date_from:
        period += " AND {column} >= ?"
        period_args.append(date_from)
    if date_to:
        period += " AND {column} <= ?"
        period_args.append(date_to)

    transactions = db.execute(
        f"""
        SELECT t.*, COALESCE(SUM(p.total_cents), 0) AS total_cents,
               COALESCE(SUM(p.vat_cents), 0) AS vat_cents,
               w.name AS wallet_name, w.currency, w.wallet_type
        FROM transactions t
        JOIN wallets w ON w.id = t.wallet_id
        LEFT JOIN products p ON p.transaction_id = t.id
        WHERE t.wallet_id IN ({marks}) {period.format(column="t.occurred_on")}
        GROUP BY t.id
        """,
        (*wallet_ids, *period_args),
    ).fetchall()

    products = defaultdict(list)
    for product in db.execute(
        f"""
        SELECT p.*, c.name AS category_name
        FROM products p
        JOIN transactions t ON t.id = p.transaction_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE t.wallet_id IN ({marks}) {period.format(column="t.occurred_on")}
        ORDER BY p.position
        """,
        (*wallet_ids, *period_args),
    ):
        products[product["transaction_id"]].append(product)

    transfers = db.execute(
        f"""
        SELECT tr.*,
               wf.name AS from_name, wf.currency AS from_currency,
               wt.name AS to_name, wt.currency AS to_currency
        FROM transfers tr
        JOIN wallets wf ON wf.id = tr.from_wallet_id
        JOIN wallets wt ON wt.id = tr.to_wallet_id
        WHERE (tr.from_wallet_id IN ({marks}) OR tr.to_wallet_id IN ({marks}))
              {period.format(column="tr.occurred_on")}
        """,
        (*wallet_ids, *wallet_ids, *period_args),
    ).fetchall()

    tags = tags_by_transaction(db, (item["id"] for item in transactions))
    entries = [
        {
            "type": "transaction",
            "item": item,
            "products": products[item["id"]],
            "tags": tags[item["id"]],
        }
        for item in transactions
    ] + [{"type": "transfer", "item": item} for item in transfers]
    entries.sort(
        key=lambda entry: (
            entry["item"]["occurred_on"],
            entry["item"]["created_at"],
            entry["item"]["id"],
        ),
        reverse=True,
    )
    entries = [entry for entry in entries if _matches(entry, wallet_ids, filters)]
    summary = {"income": {}, "expense": {}}
    for entry in entries:
        if entry["type"] == "transaction":
            item = entry["item"]
            add_to_totals(summary[item["kind"]], item["currency"], item["total_cents"])
    return entries, summary


def last_transaction_date(db, wallet_ids):
    """Najpóźniejsza data transakcji w portfelach, bez względu na filtry listy."""
    wallet_ids = list(wallet_ids)
    marks = ",".join("?" * len(wallet_ids))
    return db.execute(
        f"SELECT MAX(occurred_on) FROM transactions WHERE wallet_id IN ({marks})",
        wallet_ids,
    ).fetchone()[0]


def group_by_day(entries):
    """Grupuje posortowane operacje po dniu i sumuje przychody oraz wydatki.

    Przelewy są na liście dnia, ale nie liczą się do żadnej z sum.
    """
    days = []
    for entry in entries:
        item = entry["item"]
        if not days or days[-1]["date"] != item["occurred_on"]:
            days.append(
                {"date": item["occurred_on"], "entries": [], "income": {}, "expense": {}}
            )
        day = days[-1]
        day["entries"].append(entry)
        if entry["type"] == "transaction":
            add_to_totals(day[item["kind"]], item["currency"], item["total_cents"])
    return days
