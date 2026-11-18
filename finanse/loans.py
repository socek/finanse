"""Pożyczki udzielone i zaciągnięte, złożone z własnych pozycji: pożyczeń i spłat.

Pozycja jest poza portfelami, z własną datą, kwotą i rolą, albo jest powiązana
z transakcją w portfelu i wtedy bierze je z transakcji. Rolę transakcji wyznacza jej
rodzaj: przy pożyczce udzielonej wydatek to pożyczenie, a przychód spłata; przy
zaciągniętej odwrotnie. Dzięki temu edycja transakcji od razu zmienia stan pożyczki.
"""

from collections import defaultdict
from datetime import date

from .errors import ValidationError
from .money import format_money_input, parse_money
from .transactions import insert_products, validate_transaction
from .wallets import get_wallet

LENT, BORROWED = "lent", "borrowed"
PRINCIPAL, REPAYMENT = "principal", "repayment"
MAX_TEXT_LENGTH = 200
DIRECTION_NAMES = {LENT: "Udzielona", BORROWED: "Zaciągnięta"}
ROLE_NAMES = {PRINCIPAL: "Pożyczenie", REPAYMENT: "Spłata"}
# Warunek SQL dla raportów: pożyczki, jak przelewy, nie są przychodem ani wydatkiem.
NOT_LOAN = (
    "t.id NOT IN (SELECT transaction_id FROM loan_items WHERE transaction_id IS NOT NULL)"
)

_ITEMS = """
    SELECT li.id, li.loan_id, li.transaction_id, li.role AS own_role, l.direction,
           l.currency, t.kind, t.wallet_id, w.name AS wallet_name,
           COALESCE(t.occurred_on, li.occurred_on) AS occurred_on,
           CASE WHEN t.id IS NULL THEN li.description ELSE t.description END AS description,
           CASE WHEN t.id IS NULL THEN li.amount_cents
                ELSE (SELECT COALESCE(SUM(p.total_cents), 0) FROM products p
                      WHERE p.transaction_id = t.id)
           END AS amount_cents
    FROM loan_items li
    JOIN loans l ON l.id = li.loan_id
    LEFT JOIN transactions t ON t.id = li.transaction_id
    LEFT JOIN wallets w ON w.id = t.wallet_id
"""


def principal_kind(direction):
    """Rodzaj transakcji, który zwiększa pożyczkę."""
    return "expense" if direction == LENT else "income"


def repayment_kind(direction):
    """Rodzaj transakcji, który spłaca pożyczkę."""
    return "income" if direction == LENT else "expense"


def role_of(direction, kind):
    return PRINCIPAL if kind == principal_kind(direction) else REPAYMENT


def _kind_of(direction, role):
    return principal_kind(direction) if role == PRINCIPAL else repayment_kind(direction)


def _amount(text):
    try:
        cents = parse_money(text.strip())
    except ValueError:
        return None
    return cents if cents > 0 else None


def _date(text):
    try:
        return date.fromisoformat(text.strip()).isoformat()
    except ValueError:
        return None


def _validate_text(errors, person, description):
    person = person.strip()
    description = description.strip()
    if not person or len(person) > MAX_TEXT_LENGTH:
        errors.append(f"Podaj osobę lub instytucję (do {MAX_TEXT_LENGTH} znaków).")
    if len(description) > MAX_TEXT_LENGTH:
        errors.append(f"Opis może mieć najwyżej {MAX_TEXT_LENGTH} znaków.")
    return person, description


def default_description(direction, person, role):
    if role == REPAYMENT:
        return f"Spłata pożyczki – {person}"
    return f"Pożyczka dla {person}" if direction == LENT else f"Pożyczka od {person}"


def _item_row(row):
    item = dict(row)
    if item["transaction_id"] is None:
        item["role"] = item["own_role"]
    else:
        item["role"] = role_of(item["direction"], item["kind"])
    return item


def loan_items(db, loan_id):
    """Pozycje pożyczki od najstarszej, z rolą, kwotą i saldem pożyczki po każdej z nich."""
    items = sorted(
        (_item_row(row) for row in db.execute(_ITEMS + " WHERE li.loan_id = ?", (loan_id,))),
        key=lambda item: (item["occurred_on"], item["id"]),
    )
    balance = 0
    for item in items:
        balance += item["amount_cents"] if item["role"] == PRINCIPAL else -item["amount_cents"]
        item["balance_cents"] = balance
    return items


def get_loan_item(db, item_id):
    row = db.execute(_ITEMS + " WHERE li.id = ?", (item_id,)).fetchone()
    return _item_row(row) if row else None


def list_loans(db):
    """Pożyczki z kwotą, spłatami i pozostałą kwotą; najpierw niespłacone, od najnowszych."""
    loans = [dict(row) for row in db.execute("SELECT * FROM loans")]
    sums = defaultdict(lambda: {PRINCIPAL: 0, REPAYMENT: 0, "count": 0, "last": None})
    for row in db.execute(_ITEMS):
        item = _item_row(row)
        entry = sums[item["loan_id"]]
        entry[item["role"]] += item["amount_cents"]
        entry["count"] += 1
        entry["last"] = max(filter(None, (entry["last"], item["occurred_on"])))
    for loan in loans:
        entry = sums[loan["id"]]
        loan["principal_cents"] = entry[PRINCIPAL]
        loan["repaid_cents"] = entry[REPAYMENT]
        loan["outstanding_cents"] = entry[PRINCIPAL] - entry[REPAYMENT]
        loan["item_count"] = entry["count"]
        loan["last_on"] = entry["last"] or loan["opened_on"]
    loans.sort(key=lambda loan: (loan["opened_on"], loan["id"]), reverse=True)
    loans.sort(key=lambda loan: loan["outstanding_cents"] <= 0)
    return loans


def get_loan(db, loan_id):
    return next((loan for loan in list_loans(db) if loan["id"] == loan_id), None)


def loan_totals(loans):
    """Pozostałe do spłaty kwoty według rodzaju i waluty; spłacone pomija."""
    totals = {LENT: {}, BORROWED: {}}
    for loan in loans:
        if loan["outstanding_cents"] > 0:
            by_currency = totals[loan["direction"]]
            by_currency[loan["currency"]] = (
                by_currency.get(loan["currency"], 0) + loan["outstanding_cents"]
            )
    return totals


def _validate_item(loan, role, wallet, occurred_on, amount, description, freed=0):
    """Błędy pozycji; `freed` to zmiana pozostałej kwoty po pominięciu edytowanej pozycji."""
    errors = []
    if role not in (PRINCIPAL, REPAYMENT):
        errors.append("Wybierz, czy to pożyczenie, czy spłata.")
    if wallet is not None and wallet["currency"] != loan["currency"]:
        errors.append(f"Wybierz portfel w walucie pożyczki ({loan['currency']}).")
    cents = _amount(amount)
    left = loan["outstanding_cents"] + freed
    if cents is None:
        errors.append("Podaj poprawną, dodatnią kwotę.")
    elif role == REPAYMENT and cents > left:
        errors.append(
            "Kwota spłaty jest większa niż pozostało do spłacenia"
            f" ({format_money_input(max(left, 0))} {loan['currency']})."
        )
    occurred_on = _date(occurred_on)
    if occurred_on is None:
        errors.append("Podaj poprawną datę.")
    description = description.strip()
    if len(description) > MAX_TEXT_LENGTH:
        errors.append(f"Opis może mieć najwyżej {MAX_TEXT_LENGTH} znaków.")
    if errors:
        raise ValidationError(errors)
    return occurred_on, cents, description


def _insert_item(db, loan, role, wallet, occurred_on, cents, description):
    """Pozycja poza portfelami albo transakcja w portfelu z pozycją; zwraca id pozycji.

    Wywoływać wewnątrz `with db:`, żeby transakcja i pozycja były jedną operacją.
    """
    if wallet is None:
        return db.execute(
            "INSERT INTO loan_items (loan_id, role, occurred_on, amount_cents, description)"
            " VALUES (?, ?, ?, ?, ?)",
            (loan["id"], role, occurred_on, cents, description),
        ).lastrowid
    description = description or default_description(loan["direction"], loan["person"], role)
    kind = _kind_of(loan["direction"], role)
    rows = [{"name": description, "quantity": "1", "price": format_money_input(cents),
             "category": None}]  # fmt: skip
    occurred_on, description, products = validate_transaction(
        db, wallet["id"], kind, occurred_on, description, rows
    )
    transaction_id = db.execute(
        "INSERT INTO transactions (wallet_id, kind, occurred_on, description)"
        " VALUES (?, ?, ?, ?)",
        (wallet["id"], kind, occurred_on, description),
    ).lastrowid
    insert_products(db, transaction_id, products)
    return db.execute(
        "INSERT INTO loan_items (loan_id, transaction_id) VALUES (?, ?)",
        (loan["id"], transaction_id),
    ).lastrowid


def create_loan(
    db, direction, person, description, opened_on, amount, wallet_id=None, currency="PLN"
):
    """Nowa pożyczka z pierwszą pozycją, czyli pożyczoną kwotą. Z portfelem pozycja
    jest transakcją w nim, a bez portfela jest poza portfelami w podanej walucie."""
    errors = []
    if direction not in (LENT, BORROWED):
        errors.append("Wybierz, czy pożyczkę udzielasz, czy zaciągasz.")
    person, description = _validate_text(errors, person, description)
    opened_on = _date(opened_on)
    if opened_on is None:
        errors.append("Podaj poprawną datę.")
    cents = _amount(amount)
    if cents is None:
        errors.append("Podaj poprawną, dodatnią kwotę pożyczki.")
    wallet = None
    if wallet_id is not None:
        wallet = get_wallet(db, wallet_id)
        if wallet is None:
            errors.append("Wybierz portfel.")
        else:
            currency = wallet["currency"]
    else:
        currency = (currency or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            errors.append("Podaj kod waluty z 3 liter, np. PLN.")
    if errors:
        raise ValidationError(errors)

    with db:
        loan_id = db.execute(
            "INSERT INTO loans (direction, person, description, currency, opened_on)"
            " VALUES (?, ?, ?, ?, ?)",
            (direction, person, description, currency, opened_on),
        ).lastrowid
        loan = {"id": loan_id, "direction": direction, "person": person}
        _insert_item(db, loan, PRINCIPAL, wallet, opened_on, cents, description)
    return loan_id


def update_loan(db, loan_id, person, description, opened_on):
    """Zmienia osobę, opis i datę; rodzaj, waluta i pozycje zostają."""
    errors = []
    person, description = _validate_text(errors, person, description)
    opened_on = _date(opened_on)
    if opened_on is None:
        errors.append("Podaj poprawną datę.")
    if errors:
        raise ValidationError(errors)
    with db:
        db.execute(
            "UPDATE loans SET person = ?, description = ?, opened_on = ? WHERE id = ?",
            (person, description, opened_on, loan_id),
        )


def delete_loan(db, loan_id):
    """Usuwa pożyczkę i jej pozycje; transakcje zostają w portfelach."""
    with db:
        db.execute("DELETE FROM loans WHERE id = ?", (loan_id,))


def add_loan_item(db, loan_id, role, occurred_on, amount, description="", wallet_id=None):
    """Nowe pożyczenie lub spłata; z portfelem jako transakcja w nim. Zwraca id pozycji.

    Spłata nie może przekroczyć kwoty, która została do spłacenia.
    """
    loan = get_loan(db, loan_id)
    if loan is None:
        raise ValidationError("Pożyczka nie istnieje.")
    wallet = get_wallet(db, wallet_id) if wallet_id is not None else None
    if wallet_id is not None and wallet is None:
        raise ValidationError("Wybierz portfel.")
    occurred_on, cents, description = _validate_item(
        loan, role, wallet, occurred_on, amount, description
    )
    with db:
        return _insert_item(db, loan, role, wallet, occurred_on, cents, description)


def repay_loan(db, loan_id, occurred_on, amount, description="", wallet_id=None):
    return add_loan_item(db, loan_id, REPAYMENT, occurred_on, amount, description, wallet_id)


def update_loan_item(db, item_id, role, occurred_on, amount, description=""):
    """Zmienia pozycję poza portfelami; pozycję z transakcją zmienia się w portfelu."""
    item = get_loan_item(db, item_id)
    if item is None:
        raise ValidationError("Pozycja nie istnieje.")
    if item["transaction_id"] is not None:
        raise ValidationError("Tę pozycję tworzy transakcja: zmień ją w zakładce Portfele.")
    loan = get_loan(db, item["loan_id"])
    # Bez edytowanej pozycji zostaje więcej (gdy była spłatą) albo mniej (pożyczeniem).
    freed = item["amount_cents"] if item["role"] == REPAYMENT else -item["amount_cents"]
    occurred_on, cents, description = _validate_item(
        loan, role, None, occurred_on, amount, description, freed
    )
    with db:
        db.execute(
            "UPDATE loan_items SET role = ?, occurred_on = ?, amount_cents = ?,"
            " description = ? WHERE id = ?",
            (role, occurred_on, cents, description, item_id),
        )


def delete_loan_item(db, item_id):
    """Usuwa pozycję; powiązana transakcja zostaje w portfelu."""
    with db:
        db.execute("DELETE FROM loan_items WHERE id = ?", (item_id,))


def link_transaction(db, loan_id, transaction_id):
    """Dodaje istniejącą transakcję jako pozycję; transakcja należy do jednej pożyczki."""
    loan = db.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    transaction = transaction_summary(db, transaction_id)
    if loan is None or transaction is None:
        raise ValidationError("Wybierz pożyczkę i transakcję.")
    if transaction["currency"] != loan["currency"]:
        raise ValidationError(
            f"Transakcja jest w {transaction['currency']}, a pożyczka w {loan['currency']}."
        )
    current = loan_of_transaction(db, transaction_id)
    if current is not None and current["id"] != loan_id:
        raise ValidationError(
            f"Transakcja jest już powiązana z pożyczką „{current['person']}”."
            " Najpierw ją odłącz."
        )
    if current is not None:
        return
    with db:
        db.execute(
            "INSERT INTO loan_items (loan_id, transaction_id) VALUES (?, ?)",
            (loan_id, transaction_id),
        )


def unlink_transaction(db, transaction_id):
    """Usuwa pozycję transakcji z pożyczki; transakcja zostaje w portfelu."""
    with db:
        db.execute("DELETE FROM loan_items WHERE transaction_id = ?", (transaction_id,))


def loan_of_transaction(db, transaction_id):
    return db.execute(
        "SELECT l.* FROM loans l JOIN loan_items li ON li.loan_id = l.id"
        " WHERE li.transaction_id = ?",
        (transaction_id,),
    ).fetchone()


def transaction_summary(db, transaction_id):
    """Rodzaj, data, opis, waluta i kwota transakcji, np. do wyboru pożyczki."""
    return db.execute(
        """
        SELECT t.id, t.kind, t.occurred_on, t.description, w.currency,
               COALESCE(SUM(p.total_cents), 0) AS total_cents
        FROM transactions t
        JOIN wallets w ON w.id = t.wallet_id
        LEFT JOIN products p ON p.transaction_id = t.id
        WHERE t.id = ?
        GROUP BY t.id
        """,
        (transaction_id,),
    ).fetchone()


def loans_by_transaction(db, transaction_ids):
    """Osoba pożyczki dla każdej powiązanej transakcji z listy."""
    ids = list(transaction_ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {
        row["transaction_id"]: row["person"]
        for row in db.execute(
            f"SELECT li.transaction_id, l.person FROM loan_items li"
            f" JOIN loans l ON l.id = li.loan_id WHERE li.transaction_id IN ({marks})",
            ids,
        )
    }


def linkable_transactions(db, loan_id):
    """Transakcje w walucie pożyczki, niepowiązane z żadną pożyczką, od najnowszych."""
    loan = db.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    rows = db.execute(
        f"""
        SELECT t.id, t.kind, t.occurred_on, t.description, w.name AS wallet_name,
               w.currency, COALESCE(SUM(p.total_cents), 0) AS total_cents
        FROM transactions t
        JOIN wallets w ON w.id = t.wallet_id
        LEFT JOIN products p ON p.transaction_id = t.id
        WHERE w.currency = ? AND {NOT_LOAN}
        GROUP BY t.id
        ORDER BY t.occurred_on DESC, t.id DESC
        """,
        (loan["currency"],),
    ).fetchall()
    return [{**row, "role": role_of(loan["direction"], row["kind"])} for row in rows]
