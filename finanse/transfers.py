from datetime import date

from .errors import ValidationError
from .money import parse_money
from .wallets import list_wallets

MAX_TEXT_LENGTH = 200


def _positive_amount(text):
    """Kwota w groszach albo None, gdy jest niepoprawna lub niedodatnia."""
    try:
        cents = parse_money(text.strip())
    except ValueError:
        return None
    return cents if cents > 0 else None


def _validate(db, from_wallet, to_wallet, occurred_on, description, amount_from, amount_to):
    errors = []
    by_id = {wallet["id"]: wallet for wallet in list_wallets(db)}
    source = by_id.get(from_wallet)
    target = by_id.get(to_wallet)
    if source is None or target is None:
        errors.append("Wybierz portfel źródłowy i docelowy.")
    elif source["id"] == target["id"]:
        errors.append("Portfel źródłowy i docelowy muszą być różne.")
    try:
        occurred_on = date.fromisoformat(occurred_on.strip()).isoformat()
    except ValueError:
        errors.append("Podaj poprawną datę.")
    description = description.strip()
    if len(description) > MAX_TEXT_LENGTH:
        errors.append(f"Opis może mieć najwyżej {MAX_TEXT_LENGTH} znaków.")

    cents_from = _positive_amount(amount_from)
    cents_to = cents_from
    if cents_from is None:
        errors.append("Podaj poprawną kwotę przelewu.")
    if source and target and source["currency"] != target["currency"]:
        cents_to = _positive_amount(amount_to)
        if cents_to is None:
            errors.append(
                f"Portfele mają różne waluty: podaj kwotę w {target['currency']}."
            )
    if errors:
        raise ValidationError(errors)
    return {
        "from_wallet_id": from_wallet,
        "to_wallet_id": to_wallet,
        "occurred_on": occurred_on,
        "description": description or "Przelew",
        "amount_from_cents": cents_from,
        "amount_to_cents": cents_to,
    }


def create_transfer(
    db, from_wallet, to_wallet, occurred_on, description, amount_from, amount_to=""
):
    data = _validate(
        db, from_wallet, to_wallet, occurred_on, description, amount_from, amount_to
    )
    with db:
        return db.execute(
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
        ).lastrowid


def update_transfer(
    db, transfer_id, from_wallet, to_wallet, occurred_on, description, amount_from,
    amount_to="",
):  # fmt: skip
    data = _validate(
        db, from_wallet, to_wallet, occurred_on, description, amount_from, amount_to
    )
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


def get_transfer(db, transfer_id):
    return db.execute(
        "SELECT * FROM transfers WHERE id = ?", (transfer_id,)
    ).fetchone()


def delete_transfer(db, transfer_id):
    with db:
        db.execute("DELETE FROM transfers WHERE id = ?", (transfer_id,))
