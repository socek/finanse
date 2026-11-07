import pytest
from test_csv_import import BANK_CSV

from finanse.bank_import import import_rows, preview, safe_rows
from finanse.categories import delete_category
from finanse.csv_import import detect_mapping
from finanse.errors import ValidationError
from finanse.gui import common
from finanse.gui.import_dialog import ImportDialog
from finanse.gui.import_rules_dialog import RuleDialog, RulesDialog
from finanse.gui.main_window import MainWindow
from finanse.history import history_text
from finanse.import_rules import (
    create_rule,
    delete_rule,
    list_rules,
    matching_rule,
    move_rule,
    update_rule,
)
from finanse.transactions import get_transaction
from finanse.wallets import create_wallet, get_wallet


def category_id(db, name):
    return db.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]


def run_import(db, wallet, category=None):
    rows = safe_rows(BANK_CSV, ";")
    return import_rows(db, wallet, rows, detect_mapping(rows), category)


def imported(db):
    return {
        row["description"]: get_transaction(db, row["id"])
        for row in db.execute("SELECT id, description FROM transactions ORDER BY id")
    }


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    monkeypatch.setattr(common, "confirm", lambda *_a, **_k: True)
    return collected


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pattern": "  "}, "Podaj tekst"),
        ({"pattern": "x" * 101, "product_name": "A"}, "Podaj tekst"),
        ({"pattern": "Lidl", "kind": "x", "product_name": "A"}, "Wybierz"),
        ({"pattern": "Lidl", "category_id": 999}, "nie istnieje"),
        ({"pattern": "Lidl"}, "musi ustawiać"),
        ({"pattern": "Lidl", "tags": "x" * 60}, "za długi"),
    ],
)
def test_invalid_rule_saves_nothing(db, kwargs, message):
    with pytest.raises(ValidationError, match=message):
        create_rule(db, **kwargs)
    assert list_rules(db) == []


def test_matching_ignores_case_polish_letters_and_spaces(db):
    food = category_id(db, "Jedzenie")
    create_rule(db, "Żabka", category_id=food)
    create_rule(db, "przelew  od", kind="income", tags="Rodzice")
    rules = list_rules(db)
    assert matching_rule(rules, "ZABKA Z1234 KRAKOW", "expense")["pattern"] == "Żabka"
    assert matching_rule(rules, "PRZELEW OD Jan", "income")["tags"] == "Rodzice"
    assert matching_rule(rules, "PRZELEW OD Jan", "expense") is None
    assert matching_rule(rules, "Lidl", "expense") is None


def test_first_rule_wins_and_order_can_change(db):
    first = create_rule(db, "bilet", product_name="Bilet ZTM")
    second = create_rule(db, "bil", product_name="Inny")
    assert matching_rule(list_rules(db), "Bilet", "expense")["id"] == first
    move_rule(db, second, -1)
    assert [rule["id"] for rule in list_rules(db)] == [second, first]
    assert matching_rule(list_rules(db), "Bilet", "expense")["id"] == second
    move_rule(db, second, -5)  # już pierwsza
    assert [rule["id"] for rule in list_rules(db)] == [second, first]


def test_update_and_delete_rule(db):
    rule = create_rule(db, "bilet", product_name="Bilet")
    update_rule(db, rule, " BILET  ZTM ", "expense", category_id(db, "Transport"), "", "Praca")
    saved = list_rules(db)[0]
    assert (saved["pattern"], saved["kind"], saved["product_name"], saved["tags"]) == (
        "BILET ZTM", "expense", None, "Praca",
    )  # fmt: skip
    assert saved["category_name"] == "Transport"
    delete_rule(db, rule)
    assert list_rules(db) == []


def test_import_applies_rules_and_fallback_category(db):
    wallet = create_wallet(db, "A")
    food, transport, other = (category_id(db, n) for n in ("Jedzenie", "Transport", "Inne"))
    create_rule(db, "biedronka", "expense", food, "Zakupy spożywcze", "Dom")
    create_rule(db, "bilet", category_id=transport)
    create_rule(db, "wynagrodzenie", "expense", category_id=food)  # nie dotyczy przychodu
    counts = run_import(db, wallet, other)
    assert counts == {"imported": 4, "duplicates": 0, "invalid": 1, "matched": 3}

    saved = imported(db)
    shop = saved["Biedronka; Warszawa"]
    assert shop["rows"][0]["name"] == "Zakupy spożywcze"
    assert shop["rows"][0]["category"] == food and shop["tags"] == ["Dom"]
    assert saved["Bilet"]["rows"][0]["category"] == transport
    assert saved["Bilet"]["rows"][0]["name"] == "Bilet"
    assert saved["Wynagrodzenie"]["rows"][0]["category"] == other  # bez reguły


def test_rule_without_category_keeps_fallback(db):
    wallet = create_wallet(db, "A")
    create_rule(db, "bilet", tags="Praca")
    run_import(db, wallet, category_id(db, "Transport"))
    ticket = imported(db)["Bilet"]
    assert ticket["rows"][0]["category"] == category_id(db, "Transport")
    assert ticket["tags"] == ["Praca"]


def test_preview_shows_rules_without_saving(db):
    wallet = create_wallet(db, "A")
    create_rule(db, "bilet", category_id=category_id(db, "Transport"))
    rows = safe_rows(BANK_CSV, ";")
    records, counts = preview(db, wallet, rows, detect_mapping(rows))
    assert counts["matched"] == 2
    tickets = [r for r in records if r["description"] == "Bilet"]
    assert all(r["rule"]["pattern"] == "bilet" for r in tickets)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_deleting_category_keeps_rule_without_it(db):
    hobby = db.execute("INSERT INTO categories (name) VALUES ('Hobby')").lastrowid
    db.commit()
    create_rule(db, "lego", category_id=hobby, tags="Dzieci")
    delete_category(db, hobby)
    rule = list_rules(db)[0]
    assert rule["category_id"] is None and rule["tags"] == "Dzieci"


def test_history_describes_rules(db):
    create_rule(db, "Biedronka", "expense", category_id(db, "Jedzenie"))
    text = history_text(db)
    line = next(line for line in text.splitlines() if "regułę importu" in line)
    assert "Dodano regułę importu „Biedronka”" in line
    assert "dotyczy: wydatków" in line and "kategoria: Jedzenie" in line
    assert "nazwa produktu: opis z wyciągu" in line and "tagi: brak" in line


def test_rule_dialog_creates_and_validates(db, errors):
    dialog = RuleDialog(db, pattern="ZABKA 123", kind="expense")
    assert dialog.pattern.text() == "ZABKA 123"
    assert dialog.kind.currentData() == "expense"
    dialog.accept()
    assert "musi ustawiać" in errors[0]
    dialog.category.setCurrentIndex(dialog.category.findText("Jedzenie"))
    dialog.tags.setText("Dom")
    dialog.accept()
    rule = list_rules(db)[0]
    assert (rule["pattern"], rule["category_name"], rule["tags"]) == ("ZABKA 123", "Jedzenie", "Dom")


def test_rules_dialog_edits_moves_and_deletes(db, errors, monkeypatch):
    first = create_rule(db, "bilet", product_name="Bilet")
    create_rule(db, "lidl", category_id=category_id(db, "Jedzenie"))
    dialog = RulesDialog(db)
    assert dialog.table.rowCount() == 2
    assert dialog.table.item(0, dialog.CATEGORY).text() == "Bez zmiany"
    assert dialog.table.item(1, dialog.NAME).text() == "opis z wyciągu"
    assert not dialog.edit_button.isEnabled()

    dialog.table.setCurrentCell(0, 0)
    assert not dialog.up_button.isEnabled() and dialog.down_button.isEnabled()
    dialog.move(1)
    assert dialog.table.item(1, 0).text() == "bilet" and dialog.selected_id() == first

    def edit(rule_dialog):
        rule_dialog.product_name.setText("Bilet ZTM")
        rule_dialog.accept()
        return rule_dialog.result()

    monkeypatch.setattr(RuleDialog, "exec", edit)
    dialog.edit()
    assert dialog.table.item(1, dialog.NAME).text() == "Bilet ZTM"
    dialog.delete()
    assert dialog.table.rowCount() == 1


def test_import_dialog_shows_rule_categories(db, errors, monkeypatch):
    wallet = create_wallet(db, "A")
    create_rule(db, "bilet", category_id=category_id(db, "Transport"))
    dialog = ImportDialog(db, get_wallet(db, wallet), BANK_CSV, ";")
    assert "z regułą: 2" in dialog.counts.text()
    rows = {dialog.table.item(r, 2).text(): r for r in range(dialog.table.rowCount())}
    assert dialog.table.item(rows["Bilet"], 4).text() == "Transport ✓"
    assert "Reguła: „bilet”" in dialog.table.item(rows["Bilet"], 4).toolTip()
    assert dialog.table.item(rows["Wynagrodzenie"], 4).text() == "Bez kategorii"

    dialog.category.setCurrentIndex(dialog.category.findText("Inne"))
    assert dialog.table.item(rows["Wynagrodzenie"], 4).text() == "Inne"

    def create(rule_dialog):
        assert rule_dialog.pattern.text() == "Wynagrodzenie"
        assert rule_dialog.kind.currentData() == "income"
        rule_dialog.category.setCurrentIndex(rule_dialog.category.findText("Wynagrodzenie"))
        rule_dialog.accept()
        return rule_dialog.result()

    monkeypatch.setattr(RuleDialog, "exec", create)
    dialog.table.itemDoubleClicked.emit(dialog.table.item(rows["Wynagrodzenie"], 2))
    assert dialog.table.item(rows["Wynagrodzenie"], 4).text() == "Wynagrodzenie ✓"
    assert "z regułą: 3" in dialog.counts.text()

    dialog.accept()
    assert "z reguł dostały: 3" in dialog.summary()


def test_menu_opens_rules(db, errors, monkeypatch):
    opened = []
    monkeypatch.setattr(RulesDialog, "exec", lambda dialog: opened.append(dialog) or 0)
    window = MainWindow(db)
    file_menu = next(a.menu() for a in window.menuBar().actions() if a.text() == "&Plik")
    next(a for a in file_menu.actions() if a.text().startswith("Reguły importu")).trigger()
    assert len(opened) == 1
