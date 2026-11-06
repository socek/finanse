import re
import sqlite3
from collections import defaultdict

from .errors import ValidationError
from .money import parse_money

MAX_NAME_LENGTH = 100

_WALLET_WITH_BALANCE = """
    SELECT w.*,
           w.initial_balance_cents
           + COALESCE((
               SELECT SUM(CASE t.kind WHEN 'income' THEN p.total_cents
                                      ELSE -p.total_cents END)
               FROM transactions t
               JOIN products p ON p.transaction_id = t.id
               WHERE t.wallet_id = w.id
           ), 0)
           + COALESCE((
               SELECT SUM(amount_to_cents) FROM transfers
               WHERE to_wallet_id = w.id
           ), 0)
           - COALESCE((
               SELECT SUM(amount_from_cents) FROM transfers
               WHERE from_wallet_id = w.id
           ), 0) AS balance_cents
    FROM wallets w
"""


def get_wallet(db, wallet_id):
    return db.execute(_WALLET_WITH_BALANCE + " WHERE w.id = ?", (wallet_id,)).fetchone()


def list_wallets(db):
    return db.execute(_WALLET_WITH_BALANCE + " ORDER BY w.name").fetchall()


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


def create_wallet(db, name, currency="PLN", initial_balance="0"):
    values = _parse(name, currency, initial_balance)
    try:
        with db:
            return db.execute(
                "INSERT INTO wallets (name, currency, initial_balance_cents)"
                " VALUES (?, ?, ?)",
                values,
            ).lastrowid
    except sqlite3.IntegrityError:
        raise ValidationError("Masz już portfel o tej nazwie.") from None


def update_wallet(db, wallet_id, name, currency, initial_balance):
    values = _parse(name, currency, initial_balance)
    try:
        with db:
            db.execute(
                "UPDATE wallets SET name = ?, currency = ?, initial_balance_cents = ?"
                " WHERE id = ?",
                (*values, wallet_id),
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


def load_entries(db, wallet_id, date_from="", date_to=""):
    """Transakcje i przelewy portfela z okresu, od najnowszych."""
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
        SELECT t.*, COALESCE(SUM(p.total_cents), 0) AS total_cents
        FROM transactions t
        LEFT JOIN products p ON p.transaction_id = t.id
        WHERE t.wallet_id = ? {period.format(column="t.occurred_on")}
        GROUP BY t.id
        """,
        (wallet_id, *period_args),
    ).fetchall()

    products = defaultdict(list)
    for product in db.execute(
        f"""
        SELECT p.*, c.name AS category_name
        FROM products p
        JOIN transactions t ON t.id = p.transaction_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE t.wallet_id = ? {period.format(column="t.occurred_on")}
        ORDER BY p.position
        """,
        (wallet_id, *period_args),
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
        WHERE (tr.from_wallet_id = ? OR tr.to_wallet_id = ?)
              {period.format(column="tr.occurred_on")}
        """,
        (wallet_id, wallet_id, *period_args),
    ).fetchall()

    entries = [
        {"type": "transaction", "item": item, "products": products[item["id"]]}
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
    summary = {
        kind: sum(t["total_cents"] for t in transactions if t["kind"] == kind)
        for kind in ("income", "expense")
    }
    return entries, summary
