import sqlite3

from .budgets import parse_budgets, write_budgets
from .errors import ValidationError

MAX_NAME_LENGTH = 50


def list_categories(db):
    return db.execute(
        """
        SELECT c.id, c.name,
               (SELECT COUNT(*) FROM products p WHERE p.category_id = c.id)
                   AS product_count,
               (SELECT COUNT(*) FROM recurring_products p WHERE p.category_id = c.id)
                   AS recurring_count
        FROM categories c
        ORDER BY c.name
        """
    ).fetchall()


def _clean(name):
    name = name.strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        raise ValidationError(f"Podaj nazwę kategorii (do {MAX_NAME_LENGTH} znaków).")
    return name


def create_category(db, name):
    name = _clean(name)
    try:
        with db:
            return db.execute(
                "INSERT INTO categories (name) VALUES (?)", (name,)
            ).lastrowid
    except sqlite3.IntegrityError:
        raise ValidationError("Masz już kategorię o tej nazwie.") from None


def rename_category(db, category_id, name):
    name = _clean(name)
    try:
        with db:
            db.execute(
                "UPDATE categories SET name = ? WHERE id = ?", (name, category_id)
            )
    except sqlite3.IntegrityError:
        raise ValidationError("Masz już kategorię o tej nazwie.") from None


def update_category(db, category_id, name, amounts):
    """Nowa nazwa i miesięczne budżety ({waluta: tekst kwoty}) zapisane razem albo wcale.

    Błędy nazwy i kwot są zgłaszane jednocześnie, żeby poprawić wszystko za jednym razem.
    """
    errors = []
    try:
        name = _clean(name)
    except ValidationError as error:
        errors += error.errors
    try:
        parsed = parse_budgets(amounts)
    except ValidationError as error:
        errors += error.errors
    if errors:
        raise ValidationError(errors)
    if db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,)).fetchone() is None:
        raise ValidationError("Ta kategoria już nie istnieje.")
    try:
        with db:
            db.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))
            write_budgets(db, category_id, parsed)
    except sqlite3.IntegrityError:
        raise ValidationError("Masz już kategorię o tej nazwie.") from None


def deletion_block_reason(product_count, recurring_count):
    """Dlaczego kategorii nie można usunąć; pusty tekst, gdy można."""
    uses = []
    if product_count:
        uses.append(f"produkty: {product_count}")
    if recurring_count:
        uses.append(f"produkty transakcji cyklicznych: {recurring_count}")
    if not uses:
        return ""
    return f"Można usunąć tylko pustą kategorię, a ta jest używana ({', '.join(uses)})."


def delete_category(db, category_id):
    """Usuwa tylko pustą kategorię, żeby produkty nie traciły jej po cichu."""
    used = db.execute(
        """
        SELECT (SELECT COUNT(*) FROM products WHERE category_id = :id),
               (SELECT COUNT(*) FROM recurring_products WHERE category_id = :id)
        """,
        {"id": category_id},
    ).fetchone()
    reason = deletion_block_reason(used[0], used[1])
    if reason:
        raise ValidationError(reason)
    with db:
        db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
