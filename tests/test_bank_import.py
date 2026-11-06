import pytest
from test_csv_import import BANK_CSV

from finanse.bank_import import import_rows, load_file, preview, safe_rows
from finanse.csv_import import detect_mapping
from finanse.errors import ValidationError
from finanse.wallets import create_wallet, get_wallet


def run_import(db, wallet, content=BANK_CSV, category=None):
    rows = safe_rows(content, ";")
    return import_rows(db, wallet, rows, detect_mapping(rows), category)


def test_load_file_handles_cp1250_and_missing_file(tmp_path):
    path = tmp_path / "wyciag.csv"
    path.write_bytes("Data;Opis;Kwota\n2026-11-03;Żabka;-1,00\n".encode("cp1250"))
    content, delimiter = load_file(path)
    assert "Żabka" in content and delimiter == ";"
    with pytest.raises(ValidationError, match="odczytać"):
        load_file(tmp_path / "brak.csv")


def test_preview_does_not_save(db):
    wallet = create_wallet(db, "A")
    rows = safe_rows(BANK_CSV, ";")
    _, counts = preview(db, wallet, rows, detect_mapping(rows))
    assert counts == {"new": 4, "duplicates": 0, "invalid": 1}
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_import_updates_balance_and_skips_duplicates(db):
    wallet = create_wallet(db, "A")
    assert run_import(db, wallet) == {"imported": 4, "duplicates": 0, "invalid": 1}
    assert get_wallet(db, wallet)["balance_cents"] == 500000 - 4550 - 440 - 440
    assert run_import(db, wallet) == {"imported": 0, "duplicates": 4, "invalid": 1}

    rows = safe_rows(BANK_CSV, ";")
    _, counts = preview(db, wallet, rows, detect_mapping(rows))
    assert counts == {"new": 0, "duplicates": 4, "invalid": 1}


def test_same_file_may_go_to_another_wallet(db):
    run_import(db, create_wallet(db, "A"))
    assert run_import(db, create_wallet(db, "B"))["imported"] == 4


def test_import_with_category(db):
    category = db.execute("SELECT id FROM categories WHERE name = 'Dom'").fetchone()[0]
    run_import(db, create_wallet(db, "A"), category=category)
    assert {r[0] for r in db.execute("SELECT category_id FROM products")} == {category}


def test_same_columns_are_rejected(db):
    wallet = create_wallet(db, "A")
    rows = safe_rows(BANK_CSV, ";")
    mapping = {**detect_mapping(rows), "description": 0, "date": 0}
    with pytest.raises(ValidationError, match="różnych kolumn"):
        import_rows(db, wallet, rows, mapping)
