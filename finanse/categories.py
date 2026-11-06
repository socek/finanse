import sqlite3

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

bp = Blueprint("categories", __name__, url_prefix="/categories")

MAX_NAME_LENGTH = 50


def user_categories():
    return (
        get_db()
        .execute(
            "SELECT id, name FROM categories WHERE user_id = ? ORDER BY name",
            (g.user["id"],),
        )
        .fetchall()
    )


def _get_category_or_404(category_id):
    category = (
        get_db()
        .execute(
            "SELECT * FROM categories WHERE id = ? AND user_id = ?",
            (category_id, g.user["id"]),
        )
        .fetchone()
    )
    if category is None:
        abort(404)
    return category


def _clean_name():
    name = request.form.get("name", "").strip()
    if not name or len(name) > MAX_NAME_LENGTH:
        flash(f"Podaj nazwę kategorii (do {MAX_NAME_LENGTH} znaków).", "error")
        return None
    return name


@bp.get("")
@login_required
def index():
    categories = (
        get_db()
        .execute(
            """
            SELECT c.id, c.name, COUNT(p.id) AS product_count
            FROM categories c
            LEFT JOIN products p ON p.category_id = c.id
            WHERE c.user_id = ?
            GROUP BY c.id
            ORDER BY c.name
            """,
            (g.user["id"],),
        )
        .fetchall()
    )
    return render_template("categories/index.html", categories=categories)


@bp.post("")
@login_required
def create():
    name = _clean_name()
    if name:
        db = get_db()
        try:
            with db:
                db.execute(
                    "INSERT INTO categories (user_id, name) VALUES (?, ?)",
                    (g.user["id"], name),
                )
        except sqlite3.IntegrityError:
            flash("Masz już kategorię o tej nazwie.", "error")
    return redirect(url_for("categories.index"))


@bp.post("/<int:category_id>/rename")
@login_required
def rename(category_id):
    _get_category_or_404(category_id)
    name = _clean_name()
    if name:
        db = get_db()
        try:
            with db:
                db.execute(
                    "UPDATE categories SET name = ? WHERE id = ?", (name, category_id)
                )
        except sqlite3.IntegrityError:
            flash("Masz już kategorię o tej nazwie.", "error")
    return redirect(url_for("categories.index"))


@bp.post("/<int:category_id>/delete")
@login_required
def delete(category_id):
    category = _get_category_or_404(category_id)
    db = get_db()
    with db:
        db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
    flash(f"Usunięto kategorię „{category['name']}”.", "success")
    return redirect(url_for("categories.index"))
