import math
import re
from collections import Counter
from datetime import date

from .money import NBSP, format_money
from .wallets import list_wallets

MONTHS = (
    "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
    "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
)  # fmt: skip
MONTHS_SHORT = (
    "sty", "lut", "mar", "kwi", "maj", "cze",
    "lip", "sie", "wrz", "paź", "lis", "gru",
)  # fmt: skip
TREND_MONTHS = 12


def _shift_month(year, month, delta):
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _month_key(year, month):
    return f"{year:04d}-{month:02d}"


def _parse_month(text):
    match = re.fullmatch(r"([0-9]{4})-(0[1-9]|1[0-2])", text)
    if match and int(match[1]) >= 1:
        return int(match[1]), int(match[2])
    today = date.today()
    return today.year, today.month


def _resolve_selection(currency, wallet_ids, wallets):
    """Zwraca (walutę, wybrane portfele). Portfele w innej walucie są pomijane."""
    currencies = Counter(wallet["currency"] for wallet in wallets)
    if currency not in currencies:
        currency = min(currencies, key=lambda code: (-currencies[code], code))
    selected = [
        wallet
        for wallet in wallets
        if wallet["currency"] == currency
        and (wallet_ids is None or wallet["id"] in wallet_ids)
    ]
    return currency, selected


def axis_scale(max_cents):
    """Zaokrągla oś w górę do czytelnych wartości: zwraca (krok, maksimum) w jednostkach."""
    units = max(1, math.ceil(max_cents / 100))
    magnitude = 10 ** (len(str(units)) - 1)
    for base in (magnitude // 10, magnitude, magnitude * 10):
        for factor in (1, 2, 5):
            step = base * factor
            if step >= 1 and math.ceil(units / step) <= 5:
                return step, step * math.ceil(units / step)
    return units, units


def _format_tick(value, axis_max):
    if axis_max < 10_000:
        return f"{value:,}".replace(",", NBSP)
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value // 1_000_000}{NBSP}mln"
    if value == 0:
        return "0"
    return f"{value // 1000}{NBSP}tys."


def _trend(db, wallet_ids, year, month, currency):
    marks = ",".join("?" * len(wallet_ids))
    first_year, first_month = _shift_month(year, month, -(TREND_MONTHS - 1))
    end_year, end_month = _shift_month(year, month, 1)
    totals = {
        (row["month"], row["kind"]): row["total"]
        for row in db.execute(
            f"""
            SELECT substr(t.occurred_on, 1, 7) AS month, t.kind,
                   SUM(p.total_cents) AS total
            FROM transactions t
            JOIN products p ON p.transaction_id = t.id
            WHERE t.wallet_id IN ({marks})
              AND t.occurred_on >= ? AND t.occurred_on < ?
            GROUP BY month, t.kind
            """,
            (
                *wallet_ids,
                f"{_month_key(first_year, first_month)}-01",
                f"{_month_key(end_year, end_month)}-01",
            ),
        )
    }
    largest = max(totals.values(), default=0)
    step, axis_max = axis_scale(largest)
    months = []
    for offset in range(TREND_MONTHS):
        y, m = _shift_month(first_year, first_month, offset)
        key = _month_key(y, m)
        income = totals.get((key, "income"), 0)
        expense = totals.get((key, "expense"), 0)
        title = f"{MONTHS[m - 1]} {y}"
        months.append(
            {
                "key": key,
                "title": title,
                "short": MONTHS_SHORT[m - 1],
                "income": income,
                "expense": expense,
                "income_pct": round(income / (axis_max * 100) * 100, 2),
                "expense_pct": round(expense / (axis_max * 100) * 100, 2),
                "selected": (y, m) == (year, month),
                "tip": (
                    f"{title} · Przychody: {format_money(income, currency)}"
                    f" · Wydatki: {format_money(expense, currency)}"
                ),
            }
        )
    ticks = [
        {
            "label": _format_tick(value, axis_max),
            "pct": round(value / axis_max * 100, 2),
        }
        for value in range(0, axis_max + 1, step)
    ]
    return {"months": months, "ticks": ticks, "has_data": largest > 0}


def _by_category(db, wallet_ids, year, month, kind, currency):
    marks = ",".join("?" * len(wallet_ids))
    end_year, end_month = _shift_month(year, month, 1)
    rows = (
        db.execute(
            f"""
            SELECT COALESCE(c.name, 'Bez kategorii') AS name,
                   SUM(p.total_cents) AS total
            FROM products p
            JOIN transactions t ON t.id = p.transaction_id
            LEFT JOIN categories c ON c.id = p.category_id
            WHERE t.wallet_id IN ({marks}) AND t.kind = ?
              AND t.occurred_on >= ? AND t.occurred_on < ?
            GROUP BY c.id
            HAVING total > 0
            ORDER BY total DESC, name
            """,
            (
                *wallet_ids,
                kind,
                f"{_month_key(year, month)}-01",
                f"{_month_key(end_year, end_month)}-01",
            ),
        )
        .fetchall()
    )
    grand_total = sum(row["total"] for row in rows)
    largest = rows[0]["total"] if rows else 0
    result = []
    for row in rows:
        percent = round(row["total"] / grand_total * 100)
        share = f"{percent}%" if percent > 0 else "<1%"
        amount = format_money(row["total"], currency)
        result.append(
            {
                "name": row["name"],
                "total": row["total"],
                "share": share,
                "bar_pct": round(row["total"] / largest * 100, 2),
                "tip": f"{row['name']} · {amount} · {share}",
            }
        )
    return result, grand_total


def _wallet_totals(db, wallets, year, month):
    """Przychody, wydatki i bilans miesiąca osobno dla każdego portfela."""
    end_year, end_month = _shift_month(year, month, 1)
    marks = ",".join("?" * len(wallets))
    totals = {
        (row["wallet_id"], row["kind"]): row["total"]
        for row in db.execute(
            f"""
            SELECT t.wallet_id, t.kind, SUM(p.total_cents) AS total
            FROM transactions t
            JOIN products p ON p.transaction_id = t.id
            WHERE t.wallet_id IN ({marks})
              AND t.occurred_on >= ? AND t.occurred_on < ?
            GROUP BY t.wallet_id, t.kind
            """,
            (
                *(wallet["id"] for wallet in wallets),
                f"{_month_key(year, month)}-01",
                f"{_month_key(end_year, end_month)}-01",
            ),
        )
    }
    result = []
    for wallet in wallets:
        income = totals.get((wallet["id"], "income"), 0)
        expense = totals.get((wallet["id"], "expense"), 0)
        result.append(
            {
                "id": wallet["id"],
                "name": wallet["name"],
                "income": income,
                "expense": expense,
                "net": income - expense,
            }
        )
    return result


def build_report(db, currency="", wallet_ids=None, month=""):
    """Raport miesięczny z wybranych portfeli jednej waluty.

    `wallet_ids=None` oznacza wszystkie portfele tej waluty. Zwraca None, gdy nie
    ma żadnego portfela.
    """
    wallets = list_wallets(db)
    if not wallets:
        return None

    year, month_number = _parse_month(month)
    currency, selected = _resolve_selection(currency, wallet_ids, wallets)
    ids = [wallet["id"] for wallet in selected]
    expenses, expense_total = _by_category(
        db, ids, year, month_number, "expense", currency
    )
    incomes, income_total = _by_category(db, ids, year, month_number, "income", currency)
    return {
        "wallets": wallets,
        "currencies": sorted({wallet["currency"] for wallet in wallets}),
        "currency": currency,
        "selected_ids": ids,
        "wallet_totals": _wallet_totals(db, selected, year, month_number),
        "month_key": _month_key(year, month_number),
        "month_title": f"{MONTHS[month_number - 1]} {year}",
        "previous_month": _month_key(*_shift_month(year, month_number, -1)),
        "next_month": _month_key(*_shift_month(year, month_number, 1)),
        "expenses": expenses,
        "expense_total": expense_total,
        "incomes": incomes,
        "income_total": income_total,
        "net_total": income_total - expense_total,
        "trend": _trend(db, ids, year, month_number, currency),
    }
