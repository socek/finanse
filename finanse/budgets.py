"""Miesięczne budżety kategorii: limit wydatków w jednej walucie."""

from .errors import ValidationError
from .money import parse_money

# Od tej części limitu budżet jest wyróżniany jako bliski wyczerpania.
NEARLY_SPENT_PERCENT = 80


def list_budgets(db):
    """Budżety z nazwami kategorii, posortowane po kategorii i walucie."""
    return db.execute(
        """
        SELECT b.id, b.category_id, c.name AS category_name, b.currency, b.amount_cents
        FROM budgets b
        JOIN categories c ON c.id = b.category_id
        ORDER BY c.name, b.currency
        """
    ).fetchall()


def budget_currencies(db):
    """Waluty, w których można ustawić budżet: portfeli i już istniejących budżetów."""
    return [
        row[0]
        for row in db.execute(
            "SELECT currency FROM wallets UNION SELECT currency FROM budgets ORDER BY 1"
        )
    ]


def parse_budgets(amounts):
    """Grosze z mapy {waluta: tekst kwoty}; pusty tekst oznacza brak limitu (None)."""
    parsed = {}
    errors = []
    for currency, text in amounts.items():
        text = text.strip()
        if not text:
            parsed[currency] = None
            continue
        try:
            cents = parse_money(text)
        except ValueError:
            cents = 0
        if cents <= 0:
            errors.append(f"Podaj poprawny budżet w {currency} albo zostaw pole puste.")
        parsed[currency] = cents
    if errors:
        raise ValidationError(errors)
    return parsed


def write_budgets(db, category_id, parsed):
    """Zapis wyniku parse_budgets; wołający odpowiada za transakcję."""
    for currency, cents in parsed.items():
        if cents is None:
            db.execute(
                "DELETE FROM budgets WHERE category_id = ? AND currency = ?",
                (category_id, currency),
            )
        else:
            db.execute(
                """
                INSERT INTO budgets (category_id, currency, amount_cents)
                VALUES (?, ?, ?)
                ON CONFLICT (category_id, currency)
                DO UPDATE SET amount_cents = excluded.amount_cents
                """,
                (category_id, currency, cents),
            )


def set_budgets(db, category_id, amounts):
    """Zapisuje limity kategorii z mapy {waluta: tekst kwoty}; pusty tekst usuwa limit.

    Wszystkie waluty zapisują się razem albo żadna.
    """
    if db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone() is None:
        raise ValidationError("Ta kategoria już nie istnieje.")
    parsed = parse_budgets(amounts)
    with db:
        write_budgets(db, category_id, parsed)


def budget_usage(spent, limit):
    """Stan budżetu: wydano, zostało (ujemne po przekroczeniu) i procent limitu."""
    return {
        "spent": spent,
        "limit": limit,
        "left": limit - spent,
        "percent": round(spent / limit * 100),
        "over": spent > limit,
        "nearly": spent <= limit and spent * 100 >= limit * NEARLY_SPENT_PERCENT,
    }
