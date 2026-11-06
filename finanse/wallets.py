import re
import sqlite3
from collections import defaultdict
from datetime import date

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
from .db import get_db
from .money import format_money_input, parse_money

bp = Blueprint("wallets", __name__, url_prefix="/wallets")

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
    WHERE w.user_id = ?
"""


def get_wallet_or_404(wallet_id):
    """Zwraca portfel zalogowanego użytkownika; cudzy traktuje jak nieistniejący."""
    wallet = (
        get_db()
        .execute(_WALLET_WITH_BALANCE + " AND w.id = ?", (g.user["id"], wallet_id))
        .fetchone()
    )
    if wallet is None:
        abort(404)
    return wallet


def user_wallets():
    return (
        get_db()
        .execute(_WALLET_WITH_BALANCE + " ORDER BY w.name", (g.user["id"],))
        .fetchall()
    )


def _parse_wallet_form(form):
    values = {
        "name": form.get("name", "").strip(),
        "currency": form.get("currency", "").strip().upper(),
        "initial_balance": form.get("initial_balance", "").strip(),
    }
    errors = []
    if not values["name"] or len(values["name"]) > MAX_NAME_LENGTH:
        errors.append(f"Podaj nazwę portfela (do {MAX_NAME_LENGTH} znaków).")
    if not re.fullmatch(r"[A-Z]{3}", values["currency"]):
        errors.append("Waluta musi być trzyliterowym kodem, np. PLN.")
    initial_cents = 0
    try:
        initial_cents = parse_money(values["initial_balance"] or "0")
    except ValueError:
        errors.append("Niepoprawne saldo początkowe.")
    return values, initial_cents, errors


def _date_param(name, label):
    """Data z adresu; niepoprawną zgłasza i ignoruje."""
    text = request.args.get(name, "").strip()
    if not text:
        return ""
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        flash(f"Niepoprawna data w polu „{label}”.", "error")
        return ""


def _load_entries(wallet_id, date_from, date_to):
    """Transakcje i przelewy portfela z okresu, od najnowszych."""
    db = get_db()
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
    return entries, transactions


@bp.get("")
@login_required
def index():
    return render_template("wallets/list.html", wallets=user_wallets())


@bp.route("/new", methods=("GET", "POST"))
@login_required
def create():
    values = {"name": "", "currency": "PLN", "initial_balance": "0,00"}
    if request.method == "POST":
        values, initial_cents, errors = _parse_wallet_form(request.form)
        if not errors:
            db = get_db()
            try:
                with db:
                    cursor = db.execute(
                        "INSERT INTO wallets"
                        " (user_id, name, currency, initial_balance_cents)"
                        " VALUES (?, ?, ?, ?)",
                        (
                            g.user["id"],
                            values["name"],
                            values["currency"],
                            initial_cents,
                        ),
                    )
            except sqlite3.IntegrityError:
                errors.append("Masz już portfel o tej nazwie.")
            else:
                return redirect(url_for("wallets.detail", wallet_id=cursor.lastrowid))
        for error in errors:
            flash(error, "error")
    return render_template(
        "wallets/form.html", values=values, title="Nowy portfel", wallet=None
    )


@bp.get("/<int:wallet_id>")
@login_required
def detail(wallet_id):
    wallet = get_wallet_or_404(wallet_id)
    date_from = _date_param("date_from", "Od")
    date_to = _date_param("date_to", "Do")
    if date_from and date_to and date_from > date_to:
        flash("Data „Od” nie może być późniejsza niż „Do”.", "error")
    entries, transactions = _load_entries(wallet_id, date_from, date_to)
    filtered = bool(date_from or date_to)
    summary = None
    if filtered:
        summary = {
            kind: sum(t["total_cents"] for t in transactions if t["kind"] == kind)
            for kind in ("income", "expense")
        }
    return render_template(
        "wallets/detail.html",
        wallet=wallet,
        entries=entries,
        date_from=date_from,
        date_to=date_to,
        filtered=filtered,
        summary=summary,
    )


@bp.route("/<int:wallet_id>/edit", methods=("GET", "POST"))
@login_required
def edit(wallet_id):
    wallet = get_wallet_or_404(wallet_id)
    values = {
        "name": wallet["name"],
        "currency": wallet["currency"],
        "initial_balance": format_money_input(wallet["initial_balance_cents"]),
    }
    if request.method == "POST":
        values, initial_cents, errors = _parse_wallet_form(request.form)
        if not errors:
            db = get_db()
            try:
                with db:
                    db.execute(
                        "UPDATE wallets"
                        " SET name = ?, currency = ?, initial_balance_cents = ?"
                        " WHERE id = ?",
                        (
                            values["name"],
                            values["currency"],
                            initial_cents,
                            wallet_id,
                        ),
                    )
            except sqlite3.IntegrityError:
                errors.append("Masz już portfel o tej nazwie.")
            else:
                return redirect(url_for("wallets.detail", wallet_id=wallet_id))
        for error in errors:
            flash(error, "error")
    return render_template(
        "wallets/form.html", values=values, title="Edycja portfela", wallet=wallet
    )


@bp.post("/<int:wallet_id>/delete")
@login_required
def delete(wallet_id):
    wallet = get_wallet_or_404(wallet_id)
    db = get_db()
    has_transfers = db.execute(
        "SELECT 1 FROM transfers WHERE from_wallet_id = ? OR to_wallet_id = ? LIMIT 1",
        (wallet_id, wallet_id),
    ).fetchone()
    if has_transfers:
        flash(
            "Ten portfel ma przelewy. Usuń je najpierw, bo wpływają na saldo "
            "drugiego portfela.",
            "error",
        )
        return redirect(url_for("wallets.detail", wallet_id=wallet_id))
    with db:
        db.execute("DELETE FROM wallets WHERE id = ?", (wallet_id,))
    flash(f"Usunięto portfel „{wallet['name']}”.", "success")
    return redirect(url_for("wallets.index"))
