from datetime import date
from itertools import zip_longest

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

from .auth import login_required
from .categories import user_categories
from .db import get_db
from .money import (
    MAX_TRANSACTION_CENTS,
    format_money_input,
    format_quantity,
    line_total,
    parse_money,
    parse_quantity,
)
from .wallets import get_wallet_or_404

bp = Blueprint("transactions", __name__)

MAX_TEXT_LENGTH = 200
EMPTY_ROW = {"name": "", "category": "", "quantity": "1", "price": ""}


def _get_transaction_or_404(transaction_id):
    transaction = (
        get_db()
        .execute(
            """
            SELECT t.*
            FROM transactions t
            JOIN wallets w ON w.id = t.wallet_id
            WHERE t.id = ? AND w.user_id = ?
            """,
            (transaction_id, g.user["id"]),
        )
        .fetchone()
    )
    if transaction is None:
        abort(404)
    return transaction


def _parse_product_rows(form, category_ids):
    """Zwraca (wiersze formularza, produkty do zapisu, błędy). Puste wiersze pomija."""
    rows, products, errors = [], [], []
    columns = zip_longest(
        form.getlist("product_name"),
        form.getlist("product_quantity"),
        form.getlist("product_price"),
        form.getlist("product_category"),
        fillvalue="",
    )
    for name, quantity, price, category in columns:
        name, quantity, price = name.strip(), quantity.strip(), price.strip()
        if not name and not price and quantity in ("", "1"):
            continue
        rows.append(
            {"name": name, "category": category, "quantity": quantity, "price": price}
        )
        number = len(rows)

        if not name or len(name) > MAX_TEXT_LENGTH:
            errors.append(f"Produkt {number}: podaj nazwę (do {MAX_TEXT_LENGTH} znaków).")
        if category and category not in category_ids:
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
                "category_id": int(category) if category else None,
                "quantity_milli": quantity_milli,
                "unit_price_cents": price_cents,
                "total_cents": line_total(quantity_milli, price_cents),
            }
        )

    if not rows:
        errors.append("Dodaj co najmniej jeden produkt.")
    if sum(product["total_cents"] for product in products) > MAX_TRANSACTION_CENTS:
        errors.append("Kwota transakcji jest zbyt duża.")
    return rows, products, errors


def _parse_transaction_form(form, categories):
    values = {
        "kind": form.get("kind", ""),
        "occurred_on": form.get("occurred_on", "").strip(),
        "description": form.get("description", "").strip(),
    }
    errors = []
    if values["kind"] not in ("expense", "income"):
        errors.append("Wybierz rodzaj transakcji.")
    try:
        values["occurred_on"] = date.fromisoformat(values["occurred_on"]).isoformat()
    except ValueError:
        errors.append("Podaj poprawną datę.")
    if not values["description"] or len(values["description"]) > MAX_TEXT_LENGTH:
        errors.append(f"Podaj opis (do {MAX_TEXT_LENGTH} znaków).")
    category_ids = {str(category["id"]) for category in categories}
    rows, products, product_errors = _parse_product_rows(form, category_ids)
    return values, rows, products, errors + product_errors


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


def _render_form(wallet, values, rows, categories, title, transaction=None):
    return render_template(
        "transactions/form.html",
        wallet=wallet,
        values=values,
        rows=rows or [EMPTY_ROW],
        empty_row=EMPTY_ROW,
        categories=categories,
        title=title,
        transaction=transaction,
    )


@bp.route("/wallets/<int:wallet_id>/transactions/new", methods=("GET", "POST"))
@login_required
def create(wallet_id):
    wallet = get_wallet_or_404(wallet_id)
    categories = user_categories()
    values = {
        "kind": "expense",
        "occurred_on": date.today().isoformat(),
        "description": "",
    }
    rows = []
    if request.method == "POST":
        values, rows, products, errors = _parse_transaction_form(
            request.form, categories
        )
        if not errors:
            db = get_db()
            with db:
                cursor = db.execute(
                    "INSERT INTO transactions"
                    " (wallet_id, kind, occurred_on, description)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        wallet_id,
                        values["kind"],
                        values["occurred_on"],
                        values["description"],
                    ),
                )
                insert_products(db, cursor.lastrowid, products)
            return redirect(url_for("wallets.detail", wallet_id=wallet_id))
        for error in errors:
            flash(error, "error")
    return _render_form(wallet, values, rows, categories, "Nowa transakcja")


@bp.route("/transactions/<int:transaction_id>/edit", methods=("GET", "POST"))
@login_required
def edit(transaction_id):
    transaction = _get_transaction_or_404(transaction_id)
    wallet = get_wallet_or_404(transaction["wallet_id"])
    categories = user_categories()
    db = get_db()
    if request.method == "POST":
        values, rows, products, errors = _parse_transaction_form(
            request.form, categories
        )
        if not errors:
            with db:
                db.execute(
                    "UPDATE transactions"
                    " SET kind = ?, occurred_on = ?, description = ?"
                    " WHERE id = ?",
                    (
                        values["kind"],
                        values["occurred_on"],
                        values["description"],
                        transaction_id,
                    ),
                )
                db.execute(
                    "DELETE FROM products WHERE transaction_id = ?", (transaction_id,)
                )
                insert_products(db, transaction_id, products)
            return redirect(url_for("wallets.detail", wallet_id=wallet["id"]))
        for error in errors:
            flash(error, "error")
    else:
        values = {
            "kind": transaction["kind"],
            "occurred_on": transaction["occurred_on"],
            "description": transaction["description"],
        }
        rows = [
            {
                "name": product["name"],
                "category": str(product["category_id"] or ""),
                "quantity": format_quantity(product["quantity_milli"]),
                "price": format_money_input(product["unit_price_cents"]),
            }
            for product in db.execute(
                "SELECT * FROM products WHERE transaction_id = ? ORDER BY position",
                (transaction_id,),
            )
        ]
    return _render_form(
        wallet, values, rows, categories, "Edycja transakcji", transaction
    )


@bp.post("/transactions/<int:transaction_id>/delete")
@login_required
def delete(transaction_id):
    transaction = _get_transaction_or_404(transaction_id)
    db = get_db()
    with db:
        db.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
    flash("Usunięto transakcję.", "success")
    return redirect(url_for("wallets.detail", wallet_id=transaction["wallet_id"]))
