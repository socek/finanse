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
from .wallets import user_wallets

bp = Blueprint("transfers", __name__, url_prefix="/transfers")

MAX_TEXT_LENGTH = 200


def _get_transfer_or_404(transfer_id):
    transfer = (
        get_db()
        .execute(
            """
            SELECT tr.*
            FROM transfers tr
            JOIN wallets w ON w.id = tr.from_wallet_id
            WHERE tr.id = ? AND w.user_id = ?
            """,
            (transfer_id, g.user["id"]),
        )
        .fetchone()
    )
    if transfer is None:
        abort(404)
    return transfer


def _positive_amount(text):
    """Kwota w groszach albo None, gdy jest niepoprawna lub niedodatnia."""
    try:
        cents = parse_money(text)
    except ValueError:
        return None
    return cents if cents > 0 else None


def _parse_form(form, wallets):
    values = {
        "from_wallet": form.get("from_wallet", ""),
        "to_wallet": form.get("to_wallet", ""),
        "occurred_on": form.get("occurred_on", "").strip(),
        "description": form.get("description", "").strip(),
        "amount_from": form.get("amount_from", "").strip(),
        "amount_to": form.get("amount_to", "").strip(),
    }
    errors = []
    by_id = {str(wallet["id"]): wallet for wallet in wallets}
    source = by_id.get(values["from_wallet"])
    target = by_id.get(values["to_wallet"])
    if source is None or target is None:
        errors.append("Wybierz portfel źródłowy i docelowy.")
    elif source["id"] == target["id"]:
        errors.append("Portfel źródłowy i docelowy muszą być różne.")
    try:
        values["occurred_on"] = date.fromisoformat(values["occurred_on"]).isoformat()
    except ValueError:
        errors.append("Podaj poprawną datę.")
    if len(values["description"]) > MAX_TEXT_LENGTH:
        errors.append(f"Opis może mieć najwyżej {MAX_TEXT_LENGTH} znaków.")

    amount_from = _positive_amount(values["amount_from"])
    amount_to = amount_from
    if amount_from is None:
        errors.append("Podaj poprawną kwotę przelewu.")
    if source and target and source["currency"] != target["currency"]:
        amount_to = _positive_amount(values["amount_to"])
        if amount_to is None:
            errors.append(
                f"Portfele mają różne waluty: podaj kwotę w {target['currency']}."
            )
    data = {
        "from_wallet_id": source["id"] if source else None,
        "to_wallet_id": target["id"] if target else None,
        "occurred_on": values["occurred_on"],
        "description": values["description"] or "Przelew",
        "amount_from_cents": amount_from,
        "amount_to_cents": amount_to,
    }
    return values, data, errors


def _render_form(wallets, values, title, transfer=None):
    return render_template(
        "transfers/form.html",
        wallets=wallets,
        values=values,
        title=title,
        transfer=transfer,
    )


@bp.route("/new", methods=("GET", "POST"))
@login_required
def create():
    wallets = user_wallets()
    values = {
        "from_wallet": request.args.get("from", ""),
        "to_wallet": "",
        "occurred_on": date.today().isoformat(),
        "description": "",
        "amount_from": "",
        "amount_to": "",
    }
    if request.method == "POST":
        values, data, errors = _parse_form(request.form, wallets)
        if not errors:
            db = get_db()
            with db:
                db.execute(
                    """
                    INSERT INTO transfers (
                        from_wallet_id, to_wallet_id, occurred_on, description,
                        amount_from_cents, amount_to_cents
                    ) VALUES (
                        :from_wallet_id, :to_wallet_id, :occurred_on, :description,
                        :amount_from_cents, :amount_to_cents
                    )
                    """,
                    data,
                )
            return redirect(
                url_for("wallets.detail", wallet_id=data["from_wallet_id"])
            )
        for error in errors:
            flash(error, "error")
    return _render_form(wallets, values, "Nowy przelew")


@bp.route("/<int:transfer_id>/edit", methods=("GET", "POST"))
@login_required
def edit(transfer_id):
    transfer = _get_transfer_or_404(transfer_id)
    wallets = user_wallets()
    values = {
        "from_wallet": str(transfer["from_wallet_id"]),
        "to_wallet": str(transfer["to_wallet_id"]),
        "occurred_on": transfer["occurred_on"],
        "description": transfer["description"],
        "amount_from": format_money_input(transfer["amount_from_cents"]),
        "amount_to": format_money_input(transfer["amount_to_cents"]),
    }
    if request.method == "POST":
        values, data, errors = _parse_form(request.form, wallets)
        if not errors:
            db = get_db()
            with db:
                db.execute(
                    """
                    UPDATE transfers
                    SET from_wallet_id = :from_wallet_id,
                        to_wallet_id = :to_wallet_id,
                        occurred_on = :occurred_on,
                        description = :description,
                        amount_from_cents = :amount_from_cents,
                        amount_to_cents = :amount_to_cents
                    WHERE id = :id
                    """,
                    {**data, "id": transfer_id},
                )
            return redirect(
                url_for("wallets.detail", wallet_id=data["from_wallet_id"])
            )
        for error in errors:
            flash(error, "error")
    return _render_form(wallets, values, "Edycja przelewu", transfer)


@bp.post("/<int:transfer_id>/delete")
@login_required
def delete(transfer_id):
    transfer = _get_transfer_or_404(transfer_id)
    db = get_db()
    with db:
        db.execute("DELETE FROM transfers WHERE id = ?", (transfer_id,))
    flash("Usunięto przelew.", "success")
    return redirect(url_for("wallets.detail", wallet_id=transfer["from_wallet_id"]))
