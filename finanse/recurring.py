"""Transakcje cykliczne: szablony, z których płatność tworzy zwykłą transakcję."""

import re

from .errors import ValidationError
from .money import format_precise_input, format_quantity_input
from .transactions import (
    MAX_TEXT_LENGTH,
    insert_products,
    parse_product_rows,
    validate_transaction,
)


def list_recurring(db):
    return db.execute(
        """
        SELECT r.*, w.name AS wallet_name, w.currency,
               COUNT(p.id) AS product_count,
               SUM(p.total_cents) AS total_cents,
               (SELECT GROUP_CONCAT(name, ', ') FROM (
                    SELECT DISTINCT c.name
                    FROM recurring_products rp
                    JOIN categories c ON c.id = rp.category_id
                    WHERE rp.recurring_id = r.id
                )) AS product_categories
        FROM recurring_transactions r
        JOIN wallets w ON w.id = r.wallet_id
        LEFT JOIN recurring_products p ON p.recurring_id = r.id
        GROUP BY r.id
        ORDER BY w.name, r.description, r.id
        """
    ).fetchall()


def get_recurring(db, recurring_id):
    """Szablon wraz z wierszami produktów w postaci do edycji."""
    recurring = db.execute(
        "SELECT * FROM recurring_transactions WHERE id = ?", (recurring_id,)
    ).fetchone()
    rows = [
        {
            "name": product["name"],
            "category": product["category_id"],
            "quantity": format_quantity_input(product["quantity_e5"]),
            "price": format_precise_input(product["unit_price_e5"]),
            "total": format_precise_input(product["total_e5"]),
        }
        for product in db.execute(
            "SELECT * FROM recurring_products WHERE recurring_id = ? ORDER BY position",
            (recurring_id,),
        )
    ]
    return {**dict(recurring), "rows": rows}


def _validate(db, wallet_id, kind, description, remaining, rows):
    errors = []
    description = description.strip()
    if db.execute("SELECT 1 FROM wallets WHERE id = ?", (wallet_id,)).fetchone() is None:
        errors.append("Wybierz portfel.")
    if kind not in ("expense", "income"):
        errors.append("Wybierz rodzaj transakcji.")
    if not description or len(description) > MAX_TEXT_LENGTH:
        errors.append(f"Podaj opis (do {MAX_TEXT_LENGTH} znaków).")

    remaining = remaining.strip()
    if not remaining:
        count = None
    elif re.fullmatch(r"[0-9]{1,6}", remaining):
        count = int(remaining)
    else:
        count = None
        errors.append("Licznik musi być liczbą całkowitą nie mniejszą niż 0.")

    category_ids = {row["id"] for row in db.execute("SELECT id FROM categories")}
    products, product_errors = parse_product_rows(rows, category_ids, required=False)
    errors += product_errors
    if errors:
        raise ValidationError(errors)
    return description, count, products


def _insert_recurring_products(db, recurring_id, products):
    db.executemany(
        """
        INSERT INTO recurring_products (
            recurring_id, position, name, category_id,
            quantity_e5, unit_price_e5, total_e5, total_cents
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                recurring_id,
                position,
                product["name"],
                product["category_id"],
                product["quantity_e5"],
                product["unit_price_e5"],
                product["total_e5"],
                product["total_cents"],
            )
            for position, product in enumerate(products)
        ],
    )


def create_recurring(db, wallet_id, kind, description, remaining="", rows=()):
    description, count, products = _validate(
        db, wallet_id, kind, description, remaining, rows
    )
    with db:
        recurring_id = db.execute(
            """
            INSERT INTO recurring_transactions
                (wallet_id, kind, description, remaining)
            VALUES (?, ?, ?, ?)
            """,
            (wallet_id, kind, description, count),
        ).lastrowid
        _insert_recurring_products(db, recurring_id, products)
    return recurring_id


def update_recurring(db, recurring_id, wallet_id, kind, description, remaining="", rows=()):
    description, count, products = _validate(
        db, wallet_id, kind, description, remaining, rows
    )
    with db:
        db.execute(
            """
            UPDATE recurring_transactions
            SET wallet_id = ?, kind = ?, description = ?, remaining = ?
            WHERE id = ?
            """,
            (wallet_id, kind, description, count, recurring_id),
        )
        db.execute(
            "DELETE FROM recurring_products WHERE recurring_id = ?", (recurring_id,)
        )
        _insert_recurring_products(db, recurring_id, products)


def delete_recurring(db, recurring_id):
    """Usuwa sam szablon; zapłacone już transakcje zostają."""
    with db:
        db.execute("DELETE FROM recurring_transactions WHERE id = ?", (recurring_id,))


def payment_draft(db, recurring_id):
    """Wartości początkowe zwykłej transakcji, którą użytkownik może jeszcze zmienić."""
    recurring = get_recurring(db, recurring_id)
    # Bez produktów kwotę i kategorię podaje się dopiero przy płatności.
    rows = recurring["rows"] or [
        {
            "name": recurring["description"],
            "category": None,
            "quantity": "1",
            "price": "",
        }
    ]
    return {
        "wallet_id": recurring["wallet_id"],
        "kind": recurring["kind"],
        "occurred_on": None,
        "description": recurring["description"],
        "rows": rows,
    }


def pay_recurring(db, recurring_id, kind, occurred_on, description, rows):
    """Tworzy zwykłą transakcję i zmniejsza licznik; obie zmiany zapisują się razem."""
    recurring = db.execute(
        "SELECT wallet_id, remaining FROM recurring_transactions WHERE id = ?",
        (recurring_id,),
    ).fetchone()
    if recurring is None:
        raise ValidationError("Ta transakcja cykliczna już nie istnieje.")
    if recurring["remaining"] == 0:
        raise ValidationError("Licznik tej transakcji cyklicznej doszedł już do zera.")
    occurred_on, description, products = validate_transaction(
        db, kind, occurred_on, description, rows
    )
    with db:
        transaction_id = db.execute(
            "INSERT INTO transactions (wallet_id, kind, occurred_on, description)"
            " VALUES (?, ?, ?, ?)",
            (recurring["wallet_id"], kind, occurred_on, description),
        ).lastrowid
        insert_products(db, transaction_id, products)
        db.execute(
            """
            UPDATE recurring_transactions
            SET remaining = remaining - 1,
                last_paid_on = MAX(COALESCE(last_paid_on, ''), ?)
            WHERE id = ?
            """,
            (occurred_on, recurring_id),
        )
    return transaction_id
