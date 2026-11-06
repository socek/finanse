from datetime import date

from .errors import ValidationError
from .money import (
    MAX_TRANSACTION_CENTS,
    format_money_input,
    format_quantity,
    line_total,
    parse_money,
    parse_quantity,
)

MAX_TEXT_LENGTH = 200
EMPTY_ROW = {"name": "", "category": None, "quantity": "1", "price": ""}


def _parse_product_rows(rows, category_ids):
    """Zwraca (produkty do zapisu, błędy). Puste wiersze pomija."""
    products, errors = [], []
    number = 0
    for row in rows:
        name = row.get("name", "").strip()
        quantity = row.get("quantity", "").strip()
        price = row.get("price", "").strip()
        category = row.get("category")
        if not name and not price and quantity in ("", "1"):
            continue
        number += 1

        if not name or len(name) > MAX_TEXT_LENGTH:
            errors.append(f"Produkt {number}: podaj nazwę (do {MAX_TEXT_LENGTH} znaków).")
        if category is not None and category not in category_ids:
            errors.append(f"Produkt {number}: niepoprawna kategoria.")
            continue
        try:
            quantity_milli = parse_quantity(quantity)
        except ValueError:
            errors.append(f"Produkt {number}: niepoprawna ilość.")
            continue
        try:
            price_cents = parse_money(price)
        except ValueError:
            price_cents = -1
        if price_cents < 0:
            errors.append(f"Produkt {number}: niepoprawna cena.")
            continue
        products.append(
            {
                "name": name,
                "category_id": category,
                "quantity_milli": quantity_milli,
                "unit_price_cents": price_cents,
                "total_cents": line_total(quantity_milli, price_cents),
            }
        )

    if number == 0:
        errors.append("Dodaj co najmniej jeden produkt.")
    if sum(product["total_cents"] for product in products) > MAX_TRANSACTION_CENTS:
        errors.append("Kwota transakcji jest zbyt duża.")
    return products, errors


def _validate(db, kind, occurred_on, description, rows):
    errors = []
    description = description.strip()
    if kind not in ("expense", "income"):
        errors.append("Wybierz rodzaj transakcji.")
    try:
        occurred_on = date.fromisoformat(occurred_on.strip()).isoformat()
    except ValueError:
        errors.append("Podaj poprawną datę.")
    if not description or len(description) > MAX_TEXT_LENGTH:
        errors.append(f"Podaj opis (do {MAX_TEXT_LENGTH} znaków).")
    category_ids = {row["id"] for row in db.execute("SELECT id FROM categories")}
    products, product_errors = _parse_product_rows(rows, category_ids)
    errors += product_errors
    if errors:
        raise ValidationError(errors)
    return occurred_on, description, products


def insert_products(db, transaction_id, products):
    db.executemany(
        """
        INSERT INTO products (
            transaction_id, position, name, category_id,
            quantity_milli, unit_price_cents, total_cents
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                transaction_id,
                position,
                product["name"],
                product["category_id"],
                product["quantity_milli"],
                product["unit_price_cents"],
                product["total_cents"],
            )
            for position, product in enumerate(products)
        ],
    )


def create_transaction(db, wallet_id, kind, occurred_on, description, rows):
    occurred_on, description, products = _validate(
        db, kind, occurred_on, description, rows
    )
    with db:
        transaction_id = db.execute(
            "INSERT INTO transactions (wallet_id, kind, occurred_on, description)"
            " VALUES (?, ?, ?, ?)",
            (wallet_id, kind, occurred_on, description),
        ).lastrowid
        insert_products(db, transaction_id, products)
    return transaction_id


def update_transaction(db, transaction_id, kind, occurred_on, description, rows):
    occurred_on, description, products = _validate(
        db, kind, occurred_on, description, rows
    )
    with db:
        db.execute(
            "UPDATE transactions SET kind = ?, occurred_on = ?, description = ?"
            " WHERE id = ?",
            (kind, occurred_on, description, transaction_id),
        )
        db.execute("DELETE FROM products WHERE transaction_id = ?", (transaction_id,))
        insert_products(db, transaction_id, products)


def delete_transaction(db, transaction_id):
    with db:
        db.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))


def get_transaction(db, transaction_id):
    """Transakcja wraz z wierszami produktów w postaci do edycji."""
    transaction = db.execute(
        "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    rows = [
        {
            "name": product["name"],
            "category": product["category_id"],
            "quantity": format_quantity(product["quantity_milli"]),
            "price": format_money_input(product["unit_price_cents"]),
        }
        for product in db.execute(
            "SELECT * FROM products WHERE transaction_id = ? ORDER BY position",
            (transaction_id,),
        )
    ]
    return {
        "wallet_id": transaction["wallet_id"],
        "kind": transaction["kind"],
        "occurred_on": transaction["occurred_on"],
        "description": transaction["description"],
        "rows": rows,
    }
