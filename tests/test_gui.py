import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QDialog
from test_csv_import import BANK_CSV

from finanse.gui import common
from finanse.gui.categories_tab import CategoriesTab
from finanse.gui.dialogs import (
    PaymentDialog,
    RecurringDialog,
    TransactionDialog,
    TransferDialog,
    WalletDialog,
)
from finanse.gui.import_dialog import ImportDialog
from finanse.gui.main_window import MainWindow
from finanse.gui.products_tab import ProductsTab
from finanse.gui.recurring_tab import AMOUNT, PAY, REMAINING, RecurringTab
from finanse.gui.reports_tab import ReportsTab
from finanse.gui.wallets_tab import WalletsTab
from finanse.recurring import create_recurring, get_recurring
from finanse.transactions import create_transaction, get_transaction
from finanse.transfers import create_transfer
from finanse.wallets import create_wallet, get_wallet, list_wallets


@pytest.fixture
def errors(monkeypatch, qapp):
    """Zamiast blokujących okienek zbiera komunikaty; potwierdzenia są na tak."""
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    monkeypatch.setattr(common, "show_info", lambda _p, text: collected.append(text))
    monkeypatch.setattr(common, "confirm", lambda *_a, **_k: True)
    return collected


def add(db, wallet, name="Chleb", price="5", on="2026-11-05"):
    return create_transaction(
        db, wallet, "expense", on, "Zakupy",
        [{"name": name, "quantity": "1", "price": price, "category": None}],
    )  # fmt: skip


def test_wallet_dialog_saves_and_stays_open_on_error(db, errors):
    dialog = WalletDialog(db)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "nazwę portfela" in errors[0]

    dialog.name.setText("Gotówka")
    dialog.initial_balance.setText("12,50")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert get_wallet(db, dialog.wallet_id)["balance_cents"] == 1250


def test_transaction_dialog_totals_rows_and_save(db, errors):
    wallet = get_wallet(db, create_wallet(db, "A"))
    dialog = TransactionDialog(db, wallet)
    table = dialog.table
    table.cellWidget(0, dialog.NAME).setText("Chleb")
    table.cellWidget(0, dialog.QUANTITY).setText("2")
    table.cellWidget(0, dialog.PRICE).setText("4,50")
    dialog._add_row({"name": "Ser", "category": None, "quantity": "1", "price": "abc"})
    dialog._update_totals()
    assert "9,00" in dialog.total.text().replace("\xa0", " ")

    dialog.description.setText("Zakupy")
    dialog.accept()
    assert any("Produkt 2: niepoprawna cena" in error for error in errors)
    assert table.cellWidget(1, dialog.PRICE).text() == "abc"  # wpisane dane zostają

    dialog._remove_row(table.cellWidget(1, dialog.REMOVE))
    assert table.rowCount() == 1
    category = table.cellWidget(0, dialog.CATEGORY)
    category.setCurrentIndex(category.findText("Dom"))
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = get_transaction(db, dialog.transaction_id)
    assert saved["rows"][0]["quantity"] == "2"
    assert saved["rows"][0]["category"] is not None


def test_transaction_dialog_edits_existing(db, errors):
    wallet_id = create_wallet(db, "A")
    transaction = add(db, wallet_id)
    dialog = TransactionDialog(db, get_wallet(db, wallet_id), transaction)
    assert dialog.description.text() == "Zakupy"
    assert dialog.occurred_on.date() == QDate(2026, 11, 5)
    dialog.description.setText("Inne")
    dialog.accept()
    assert get_transaction(db, transaction)["description"] == "Inne"


def test_transfer_dialog_second_amount_only_for_other_currency(db, errors):
    source = create_wallet(db, "A", "PLN", "100")
    euro = create_wallet(db, "B", "EUR")
    same = create_wallet(db, "C", "PLN")
    dialog = TransferDialog(db, from_wallet=source)
    assert dialog.source.currentData() == source
    assert not dialog.amount_to.isEnabled()
    dialog.target.setCurrentIndex(dialog.target.findData(euro))
    assert dialog.amount_to.isEnabled()
    dialog.target.setCurrentIndex(dialog.target.findData(same))
    assert not dialog.amount_to.isEnabled()

    dialog.amount_from.setText("10")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert get_wallet(db, same)["balance_cents"] == 1000


def test_wallets_tab_lists_entries_and_filters(db, errors):
    wallet = create_wallet(db, "A", "PLN", "100")
    other = create_wallet(db, "B")
    add(db, wallet, on="2026-10-01")
    create_transfer(db, wallet, other, "2026-11-01", "", "1")
    tab = WalletsTab(db)
    assert tab.wallet_list.count() == 2
    assert tab.tree.topLevelItemCount() == 2
    transfer_day, purchase_day = tab.tree.topLevelItem(0), tab.tree.topLevelItem(1)
    assert transfer_day.text(0) == "2026-11-01"
    assert transfer_day.child(0).text(2) == "Przelew"
    assert "→ B" in transfer_day.child(0).text(1)
    assert purchase_day.child(0).text(1) == "Zakupy"
    assert purchase_day.child(0).childCount() == 0  # produkty są w osobnej zakładce
    assert tab.tree.columnCount() == 6

    tab.filter_bar.date_from.setDate(QDate(2026, 10, 15))
    tab.filter_bar.use_from.setChecked(True)
    assert tab.tree.topLevelItemCount() == 1
    assert not tab.summary.isHidden()

    tab.filter_bar.date_to.setDate(QDate(2026, 10, 16))
    tab.filter_bar.use_to.setChecked(True)
    assert tab.tree.topLevelItemCount() == 0
    assert "Brak operacji" in tab.empty.text()


def test_day_row_sums_income_and_expense_separately(db, errors):
    wallet = create_wallet(db, "A", "PLN", "100")
    other = create_wallet(db, "B")
    add(db, wallet, name="Chleb", price="5", on="2026-11-05")
    add(db, wallet, name="Ser", price="7,50", on="2026-11-05")
    create_transaction(
        db, wallet, "income", "2026-11-05", "Zwrot",
        [{"name": "Zwrot", "quantity": "1", "price": "20", "category": None}],
    )  # fmt: skip
    create_transfer(db, wallet, other, "2026-11-05", "", "1000")
    add(db, wallet, name="Inny dzień", price="99", on="2026-11-04")

    tab = WalletsTab(db)
    day = tab.tree.topLevelItem(0)
    assert tab.tree.topLevelItemCount() == 2
    assert day.text(0) == "2026-11-05" and day.childCount() == 4
    assert day.isExpanded()
    plain = lambda text: text.replace("\xa0", " ")  # noqa: E731
    income_column, expense_column = 4, 5
    assert plain(day.text(income_column)) == "+20,00 PLN"
    assert plain(day.text(expense_column)) == "−12,50 PLN"
    older = tab.tree.topLevelItem(1)
    assert older.text(income_column) == ""
    assert plain(older.text(expense_column)) == "−99,00 PLN"


def test_refresh_keeps_collapsed_days_and_selection(db, errors):
    wallet = create_wallet(db, "A")
    other = create_wallet(db, "B")
    add(db, wallet, on="2026-11-05")
    add(db, wallet, on="2026-11-04")
    add(db, other, on="2026-11-05")
    tab = WalletsTab(db)
    newer, older = tab.tree.topLevelItem(0), tab.tree.topLevelItem(1)
    assert newer.isExpanded() and older.isExpanded()
    older.setExpanded(False)
    tab.tree.setCurrentItem(newer.child(0))
    selected = tab.selected_entry()

    tab.refresh()
    assert tab.tree.topLevelItem(0).isExpanded()
    assert not tab.tree.topLevelItem(1).isExpanded()
    assert tab.selected_entry() == selected

    add(db, wallet, on="2026-11-03")  # nowy dzień też jest rozwinięty
    tab.refresh()
    assert tab.tree.topLevelItem(2).isExpanded()
    assert not tab.tree.topLevelItem(1).isExpanded()

    tab.wallet_list.setCurrentRow(1)  # inny portfel startuje w pełni rozwinięty
    assert tab.tree.topLevelItem(0).isExpanded()
    assert tab.selected_entry() is None
    tab.wallet_list.setCurrentRow(0)
    assert tab.tree.topLevelItem(1).isExpanded()


def test_expand_and_collapse_all(db, errors):
    wallet = create_wallet(db, "A")
    add(db, wallet, on="2026-11-05")
    add(db, wallet, on="2026-11-04")
    tab = WalletsTab(db)

    def expanded():
        return [
            tab.tree.topLevelItem(i).isExpanded()
            for i in range(tab.tree.topLevelItemCount())
        ]

    assert expanded() == [True, True]
    tab.collapse_all_button.click()
    assert expanded() == [False, False]
    tab.refresh()
    assert expanded() == [False, False]  # odświeżenie nie rozwija zwiniętych
    tab.expand_all_button.click()
    assert expanded() == [True, True]
    tab.refresh()
    assert expanded() == [True, True]


def test_wallets_tab_delete_entry_and_wallet(db, errors):
    wallet = create_wallet(db, "A")
    other = create_wallet(db, "B")
    transfer = create_transfer(db, wallet, other, "2026-11-01", "", "1")
    add(db, wallet, on="2026-10-01")
    tab = WalletsTab(db)

    tab.delete_wallet()
    assert "ma przelewy" in errors[0]
    assert len(list_wallets(db)) == 2

    tab.tree.setCurrentItem(tab.tree.topLevelItem(1))
    assert tab.selected_entry() is None
    assert not tab.delete_entry_button.isEnabled()
    tab.delete_entry()
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1

    tab.tree.setCurrentItem(tab.tree.topLevelItem(1).child(0))
    assert tab.selected_entry()[0] == "transaction"
    tab.delete_entry()
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0

    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))
    assert tab.selected_entry() == ("transfer", transfer)
    tab.delete_entry()
    tab.delete_wallet()
    assert len(list_wallets(db)) == 1
    assert tab.wallet_list.count() == 1


def _visible_bills(tab):
    return sorted(
        tab.tree.topLevelItem(d).child(b).text(1)
        for d in range(tab.tree.topLevelItemCount())
        for b in range(tab.tree.topLevelItem(d).childCount())
    )


def _filter_wallet(db):
    wallet = create_wallet(db, "A")
    dom = db.execute("SELECT id FROM categories WHERE name = 'Dom'").fetchone()[0]
    create_transaction(
        db, wallet, "expense", "2026-11-05", "Żabka",
        [{"name": "Mydło", "quantity": "1", "price": "90", "category": dom}],
    )  # fmt: skip
    create_transaction(
        db, wallet, "expense", "2026-11-04", "Kiosk",
        [{"name": "Gazeta", "quantity": "1", "price": "20", "category": None}],
    )  # fmt: skip
    return dom


def test_search_and_filters_narrow_the_list(db, errors):
    dom = _filter_wallet(db)
    tab = WalletsTab(db)
    assert tab.summary.isHidden()
    assert tab.tree.topLevelItem(0).isExpanded()
    tab.collapse_all_button.click()

    tab.filter_bar.search.setText("mydło")
    assert _visible_bills(tab) == ["Żabka"]
    assert tab.tree.topLevelItem(0).isExpanded()
    assert "90,00" in tab.summary.text()

    tab.filter_bar.search.clear()
    assert _visible_bills(tab) == ["Kiosk", "Żabka"]
    assert not tab.tree.topLevelItem(0).isExpanded()  # układ sprzed szukania
    assert tab.summary.isHidden()

    tab.filter_bar.category.setCurrentIndex(tab.filter_bar.category.findData(dom))
    assert _visible_bills(tab) == ["Żabka"]
    tab.filter_bar.category.setCurrentIndex(tab.filter_bar.category.findData(0))
    assert _visible_bills(tab) == ["Kiosk"]
    tab.filter_bar.category.setCurrentIndex(0)

    tab.filter_bar.amount_from.setText("50")
    assert _visible_bills(tab) == ["Żabka"]
    tab.filter_bar.amount_from.clear()
    tab.filter_bar.amount_to.setText("50,50")
    assert _visible_bills(tab) == ["Kiosk"]

    tab.filter_bar.search.setText("nie ma takiego")
    assert _visible_bills(tab) == []
    assert "Brak operacji" in tab.empty.text() and not tab.empty.isHidden()

    tab.filter_bar.clear()
    assert _visible_bills(tab) == ["Kiosk", "Żabka"]


@pytest.mark.parametrize("text", ["abc", "-5"])
def test_invalid_amount_is_reported_and_ignored(db, errors, text):
    _filter_wallet(db)
    tab = WalletsTab(db)
    tab.filter_bar.amount_from.setText(text)
    assert _visible_bills(tab) == ["Kiosk", "Żabka"]
    assert "Niepoprawna kwota" in tab.summary.text()
    assert not tab.summary.isHidden()


def test_category_filter_follows_category_changes(db, errors):
    dom = _filter_wallet(db)
    tab = WalletsTab(db)
    tab.filter_bar.category.setCurrentIndex(tab.filter_bar.category.findData(dom))
    tab.refresh()
    assert tab.filter_bar.category.currentData() == dom
    db.execute("DELETE FROM categories WHERE id = ?", (dom,))
    db.commit()
    tab.refresh()
    assert tab.filter_bar.category.findData(dom) == -1
    assert tab.filter_bar.category.currentData() is None
    assert _visible_bills(tab) == ["Kiosk", "Żabka"]


def test_transaction_can_be_deleted_from_menu_and_key(db, errors, monkeypatch):
    wallet = create_wallet(db, "A", "PLN", "100")
    add(db, wallet, name="Chleb", price="5", on="2026-11-05")
    add(db, wallet, name="Ser", price="7", on="2026-11-05")
    add(db, wallet, name="Mleko", price="3", on="2026-11-04")
    questions = []
    monkeypatch.setattr(
        common, "confirm", lambda _p, text, **_k: questions.append(text) or True
    )
    tab = WalletsTab(db)

    tab.tree.setCurrentItem(tab.tree.topLevelItem(0))
    assert tab._entry_menu() is None  # wiersz dnia

    day = tab.tree.topLevelItem(0)
    day.setExpanded(True)
    tab.tree.setCurrentItem(day.child(0))
    menu = tab._entry_menu()
    assert [action.text() for action in menu.actions()] == ["Edytuj", "Usuń"]
    menu.actions()[1].trigger()
    assert questions == ["Usunąć transakcję „Zakupy”?"]
    assert get_wallet(db, wallet)["balance_cents"] < 10000
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
    assert tab.tree.topLevelItem(0).isExpanded()  # dzień zostaje rozwinięty

    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))
    tab.delete_shortcut.activated.emit()
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    assert tab.tree.topLevelItemCount() == 1  # pusty dzień znika
    assert get_wallet(db, wallet)["balance_cents"] == 9700


def test_declined_confirmation_keeps_transaction(db, errors, monkeypatch):
    wallet = create_wallet(db, "A")
    add(db, wallet)
    monkeypatch.setattr(common, "confirm", lambda *_a, **_k: False)
    tab = WalletsTab(db)
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))
    tab.delete_entry()
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1


def test_empty_database_disables_wallet_actions(db, errors):
    tab = WalletsTab(db)
    assert tab.title.text() == "Dodaj pierwszy portfel"
    assert not tab.new_transaction_button.isEnabled()
    reports = ReportsTab(db)
    assert not reports.no_wallets.isHidden()
    assert reports.scroll.isHidden()


def test_user_text_is_never_read_as_html(db, errors):
    tab = WalletsTab(db)
    create_wallet(db, "<b>Portfel</b>")
    tab.refresh()
    assert tab.title.textFormat() == Qt.TextFormat.PlainText
    assert tab.title.text() == "<b>Portfel</b>"


def test_import_file_from_wallets_tab(db, errors, tmp_path, monkeypatch):
    create_wallet(db, "A")
    path = tmp_path / "wyciag.csv"
    path.write_text(BANK_CSV, encoding="utf-8")

    def exec_accepting(dialog):
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(ImportDialog, "exec", exec_accepting)
    tab = WalletsTab(db)
    tab.import_file(path)
    assert "Zaimportowano transakcje: 4" in errors[0]
    assert tab.tree.topLevelItemCount() == 3  # cztery operacje z trzech dni

    tab.import_file(tmp_path / "brak.csv")
    assert "odczytać" in errors[1]


def test_import_dialog_preview_and_import(db, errors):
    wallet = get_wallet(db, create_wallet(db, "A"))

    dialog = ImportDialog(db, wallet, BANK_CSV, ";")
    assert "Nowe: 4" in dialog.counts.text()
    assert dialog.table.item(0, 2).text() == "Biedronka; Warszawa"
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0

    dialog.delimiter.setCurrentIndex(dialog.delimiter.findData("|"))
    assert dialog.table.rowCount() <= 20
    dialog.delimiter.setCurrentIndex(dialog.delimiter.findData(";"))

    dialog.description_column.setCurrentIndex(dialog.date_column.currentIndex())
    dialog.accept()
    assert any("różnych kolumn" in error for error in errors)
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog = ImportDialog(db, wallet, BANK_CSV, ";")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert "Zaimportowano transakcje: 4" in dialog.summary()

    again = ImportDialog(db, wallet, BANK_CSV, ";")
    assert "duplikaty: 4" in again.counts.text()
    assert not again.import_button.isEnabled()


def test_categories_tab(db, errors):
    tab = CategoriesTab(db)
    assert tab.table.rowCount() == 9
    tab.new_name.setText("Psy")
    tab.add()
    assert tab.table.rowCount() == 10 and tab.new_name.text() == ""
    tab.new_name.setText("psy")
    tab.add()
    assert "już kategorię" in errors[0]

    row = next(r for r in range(10) if tab.table.item(r, 0).text() == "Psy")
    tab.table.setCurrentCell(row, 0)
    assert tab.delete_button.isEnabled()
    tab.delete()
    assert tab.table.rowCount() == 9


def test_reports_tab_shows_month_and_navigates(db, errors):
    wallet = create_wallet(db, "A")
    add(db, wallet, on="2026-10-05", price="123")
    tab = ReportsTab(db)
    tab.resize(1000, 800)
    tab.show_month("2026-10")
    assert tab.month_title.text() == "październik 2026"
    assert "123,00" in tab.expense_label.text()
    assert tab.expenses_grid.count() == 3

    tab.chart.resize(800, 240)
    assert not tab.chart.grab().isNull()

    clicked = []
    tab.chart.monthClicked.connect(clicked.append)
    tab.chart.monthClicked.emit("2026-09")
    assert clicked == ["2026-09"]
    assert tab.report["month_key"] == "2026-09"
    assert "Brak wydatków" in tab.expenses_empty.text()
    assert tab.expenses_grid.count() == 0

    tab.next_button.click()
    assert tab.report["month_key"] == "2026-10"
    tab.table_button.setChecked(True)
    assert tab.trend_table.rowCount() == 12
    assert tab.chart._month_at(10) is None
    assert tab.chart._month_at(tab.chart.width() - 1) == 11


def _check(tab, name, checked):
    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    tab.wallet_list.findItems(name, Qt.MatchFlag.MatchExactly)[0].setCheckState(state)


def _cleaned(label):
    return label.text().replace("\xa0", " ")


def test_reports_tab_combines_chosen_wallets(db, errors):
    for name, price in (("A", "10"), ("B", "20"), ("C", "40")):
        add(db, create_wallet(db, name), price=price, on="2026-10-05")
    tab = ReportsTab(db)
    tab.show_month("2026-10")

    assert tab.wallet_list.count() == 3
    assert _cleaned(tab.expense_label) == "70,00 PLN"
    assert tab.selection_label.text() == "Wszystkie portfele w PLN"
    assert tab.wallets_table.rowCount() == 3

    _check(tab, "C", False)
    assert _cleaned(tab.expense_label) == "30,00 PLN"
    assert tab.selection_label.text() == "A, B"
    assert tab.wallets_table.item(1, 0).text() == "B"
    assert not tab.wallets_table.isHidden()

    _check(tab, "B", False)
    assert _cleaned(tab.expense_label) == "10,00 PLN"
    assert tab.wallets_table.isHidden()  # jeden portfel nie wymaga rozbicia

    tab.select_none_button.click()
    assert not tab.no_selection.isHidden() and tab.scroll.isHidden()
    tab.select_all_button.click()
    assert tab.no_selection.isHidden() and not tab.scroll.isHidden()
    assert _cleaned(tab.expense_label) == "70,00 PLN"


def test_reports_tab_keeps_selection_and_includes_new_wallet(db, errors):
    add(db, create_wallet(db, "A"), price="10", on="2026-10-05")
    add(db, create_wallet(db, "B"), price="20", on="2026-10-05")
    tab = ReportsTab(db)
    tab.show_month("2026-10")
    _check(tab, "B", False)

    add(db, create_wallet(db, "C"), price="40", on="2026-10-05")
    tab.refresh()
    assert _cleaned(tab.expense_label) == "50,00 PLN"
    assert tab.wallet_list.findItems("B", Qt.MatchFlag.MatchExactly)[0].checkState() == (
        Qt.CheckState.Unchecked
    )
    tab.next_button.click()
    tab.previous_button.click()
    assert _cleaned(tab.expense_label) == "50,00 PLN"


def test_reports_tab_lists_wallets_of_one_currency(db, errors):
    add(db, create_wallet(db, "Złotówki"), price="11", on="2026-10-05")
    add(db, create_wallet(db, "Euro", "EUR"), price="22", on="2026-10-05")
    add(db, create_wallet(db, "Dolary", "USD"), price="33", on="2026-10-05")
    tab = ReportsTab(db)
    tab.show_month("2026-10")
    assert not tab.currency_combo.isHidden()

    tab.currency_combo.setCurrentIndex(tab.currency_combo.findData("EUR"))
    assert [tab.wallet_list.item(r).text() for r in range(tab.wallet_list.count())] == ["Euro"]
    assert _cleaned(tab.expense_label) == "22,00 EUR"


def _product_tab(db):
    wallet = create_wallet(db, "A")
    dom = db.execute("SELECT id FROM categories WHERE name = 'Dom'").fetchone()[0]
    create_transaction(
        db, wallet, "expense", "2026-11-05", "Biedronka",
        [
            {"name": "Mydło", "quantity": "2", "price": "5", "category": dom},
            {"name": "Żurek", "quantity": "1", "price": "30", "category": None},
        ],
    )  # fmt: skip
    create_transaction(
        db, wallet, "income", "2026-11-05", "Zwrot",
        [{"name": "Kaucja", "quantity": "1", "price": "7", "category": None}],
    )  # fmt: skip
    return wallet, dom, ProductsTab(db)


def _product_names(tab):
    return sorted(
        tab.tree.topLevelItem(d).child(p).text(1)
        for d in range(tab.tree.topLevelItemCount())
        for p in range(tab.tree.topLevelItem(d).childCount())
    )


def test_products_tab_lists_products_by_day(db, errors):
    _, _, tab = _product_tab(db)
    day = tab.tree.topLevelItem(0)
    assert tab.tree.topLevelItemCount() == 1
    assert day.text(0) == "2026-11-05" and day.text(1) == "Produkty: 3"
    assert day.isExpanded()
    assert day.text(7).replace("\xa0", " ") == "+7,00 PLN"
    assert day.text(8).replace("\xa0", " ") == "−40,00 PLN"
    assert _product_names(tab) == ["Kaucja", "Mydło", "Żurek"]

    soap = next(day.child(i) for i in range(3) if day.child(i).text(1) == "Mydło")
    assert [soap.text(c) for c in (2, 3, 4)] == ["Biedronka", "Dom", "2"]
    assert soap.text(5) == "5,00"
    assert soap.text(6).replace("\xa0", " ") == "−10,00 PLN"


def test_products_tab_filters(db, errors):
    _, dom, tab = _product_tab(db)
    bar = tab.filter_bar
    bar.search.setText("ŻUR")
    assert _product_names(tab) == ["Żurek"]
    assert tab.tree.topLevelItem(0).isExpanded()
    assert "30,00" in tab.summary.text()
    bar.search.setText("Biedronka")  # szuka tylko w nazwach produktów
    assert _product_names(tab) == []
    assert not tab.empty.isHidden()
    bar.clear()

    # Filtr kategorii nie pokazuje drugiego produktu z tego samego rachunku.
    bar.category.setCurrentIndex(bar.category.findData(dom))
    assert _product_names(tab) == ["Mydło"]
    bar.category.setCurrentIndex(0)

    # Kwota dotyczy wartości produktu, a nie całego rachunku.
    bar.amount_to.setText("10")
    assert _product_names(tab) == ["Kaucja", "Mydło"]
    bar.amount_from.setText("10")
    assert _product_names(tab) == ["Mydło"]


def test_products_tab_edit_opens_transaction(db, errors, monkeypatch):
    wallet, _, tab = _product_tab(db)
    opened = []

    def exec_recording(dialog):
        opened.append(dialog.transaction_id)
        dialog.description.setText("Zmieniony")
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(TransactionDialog, "exec", exec_recording)
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0))
    assert tab.selected_transaction() is None
    assert not tab.edit_button.isEnabled()
    tab.edit_transaction()
    assert opened == []

    day = tab.tree.topLevelItem(0)
    tab.tree.setCurrentItem(day.child(0))
    assert tab.edit_button.isEnabled()
    tab.edit_button.click()
    assert len(opened) == 1
    assert tab.tree.topLevelItem(0).isExpanded()
    assert tab.wallet_id() == wallet
    texts = [tab.tree.topLevelItem(0).child(i).text(2) for i in range(3)]
    assert "Zmieniony" in texts


def test_products_tab_without_wallets(db, errors):
    tab = ProductsTab(db)
    assert tab.title.text() == "Dodaj pierwszy portfel"
    assert not tab.edit_button.isEnabled()


def test_main_window_refreshes_tab_on_switch(db, errors):
    window = MainWindow(db)
    assert window.tabs.count() == 6
    create_wallet(db, "Nowy")
    window.tabs.setCurrentWidget(window.reports)
    assert window.reports.report is not None
    window.tabs.setCurrentWidget(window.wallets)
    assert window.wallets.wallet_list.count() == 1


def test_history_tab_shows_changes_as_read_only_text(db, errors):
    window = MainWindow(db)
    assert "Historia jest pusta" in window.history.text.toPlainText()
    create_wallet(db, "<b>Portfel</b>")
    window.tabs.setCurrentWidget(window.history)
    assert "Dodano portfel „<b>Portfel</b>”" in window.history.text.toPlainText()
    assert window.history.text.isReadOnly()


def _accept_on_exec(monkeypatch, dialog_class, before=None):
    def fake_exec(dialog):
        if before:
            before(dialog)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(dialog_class, "exec", fake_exec)


def test_recurring_dialog_without_and_with_products(db, errors):
    wallet = create_wallet(db, "A")
    dialog = RecurringDialog(db)
    dialog.accept()
    assert any("Podaj opis" in error for error in errors)
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog.description.setText("Czynsz")
    dialog.amount.setText("500")
    dialog.remaining.setText("3")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = get_recurring(db, dialog.recurring_id)
    assert (saved["wallet_id"], saved["amount_cents"], saved["remaining"]) == (wallet, 50000, 3)
    assert saved["rows"] == []

    dialog = RecurringDialog(db, dialog.recurring_id)
    assert dialog.amount.isEnabled() and dialog.remaining.text() == "3"
    dialog.table.cellWidget(0, dialog.NAME).setText("Woda")
    dialog.table.cellWidget(0, dialog.PRICE).setText("70")
    assert not dialog.amount.isEnabled() and not dialog.category.isEnabled()
    dialog.accept()
    saved = get_recurring(db, dialog.recurring_id)
    assert saved["amount_cents"] is None
    assert [row["name"] for row in saved["rows"]] == ["Woda"]


def test_pay_button_moves_recurring_to_transactions_and_counts_down(
    db, errors, monkeypatch
):
    wallet = create_wallet(db, "A", "PLN", "100")
    create_recurring(db, wallet, "expense", "Czynsz", "10", remaining="2")
    _accept_on_exec(monkeypatch, PaymentDialog)
    tab = RecurringTab(db)
    assert tab.table.item(0, REMAINING).text() == "2"

    tab.table.cellWidget(0, PAY).click()
    assert tab.table.item(0, REMAINING).text() == "1"
    assert get_wallet(db, wallet)["balance_cents"] == 9000
    tab.table.cellWidget(0, PAY).click()
    assert tab.table.item(0, REMAINING).text() == "0 (zakończona)"
    assert get_wallet(db, wallet)["balance_cents"] == 8000
    assert not tab.table.cellWidget(0, PAY).isEnabled()

    wallets = WalletsTab(db)
    assert wallets.tree.topLevelItem(0).child(0).text(1) == "Czynsz"


def test_cancelled_payment_changes_nothing(db, errors, monkeypatch):
    wallet = create_wallet(db, "A")
    create_recurring(db, wallet, "expense", "Czynsz", "10", remaining="2")
    monkeypatch.setattr(PaymentDialog, "exec", lambda _dialog: 0)
    tab = RecurringTab(db)
    tab.table.cellWidget(0, PAY).click()
    assert tab.table.item(0, REMAINING).text() == "2"
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_payment_dialog_is_prefilled_and_requires_unknown_amount(db, errors):
    wallet = create_wallet(db, "A")
    unknown = create_recurring(db, wallet, "income", "Prąd")
    dialog = PaymentDialog(db, get_wallet(db, wallet), unknown)
    assert dialog.kind.currentData() == "income"
    assert dialog.table.cellWidget(0, dialog.NAME).text() == "Prąd"
    assert dialog.table.cellWidget(0, dialog.PRICE).text() == ""
    dialog.accept()
    assert any("niepoprawna cena" in error for error in errors)
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog.table.cellWidget(0, dialog.PRICE).setText("321,50")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert get_wallet(db, wallet)["balance_cents"] == 32150


def test_recurring_tab_shows_amounts_and_deletes(db, errors):
    wallet = create_wallet(db, "A")
    create_recurring(db, wallet, "expense", "Bez kwoty")
    create_recurring(
        db, wallet, "income", "Z produktami",
        rows=[{"name": "X", "quantity": "2", "price": "5", "category": None}],
    )  # fmt: skip
    tab = RecurringTab(db)
    assert tab.table.item(0, AMOUNT).text() == "ustalana przy płatności"
    assert tab.table.item(1, AMOUNT).text().replace("\xa0", " ") == "+10,00 PLN"
    assert tab.table.item(1, REMAINING).text() == "bez limitu"
    assert not tab.delete_button.isEnabled()

    tab.table.setCurrentCell(0, 0)
    assert tab.delete_button.isEnabled()
    tab.delete()
    assert tab.table.rowCount() == 1
    assert tab.table.item(0, 0).text() == "Z produktami"


def test_new_recurring_requires_a_wallet(db, errors):
    RecurringTab(db).create()
    assert "Dodaj najpierw portfel" in errors[0]
