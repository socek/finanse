import functools
import hashlib
import re
import secrets
import sqlite3

import click
from flask import (
    Blueprint,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, seed_default_categories

bp = Blueprint("auth", __name__, cli_group=None)

MIN_PASSWORD_LENGTH = 8
MAX_USERNAME_LENGTH = 50


@bp.before_app_request
def load_user():
    user_id = session.get("user_id")
    g.user = None
    if user_id is None:
        return
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None or user["session_epoch"] != session.get("epoch", 0):
        session.clear()
        return
    g.user = user


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login"))
        return view(**kwargs)

    return wrapped


def _start_session(user_id):
    user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    session.clear()
    session["user_id"] = user_id
    session["epoch"] = user["session_epoch"]
    g.user = user


def _password_error(password):
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Hasło musi mieć co najmniej {MIN_PASSWORD_LENGTH} znaków."
    return None


def _hash_recovery_code(code):
    normalized = re.sub(r"[^0-9A-Z]", "", code.upper())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _new_recovery_code(db, user_id):
    """Zapisuje hash nowego kodu i zwraca kod, który pokazujemy tylko raz."""
    raw = secrets.token_hex(10).upper()
    db.execute(
        "UPDATE users SET recovery_code_hash = ? WHERE id = ?",
        (_hash_recovery_code(raw), user_id),
    )
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def _set_password(db, user_id, password):
    db.execute(
        "UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1"
        " WHERE id = ?",
        (generate_password_hash(password), user_id),
    )


def _recovery_code_page(code):
    response = make_response(render_template("account/recovery_code.html", code=code))
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        error = None
        if not username or len(username) > MAX_USERNAME_LENGTH:
            error = f"Podaj nazwę użytkownika (do {MAX_USERNAME_LENGTH} znaków)."
        else:
            error = _password_error(password)
        if error is None:
            db = get_db()
            try:
                with db:
                    cursor = db.execute(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, generate_password_hash(password)),
                    )
                    user_id = cursor.lastrowid
                    seed_default_categories(db, user_id)
                    code = _new_recovery_code(db, user_id)
            except sqlite3.IntegrityError:
                error = "Ta nazwa użytkownika jest już zajęta."
            else:
                _start_session(user_id)
                return _recovery_code_page(code)
        flash(error, "error")
    return render_template(
        "auth_form.html",
        title="Rejestracja",
        submit="Załóż konto",
        new_password=True,
    )


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        user = (
            get_db()
            .execute(
                "SELECT * FROM users WHERE username = ?",
                (request.form.get("username", "").strip(),),
            )
            .fetchone()
        )
        password = request.form.get("password", "")
        if user is not None and check_password_hash(user["password_hash"], password):
            _start_session(user["id"])
            return redirect(url_for("wallets.index"))
        flash("Niepoprawna nazwa użytkownika lub hasło.", "error")
    return render_template(
        "auth_form.html",
        title="Logowanie",
        submit="Zaloguj się",
        new_password=False,
    )


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/reset-password", methods=("GET", "POST"))
def reset_password():
    if request.method == "POST":
        password = request.form.get("password", "")
        error = _password_error(password)
        if error is None:
            db = get_db()
            user = db.execute(
                "SELECT * FROM users WHERE username = ?",
                (request.form.get("username", "").strip(),),
            ).fetchone()
            sent = _hash_recovery_code(request.form.get("code", ""))
            stored = (user["recovery_code_hash"] if user else None) or ""
            if stored and secrets.compare_digest(sent, stored):
                with db:
                    _set_password(db, user["id"], password)
                    code = _new_recovery_code(db, user["id"])
                _start_session(user["id"])
                return _recovery_code_page(code)
            error = "Niepoprawna nazwa użytkownika lub kod odzyskiwania."
        flash(error, "error")
    return render_template("account/reset_password.html")


@bp.get("/account")
@login_required
def account():
    return render_template("account/index.html")


def _current_password_ok():
    return check_password_hash(
        g.user["password_hash"], request.form.get("current_password", "")
    )


@bp.post("/account/password")
@login_required
def change_password():
    new_password = request.form.get("new_password", "")
    error = _password_error(new_password)
    if not _current_password_ok():
        error = "Niepoprawne obecne hasło."
    if error is None:
        db = get_db()
        with db:
            _set_password(db, g.user["id"], new_password)
        _start_session(g.user["id"])
        flash("Hasło zostało zmienione.", "success")
    else:
        flash(error, "error")
    return redirect(url_for("auth.account"))


@bp.post("/account/recovery-code")
@login_required
def regenerate_recovery_code():
    if not _current_password_ok():
        flash("Niepoprawne obecne hasło.", "error")
        return redirect(url_for("auth.account"))
    db = get_db()
    with db:
        code = _new_recovery_code(db, g.user["id"])
    return _recovery_code_page(code)


@bp.cli.command("reset-password")
@click.argument("username")
@click.option(
    "--password", prompt="Nowe hasło", hide_input=True, confirmation_prompt=True
)
def reset_password_command(username, password):
    """Ustawia nowe hasło użytkownika z poziomu serwera."""
    error = _password_error(password)
    if error:
        raise click.ClickException(error)
    db = get_db()
    user = db.execute(
        "SELECT id FROM users WHERE username = ?", (username,)
    ).fetchone()
    if user is None:
        raise click.ClickException(f"Nie ma użytkownika {username}.")
    with db:
        _set_password(db, user["id"], password)
    click.echo("Hasło zostało zmienione.")
