"""Transakcje cykliczne: szablony, z których płatność tworzy zwykłą transakcję."""

import calendar
import re
from datetime import date, timedelta

from .errors import ValidationError
from .money import format_precise_input, format_quantity_input
from .tags import set_transaction_tags
from .transactions import (
    MAX_TEXT_LENGTH,
    insert_products,
    parse_product_rows,
    validate_tags,
    validate_transaction,
)
from .wallets import wallet_has_vat

PERIOD_UNITS = ("day", "week", "month", "year")
# Formy po liczbie: 1, 2–4 (poza 12–14) i pozostałe.
_UNIT_FORMS = {
    "day": ("dzień", "dni", "dni"),
    "week": ("tydzień", "tygodnie", "tygodni"),
    "month": ("miesiąc", "miesiące", "miesięcy"),
    "year": ("rok", "lata", "lat"),
}
# Tyle dni przed terminem płatność jest wyróżniana jako zbliżająca się.
DUE_SOON_DAYS = 7
MAX_PERIOD_COUNT = 999
NO_SCHEDULE = {"unit": None, "count": 1, "next_due_on": None}


def unit_name(unit, count):
    one, few, many = _UNIT_FORMS[unit]
    if count == 1:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many


def period_text(unit, count):
    """Np. „co miesiąc” albo „co 3 miesiące”."""
    if unit is None:
        return "bez terminu"
    if count == 1:
        return f"co {unit_name(unit, 1)}"
    return f"co {count} {unit_name(unit, count)}"


def advance_due(due_on, unit, count, due_day):
    """Termin o jeden okres później. Miesiące i lata wracają do dnia `due_day`."""
    due = date.fromisoformat(due_on)
    if unit == "day":
        return (due + timedelta(days=count)).isoformat()
    if unit == "week":
        return (due + timedelta(weeks=count)).isoformat()
    months = count * (12 if unit == "year" else 1)
    year, month = divmod(due.year * 12 + due.month - 1 + months, 12)
    month += 1
    day = min(due_day or due.day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


def days_until_due(item, today=None):
    """Dni do terminu, ujemne po terminie; None bez terminu, po ostatniej płatności i w zawieszeniu."""
    if item["next_due_on"] is None or item["remaining"] == 0 or item["suspended"]:
        return None
    today = today or date.today()
    return (date.fromisoformat(item["next_due_on"]) - today).days


def due_text(days):
    if days is None:
        return ""
    if days < 0:
        return f"po terminie {-days} {unit_name('day', -days)}"
    if days == 0:
        return "dzisiaj"
    if days == 1:
        return "jutro"
    return f"za {days} {unit_name('day', days)}"


def count_due(db, today=None):
    """Liczba płatności, których termin minął albo przypada dzisiaj."""
    today = today or date.today()
    return db.execute(
        """
        SELECT COUNT(*) FROM recurring_transactions
        WHERE next_due_on IS NOT NULL AND next_due_on <= ?
          AND (remaining IS NULL OR remaining > 0)
          AND NOT suspended
        """,
        (today.isoformat(),),
    ).fetchone()[0]


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
        ORDER BY r.remaining IS NOT NULL AND r.remaining = 0, r.suspended,
                 r.next_due_on IS NULL, r.next_due_on,
                 w.name, r.description, r.id
        """
    ).fetchall()


def recurring_totals(items):
    """Sumy kwot wg rodzaju i waluty; bez zakończonych, zawieszonych i bez ustalonej kwoty."""
    totals = {"expense": {}, "income": {}}
    for item in items:
        if item["total_cents"] is None or item["remaining"] == 0 or item["suspended"]:
            continue
        by_currency = totals[item["kind"]]
        by_currency[item["currency"]] = (
            by_currency.get(item["currency"], 0) + item["total_cents"]
        )
    return totals


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
            "vat_rate": product["vat_rate"],
        }
        for product in db.execute(
            "SELECT * FROM recurring_products WHERE recurring_id = ? ORDER BY position",
            (recurring_id,),
        )
    ]
    return {**dict(recurring), "rows": rows}


def _validate_schedule(schedule, errors):
    """Zwraca (termin, jednostka, liczba) albo trzy None dla transakcji bez terminu."""
    schedule = schedule or NO_SCHEDULE
    unit = schedule.get("unit")
    if unit is None:
        return None, None, None
    if unit not in PERIOD_UNITS:
        errors.append("Wybierz okres powtarzania.")
        return None, None, None
    count = str(schedule.get("count", "")).strip()
    if re.fullmatch(r"[0-9]{1,3}", count) and 1 <= int(count) <= MAX_PERIOD_COUNT:
        count = int(count)
    else:
        errors.append(f"Okres musi być liczbą od 1 do {MAX_PERIOD_COUNT}.")
        count = None
    try:
        due_on = date.fromisoformat(str(schedule.get("next_due_on") or "").strip())
    except ValueError:
        errors.append("Podaj poprawny termin następnej płatności.")
        due_on = None
    return (due_on.isoformat() if due_on else None), unit, count


def _due_day(db, recurring_id, due_on, unit):
    """Dzień terminu; bez zmiany terminu zostaje dotychczasowy, np. 31 mimo 28 lutego."""
    if due_on is None:
        return None
    if recurring_id is not None:
        old = db.execute(
            "SELECT next_due_on, period_unit, due_day FROM recurring_transactions"
            " WHERE id = ?",
            (recurring_id,),
        ).fetchone()
        if old and old["next_due_on"] == due_on and old["period_unit"] == unit:
            return old["due_day"]
    return date.fromisoformat(due_on).day


def _validate(db, wallet_id, kind, description, remaining, rows, schedule=None):
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
    products, product_errors = parse_product_rows(
        rows, category_ids, required=False, has_vat=wallet_has_vat(db, wallet_id)
    )
    errors += product_errors
    due = _validate_schedule(schedule, errors)
    if errors:
        raise ValidationError(errors)
    return description, count, products, due


def _insert_recurring_products(db, recurring_id, products):
    db.executemany(
        """
        INSERT INTO recurring_products (
            recurring_id, position, name, category_id,
            quantity_e5, unit_price_e5, total_e5, total_cents, vat_rate, vat_cents
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                product["vat_rate"],
                product["vat_cents"],
            )
            for position, product in enumerate(products)
        ],
    )


def create_recurring(
    db, wallet_id, kind, description, remaining="", rows=(), schedule=None
):
    """`schedule` to {"unit", "count", "next_due_on"}; bez niego transakcja nie ma terminu."""
    description, count, products, (due_on, unit, period) = _validate(
        db, wallet_id, kind, description, remaining, rows, schedule
    )
    with db:
        recurring_id = db.execute(
            """
            INSERT INTO recurring_transactions (
                wallet_id, kind, description, remaining,
                next_due_on, period_unit, period_count, due_day
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                wallet_id, kind, description, count,
                due_on, unit, period, _due_day(db, None, due_on, unit),
            ),
        ).lastrowid
        _insert_recurring_products(db, recurring_id, products)
    return recurring_id


def update_recurring(
    db, recurring_id, wallet_id, kind, description, remaining="", rows=(), schedule=None
):
    description, count, products, (due_on, unit, period) = _validate(
        db, wallet_id, kind, description, remaining, rows, schedule
    )
    due_day = _due_day(db, recurring_id, due_on, unit)
    with db:
        db.execute(
            """
            UPDATE recurring_transactions
            SET wallet_id = ?, kind = ?, description = ?, remaining = ?,
                next_due_on = ?, period_unit = ?, period_count = ?, due_day = ?
            WHERE id = ?
            """,
            (
                wallet_id, kind, description, count,
                due_on, unit, period, due_day, recurring_id,
            ),
        )
        db.execute(
            "DELETE FROM recurring_products WHERE recurring_id = ?", (recurring_id,)
        )
        _insert_recurring_products(db, recurring_id, products)


def delete_recurring(db, recurring_id):
    """Usuwa sam szablon; zapłacone już transakcje zostają."""
    with db:
        db.execute("DELETE FROM recurring_transactions WHERE id = ?", (recurring_id,))


def set_suspended(db, recurring_id, suspended):
    """Zawiesza albo wznawia transakcję; termin zostaje taki, jaki był."""
    with db:
        db.execute(
            "UPDATE recurring_transactions SET suspended = ? WHERE id = ?",
            (int(suspended), recurring_id),
        )


def _advanced_due(recurring):
    if recurring["next_due_on"] is None:
        return None
    return advance_due(
        recurring["next_due_on"],
        recurring["period_unit"],
        recurring["period_count"],
        recurring["due_day"],
    )


def skip_due(db, recurring_id):
    """Przesuwa termin o jeden okres bez płatności, np. gdy rachunku w tym miesiącu nie ma."""
    recurring = db.execute(
        "SELECT * FROM recurring_transactions WHERE id = ?", (recurring_id,)
    ).fetchone()
    if recurring is None:
        raise ValidationError("Ta transakcja cykliczna już nie istnieje.")
    if recurring["next_due_on"] is None:
        raise ValidationError("Ta transakcja cykliczna nie ma terminu.")
    if recurring["suspended"]:
        raise ValidationError("Ta transakcja cykliczna jest zawieszona.")
    if recurring["remaining"] == 0:
        raise ValidationError("Licznik tej transakcji cyklicznej doszedł już do zera.")
    with db:
        db.execute(
            "UPDATE recurring_transactions SET next_due_on = ? WHERE id = ?",
            (_advanced_due(recurring), recurring_id),
        )


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


def pay_recurring(db, recurring_id, kind, occurred_on, description, rows, tags=None):
    """Tworzy zwykłą transakcję, zmniejsza licznik i przesuwa termin o jeden okres.

    Termin liczy się od poprzedniego terminu, a nie od daty płatności, więc spóźniona
    płatność nie przesuwa kolejnych.
    """
    recurring = db.execute(
        "SELECT * FROM recurring_transactions WHERE id = ?", (recurring_id,)
    ).fetchone()
    if recurring is None:
        raise ValidationError("Ta transakcja cykliczna już nie istnieje.")
    if recurring["remaining"] == 0:
        raise ValidationError("Licznik tej transakcji cyklicznej doszedł już do zera.")
    occurred_on, description, products = validate_transaction(
        db, recurring["wallet_id"], kind, occurred_on, description, rows
    )
    tags = validate_tags(tags)
    with db:
        transaction_id = db.execute(
            "INSERT INTO transactions (wallet_id, kind, occurred_on, description)"
            " VALUES (?, ?, ?, ?)",
            (recurring["wallet_id"], kind, occurred_on, description),
        ).lastrowid
        insert_products(db, transaction_id, products)
        if tags:
            set_transaction_tags(db, transaction_id, tags)
        db.execute(
            """
            UPDATE recurring_transactions
            SET remaining = remaining - 1,
                last_paid_on = MAX(COALESCE(last_paid_on, ''), ?),
                next_due_on = ?
            WHERE id = ?
            """,
            (occurred_on, _advanced_due(recurring), recurring_id),
        )
    return transaction_id
