"""Prognoza salda: saldo dziś, wpisane już przyszłe operacje i zaplanowane płatności cykliczne.

Zaległe płatności cykliczne liczą się do prognozy, bo nadal trzeba je zapłacić. Szablon
bez produktów nie ma kwoty, więc jego płatności są wymienione, ale nie zmieniają salda.
"""

import calendar
from datetime import date

from .recurring import advance_due
from .wallets import list_wallets

# Zabezpieczenie przed nieskończoną pętlą, np. płatność codzienna na wiele lat naprzód.
MAX_PAYMENTS_PER_TEMPLATE = 1000


def end_of_month(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def scheduled_payments(db, until, today=None):
    """Płatności cykliczne z terminem do `until` włącznie, od najwcześniejszej."""
    today = today or date.today()
    templates = db.execute(
        """
        SELECT r.*, w.name AS wallet_name, w.currency,
               (SELECT COUNT(*) FROM recurring_products p WHERE p.recurring_id = r.id)
                   AS product_count,
               (SELECT SUM(p.total_cents) FROM recurring_products p
                WHERE p.recurring_id = r.id) AS total_cents
        FROM recurring_transactions r
        JOIN wallets w ON w.id = r.wallet_id
        WHERE r.next_due_on IS NOT NULL AND r.next_due_on <= ?
          AND (r.remaining IS NULL OR r.remaining > 0)
          AND NOT r.suspended
        """,
        (until.isoformat(),),
    ).fetchall()
    payments = []
    for template in templates:
        due = template["next_due_on"]
        left = template["remaining"]
        count = 0
        while due <= until.isoformat() and (left is None or count < left):
            payments.append(
                {
                    "recurring_id": template["id"],
                    "description": template["description"],
                    "wallet_id": template["wallet_id"],
                    "wallet_name": template["wallet_name"],
                    "currency": template["currency"],
                    "kind": template["kind"],
                    "due_on": due,
                    "amount_cents": template["total_cents"] if template["product_count"] else None,
                    "overdue": due < today.isoformat(),
                }
            )
            count += 1
            if count >= MAX_PAYMENTS_PER_TEMPLATE:
                break
            due = advance_due(
                due, template["period_unit"], template["period_count"], template["due_day"]
            )
    payments.sort(key=lambda payment: (payment["due_on"], payment["description"].casefold()))
    return payments


def balance_forecast(db, until=None, today=None, wallet_ids=None):
    """Prognoza salda każdego portfela na koniec dnia `until`, domyślnie końca miesiąca.

    Dzień wcześniejszy niż dzisiaj jest zamieniany na dzisiaj, bo prognoza patrzy naprzód.
    `wallet_ids=None` oznacza wszystkie portfele.
    """
    today = today or date.today()
    until = max(until or end_of_month(today), today)
    now = {wallet["id"]: wallet for wallet in list_wallets(db, today.isoformat())}
    later = {wallet["id"]: wallet for wallet in list_wallets(db, until.isoformat())}
    payments = [
        payment
        for payment in scheduled_payments(db, until, today)
        if wallet_ids is None or payment["wallet_id"] in wallet_ids
    ]
    wallets = []
    for wallet_id, wallet in now.items():
        if wallet_ids is not None and wallet_id not in wallet_ids:
            continue
        own = [payment for payment in payments if payment["wallet_id"] == wallet_id]
        known = [payment for payment in own if payment["amount_cents"] is not None]
        income = sum(p["amount_cents"] for p in known if p["kind"] == "income")
        expense = sum(p["amount_cents"] for p in known if p["kind"] == "expense")
        planned = later[wallet_id]["balance_cents"] - wallet["balance_cents"]
        wallets.append(
            {
                "id": wallet_id,
                "name": wallet["name"],
                "currency": wallet["currency"],
                "balance": wallet["balance_cents"],
                "planned": planned,
                "recurring_income": income,
                "recurring_expense": expense,
                "unknown": len(own) - len(known),
                "forecast": later[wallet_id]["balance_cents"] + income - expense,
            }
        )
    totals = {}
    for wallet in wallets:
        total = totals.setdefault(wallet["currency"], {"balance": 0, "forecast": 0})
        total["balance"] += wallet["balance"]
        total["forecast"] += wallet["forecast"]
    return {
        "today": today.isoformat(),
        "until": until.isoformat(),
        "wallets": wallets,
        "payments": payments,
        "totals": totals,
        "unknown": sum(wallet["unknown"] for wallet in wallets),
    }
