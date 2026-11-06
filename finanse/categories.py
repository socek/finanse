import sqlite3

from .errors import ValidationError

MAX_NAME_LENGTH = 50


def list_categories(db):
    return db.execute(
        """
        SELECT c.id, c.name, COUNT(p.id) AS product_count
        FROM categories c
        LEFT JOIN products p ON p.category_id = c.id
        GROUP BY c.id
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


def delete_category(db, category_id):
    with db:
        db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
