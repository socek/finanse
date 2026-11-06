import os
import secrets
from pathlib import Path

from flask import Flask, abort, redirect, request, session, url_for

from . import (
    auth,
    bank_import,
    categories,
    db,
    money,
    reports,
    transactions,
    transfers,
    wallets,
)

MAX_REQUEST_BYTES = 8 * 1024 * 1024


def _load_secret_key(instance_path):
    """Klucz z FINANSE_SECRET_KEY albo trwale zapisany w katalogu instance."""
    key = os.environ.get("FINANSE_SECRET_KEY")
    if key:
        return key
    path = Path(instance_path) / "secret_key"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path.read_text().strip()
    key = secrets.token_hex(32)
    with os.fdopen(fd, "w") as file:
        file.write(key)
    return key


def _csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def _csrf_protect():
    if request.method != "POST":
        return
    expected = session.get("csrf_token", "")
    sent = request.form.get("csrf_token", "")
    if not expected or not secrets.compare_digest(expected.encode(), sent.encode()):
        abort(400, "Niepoprawny token formularza. Odśwież stronę i spróbuj ponownie.")


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    app.config.update(
        DATABASE=str(Path(app.instance_path) / "finanse.db"),
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
        MAX_FORM_MEMORY_SIZE=MAX_REQUEST_BYTES,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _load_secret_key(app.instance_path)

    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)
    app.before_request(_csrf_protect)

    app.jinja_env.globals["csrf_token"] = _csrf_token
    app.jinja_env.filters["money"] = money.format_money
    app.jinja_env.filters["quantity"] = money.format_quantity

    for module in (
        auth,
        wallets,
        transactions,
        transfers,
        categories,
        reports,
        bank_import,
    ):
        app.register_blueprint(module.bp)

    @app.get("/")
    def index():
        return redirect(url_for("wallets.index"))

    @app.errorhandler(413)
    def too_large(_error):
        return "Przesłane dane są zbyt duże.", 413

    return app
