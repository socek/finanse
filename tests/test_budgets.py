import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from finanse.budgets import budget_currencies, budget_usage, list_budgets, set_budgets
from finanse.categories import create_category, delete_category
from finanse.errors import ValidationError
from finanse.gui import common
from finanse.gui.categories_tab import BUDGET, CategoriesTab
from finanse.gui.dialogs import CategoryDialog
from finanse.gui.reports_tab import ReportsTab
from finanse.history import history_text
from finanse.reports import build_report
from finanse.transactions import create_transaction
from finanse.wallets import create_wallet


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    monkeypatch.setattr(common, "confirm", lambda *_a, **_k: True)
    return collected


def category_id(db, name):
    return db.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()[0]


def spend(db, wallet, on, price, category, kind="expense"):
    create_transaction(db, wallet, kind, on, "Zakupy", [
        {"name": "X", "quantity": "1", "price": price, "category": category},
    ])  # fmt: skip


def budgets(db):
    return [
        (row["category_name"], row["currency"], row["amount_cents"])
        for row in list_budgets(db)
    ]


def test_set_change_and_remove_budgets(db):
    create_wallet(db, "A", "PLN")
    create_wallet(db, "B", "EUR")
    food = category_id(db, "Jedzenie")
    assert budget_currencies(db) == ["EUR", "PLN"]

    set_budgets(db, food, {"PLN": "800", "EUR": ""})
    assert budgets(db) == [("Jedzenie", "PLN", 80000)]
    set_budgets(db, food, {"PLN": "1 000,50", "EUR": "50"})
    assert budgets(db) == [("Jedzenie", "EUR", 5000), ("Jedzenie", "PLN", 100050)]
    set_budgets(db, food, {"PLN": " ", "EUR": "50"})
    assert budgets(db) == [("Jedzenie", "EUR", 5000)]


@pytest.mark.parametrize("text", ["0", "-5", "abc", "1,234"])
def test_invalid_budget_saves_nothing(db, text):
    create_wallet(db, "A", "PLN")
    create_wallet(db, "B", "EUR")
    food = category_id(db, "Jedzenie")
    with pytest.raises(ValidationError, match="budżet w PLN"):
        set_budgets(db, food, {"EUR": "50", "PLN": text})
    assert budgets(db) == []


def test_budget_of_missing_category(db):
    with pytest.raises(ValidationError, match="nie istnieje"):
        set_budgets(db, 999, {"PLN": "10"})


def test_deleting_empty_category_deletes_its_budget(db):
    create_wallet(db, "A", "PLN")
    category = create_category(db, "Hobby")
    set_budgets(db, category, {"PLN": "100"})
    delete_category(db, category)
    assert budgets(db) == []


def test_budget_usage():
    assert budget_usage(0, 1000) == {
        "spent": 0, "limit": 1000, "left": 1000, "percent": 0, "over": False, "nearly": False,
    }  # fmt: skip
    assert budget_usage(800, 1000)["nearly"]
    assert budget_usage(1000, 1000)["nearly"] and not budget_usage(1000, 1000)["over"]
    over = budget_usage(1250, 1000)
    assert (over["over"], over["nearly"], over["left"], over["percent"]) == (True, False, -250, 125)


def test_report_compares_month_expenses_of_selected_wallets(db):
    home = create_wallet(db, "Dom", "PLN")
    work = create_wallet(db, "Firma", "PLN")
    euro = create_wallet(db, "Euro", "EUR")
    food, bills = category_id(db, "Jedzenie"), category_id(db, "Rachunki")
    set_budgets(db, food, {"PLN": "100", "EUR": "10"})
    set_budgets(db, bills, {"PLN": "50"})
    spend(db, home, "2026-11-02", "60", food)
    spend(db, work, "2026-11-03", "30", food)
    spend(db, home, "2026-11-04", "500", food, kind="income")
    spend(db, home, "2026-10-31", "500", food)
    spend(db, home, "2026-12-01", "500", food)
    spend(db, euro, "2026-11-02", "500", food)
    spend(db, home, "2026-11-05", "70", bills)

    report = build_report(db, "PLN", {home, work}, "2026-11")
    rows = {row["name"]: row for row in report["budgets"]}
    assert list(rows) == ["Jedzenie", "Rachunki"]
    assert (rows["Jedzenie"]["spent"], rows["Jedzenie"]["left"]) == (9000, 1000)
    assert rows["Jedzenie"]["nearly"] and not rows["Jedzenie"]["over"]
    assert rows["Rachunki"]["over"] and rows["Rachunki"]["left"] == -2000

    only_home = build_report(db, "PLN", {home}, "2026-11")["budgets"]
    assert only_home[0]["spent"] == 6000
    assert build_report(db, "EUR", None, "2026-11")["budgets"][0]["spent"] == 50000
    assert build_report(db, "PLN", set(), "2026-11")["budgets"][0]["spent"] == 0


def test_history_describes_budget(db):
    create_wallet(db, "A", "PLN")
    food = category_id(db, "Jedzenie")
    set_budgets(db, food, {"PLN": "800"})
    set_budgets(db, food, {"PLN": "900"})
    set_budgets(db, food, {"PLN": ""})
    text = history_text(db).replace("\xa0", " ")
    assert "Dodano budżet kategorii „Jedzenie” (waluta: PLN, kwota: 800,00)" in text
    assert "Zmieniono budżet kategorii „Jedzenie”: kwota: 800,00 → 900,00" in text
    assert "Usunięto budżet kategorii „Jedzenie”" in text


def test_budget_dialog_and_categories_column(db, errors):
    create_wallet(db, "A", "PLN")
    create_wallet(db, "B", "EUR")
    tab = CategoriesTab(db)
    assert not tab.edit_button.isEnabled()
    row = next(r for r in range(tab.table.rowCount()) if tab.table.item(r, 0).text() == "Jedzenie")
    assert tab.table.item(row, BUDGET).text() == "–"

    food = category_id(db, "Jedzenie")
    dialog = CategoryDialog(db, food, "Jedzenie")
    assert dialog.name.text() == "Jedzenie"
    assert list(dialog.amounts) == ["EUR", "PLN"]
    QTest.keyClicks(dialog.amounts["PLN"], "-800")
    assert dialog.amounts["PLN"].text() == "800"
    dialog.amounts["EUR"].setText("x")
    dialog.accept()
    assert any("budżet w EUR" in error for error in errors)
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.amounts["EUR"].clear()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted

    tab.refresh()
    assert tab.table.item(row, BUDGET).text().replace("\xa0", " ") == "800,00 PLN"
    reopened = CategoryDialog(db, food, "Jedzenie")
    assert reopened.amounts["PLN"].text() == "800,00"
    tab.table.setCurrentCell(row, 0)
    assert tab.edit_button.isEnabled()
    assert "budżet też zostanie usunięty" in tab._delete_question("Jedzenie")


def test_category_dialog_without_wallets_only_renames(db, errors):
    food = category_id(db, "Jedzenie")
    dialog = CategoryDialog(db, food, "Jedzenie")
    assert dialog.amounts == {}
    dialog.name.setText("Jedzonko")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert category_id(db, "Jedzonko") == food


def test_category_dialog_saves_name_and_budget_together(db, errors):
    create_wallet(db, "A", "PLN")
    food = category_id(db, "Jedzenie")
    dialog = CategoryDialog(db, food, "Jedzenie")
    dialog.name.setText("Rachunki")  # zajęta nazwa
    dialog.amounts["PLN"].setText("300")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert errors == ["Masz już kategorię o tej nazwie."]
    assert list_budgets(db) == []  # budżet nie zapisał się bez nazwy

    errors.clear()
    dialog.name.setText("")
    dialog.amounts["PLN"].setText("x")
    dialog.accept()
    assert len(errors) == 2  # oba błędy naraz
    assert category_id(db, "Jedzenie") == food

    errors.clear()
    dialog.name.setText("Jedzonko")
    dialog.amounts["PLN"].setText("300")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert category_id(db, "Jedzonko") == food
    assert [(b["category_name"], b["amount_cents"]) for b in list_budgets(db)] == [("Jedzonko", 30000)]


def test_reports_tab_shows_budgets(db, errors):
    from datetime import date

    wallet = create_wallet(db, "A", "PLN")
    month = date.today().strftime("%Y-%m")
    tab = ReportsTab(db)
    assert tab.budgets_empty.isVisibleTo(tab) and "PLN" in tab.budgets_empty.text()

    food, bills = category_id(db, "Jedzenie"), category_id(db, "Rachunki")
    set_budgets(db, food, {"PLN": "100"})
    set_budgets(db, bills, {"PLN": "50"})
    spend(db, wallet, f"{month}-01", "40", food)
    spend(db, wallet, f"{month}-01", "70", bills)
    tab.refresh()
    assert not tab.budgets_empty.isVisibleTo(tab)
    texts = [
        tab.budgets_grid.itemAt(index).widget().text().replace("\xa0", " ")
        for index in range(tab.budgets_grid.count())
        if isinstance(tab.budgets_grid.itemAt(index).widget(), QLabel)
    ]
    assert "40,00 PLN z 100,00 PLN  (40%)" in texts
    assert "zostało 60,00 PLN" in texts
    assert "przekroczono o 20,00 PLN" in texts


def test_double_click_opens_dialog_focused_on_clicked_column(db, errors, monkeypatch):
    create_wallet(db, "A", "PLN")
    opened = []
    monkeypatch.setattr(CategoryDialog, "exec", lambda dialog: opened.append(dialog) or 0)
    tab = CategoriesTab(db)
    tab.show()
    tab.table.setCurrentCell(0, BUDGET)
    tab.table.itemDoubleClicked.emit(tab.table.item(0, BUDGET))
    tab.table.itemDoubleClicked.emit(tab.table.item(0, 0))
    assert len(opened) == 2
    for dialog in opened:
        dialog.show()
    QApplication.processEvents()
    assert opened[0].focusWidget() is opened[0].amounts["PLN"]
    assert opened[1].focusWidget() is opened[1].name
    tab.close()
