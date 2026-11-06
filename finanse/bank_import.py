import csv

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .auth import login_required
from .categories import user_categories
from .csv_import import (
    DELIMITERS,
    cell,
    decode,
    detect_delimiter,
    detect_mapping,
    parse_records,
    read_rows,
)
from .db import get_db
from .transactions import insert_products
from .wallets import get_wallet_or_404

bp = Blueprint("bank_import", __name__)

MAX_FILE_BYTES = 2 * 1024 * 1024
PREVIEW_ROWS = 20


def _existing_hashes(wallet_id):
    rows = get_db().execute(
        "SELECT import_hash FROM transactions"
        " WHERE wallet_id = ? AND import_hash IS NOT NULL",
        (wallet_id,),
    )
    return {row["import_hash"] for row in rows}


def _column_options(rows, start):
    """Opcje wyboru kolumny: nazwa z nagłówka i przykładowa wartość."""
    data = rows[start:]
    width = max((len(row) for row in data), default=0)
    header = rows[start - 1] if 0 < start <= len(rows) else []
    example = data[0] if data else []
    options = []
    for index in range(width):
        name = cell(header, index) or f"Kolumna {index + 1}"
        sample = cell(example, index)[:30]
        options.append(
            {"index": index, "label": f"{name} ({sample})" if sample else name}
        )
    return options


def _mapping_from_form(form, rows):
    """Mapowanie z formularza; gdy nie pasuje do pliku, zgadywane od nowa."""
    try:
        mapping = {
            "start": int(form.get("start", "1")) - 1,
            "date": int(form.get("date_column", "")),
            "description": int(form.get("description_column", "")),
            "amount": int(form.get("amount_column", "")),
        }
    except ValueError:
        return detect_mapping(rows)
    width = max((len(row) for row in rows), default=0)
    columns = (mapping["date"], mapping["description"], mapping["amount"])
    if not 0 <= mapping["start"] < len(rows) or not all(
        0 <= column < width for column in columns
    ):
        return detect_mapping(rows)
    return mapping


def _render_mapping(wallet, content, delimiter, rows, mapping, category):
    records = parse_records(rows, mapping)
    existing = _existing_hashes(wallet["id"])
    for record in records:
        record["duplicate"] = record["hash"] in existing
    counts = {
        "new": sum(1 for r in records if r["hash"] and not r["duplicate"]),
        "duplicates": sum(1 for r in records if r["duplicate"]),
        "invalid": sum(1 for r in records if r["error"]),
    }
    return render_template(
        "bank_import/mapping.html",
        wallet=wallet,
        content=content,
        delimiter=delimiter,
        delimiters=DELIMITERS,
        options=_column_options(rows, mapping["start"]),
        mapping=mapping,
        categories=user_categories(),
        category=category,
        preview=records[:PREVIEW_ROWS],
        total=len(records),
        counts=counts,
    )


def _import_records(wallet_id, records, category_id):
    """Zapisuje poprawne rekordy; zwraca (zaimportowane, duplikaty)."""
    db = get_db()
    imported = duplicates = 0
    with db:
        for record in records:
            if record["error"]:
                continue
            cents = record["amount_cents"]
            cursor = db.execute(
                "INSERT OR IGNORE INTO transactions"
                " (wallet_id, kind, occurred_on, description, import_hash)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    wallet_id,
                    "income" if cents > 0 else "expense",
                    record["occurred_on"],
                    record["description"],
                    record["hash"],
                ),
            )
            if cursor.rowcount == 0:
                duplicates += 1
                continue
            insert_products(
                db,
                cursor.lastrowid,
                [
                    {
                        "name": record["description"],
                        "category_id": category_id,
                        "quantity_milli": 1000,
                        "unit_price_cents": abs(cents),
                        "total_cents": abs(cents),
                    }
                ],
            )
            imported += 1
    return imported, duplicates


@bp.route("/wallets/<int:wallet_id>/import", methods=("GET", "POST"))
@login_required
def upload(wallet_id):
    wallet = get_wallet_or_404(wallet_id)
    if request.method == "GET":
        return render_template("bank_import/upload.html", wallet=wallet)

    file = request.files.get("file")
    if file is None or not file.filename:
        flash("Wybierz plik CSV.", "error")
        return render_template("bank_import/upload.html", wallet=wallet)
    data = file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        flash("Plik jest zbyt duży (limit to 2 MB).", "error")
        return render_template("bank_import/upload.html", wallet=wallet)

    content = decode(data)
    delimiter = detect_delimiter(content)
    try:
        rows = read_rows(content, delimiter)
    except csv.Error:
        rows = []
    if not rows:
        flash("Nie udało się odczytać pliku jako CSV.", "error")
        return render_template("bank_import/upload.html", wallet=wallet)
    return _render_mapping(
        wallet, content, delimiter, rows, detect_mapping(rows), ""
    )


@bp.post("/wallets/<int:wallet_id>/import/confirm")
@login_required
def confirm(wallet_id):
    wallet = get_wallet_or_404(wallet_id)
    content = request.form.get("content", "")
    delimiter = request.form.get("delimiter", "")
    if delimiter not in DELIMITERS:
        delimiter = detect_delimiter(content)
    try:
        rows = read_rows(content, delimiter)
    except csv.Error:
        rows = []
    if not rows:
        flash("Przy tym separatorze plik jest pusty lub nieczytelny.", "error")
        return redirect(url_for("bank_import.upload", wallet_id=wallet_id))

    mapping = _mapping_from_form(request.form, rows)
    category = request.form.get("category", "")
    errors = []
    if len({mapping["date"], mapping["description"], mapping["amount"]}) < 3:
        errors.append("Data, opis i kwota muszą pochodzić z różnych kolumn.")
    if category and category not in {str(c["id"]) for c in user_categories()}:
        errors.append("Niepoprawna kategoria.")
        category = ""

    if request.form.get("action") == "import" and not errors:
        records = parse_records(rows, mapping)
        invalid = sum(1 for record in records if record["error"])
        imported, duplicates = _import_records(
            wallet_id, records, int(category) if category else None
        )
        if imported:
            flash(f"Zaimportowano transakcje: {imported}.", "success")
        else:
            flash("Nie zaimportowano żadnej nowej transakcji.", "error")
        if duplicates:
            flash(f"Pominięte duplikaty: {duplicates}.", "success")
        if invalid:
            flash(f"Pominięte niepoprawne wiersze: {invalid}.", "error")
        return redirect(url_for("wallets.detail", wallet_id=wallet_id))

    for error in errors:
        flash(error, "error")
    return _render_mapping(wallet, content, delimiter, rows, mapping, category)
