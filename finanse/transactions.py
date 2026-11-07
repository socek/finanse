from datetime import date

from .errors import ValidationError
from .money import (
    MAX_TRANSACTION_CENTS,
    format_precise_input,
    format_quantity_input,
    line_total,
    parse_precise,
    parse_quantity,
    to_cents,
    vat_from_gross,
)
from .wallets import wallet_has_vat

MAX_TEXT_LENGTH = 200
VAT_RATES = (23, 8, 5, 0)
EMPTY_ROW = {"name": "", "category": None, "quantity": "1", "price": "", "total": ""}


def parse_product_rows(rows, category_ids, required=True, has_vat=False):
    """Zwraca (produkty do zapisu, błędy). Puste wiersze pomija."""
    products, errors = [], []
    number = 0
    for row in rows:
        name = row.get("name", "").strip()
        quantity = row.get("quantity", "").strip()
        price = row.get("price", "").strip()
        total = row.get("total", "").strip()
        category = row.get("category")
        if not name and not price and not total and quantity in ("", "1"):
            continue
        number += 1

        if not name or len(name) > MAX_TEXT_LENGTH:
            errors.append(f"Produkt {number}: podaj nazwę (do {MAX_TEXT_LENGTH} znaków).")
        if category is not None and category not in category_ids:
            errors.append(f"Produkt {number}: niepoprawna kategoria.")
            continue
        try:
            quantity_e5 = parse_quantity(quantity)
        except ValueError:
            errors.append(f"Produkt {number}: niepoprawna ilość.")
            continue
        try:
            price_e5 = parse_precise(price)
        except ValueError:
            price_e5 = -1
        if price_e5 < 0:
            errors.append(f"Produkt {number}: niepoprawna cena.")
            continue
        # Podana wartość ma pierwszeństwo: cena wyliczona z niej jest zaokrąglona,
        # więc ilość razy cena nie musi dać dokładnie tej samej kwoty.
        total_e5 = line_total(quantity_e5, price_e5)
        if total:
            try:
                total_e5 = parse_precise(total)
            except ValueError:
                total_e5 = -1
            if total_e5 < 0:
                errors.append(f"Produkt {number}: niepoprawna wartość.")
                continue
        # Portfel bez VAT nie zapisuje stawki, nawet jeśli wiersz ją ma, np. z szablonu.
        vat_rate = row.get("vat_rate") if has_vat else None
        if vat_rate is not None and vat_rate not in VAT_RATES:
            errors.append(f"Produkt {number}: niepoprawna stawka VAT.")
            continue
        total_cents = to_cents(total_e5)
        products.append(
            {
                "name": name,
                "category_id": category,
                "quantity_e5": quantity_e5,
                "unit_price_e5": price_e5,
                "total_e5": total_e5,
                "total_cents": total_cents,
                "vat_rate": vat_rate,
                "vat_cents": vat_from_gross(total_cents, vat_rate),
            }
        )

    if required and number == 0:
        errors.append("Dodaj co najmniej jeden produkt.")
    if sum(product["total_cents"] for product in products) > MAX_TRANSACTION_CENTS:
        errors.append("Kwota transakcji jest zbyt duża.")
    return products, errors


def validate_transaction(db, wallet_id, kind, occurred_on, description, rows):
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
    products, product_errors = parse_product_rows(
        rows, category_ids, has_vat=wallet_has_vat(db, wallet_id)
    )
    errors += product_errors
    if errors:
        raise ValidationError(errors)
    return occurred_on, description, products


def insert_products(db, transaction_id, products):
    db.executemany(
        """
        INSERT INTO products (
            transaction_id, position, name, category_id,
            quantity_e5, unit_price_e5, total_e5, total_cents, vat_rate, vat_cents
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                transaction_id,
                position,
                product["name"],
                product["category_id"],
                product["quantity_e5"],
                product["unit_price_e5"],
                product["total_e5"],
                product["total_cents"],
                product.get("vat_rate"),
                product.get("vat_cents", 0),
            )
            for position, product in enumerate(products)
        ],
    )


def create_transaction(db, wallet_id, kind, occurred_on, description, rows):
    occurred_on, description, products = validate_transaction(
        db, wallet_id, kind, occurred_on, description, rows
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
    wallet_id = db.execute(
        "SELECT wallet_id FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()["wallet_id"]
    occurred_on, description, products = validate_transaction(
        db, wallet_id, kind, occurred_on, description, rows
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
            "quantity": format_quantity_input(product["quantity_e5"]),
            "price": format_precise_input(product["unit_price_e5"]),
            "total": format_precise_input(product["total_e5"]),
            "vat_rate": product["vat_rate"],
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
