import math
import re
from collections import Counter
import calendar
from datetime import date, timedelta

from .budgets import budget_usage
from .money import NBSP, format_money
from .transactions import VAT_RATES
from .wallets import VAT, list_wallets

MONTHS = (
    "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec",
    "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień",
)  # fmt: skip
MONTHS_SHORT = (
    "sty", "lut", "mar", "kwi", "maj", "cze",
    "lip", "sie", "wrz", "paź", "lis", "gru",
)  # fmt: skip
MONTHS_GENITIVE = (
    "stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
    "lipca", "sierpnia", "września", "października", "listopada", "grudnia",
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


PERIODS = ("month", "year", "range")
# Dłuższy zakres pokazuje wykres po latach, bo słupki miesięcy byłyby nieczytelne.
MAX_TREND_MONTHS = 24


def _parse_year(text):
    text = str(text).strip()
    if re.fullmatch(r"[0-9]{4}", text) and int(text) >= 1:
        return int(text)
    return date.today().year


def _parse_date(text, default):
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        return default


def _format_date(day):
    return f"{day.day} {MONTHS_GENITIVE[day.month - 1]} {day.year}"


def _month_start(day):
    return day.replace(day=1)


def _next_month_start(day):
    year, month = _shift_month(day.year, day.month, 1)
    return date(year, month, 1)


def _period(period, month, year, start, end):
    """Okres raportu: początek, koniec (bez niego), tytuł i sąsiednie okresy."""
    if period == "year":
        number = _parse_year(year)
        return {
            "period": "year",
            "start": date(number, 1, 1),
            "end": date(number + 1, 1, 1),
            "title": f"rok {number}",
            "previous": {"period": "year", "year": str(number - 1)},
            "next": {"period": "year", "year": str(number + 1)},
        }
    if period == "range":
        today = date.today()
        first = _parse_date(start, _month_start(today))
        last = _parse_date(end, today)
        if last < first:
            first, last = last, first
        length = (last - first).days + 1
        shift = timedelta(days=length)

        def neighbour(offset):
            return {
                "period": "range",
                "start": (first + offset).isoformat(),
                "end": (last + offset).isoformat(),
            }

        return {
            "period": "range",
            "start": first,
            "end": last + timedelta(days=1),
            "title": f"{_format_date(first)} – {_format_date(last)}",
            "previous": neighbour(-shift),
            "next": neighbour(shift),
        }
    number, month_number = _parse_month(month)
    return {
        "period": "month",
        "start": date(number, month_number, 1),
        "end": date(*_shift_month(number, month_number, 1), 1),
        "title": f"{MONTHS[month_number - 1]} {number}",
        "previous": {"period": "month", "month": _month_key(*_shift_month(number, month_number, -1))},
        "next": {"period": "month", "month": _month_key(*_shift_month(number, month_number, 1))},
    }


def _month_buckets(first, count, selected=None):
    buckets = []
    for offset in range(count):
        year, month = _shift_month(first.year, first.month, offset)
        buckets.append(
            {
                "key": _month_key(year, month),
                "title": f"{MONTHS[month - 1]} {year}",
                "short": MONTHS_SHORT[month - 1],
                "selected": (year, month) == selected,
            }
        )
    return buckets


def _trend_buckets(span):
    """Słupki wykresu i przedział dat, z którego się sumują."""
    start, end = span["start"], span["end"]
    if span["period"] == "month":
        first = date(*_shift_month(start.year, start.month, -(TREND_MONTHS - 1)), 1)
        buckets = _month_buckets(first, TREND_MONTHS, (start.year, start.month))
        return "Ostatnie 12 miesięcy", buckets, first, end
    if span["period"] == "year":
        return f"Miesiące roku {start.year}", _month_buckets(start, 12), start, end
    last = end - timedelta(days=1)
    months = (last.year - start.year) * 12 + last.month - start.month + 1
    if months <= MAX_TREND_MONTHS:
        return "Według miesięcy", _month_buckets(start, months), start, end
    buckets = [
        {"key": str(year), "title": str(year), "short": str(year), "selected": False}
        for year in range(start.year, last.year + 1)
    ]
    return "Według lat", buckets, start, end


def _trend(db, wallet_ids, span, currency):
    title, buckets, first, end = _trend_buckets(span)
    marks = ",".join("?" * len(wallet_ids))
    by_month = db.execute(
        f"""
        SELECT substr(t.occurred_on, 1, 7) AS month, t.kind,
               SUM(p.total_cents) AS total
        FROM transactions t
        JOIN products p ON p.transaction_id = t.id
        WHERE t.wallet_id IN ({marks})
          AND t.occurred_on >= ? AND t.occurred_on < ?
        GROUP BY month, t.kind
        """,
        (*wallet_ids, first.isoformat(), end.isoformat()),
    ).fetchall()
    # Klucz roku jest początkiem klucza miesiąca, więc oba rodzaje słupków sumują się tak samo.
    totals = Counter()
    for row in by_month:
        for bucket in buckets:
            if row["month"].startswith(bucket["key"]):
                totals[(bucket["key"], row["kind"])] += row["total"]
    largest = max(totals.values(), default=0)
    step, axis_max = axis_scale(largest)
    months = []
    for bucket in buckets:
        income = totals.get((bucket["key"], "income"), 0)
        expense = totals.get((bucket["key"], "expense"), 0)
        months.append(
            {
                **bucket,
                "income": income,
                "expense": expense,
                "income_pct": round(income / (axis_max * 100) * 100, 2),
                "expense_pct": round(expense / (axis_max * 100) * 100, 2),
                "tip": (
                    f"{bucket['title']} · Przychody: {format_money(income, currency)}"
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
    return {"title": title, "months": months, "ticks": ticks, "has_data": largest > 0}


def budget_months(start, end):
    """Ile miesięcznych limitów przypada na okres; niepełny miesiąc liczy się według dni."""
    months = 0.0
    day = _month_start(start)
    while day < end:
        following = _next_month_start(day)
        days_in_month = calendar.monthrange(day.year, day.month)[1]
        covered = (min(end, following) - max(start, day)).days
        months += covered / days_in_month
        day = following
    return months


def _by_category(db, wallet_ids, start, end, kind, currency):
    marks = ",".join("?" * len(wallet_ids))
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
                start.isoformat(),
                end.isoformat(),
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


def _wallet_totals(db, wallets, start, end):
    """Przychody, wydatki i bilans okresu osobno dla każdego portfela."""
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
                start.isoformat(),
                end.isoformat(),
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


def _vat_report(db, wallets, start, end):
    """Zestawienie VAT z portfeli z VAT; None, gdy żaden nie jest wybrany."""
    ids = [wallet["id"] for wallet in wallets if wallet["wallet_type"] == VAT]
    if not ids:
        return None
    marks = ",".join("?" * len(ids))
    rows = db.execute(
        f"""
        SELECT p.vat_rate, t.kind,
               SUM(p.total_cents - p.vat_cents) AS net, SUM(p.vat_cents) AS vat
        FROM products p
        JOIN transactions t ON t.id = p.transaction_id
        WHERE t.wallet_id IN ({marks})
          AND t.occurred_on >= ? AND t.occurred_on < ?
        GROUP BY p.vat_rate, t.kind
        """,
        (*ids, start.isoformat(), end.isoformat()),
    ).fetchall()
    found = {(row["vat_rate"], row["kind"]): row for row in rows}

    def amount(rate, kind, column):
        row = found.get((rate, kind))
        return row[column] if row else 0

    by_rate = []
    for rate in (*VAT_RATES, None):
        if (rate, "income") in found or (rate, "expense") in found:
            by_rate.append(
                {
                    "label": "zw." if rate is None else f"{rate}%",
                    "sales_net": amount(rate, "income", "net"),
                    "sales_vat": amount(rate, "income", "vat"),
                    "purchases_net": amount(rate, "expense", "net"),
                    "purchases_vat": amount(rate, "expense", "vat"),
                }
            )
    totals = {
        key: sum(row[key] for row in by_rate)
        for key in ("sales_net", "sales_vat", "purchases_net", "purchases_vat")
    }
    return {
        "by_rate": by_rate,
        **totals,
        "balance": totals["sales_vat"] - totals["purchases_vat"],
    }


def _budgets(db, wallet_ids, start, end, currency):
    """Budżety waluty raportu z wydatkami wybranych portfeli, z limitem przeliczonym na okres."""
    budgets = db.execute(
        """
        SELECT b.category_id, c.name, b.amount_cents
        FROM budgets b
        JOIN categories c ON c.id = b.category_id
        WHERE b.currency = ?
        ORDER BY c.name
        """,
        (currency,),
    ).fetchall()
    if not budgets:
        return []
    months = budget_months(start, end)
    marks = ",".join("?" * len(wallet_ids))
    spent = {
        row["category_id"]: row["total"]
        for row in db.execute(
            f"""
            SELECT p.category_id, SUM(p.total_cents) AS total
            FROM products p
            JOIN transactions t ON t.id = p.transaction_id
            WHERE t.wallet_id IN ({marks}) AND t.kind = 'expense'
              AND t.occurred_on >= ? AND t.occurred_on < ?
              AND p.category_id IS NOT NULL
            GROUP BY p.category_id
            """,
            (*wallet_ids, start.isoformat(), end.isoformat()),
        )
    }
    return [
        {
            "category_id": budget["category_id"],
            "name": budget["name"],
            "monthly": budget["amount_cents"],
            **budget_usage(
                spent.get(budget["category_id"], 0), round(budget["amount_cents"] * months)
            ),
        }
        for budget in budgets
    ]


def build_report(
    db, currency="", wallet_ids=None, month="", period="month", year="", start="", end=""
):
    """Raport z wybranych portfeli jednej waluty za miesiąc, rok albo zakres dat.

    `wallet_ids=None` oznacza wszystkie portfele tej waluty. Zakres dat obejmuje oba
    końce. Zwraca None, gdy nie ma żadnego portfela.
    """
    wallets = list_wallets(db)
    if not wallets:
        return None

    span = _period(period if period in PERIODS else "month", month, year, start, end)
    first, after = span["start"], span["end"]
    currency, selected = _resolve_selection(currency, wallet_ids, wallets)
    ids = [wallet["id"] for wallet in selected]
    expenses, expense_total = _by_category(db, ids, first, after, "expense", currency)
    incomes, income_total = _by_category(db, ids, first, after, "income", currency)
    return {
        "wallets": wallets,
        "currencies": sorted({wallet["currency"] for wallet in wallets}),
        "currency": currency,
        "selected_ids": ids,
        "period": span["period"],
        "start": first.isoformat(),
        "end": (after - timedelta(days=1)).isoformat(),
        "year": str(first.year),
        "wallet_totals": _wallet_totals(db, selected, first, after),
        "month_key": _month_key(first.year, first.month),
        "title": span["title"],
        "month_title": span["title"],
        "previous": span["previous"],
        "next": span["next"],
        "expenses": expenses,
        "expense_total": expense_total,
        "incomes": incomes,
        "income_total": income_total,
        "net_total": income_total - expense_total,
        "trend": _trend(db, ids, span, currency),
        "vat": _vat_report(db, selected, first, after),
        "budget_months": budget_months(first, after),
        "budgets": _budgets(db, ids, first, after, currency),
    }
