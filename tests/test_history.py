import json
import re
import sqlite3

import pytest

from helpers import priced

from finanse.categories import create_category, rename_category
from finanse.db import connect, init_db
from finanse.history import history_text
from finanse.recurring import create_recurring, pay_recurring, payment_draft
from finanse.transactions import (
    create_transaction,
    delete_transaction,
    get_transaction,
    update_transaction,
)
from finanse.transfers import create_transfer, delete_transfer
from finanse.wallets import create_wallet, delete_wallet, get_wallet, update_wallet


def product(name="Chleb", quantity="2", price="5", category=None):
    return {"name": name, "quantity": quantity, "price": price, "category": category}


def add(db, wallet, *products):
    return create_transaction(
        db, wallet, "expense", "2026-11-05", "Zakupy", list(products) or [product()]
    )


def log(db):
    return db.execute("SELECT * FROM change_log ORDER BY id").fetchall()


def test_every_data_column_is_logged(db):
    """Nowa kolumna lub tabela musi trafić do triggerów w migracji."""
    tables = [
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
            " AND name NOT IN ('operations', 'change_log') AND name NOT LIKE 'sqlite_%'"
        )
    ]
    assert len(tables) == 10
    for table in tables:
        columns = [row["name"] for row in db.execute(f"PRAGMA table_info({table})")]
        for action in ("insert", "update", "delete"):
            sql = db.execute(
                "SELECT sql FROM sqlite_master WHERE name = ?",
                (f"log_{table}_{action}",),
            ).fetchone()["sql"]
            for column in columns:
                assert f"'{column}'" in sql, (table, action, column)


def test_changes_store_old_and_new_values(db):
    wallet = create_wallet(db, "A", "PLN", "1")
    update_wallet(db, wallet, "B", "PLN", "1")
    delete_wallet(db, wallet)
    insert, update, delete = log(db)
    assert (insert["action"], insert["old_values"]) == ("insert", None)
    assert json.loads(insert["new_values"])["name"] == "A"
    assert json.loads(update["old_values"])["name"] == "A"
    assert json.loads(update["new_values"])["name"] == "B"
    assert (delete["action"], delete["new_values"]) == ("delete", None)
    assert json.loads(delete["old_values"])["initial_balance_cents"] == 100
    assert {row["row_id"] for row in log(db)} == {wallet}


def test_saving_same_values_logs_nothing(db):
    wallet = create_wallet(db, "A")
    before = len(log(db))
    update_wallet(db, wallet, "A", "PLN", "0")
    assert len(log(db)) == before
    # Operacja bez zmian nie zostaje w bazie.
    assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1


def test_one_action_is_one_operation(db):
    wallet = create_wallet(db, "A")
    add(db, wallet, product(), product("Ser"))
    rows = log(db)
    assert [row["table_name"] for row in rows] == [
        "wallets", "transactions", "products", "products",
    ]  # fmt: skip
    assert rows[0]["operation_id"] != rows[1]["operation_id"]
    assert len({row["operation_id"] for row in rows[1:]}) == 1
    assert db.execute("SELECT COUNT(*) FROM operations WHERE is_open = 1").fetchone()[0] == 0


def test_payment_groups_transaction_and_counter(db):
    wallet = create_wallet(db, "A")
    recurring = create_recurring(db, wallet, "expense", "Rata", remaining="2", rows=priced("Rata", "10"))
    draft = payment_draft(db, recurring)
    pay_recurring(db, recurring, "expense", "2026-11-05", "Rata", draft["rows"])
    rows = log(db)[-3:]
    assert [(r["table_name"], r["action"]) for r in rows] == [
        ("transactions", "insert"),
        ("products", "insert"),
        ("recurring_transactions", "update"),
    ]
    assert len({r["operation_id"] for r in rows}) == 1


def test_cascades_are_logged_in_the_same_operation(db):
    wallet = create_wallet(db, "A")
    add(db, wallet)
    delete_wallet(db, wallet)
    deletes = [r for r in log(db) if r["action"] == "delete"]
    assert {r["table_name"] for r in deletes} == {"wallets", "transactions", "products"}
    assert len({r["operation_id"] for r in deletes}) == 1


def test_category_delete_logs_set_null(db):
    wallet = create_wallet(db, "A")
    category = create_category(db, "Psy")
    add(db, wallet, product(category=category))
    # Aplikacja nie usunie używanej kategorii, ale baza nadal chroni spójność, np. z konsoli.
    with db:
        db.execute("DELETE FROM categories WHERE id = ?", (category,))
    update = next(r for r in log(db) if r["action"] == "update")
    assert update["table_name"] == "products"
    assert json.loads(update["old_values"])["category_id"] == category
    assert json.loads(update["new_values"])["category_id"] is None


def test_failed_operation_leaves_no_trace(db):
    create_wallet(db, "A")
    before = len(log(db))
    with pytest.raises(sqlite3.IntegrityError), db:
        db.execute("INSERT INTO wallets (name) VALUES ('B')")
        db.execute("INSERT INTO wallets (name) VALUES ('B')")
    assert len(log(db)) == before
    assert db.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM operations WHERE is_open = 1").fetchone()[0] == 0
    # Kolejna operacja działa normalnie.
    create_wallet(db, "C")


def test_ids_returned_by_inserts_are_not_affected_by_triggers(db):
    wallet = create_wallet(db, "A", "PLN", "10")
    transaction = add(db, wallet)
    assert get_wallet(db, wallet)["name"] == "A"
    assert get_transaction(db, transaction)["description"] == "Zakupy"


def test_changes_outside_the_app_are_logged_without_operation(tmp_path):
    path = str(tmp_path / "outside.db")
    init_db(path)
    plain = sqlite3.connect(path)  # jak konsola: bez funkcji i klasy z aplikacji
    plain.execute("INSERT INTO wallets (name) VALUES ('Z konsoli')")
    plain.commit()
    plain.close()
    db = connect(path)
    assert log(db)[-1]["operation_id"] is None
    assert "(zmiana spoza aplikacji)" in history_text(db)
    assert "Dodano portfel „Z konsoli”" in history_text(db)
    db.close()


def test_history_text_describes_changes_newest_first(db):
    assert "Historia jest pusta" in history_text(db)
    wallet = create_wallet(db, "Gotówka", "PLN", "100")
    update_wallet(db, wallet, "Portfel", "PLN", "150")
    category = create_category(db, "Psy")
    rename_category(db, category, "Koty")
    add(db, wallet, product("Karma", "2", "5", category))

    text = history_text(db).replace("\xa0", " ")
    assert "Dodano portfel „Gotówka” (waluta: PLN, saldo początkowe: 100,00)" in text
    assert (
        "Zmieniono portfel „Portfel”: nazwa: „Gotówka” → „Portfel”,"
        " saldo początkowe: 100,00 → 150,00"
    ) in text
    assert "Zmieniono kategorię „Koty”: nazwa: „Psy” → „Koty”" in text
    assert "Dodano transakcję „Zakupy” (portfel: Portfel, rodzaj: wydatek" in text
    assert "Dodano produkt „Karma” (kategoria: Koty, ilość: 2, cena: 5,00, wartość: 10,00)" in text
    assert text.index("Dodano transakcję") < text.index("Dodano portfel")
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\n  Dodano transakcję", text)


def test_history_ignores_products_rewritten_without_changes(db):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet, product("Stały"), product("Ser"))
    data = get_transaction(db, transaction)
    rows = data["rows"]

    update_transaction(db, transaction, "expense", "2026-11-05", "Zakupy", rows)
    assert history_text(db).count("Usunięto produkt") == 0

    rows[1] = product("Mleko", "1", "3")
    update_transaction(db, transaction, "expense", "2026-11-06", "Zakupy", rows)
    text = history_text(db)
    assert "Zmieniono transakcję „Zakupy”: data: 2026-11-05 → 2026-11-06" in text
    assert "Usunięto produkt „Ser”" in text and "Dodano produkt „Mleko”" in text
    assert "Usunięto produkt „Stały”" not in text


def test_history_uses_names_of_deleted_wallets(db):
    source = create_wallet(db, "Stary")
    target = create_wallet(db, "Nowy")
    transfer = create_transfer(db, source, target, "2026-11-05", "", "5")
    delete_transfer(db, transfer)
    delete_wallet(db, source)
    assert history_text(db).count("z portfela: Stary") == 2
    transaction = add(db, target)
    delete_transaction(db, transaction)
    assert "Usunięto transakcję „Zakupy” (portfel: Nowy" in history_text(db)


def test_history_shows_old_entries_and_skips_missing_columns(db):
    wallet = create_wallet(db, "A")
    create_recurring(db, wallet, "expense", "Nowa", remaining="2")
    old_values = json.dumps(
        {"id": 77, "wallet_id": wallet, "kind": "expense", "description": "Stara",
         "amount_cents": 5000, "category_id": None, "remaining": None, "last_paid_on": None}
    )  # fmt: skip
    with db:
        db.execute(
            "INSERT INTO change_log (table_name, row_id, action, new_values)"
            " VALUES ('recurring_transactions', 77, 'insert', ?)",
            (old_values,),
        )
    text = history_text(db).replace("\xa0", " ")
    old_line = next(line for line in text.splitlines() if "„Stara”" in line)
    assert "kwota: 50,00" in old_line and "kategoria: bez kategorii" in old_line
    new_line = next(line for line in text.splitlines() if "„Nowa”" in line)
    assert "kwota" not in new_line and "kategoria" not in new_line
    assert "licznik: 2" in new_line


def test_history_shows_old_and_precise_product_values(db):
    wallet = create_wallet(db, "A")
    create_transaction(db, wallet, "expense", "2026-11-05", "Paliwo", [
        {"name": "Benzyna", "category": None, "quantity": "2,12345", "price": "1,00001"},
    ])  # fmt: skip
    with db:
        db.execute(
            "INSERT INTO change_log (table_name, row_id, action, new_values)"
            " VALUES ('products', 77, 'insert', ?)",
            (json.dumps({"id": 77, "transaction_id": 1, "position": 0, "name": "Stary",
                         "category_id": None, "quantity_milli": 1500,
                         "unit_price_cents": 200, "total_cents": 300}),),
        )  # fmt: skip
    text = history_text(db).replace("\xa0", " ")
    new_line = next(line for line in text.splitlines() if "„Benzyna”" in line)
    assert "ilość: 2,12345" in new_line and "cena: 1,00001" in new_line
    assert new_line.count("wartość:") == 1
    old_line = next(line for line in text.splitlines() if "„Stary”" in line)
    assert "ilość: 1,5" in old_line and "cena: 2,00" in old_line and "wartość: 3,00" in old_line


def test_history_is_limited_and_says_so(db):
    wallet = create_wallet(db, "A")
    for _ in range(3):
        add(db, wallet)
    text = history_text(db, max_rows=2)
    assert text.startswith("Pokazano 2 najnowszych zmian z 7.")


def test_history_describes_schedule(db):
    wallet = create_wallet(db, "A")
    create_recurring(db, wallet, "expense", "Bez terminu")
    recurring = create_recurring(
        db, wallet, "expense", "Czynsz", rows=[product("Czynsz", "1", "10")],
        schedule={"unit": "month", "count": "1", "next_due_on": "2026-11-10"},
    )  # fmt: skip
    draft = payment_draft(db, recurring)
    pay_recurring(db, recurring, "expense", "2026-11-12", "Czynsz", draft["rows"])
    text = history_text(db)
    plain = next(line for line in text.splitlines() if "„Bez terminu”" in line)
    assert "termin:" not in plain and "okres:" not in plain
    added = next(line for line in text.splitlines() if "Dodano transakcję cykliczną „Czynsz”" in line)
    assert "termin: 2026-11-10, co ile: 1, okres: miesiące" in added
    assert "termin: 2026-11-10 → 2026-12-10" in text
