import pytest
from PySide6.QtCore import QDate, QEvent, Qt
from PySide6.QtGui import QFocusEvent, QHelpEvent, QKeyEvent, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QToolTip
from helpers import priced
from test_csv_import import BANK_CSV

from finanse import __version__
from finanse.categories import create_category
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
    assert transfer_day.child(0).text(3) == "Przelew"
    assert "→ B" in transfer_day.child(0).text(1)
    assert purchase_day.child(0).text(1) == "Zakupy"
    assert purchase_day.child(0).childCount() == 0  # produkty są w osobnej zakładce
    assert tab.tree.columnCount() == 7

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
    income_column, expense_column = 5, 6
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

    # Zmiana zaznaczenia portfeli znów rozwija całą listę.
    tab.wallet_list.item(1).setCheckState(Qt.CheckState.Unchecked)
    assert all(
        tab.tree.topLevelItem(i).isExpanded() for i in range(tab.tree.topLevelItemCount())
    )
    assert tab.selected_entry() is None


def _check_wallet(tab, row, checked):
    state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
    tab.wallet_list.item(row).setCheckState(state)


def _plain(text):
    return text.replace("\xa0", " ")


def _three_wallets(db):
    first = create_wallet(db, "A", "PLN", "100")
    second = create_wallet(db, "B", "PLN", "50")
    euro = create_wallet(db, "C", "EUR", "10")
    add(db, first, name="Chleb", price="5", on="2026-11-05")
    add(db, second, name="Ser", price="7", on="2026-11-05")
    add(db, euro, name="Kawa", price="2", on="2026-11-05")
    return first, second, euro


def test_transactions_list_starts_with_all_wallets_and_narrows(db, errors):
    first, second, euro = _three_wallets(db)
    tab = WalletsTab(db)
    assert tab.wallet_list.checked_ids() == {first, second, euro}
    assert tab.title.text() == "Wybrane portfele: 3"
    assert _plain(tab.balance.text()) == "8,00 EUR, 138,00 PLN"
    day = tab.tree.topLevelItem(0)
    assert day.childCount() == 3
    assert _plain(day.text(6)) == "−2,00 EUR, −12,00 PLN"
    assert not tab.tree.isColumnHidden(2)
    assert sorted(day.child(i).text(2) for i in range(3)) == ["A", "B", "C"]

    _check_wallet(tab, 2, False)
    assert tab.title.text() == "Wybrane portfele: 2"
    assert _plain(tab.tree.topLevelItem(0).text(6)) == "−12,00 PLN"

    _check_wallet(tab, 1, False)
    assert tab.title.text() == "A"
    assert tab.tree.isColumnHidden(2)  # jeden portfel nie wymaga tej kolumny
    assert tab.tree.topLevelItem(0).childCount() == 1

    _check_wallet(tab, 0, False)
    assert tab.title.text() == "Nie wybrano portfela"
    assert tab.tree.topLevelItemCount() == 0
    assert "Zaznacz co najmniej jeden" in tab.empty.text()
    assert not tab.empty.isHidden()

    tab.wallet_list.set_all_checked(True)
    assert tab.tree.topLevelItem(0).childCount() == 3


def test_products_list_starts_with_all_wallets_and_narrows(db, errors):
    first, second, euro = _three_wallets(db)
    tab = ProductsTab(db)
    assert tab.wallet_list.checked_ids() == {first, second, euro}
    assert tab.title.text() == "Wybrane portfele: 3"
    assert _product_names(tab) == ["Chleb", "Kawa", "Ser"]
    assert _plain(tab.tree.topLevelItem(0).text(9)) == "−2,00 EUR, −12,00 PLN"
    euro_row = next(
        tab.tree.topLevelItem(0).child(i)
        for i in range(3)
        if tab.tree.topLevelItem(0).child(i).text(1) == "Kawa"
    )
    assert euro_row.text(3) == "C" and "EUR" in euro_row.text(7)

    _check_wallet(tab, 0, False)
    assert _product_names(tab) == ["Kawa", "Ser"]
    tab.wallet_list.set_all_checked(False)
    assert _product_names(tab) == []
    assert "Zaznacz co najmniej jeden" in tab.empty.text()


def test_transfer_row_depends_on_selected_wallets(db, errors):
    source = create_wallet(db, "A", "PLN", "100")
    target = create_wallet(db, "B")
    create_transfer(db, source, target, "2026-11-05", "", "50")
    tab = WalletsTab(db)
    row = tab.tree.topLevelItem(0).child(0)
    assert "(A → B)" in row.text(1)
    assert _plain(row.text(4)) == "50,00 PLN"
    assert tab.tree.topLevelItem(0).text(6) == ""

    _check_wallet(tab, 1, False)
    assert _plain(tab.tree.topLevelItem(0).child(0).text(4)) == "−50,00 PLN"
    _check_wallet(tab, 1, True)
    _check_wallet(tab, 0, False)
    row = tab.tree.topLevelItem(0).child(0)
    assert "(← A)" in row.text(1)
    assert _plain(row.text(4)) == "+50,00 PLN"


def test_selection_survives_refresh_and_new_wallet_is_checked(db, errors):
    first = create_wallet(db, "A")
    second = create_wallet(db, "B")
    tab = WalletsTab(db)
    _check_wallet(tab, 1, False)
    tab.refresh()
    assert tab.wallet_list.checked_ids() == {first}
    assert second not in tab.wallet_list.checked_ids()
    third = create_wallet(db, "C")
    tab.refresh()
    assert tab.wallet_list.checked_ids() == {first, third}


def test_wallet_context_menu_replaces_buttons(db, errors, monkeypatch):
    wallet = create_wallet(db, "A")
    tab = WalletsTab(db)
    menu = tab._wallet_menu()
    assert [action.text() for action in menu.actions()] == [
        "Nowa transakcja",
        "Import CSV",
        "Edytuj portfel",
        "Usuń portfel",
    ]
    for name in ("import_button", "edit_wallet_button", "delete_wallet_button"):
        assert not hasattr(tab, name)

    created = []

    def exec_recording(dialog):
        created.append(dialog.selected_wallet_id())
        return 0

    monkeypatch.setattr(TransactionDialog, "exec", exec_recording)
    menu.actions()[0].trigger()
    assert created == [wallet]
    menu.actions()[3].trigger()
    assert list_wallets(db) == []


def test_empty_wallet_list_has_no_menu(db, errors):
    assert WalletsTab(db)._wallet_menu() is None


def test_new_transaction_dialog_chooses_wallet(db, errors):
    first = create_wallet(db, "A", "PLN")
    euro = create_wallet(db, "B", "EUR")
    dialog = TransactionDialog(db, get_wallet(db, first))
    assert dialog.wallet_combo.currentData() == first
    assert "PLN" in dialog.total.text()
    dialog.wallet_combo.setCurrentIndex(dialog.wallet_combo.findData(euro))
    assert "EUR" in dialog.total.text()
    dialog.description.setText("Zakupy")
    dialog.table.cellWidget(0, dialog.NAME).setText("Kawa")
    dialog.table.cellWidget(0, dialog.PRICE).setText("3")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert get_transaction(db, dialog.transaction_id)["wallet_id"] == euro
    assert get_wallet(db, euro)["balance_cents"] == -300


def _new_transaction_dialog(db):
    return TransactionDialog(db, get_wallet(db, create_wallet(db, "A")))


def _fill_product(dialog, row, name, price="3"):
    dialog.table.cellWidget(row, dialog.NAME).setText(name)
    dialog.table.cellWidget(row, dialog.PRICE).setText(price)


def test_single_product_name_is_suggested_and_used_as_description(db, errors):
    dialog = _new_transaction_dialog(db)
    assert dialog.description.placeholderText() == "np. Zakupy spożywcze"
    _fill_product(dialog, 0, "  Kawa ")
    assert dialog.description.placeholderText() == "Kawa"
    assert dialog.description.text() == ""  # to tylko propozycja
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = get_transaction(db, dialog.transaction_id)
    assert saved["description"] == "Kawa"
    assert saved["rows"][0]["name"] == "Kawa"
    assert errors == []


def test_typed_description_wins_over_suggestion(db, errors):
    dialog = _new_transaction_dialog(db)
    _fill_product(dialog, 0, "Kawa")
    dialog.description.setText("Zakupy")
    dialog.accept()
    assert get_transaction(db, dialog.transaction_id)["description"] == "Zakupy"


def test_blank_description_counts_as_missing(db, errors):
    dialog = _new_transaction_dialog(db)
    _fill_product(dialog, 0, "Kawa")
    dialog.description.setText("   ")
    dialog.accept()
    assert get_transaction(db, dialog.transaction_id)["description"] == "Kawa"


def test_no_suggestion_for_many_products_or_no_name(db, errors):
    dialog = _new_transaction_dialog(db)
    _fill_product(dialog, 0, "Kawa")
    dialog._add_row({"name": "Ser", "category": None, "quantity": "1", "price": "5"})
    dialog._update_totals()
    assert dialog.description.placeholderText() == "np. Zakupy spożywcze"
    dialog.accept()
    assert any("Podaj opis" in error for error in errors)
    assert dialog.result() != QDialog.DialogCode.Accepted

    # Po usunięciu drugiego produktu propozycja wraca.
    dialog._remove_row(dialog.table.cellWidget(1, dialog.REMOVE))
    assert dialog.description.placeholderText() == "Kawa"

    # Pusty wiersz się nie liczy, a produkt bez nazwy niczego nie proponuje.
    dialog._add_row({"name": "", "category": None, "quantity": "1", "price": ""})
    dialog._update_totals()
    assert dialog.description.placeholderText() == "Kawa"
    dialog._remove_row(dialog.table.cellWidget(1, dialog.REMOVE))
    _fill_product(dialog, 0, "")
    assert dialog.suggested_description() == ""
    assert dialog.description.placeholderText() == "np. Zakupy spożywcze"


def test_suggestion_only_in_new_transaction(db, errors):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet)
    edit = TransactionDialog(db, get_wallet(db, wallet), transaction)
    edit.description.clear()
    assert edit.suggested_description() == ""
    edit.accept()
    assert any("Podaj opis" in error for error in errors)
    assert get_transaction(db, transaction)["description"] == "Zakupy"

    recurring = create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"))
    payment = PaymentDialog(db, get_wallet(db, wallet), recurring)
    assert payment.suggested_description() == ""


def _cells(dialog, row=0):
    return (
        dialog.table.cellWidget(row, dialog.QUANTITY),
        dialog.table.cellWidget(row, dialog.PRICE),
        dialog.table.cellWidget(row, dialog.VALUE),
    )


def test_price_and_quantity_calculate_value(db, errors):
    dialog = _new_transaction_dialog(db)
    quantity, price, value = _cells(dialog)
    assert value.isEnabled() and not value.isReadOnly()
    price.setText("5")
    assert value.text() == "5,00"
    quantity.setText("3")
    assert value.text() == "15,00"
    assert price.text() == "5"  # wpisana cena zostaje
    assert "15,00" in dialog.total.text()


def test_value_calculates_price(db, errors):
    dialog = _new_transaction_dialog(db)
    quantity, price, value = _cells(dialog)
    quantity.setText("4")
    value.setText("100")
    assert price.text() == "25,00"
    assert value.text() == "100"  # wpisana wartość zostaje
    assert "100,00" in dialog.total.text()

    quantity.setText("5")  # ostatnio zmieniana była wartość, więc przelicza się cena
    assert price.text() == "20,00"
    assert value.text() == "100"

    price.setText("30")  # teraz ostatnia jest cena, więc przelicza się wartość
    assert value.text() == "150,00"
    quantity.setText("2")
    assert price.text() == "30"
    assert value.text() == "60,00"


def test_rounded_price_keeps_entered_value_when_saved(db, errors):
    dialog = _new_transaction_dialog(db)
    quantity, price, value = _cells(dialog)
    dialog.table.cellWidget(0, dialog.NAME).setText("Ser")
    quantity.setText("3")
    value.setText("10")
    assert price.text() == "3,33"
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    row = db.execute("SELECT unit_price_cents, total_cents FROM products").fetchone()
    assert tuple(row) == (333, 1000)

    # Ponowne otwarcie i zapis nie zmieniają wartości na 9,99.
    edit = TransactionDialog(db, get_wallet(db, 1), dialog.transaction_id)
    assert _cells(edit)[2].text() == "10,00"
    assert _cells(edit)[1].text() == "3,33"
    assert "10,00" in edit.total.text()
    edit.accept()
    assert db.execute("SELECT total_cents FROM products").fetchone()[0] == 1000

    # Zmiana ilości w edycji przelicza cenę, bo wartość nie wynika z ceny.
    edit = TransactionDialog(db, get_wallet(db, 1), dialog.transaction_id)
    _cells(edit)[0].setText("2")
    assert _cells(edit)[1].text() == "5,00"


def test_editing_regular_product_recalculates_value_from_price(db, errors):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet, price="5")
    edit = TransactionDialog(db, get_wallet(db, wallet), transaction)
    quantity, price, value = _cells(edit)
    assert value.text() == "5,00"
    quantity.setText("2")
    assert value.text() == "10,00"
    assert price.text() == "5,00"


def test_clearing_value_while_typing_overwrites_nothing(db, errors):
    dialog = _new_transaction_dialog(db)
    quantity, price, value = _cells(dialog)
    value.setText("100")
    value.clear()
    assert price.text() == "100,00"
    assert value.text() == ""
    value.setText("80")
    assert price.text() == "80,00"


def test_value_without_name_and_invalid_inputs(db, errors):
    dialog = _new_transaction_dialog(db)
    quantity, price, value = _cells(dialog)
    dialog.description.setText("Zakupy")
    value.setText("abc")
    assert price.text() == ""  # niepoprawna wartość niczego nie wylicza
    assert "0,00" in dialog.total.text()
    dialog.table.cellWidget(0, dialog.NAME).setText("Ser")
    dialog.accept()
    assert any("niepoprawna cena" in error for error in errors)
    assert dialog.result() != QDialog.DialogCode.Accepted

    errors.clear()
    value.setText("10")
    quantity.setText("abc")
    assert price.text() == "10,00"  # zostaje do czasu poprawienia ilości
    dialog.accept()
    assert any("niepoprawna ilość" in error for error in errors)

    errors.clear()
    quantity.setText("0")
    dialog.accept()
    assert any("niepoprawna ilość" in error for error in errors)
    quantity.setText("2")
    assert price.text() == "5,00"
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_removing_last_row_clears_value(db, errors):
    dialog = _new_transaction_dialog(db)
    quantity, price, value = _cells(dialog)
    value.setText("100")
    dialog._remove_row(dialog.table.cellWidget(0, dialog.REMOVE))
    quantity, price, value = _cells(dialog)
    assert (quantity.text(), price.text(), value.text()) == ("1", "", "")
    price.setText("5")  # po wyczyszczeniu wiersz znów liczy wartość z ceny
    assert value.text() == "5,00"
    assert dialog.rows()[0]["total"] == ""


def test_value_works_in_recurring_dialog(db, errors):
    create_wallet(db, "A")
    dialog = RecurringDialog(db)
    quantity, price, value = _cells(dialog)
    dialog.description.setText("Media")
    dialog.table.cellWidget(0, dialog.NAME).setText("Woda")
    quantity.setText("3")
    value.setText("10")
    assert price.text() == "3,33"
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    payment = PaymentDialog(db, get_wallet(db, 1), dialog.recurring_id)
    assert _cells(payment)[2].text() == "10,00"
    assert "10,00" in payment.total.text()


def _press(widget, key=Qt.Key.Key_Return, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(widget, key, modifier)


def test_enter_adds_product_instead_of_saving(db, errors):
    dialog = _new_transaction_dialog(db)
    dialog.show()
    _fill_product(dialog, 0, "Kawa")
    _press(dialog.table.cellWidget(0, dialog.PRICE))
    assert dialog.table.rowCount() == 2
    assert dialog.focusWidget() is dialog.table.cellWidget(1, dialog.NAME)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert dialog.isVisible()

    # Klawisz Enter z bloku numerycznego działa tak samo.
    _fill_product(dialog, 1, "Ser")
    _press(dialog.table.cellWidget(1, dialog.NAME), Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier)
    assert dialog.table.rowCount() == 3
    dialog.close()


def test_enter_works_from_every_field(db, errors):
    dialog = _new_transaction_dialog(db)
    dialog.show()
    _fill_product(dialog, 0, "Kawa")
    for widget, rows in (
        (dialog.description, 2),
        (dialog.occurred_on, 2),  # ostatni wiersz jest już pusty, więc nie ma kolejnego
        (dialog.kind, 2),
    ):
        _press(widget)
        assert dialog.table.rowCount() == rows
        assert dialog.focusWidget() is dialog.table.cellWidget(1, dialog.NAME)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    dialog.close()


def test_enter_on_empty_row_only_moves_focus(db, errors):
    dialog = _new_transaction_dialog(db)
    dialog.show()
    _press(dialog.description)
    assert dialog.table.rowCount() == 1
    assert dialog.focusWidget() is dialog.table.cellWidget(0, dialog.NAME)
    dialog.close()


@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_shift_enter_saves_whole_transaction(db, errors, key):
    dialog = _new_transaction_dialog(db)
    dialog.show()
    _fill_product(dialog, 0, "Kawa")
    _press(dialog.table.cellWidget(0, dialog.PRICE), key, Qt.KeyboardModifier.ShiftModifier)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert get_transaction(db, dialog.transaction_id)["description"] == "Kawa"


def test_shift_enter_with_errors_stays_open(db, errors):
    dialog = _new_transaction_dialog(db)
    dialog.show()
    _press(dialog.description, modifier=Qt.KeyboardModifier.ShiftModifier)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.isVisible()
    assert errors
    dialog.close()


def test_enter_in_edit_payment_and_recurring_dialogs(db, errors):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet)
    edit = TransactionDialog(db, get_wallet(db, wallet), transaction)
    edit.show()
    _press(edit.description)
    assert edit.table.rowCount() == 2
    _press(edit.description, modifier=Qt.KeyboardModifier.ShiftModifier)
    assert edit.result() == QDialog.DialogCode.Accepted

    recurring = create_recurring(db, wallet, "expense", "Czynsz", remaining="1", rows=priced("Czynsz", "10"))
    payment = PaymentDialog(db, get_wallet(db, wallet), recurring)
    payment.show()
    _press(payment.description, modifier=Qt.KeyboardModifier.ShiftModifier)
    assert payment.result() == QDialog.DialogCode.Accepted
    assert get_recurring(db, recurring)["remaining"] == 0

    template = RecurringDialog(db)
    template.show()
    _press(template.description)
    assert template.result() != QDialog.DialogCode.Accepted
    assert template.isVisible()
    template.close()


def test_escape_still_closes_dialog(db, errors):
    dialog = _new_transaction_dialog(db)
    dialog.show()
    _press(dialog.description, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_wallet_dialog_still_saves_on_enter(db, errors):
    dialog = WalletDialog(db)
    dialog.show()
    dialog.name.setText("Nowy")
    _press(dialog.name)
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_saved_transaction_makes_its_wallet_visible(db, errors, monkeypatch):
    first = create_wallet(db, "A")
    second = create_wallet(db, "B")
    tab = WalletsTab(db)
    _check_wallet(tab, 1, False)

    def exec_saving(dialog):
        dialog.wallet_combo.setCurrentIndex(dialog.wallet_combo.findData(second))
        dialog.description.setText("Zakupy")
        dialog.table.cellWidget(0, dialog.NAME).setText("Kawa")
        dialog.table.cellWidget(0, dialog.PRICE).setText("3")
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(TransactionDialog, "exec", exec_saving)
    tab.create_transaction()
    assert tab.wallet_list.checked_ids() == {first, second}
    assert tab.tree.topLevelItemCount() == 1


def test_editing_uses_wallet_of_the_transaction_without_chooser(db, errors, monkeypatch):
    first = create_wallet(db, "A", "PLN")
    euro = create_wallet(db, "B", "EUR")
    add(db, euro, on="2026-11-05")
    seen = []

    def exec_recording(dialog):
        seen.append((dialog.wallet_combo, dialog.wallet["id"], dialog._currency()))
        return 0

    monkeypatch.setattr(TransactionDialog, "exec", exec_recording)
    tab = WalletsTab(db)
    assert tab.wallet_id() == first  # podświetlony inny portfel niż portfel rachunku
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))
    tab.edit_entry()
    assert seen == [(None, euro, "EUR")]


@pytest.mark.parametrize("tab_class", [WalletsTab, ProductsTab])
def test_last_transaction_follows_selected_wallets(db, errors, tab_class):
    first = create_wallet(db, "A")
    create_wallet(db, "B")
    create_wallet(db, "C")
    add(db, first, on="2026-10-01")
    add(db, db.execute("SELECT id FROM wallets WHERE name = 'B'").fetchone()[0], on="2026-11-05")
    tab = tab_class(db)
    assert tab.last_transaction.text() == "Najnowsza transakcja: 2026-11-05"

    _check_wallet(tab, 1, False)
    assert tab.last_transaction.text() == "Najnowsza transakcja: 2026-10-01"
    # Filtry listy nie zmieniają tej informacji.
    tab.filter_bar.search.setText("nie ma takiego")
    assert tab.last_transaction.text() == "Najnowsza transakcja: 2026-10-01"
    tab.filter_bar.clear()

    tab.wallet_list.set_all_checked(False)
    assert tab.last_transaction.text() == ""
    _check_wallet(tab, 2, True)
    assert tab.last_transaction.text() == "Brak transakcji"


def test_last_transaction_updates_after_change(db, errors):
    wallet = create_wallet(db, "A")
    add(db, wallet, on="2026-10-01")
    tab = WalletsTab(db)
    add(db, wallet, on="2026-11-01")
    tab.refresh()
    assert tab.last_transaction.text() == "Najnowsza transakcja: 2026-11-01"


def _balance_wallets(db):
    first = create_wallet(db, "A", "PLN", "100")
    second = create_wallet(db, "B", "PLN", "50")
    add(db, first, price="20", on="2026-10-10")
    add(db, first, price="5", on="2026-11-01")
    add(db, second, price="7", on="2026-11-02")
    return first, second


def test_wallet_values_follow_date_to_filter(db, errors):
    first, second = _balance_wallets(db)
    tab = WalletsTab(db)
    assert _plain(tab.wallet_list.item(0).text()) == "A\n75,00 PLN"
    assert _plain(tab.wallet_list.item(1).text()) == "B\n43,00 PLN"
    assert _plain(tab.balance.text()) == "118,00 PLN"

    tab.filter_bar.date_to.setDate(QDate(2026, 10, 31))
    tab.filter_bar.use_to.setChecked(True)
    assert _plain(tab.wallet_list.item(0).text()) == "A\n80,00 PLN"
    assert _plain(tab.wallet_list.item(1).text()) == "B\n50,00 PLN"
    assert _plain(tab.balance.text()) == "Saldo na 2026-10-31: 130,00 PLN"

    tab.filter_bar.date_to.setDate(QDate(2026, 11, 1))
    assert _plain(tab.wallet_list.item(0).text()) == "A\n75,00 PLN"
    assert _plain(tab.balance.text()) == "Saldo na 2026-11-01: 125,00 PLN"

    # Zaznaczenie liczy się razem z datą i przetrwa odświeżenie.
    _check_wallet(tab, 1, False)
    assert _plain(tab.balance.text()) == "Saldo na 2026-11-01: 75,00 PLN"
    tab.refresh()
    assert _plain(tab.wallet_list.item(0).text()) == "A\n75,00 PLN"
    assert tab.wallet_list.checked_ids() == {first}
    _check_wallet(tab, 1, True)

    tab.filter_bar.clear()
    assert _plain(tab.wallet_list.item(1).text()) == "B\n43,00 PLN"
    assert _plain(tab.balance.text()) == "118,00 PLN"


def test_other_filters_do_not_change_wallet_values(db, errors):
    _balance_wallets(db)
    tab = WalletsTab(db)
    tab.filter_bar.date_from.setDate(QDate(2026, 11, 2))
    tab.filter_bar.use_from.setChecked(True)  # samo „Od” nie określa końca okresu
    tab.filter_bar.search.setText("nie ma takiego")
    tab.filter_bar.amount_from.setText("999")
    assert _plain(tab.balance.text()) == "118,00 PLN"
    assert _plain(tab.wallet_list.item(0).text()) == "A\n75,00 PLN"


def test_changing_filter_keeps_highlight_and_expanded_days(db, errors):
    first, second = _balance_wallets(db)
    tab = WalletsTab(db)
    tab.wallet_list.setCurrentRow(1)
    tab.filter_bar.date_to.setDate(QDate(2026, 11, 30))
    tab.filter_bar.use_to.setChecked(True)
    assert tab.wallet_id() == second
    assert tab.wallet_list.checked_ids() == {first, second}


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
    assert day.text(8).replace("\xa0", " ") == "+7,00 PLN"
    assert day.text(9).replace("\xa0", " ") == "−40,00 PLN"
    assert _product_names(tab) == ["Kaucja", "Mydło", "Żurek"]

    soap = next(day.child(i) for i in range(3) if day.child(i).text(1) == "Mydło")
    assert [soap.text(c) for c in (2, 3, 4, 5)] == ["Biedronka", "A", "Dom", "2"]
    assert soap.text(6) == "5,00"
    assert soap.text(7).replace("\xa0", " ") == "−10,00 PLN"


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
    assert tab.wallet_list.checked_ids() == {wallet}
    texts = [tab.tree.topLevelItem(0).child(i).text(2) for i in range(3)]
    assert "Zmieniony" in texts


def test_products_tab_without_wallets(db, errors):
    tab = ProductsTab(db)
    assert tab.title.text() == "Dodaj pierwszy portfel"
    assert not tab.edit_button.isEnabled()


def test_main_window_refreshes_tab_on_switch(db, errors):
    window = MainWindow(db)
    assert window.tabs.count() == 9
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


def test_files_tab_lists_files_with_sums(db, errors, tmp_path):
    (tmp_path / "test.db.backup-v2").write_bytes(b"x" * 2048)
    (tmp_path / "notatka.txt").write_bytes(b"x" * 10)
    window = MainWindow(db)
    window.tabs.setCurrentWidget(window.files)
    tree = window.files.tree
    groups = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert groups == [
        "Baza danych (plików: 1)",
        "Kopie przed migracjami i ręczne (plików: 1)",
        "Inne pliki (plików: 1)",
    ]
    assert tree.topLevelItem(1).text(1) == "2,0 KB"
    assert tree.topLevelItem(1).isExpanded()
    assert tree.topLevelItem(2).child(0).text(0) == "notatka.txt"
    assert tree.topLevelItem(2).child(0).text(1) == "10 B"
    assert "plików: 3" in window.files.total.text()
    assert str(tmp_path) in window.files.directory.text()

    (tmp_path / "nowy.txt").write_bytes(b"x")
    window.tabs.setCurrentWidget(window.wallets)
    window.tabs.setCurrentWidget(window.files)
    assert "plików: 4" in window.files.total.text()


def test_about_tab_shows_version_and_changelog(db, errors):
    window = MainWindow(db)
    window.tabs.setCurrentWidget(window.about)
    assert window.tabs.tabText(window.tabs.currentIndex()) == "O programie"
    assert window.about.version.text() == f"Wersja {__version__}"
    text = window.about.changelog.toPlainText()
    assert "Historia zmian" in text and f"{__version__} (" in text
    assert window.about.changelog.isReadOnly()


def _is_warning(item, column=None):
    args = () if column is None else (column,)
    return (
        item.background(*args).color() == common.warning_background()
        and item.foreground(*args).color() == common.warning_text()
    )


def _contrast(color, background):
    def luminance(c):
        channels = [v / 255 for v in (c.red(), c.green(), c.blue())]
        linear = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(color), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_warning_text_is_readable_on_warning_background(qapp):
    assert _contrast(common.warning_text(), common.warning_background()) >= 7


def _categorized_wallet(db):
    wallet = create_wallet(db, "A")
    dom = db.execute("SELECT id FROM categories WHERE name = 'Dom'").fetchone()[0]
    for description, rows in (
        ("Bez", [(None, "X")]),
        ("Z", [(dom, "Y")]),
        ("Mieszany", [(dom, "V"), (None, "W")]),
    ):
        create_transaction(
            db, wallet, "expense", "2026-10-05", description,
            [
                {"name": name, "quantity": "1", "price": "1", "category": category}
                for category, name in rows
            ],
        )  # fmt: skip
    return wallet, dom


def test_transaction_list_marks_no_category(db, errors):
    _categorized_wallet(db)
    day = WalletsTab(db).tree.topLevelItem(0)
    rows = {day.child(i).text(1): day.child(i) for i in range(3)}
    category_column = 3
    assert _is_warning(rows["Bez"], category_column)
    assert rows["Bez"].toolTip(category_column) == common.NO_CATEGORY_HINT
    assert "Bez kategorii" in rows["Mieszany"].text(category_column)
    assert _is_warning(rows["Mieszany"], category_column)
    assert not _is_warning(rows["Z"], category_column)
    assert rows["Z"].toolTip(category_column) == ""


def test_products_list_marks_only_products_without_category(db, errors):
    _categorized_wallet(db)
    day = ProductsTab(db).tree.topLevelItem(0)
    rows = {day.child(i).text(1): day.child(i) for i in range(day.childCount())}
    category_column = 4
    assert _is_warning(rows["W"], category_column)
    assert not _is_warning(rows["V"], category_column)


def test_recurring_list_marks_no_category(db, errors):
    wallet, dom = _categorized_wallet(db)
    create_recurring(db, wallet, "expense", "Bez")
    create_recurring(db, wallet, "expense", "Z", rows=priced("Z", "1", dom))
    create_recurring(db, wallet, "expense", "Y", rows=priced("Y", "1"))
    table = RecurringTab(db).table
    # Bez produktów kategorii jeszcze nie ma, więc nie ma też czego wyróżniać.
    assert table.item(0, 2).text() == "–" and not _is_warning(table.item(0, 2))
    assert table.item(1, 2).text() == "Bez kategorii" and _is_warning(table.item(1, 2))
    assert table.item(2, 2).text() == "Dom" and not _is_warning(table.item(2, 2))


def test_report_marks_no_category(db, errors):
    _categorized_wallet(db)
    tab = ReportsTab(db)
    tab.show_month("2026-10")
    names = {}
    for row in range(tab.expenses_grid.rowCount()):
        item = tab.expenses_grid.itemAtPosition(row, 0)
        if item:
            names[item.widget().text()] = item.widget()
    style = names["Bez kategorii"].styleSheet()
    assert common.warning_background().name() in style
    assert common.warning_text().name() in style
    assert names["Bez kategorii"].toolTip() == common.NO_CATEGORY_HINT
    assert names["Dom"].styleSheet() == ""


def test_category_combo_marks_no_category_when_selected(db, errors):
    wallet = create_wallet(db, "A")
    dialog = TransactionDialog(db, get_wallet(db, wallet))
    combo = dialog.table.cellWidget(0, dialog.CATEGORY)
    background, text = QPalette.ColorRole.Button, QPalette.ColorRole.ButtonText
    assert combo.currentText() == "Bez kategorii"
    assert combo.palette().color(background) == common.warning_background()
    assert combo.palette().color(text) == common.warning_text()
    assert combo.toolTip() == common.NO_CATEGORY_HINT
    assert combo.itemData(0, Qt.ItemDataRole.BackgroundRole) == common.warning_background()
    assert combo.itemData(0, Qt.ItemDataRole.ForegroundRole) == common.warning_text()

    combo.setCurrentIndex(combo.findText("Dom"))
    assert combo.palette().color(background) != common.warning_background()
    assert combo.palette().color(text) != common.warning_text()
    assert combo.toolTip() == ""
    combo.setCurrentIndex(0)
    assert combo.palette().color(background) == common.warning_background()


def test_filter_marks_no_category_item_but_keeps_all_categories_plain(db, errors):
    tab = WalletsTab(db)
    combo = tab.filter_bar.category
    index = combo.findText("Bez kategorii")
    assert combo.itemData(index, Qt.ItemDataRole.BackgroundRole) == common.warning_background()
    assert combo.itemData(0, Qt.ItemDataRole.BackgroundRole) is None


def _fill_new_transaction(dialog):
    dialog.description.setText("Skrót")
    dialog.table.cellWidget(0, dialog.NAME).setText("Kawa")
    dialog.table.cellWidget(0, dialog.PRICE).setText("3")
    dialog.accept()
    return dialog.result()


def test_ctrl_n_opens_new_transaction_from_any_tab(db, errors, monkeypatch):
    wallet = create_wallet(db, "A")
    monkeypatch.setattr(TransactionDialog, "exec", _fill_new_transaction)
    window = MainWindow(db)
    assert window.new_transaction_shortcut.key().toString() == "Ctrl+N"

    window.tabs.setCurrentWidget(window.products)
    window.new_transaction_shortcut.activated.emit()
    assert get_wallet(db, wallet)["balance_cents"] == -300
    # Widoczna zakładka i lista transakcji od razu pokazują nowy wpis.
    assert window.products.tree.topLevelItemCount() == 1
    assert window.wallets.tree.topLevelItem(0).child(0).text(1) == "Skrót"
    assert window.tabs.currentWidget() is window.products


def test_ctrl_n_real_key_press_opens_dialog(db, errors, monkeypatch):
    create_wallet(db, "A")
    opened = []
    monkeypatch.setattr(TransactionDialog, "exec", lambda d: opened.append(d) or 0)
    window = MainWindow(db)
    window.show()
    assert QTest.qWaitForWindowActive(window)
    QTest.keyClick(window.wallets.tree, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    assert len(opened) == 1
    assert opened[0].wallet_combo is not None
    window.close()


def test_ctrl_n_without_wallets_reports_it(db, errors):
    window = MainWindow(db)
    window.new_transaction()
    assert "Dodaj najpierw portfel" in errors[0]


def test_new_transaction_button_shows_shortcut_in_tooltip(db, errors):
    button = WalletsTab(db).new_transaction_button
    assert button.text() == "Nowa transakcja"
    assert "Ctrl+N" in button.toolTip()


def _save_new_transaction(db, wallet, date=None):
    dialog = TransactionDialog(db, get_wallet(db, wallet))
    if date:
        dialog.occurred_on.setDate(date)
    _fill_product(dialog, 0, "Kawa")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    return dialog


def test_new_transaction_remembers_last_saved_date(db, errors):
    wallet = create_wallet(db, "A")
    assert TransactionDialog(db, get_wallet(db, wallet)).occurred_on.date() == QDate.currentDate()

    past = QDate(2026, 3, 14)
    saved = _save_new_transaction(db, wallet, past)
    assert get_transaction(db, saved.transaction_id)["occurred_on"] == "2026-03-14"
    assert TransactionDialog(db, get_wallet(db, wallet)).occurred_on.date() == past

    # Kolejna zapisana data zastępuje poprzednią.
    _save_new_transaction(db, wallet, QDate(2026, 3, 15))
    assert TransactionDialog(db, get_wallet(db, wallet)).occurred_on.date() == QDate(2026, 3, 15)


def test_unsaved_dialogs_do_not_change_remembered_date(db, errors):
    wallet = create_wallet(db, "A")
    _save_new_transaction(db, wallet, QDate(2026, 3, 14))

    cancelled = TransactionDialog(db, get_wallet(db, wallet))
    cancelled.occurred_on.setDate(QDate(2020, 1, 1))
    cancelled.reject()
    invalid = TransactionDialog(db, get_wallet(db, wallet))
    invalid.occurred_on.setDate(QDate(2020, 1, 2))
    invalid.accept()  # brak produktu, więc zapis się nie udaje
    assert invalid.result() != QDialog.DialogCode.Accepted
    assert TransactionDialog(db, get_wallet(db, wallet)).occurred_on.date() == QDate(2026, 3, 14)


def test_edit_and_payment_neither_use_nor_change_remembered_date(db, errors):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet, on="2026-11-05")
    _save_new_transaction(db, wallet, QDate(2026, 3, 14))

    edit = TransactionDialog(db, get_wallet(db, wallet), transaction)
    assert edit.occurred_on.date() == QDate(2026, 11, 5)
    edit.accept()

    recurring = create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"))
    payment = PaymentDialog(db, get_wallet(db, wallet), recurring)
    assert payment.occurred_on.date() == QDate.currentDate()
    payment.occurred_on.setDate(QDate(2020, 1, 1))
    payment.accept()
    assert payment.result() == QDialog.DialogCode.Accepted

    assert TransactionDialog(db, get_wallet(db, wallet)).occurred_on.date() == QDate(2026, 3, 14)


def test_today_button_sets_current_date_in_every_dialog(db, errors):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet, on="2026-03-14")
    recurring = create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "10"))
    for dialog in (
        TransactionDialog(db, get_wallet(db, wallet)),
        TransactionDialog(db, get_wallet(db, wallet), transaction),
        PaymentDialog(db, get_wallet(db, wallet), recurring),
    ):
        dialog.occurred_on.setDate(QDate(2020, 1, 1))
        dialog.today_button.click()
        assert dialog.occurred_on.date() == QDate.currentDate()
        assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.today_button.text() == "Dzisiaj"
    assert "Ctrl+T" in dialog.today_button.toolTip()


@pytest.mark.parametrize("field", ["description", "product"])
def test_ctrl_t_sets_today_without_changing_typed_text(db, errors, field):
    dialog = _new_transaction_dialog(db)
    dialog.show()
    assert QTest.qWaitForWindowActive(dialog)
    dialog.occurred_on.setDate(QDate(2020, 1, 1))
    widget = (
        dialog.description if field == "description"
        else dialog.table.cellWidget(0, dialog.NAME)
    )  # fmt: skip
    widget.setFocus()
    widget.setText("Tekst")
    QTest.keyClick(widget, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
    assert dialog.occurred_on.date() == QDate.currentDate()
    assert widget.text() == "Tekst"
    dialog.close()


def test_enter_on_today_button_does_not_save(db, errors):
    dialog = _new_transaction_dialog(db)
    dialog.show()
    _fill_product(dialog, 0, "Kawa")
    _press(dialog.today_button)
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    dialog.close()


def _row_color(tree, item):
    tree.viewport().repaint()
    rect = tree.visualItemRect(item)
    pixel = tree.viewport().grab().toImage().pixelColor(rect.right() - 5, rect.center().y())
    return pixel.name()


def _flash_key(tab, transaction_id):
    return tab.tree.flash_match(("transaction", transaction_id))


def _add_many_days(db, wallet, days=60):
    for day in range(1, days + 1):
        on = QDate(2026, 1, 1).addDays(day).toString("yyyy-MM-dd")
        add(db, wallet, name=f"Dzień {day}", on=on)


def test_new_transaction_flashes_for_two_seconds(db, errors, monkeypatch):
    wallet = create_wallet(db, "A")
    add(db, wallet, on="2026-10-01")
    monkeypatch.setattr(TransactionDialog, "exec", _fill_new_transaction)
    tab = WalletsTab(db)
    transaction_id = tab.create_transaction()

    tree = tab.tree
    assert tree.flash_visible
    assert tree.flash_timer.isActive() and tree.flash_timer.interval() == 250
    assert _flash_key(tab, transaction_id)
    assert not tree.flash_match(("transaction", transaction_id + 1))
    assert not tree.flash_match(("day", "2026-11-05"))

    # 8 faz po 250 ms: stan początkowy i 7 przełączeń, a potem koniec migania.
    phases = [tree.flash_visible]
    while tree.flash_timer.isActive():
        tree._flash_tick()
        if tree.flash_timer.isActive():
            phases.append(tree.flash_visible)
    assert phases == [True, False, True, False, True, False, True, False]
    assert len(phases) * 250 == 2000
    assert not tree.flash_visible


def test_flash_really_changes_the_row_and_ends_on_its_own(db, errors):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet, on="2026-10-01")
    tab = WalletsTab(db)
    tab.resize(1000, 600)
    tab.show()
    assert QTest.qWaitForWindowExposed(tab)
    tree = tab.tree
    row = tree.topLevelItem(0).child(0)
    normal = _row_color(tree, row)

    tree.flash(lambda key: key == ("transaction", transaction), duration=200, interval=50)
    assert _row_color(tree, row) == tree.palette().color(QPalette.ColorRole.Highlight).name()
    QTest.qWait(400)
    assert not tree.flash_timer.isActive() and not tree.flash_visible
    assert _row_color(tree, row) == normal
    tab.close()


def test_flash_expands_day_and_scrolls_to_transaction(db, errors, monkeypatch):
    wallet = create_wallet(db, "A")
    _add_many_days(db, wallet)
    tab = WalletsTab(db)
    tab.resize(800, 400)
    tab.show()
    assert QTest.qWaitForWindowExposed(tab)
    tab.collapse_all_button.click()

    def exec_saving_old(dialog):
        dialog.occurred_on.setDate(QDate(2026, 1, 3))
        return _fill_new_transaction(dialog)

    monkeypatch.setattr(TransactionDialog, "exec", exec_saving_old)
    tab.create_transaction()
    target = next(
        tab.tree.topLevelItem(i)
        for i in range(tab.tree.topLevelItemCount())
        if tab.tree.topLevelItem(i).text(0) == "2026-01-03"
    )
    assert target.isExpanded()
    row = next(
        target.child(i) for i in range(target.childCount()) if target.child(i).text(1) == "Skrót"
    )
    assert tab.tree.viewport().rect().intersects(tab.tree.visualItemRect(row))
    tab.tree.flash_timer.stop()
    tab.close()


def test_flash_survives_refresh_and_keeps_stored_colors(db, errors):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet, on="2026-10-01")
    tab = WalletsTab(db)
    tab.tree.flash(lambda key: key == ("transaction", transaction))
    tab.refresh()
    assert tab.tree.flash_visible and tab.tree.flash_timer.isActive()
    assert _flash_key(tab, transaction)
    # Bursztynowe tło braku kategorii zostaje zapisane w elemencie.
    row = tab.tree.topLevelItem(0).child(0)
    assert _is_warning(row, 3)
    tab.tree.flash_timer.stop()


def test_cancelled_or_filtered_out_transaction_does_not_flash(db, errors, monkeypatch):
    create_wallet(db, "A")
    tab = WalletsTab(db)
    monkeypatch.setattr(TransactionDialog, "exec", lambda _dialog: 0)
    assert tab.create_transaction() is None
    assert not tab.tree.flash_timer.isActive()

    monkeypatch.setattr(TransactionDialog, "exec", _fill_new_transaction)
    tab.filter_bar.search.setText("nie ma takiego")
    assert tab.create_transaction() is not None
    assert not tab.tree.flash_timer.isActive() and not tab.tree.flash_visible


def test_editing_transaction_does_not_flash(db, errors, monkeypatch):
    wallet = create_wallet(db, "A")
    add(db, wallet, on="2026-10-01")
    tab = WalletsTab(db)
    monkeypatch.setattr(TransactionDialog, "exec", lambda d: (d.accept(), d.result())[1])
    tab.tree.setCurrentItem(tab.tree.topLevelItem(0).child(0))
    tab.edit_entry()
    assert not tab.tree.flash_timer.isActive()


def test_ctrl_n_flashes_in_visible_list(db, errors, monkeypatch):
    create_wallet(db, "A")
    monkeypatch.setattr(TransactionDialog, "exec", _fill_new_transaction)
    window = MainWindow(db)

    window.new_transaction()  # zakładka Portfele
    assert window.wallets.tree.flash_timer.isActive()
    window.wallets.tree.flash_timer.stop()

    window.tabs.setCurrentWidget(window.products)
    window.new_transaction()
    products = window.products.tree
    assert products.flash_timer.isActive()
    transaction_id = db.execute("SELECT MAX(id) FROM transactions").fetchone()[0]
    assert products.flash_match(("product", 999, transaction_id))
    assert not products.flash_match(("product", 999, transaction_id - 1))
    assert not products.flash_match(("day", "2026-11-05"))
    products.flash_timer.stop()
    window.wallets.tree.flash_timer.stop()


def test_categories_tab_deletes_only_empty(db, errors):
    wallet = create_wallet(db, "A")
    used = create_category(db, "Używana")
    template = create_category(db, "W szablonie")
    create_category(db, "Pusta")
    create_transaction(
        db, wallet, "expense", "2026-11-05", "Zakupy",
        [{"name": "X", "quantity": "1", "price": "1", "category": used}],
    )  # fmt: skip
    create_recurring(db, wallet, "expense", "Media", rows=priced("Woda", "1", template))
    tab = CategoriesTab(db)

    def select(name):
        row = next(r for r in range(tab.table.rowCount()) if tab.table.item(r, 0).text() == name)
        tab.table.setCurrentCell(row, 0)
        return row

    row = select("Używana")
    assert (tab.table.item(row, 1).text(), tab.table.item(row, 2).text()) == ("1", "0")
    assert not tab.delete_button.isEnabled() and tab.rename_button.isEnabled()
    assert "pustą" in tab.delete_button.toolTip()
    assert "(produkty: 1)" in tab.delete_button.toolTip()
    tab.delete()  # np. klawiszem Delete
    assert errors[0] in tab.delete_button.toolTip()
    assert db.execute("SELECT COUNT(*) FROM categories WHERE id = ?", (used,)).fetchone()[0] == 1

    errors.clear()
    row = select("W szablonie")
    assert tab.table.item(row, 2).text() == "1"
    assert not tab.delete_button.isEnabled()
    assert "(produkty transakcji cyklicznych: 1)" in tab.delete_button.toolTip()
    tab.delete()
    assert "cyklicznych: 1" in errors[0]

    errors.clear()
    select("Pusta")
    assert tab.delete_button.isEnabled() and "pustą" not in tab.delete_button.toolTip()
    tab.delete_button.click()
    assert errors == []
    names = [tab.table.item(r, 0).text() for r in range(tab.table.rowCount())]
    assert "Pusta" not in names and "Używana" in names


def test_disabled_delete_button_really_shows_tooltip(db, errors):
    wallet = create_wallet(db, "A")
    used = create_category(db, "Używana")
    create_transaction(
        db, wallet, "expense", "2026-11-05", "Zakupy",
        [{"name": "X", "quantity": "1", "price": "1", "category": used}],
    )  # fmt: skip
    tab = CategoriesTab(db)
    tab.show()
    assert QTest.qWaitForWindowExposed(tab)
    button = tab.delete_button
    assert not button.isEnabled()
    assert "Zaznacz kategorię." in button.toolTip()

    row = next(r for r in range(tab.table.rowCount()) if tab.table.item(r, 0).text() == "Używana")
    tab.table.setCurrentCell(row, 0)
    position = button.rect().center()
    event = QHelpEvent(QEvent.Type.ToolTip, position, button.mapToGlobal(position))
    QApplication.sendEvent(button, event)
    assert QToolTip.isVisible()
    assert QToolTip.text() == button.toolTip()
    assert "(produkty: 1)" in QToolTip.text()
    QToolTip.hideText()
    tab.close()


def test_declined_category_delete_keeps_it(db, errors, monkeypatch):
    monkeypatch.setattr(common, "confirm", lambda *_a, **_k: False)
    create_category(db, "Pusta")
    tab = CategoriesTab(db)
    rows = tab.table.rowCount()
    row = next(r for r in range(rows) if tab.table.item(r, 0).text() == "Pusta")
    tab.table.setCurrentCell(row, 0)
    tab.delete()
    assert tab.table.rowCount() == rows


def _kind_rows(db):
    wallet = create_wallet(db, "A")
    other = create_wallet(db, "B")
    dom = db.execute("SELECT id FROM categories WHERE name = 'Dom'").fetchone()[0]
    create_transaction(
        db, wallet, "income", "2026-11-05", "Pensja",
        [{"name": "Etat", "quantity": "1", "price": "100", "category": dom}],
    )  # fmt: skip
    create_transaction(
        db, wallet, "expense", "2026-11-05", "Zakupy",
        [{"name": "Chleb", "quantity": "1", "price": "5", "category": None}],
    )  # fmt: skip
    create_transfer(db, wallet, other, "2026-11-05", "", "1")


def _rows_by_name(tree):
    day = tree.topLevelItem(0)
    return {day.child(i).text(1): day.child(i) for i in range(day.childCount())}


def test_transaction_rows_differ_by_kind(db, errors):
    _kind_rows(db)
    tree = WalletsTab(db).tree
    rows = _rows_by_name(tree)
    income, expense = common.income_row_background(), common.expense_row_background()
    for column in range(tree.columnCount()):
        assert rows["Pensja"].background(column).color() == income
    for column in (0, 1, 2, 4, 5, 6):
        assert rows["Zakupy"].background(column).color() == expense
    # Brak kategorii nadal wyróżnia swoją komórkę.
    assert _is_warning(rows["Zakupy"], 3)
    transfer = next(row for name, row in rows.items() if name.startswith("Przelew"))
    assert transfer.background(1).style() == Qt.BrushStyle.NoBrush
    day = tree.topLevelItem(0)
    assert day.background(1).style() == Qt.BrushStyle.NoBrush


def test_product_rows_differ_by_kind(db, errors):
    _kind_rows(db)
    tree = ProductsTab(db).tree
    rows = _rows_by_name(tree)
    for column in range(tree.columnCount()):
        assert rows["Etat"].background(column).color() == common.income_row_background()
    assert rows["Chleb"].background(1).color() == common.expense_row_background()
    assert _is_warning(rows["Chleb"], 4)


def test_row_background_is_really_painted_and_flash_covers_it(db, errors):
    wallet = create_wallet(db, "A")
    transaction = create_transaction(
        db, wallet, "income", "2026-11-05", "Pensja",
        [{"name": "Etat", "quantity": "1", "price": "100", "category": None}],
    )  # fmt: skip
    tab = WalletsTab(db)
    tab.resize(1000, 600)
    tab.show()
    assert QTest.qWaitForWindowExposed(tab)
    tree = tab.tree
    row = tree.topLevelItem(0).child(0)
    assert _row_color(tree, row) == common.income_row_background().name()

    def indent_color():
        tree.viewport().repaint()
        y = tree.visualItemRect(row).center().y()
        return tree.viewport().grab().toImage().pixelColor(3, y).name()

    assert indent_color() == common.income_row_background().name()
    tree.flash(lambda key: key == ("transaction", transaction))
    highlight = tree.palette().color(QPalette.ColorRole.Highlight).name()
    assert _row_color(tree, row) == highlight
    assert indent_color() == highlight
    tree.flash_timer.stop()
    tab.close()


def test_new_transaction_starts_in_first_product_name(db, errors):
    wallet = create_wallet(db, "A")
    dialog = TransactionDialog(db, get_wallet(db, wallet))
    dialog.show()
    assert QTest.qWaitForWindowActive(dialog)
    name = dialog.table.cellWidget(0, dialog.NAME)
    assert QApplication.focusWidget() is name
    QTest.keyClicks(QApplication.focusWidget(), "Kawa")
    assert name.text() == "Kawa"
    dialog.close()


def test_edit_and_payment_do_not_start_in_product_name(db, errors):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet)
    recurring = create_recurring(db, wallet, "expense", "Czynsz", rows=priced("Czynsz", "1"))
    for dialog in (
        TransactionDialog(db, get_wallet(db, wallet), transaction),
        PaymentDialog(db, get_wallet(db, wallet), recurring),
    ):
        dialog.show()
        assert QTest.qWaitForWindowActive(dialog)
        assert QApplication.focusWidget() is not dialog.table.cellWidget(0, dialog.NAME)
        dialog.close()


def _category_dialog(db):
    dialog = _new_transaction_dialog(db)
    dialog.show()
    assert QTest.qWaitForWindowActive(dialog)
    dialog.table.cellWidget(0, dialog.NAME).setText("Kawa")
    dialog.table.cellWidget(0, dialog.PRICE).setText("3")
    combo = dialog.table.cellWidget(0, dialog.CATEGORY)
    combo.setFocus()
    QApplication.processEvents()
    return dialog, combo


def _saved_category(db, dialog):
    category_id = get_transaction(db, dialog.transaction_id)["rows"][0]["category"]
    row = db.execute("SELECT name FROM categories WHERE id = ?", (category_id,)).fetchone()
    return row[0] if row else None


def test_typing_shows_fuzzy_matches_and_keeps_typed_text(db, errors):
    dialog, combo = _category_dialog(db)
    assert combo.isEditable()
    line = combo.lineEdit()
    QTest.keyClick(line, Qt.Key.Key_J)
    assert line.text() == "j"  # wynik nie podmienia tekstu w trakcie pisania
    QTest.keyClick(line, Qt.Key.Key_D)
    QTest.keyClick(line, Qt.Key.Key_Z)
    assert line.text() == "jdz"
    assert line.cursorPosition() == 3
    assert combo.results.isVisible()
    assert combo.match_names()[0] == "Jedzenie"
    assert combo.results.currentItem().text() == "Jedzenie"
    assert QApplication.focusWidget() is combo  # pole tekstowe przekazuje fokus listy
    dialog.close()


def _focused_dialog(db):
    dialog = _new_transaction_dialog(db)
    dialog.show()
    assert QTest.qWaitForWindowActive(dialog)
    return dialog, dialog.table.cellWidget(0, dialog.CATEGORY)


def test_entering_field_with_tab_selects_whole_text_and_typing_replaces_it(db, errors):
    dialog, combo = _focused_dialog(db)
    name = dialog.table.cellWidget(0, dialog.NAME)
    assert QApplication.focusWidget() is name
    QTest.keyClick(name, Qt.Key.Key_Tab)
    QApplication.processEvents()
    assert QApplication.focusWidget() is combo
    line = combo.lineEdit()
    assert line.selectedText() == "Bez kategorii"
    QTest.keyClick(line, Qt.Key.Key_D)
    assert line.text() == "d"
    dialog.close()


def test_entering_field_with_mouse_selects_whole_text(db, errors):
    dialog, combo = _focused_dialog(db)
    line = combo.lineEdit()
    QTest.mouseClick(line, Qt.MouseButton.LeftButton, pos=line.rect().center())
    QApplication.processEvents()
    assert QApplication.focusWidget() is combo
    assert line.selectedText() == "Bez kategorii"

    # Kolejne kliknięcie w tym samym polu ustawia już kursor, żeby można było poprawić tekst.
    QTest.mouseClick(line, Qt.MouseButton.LeftButton, pos=line.rect().center())
    QApplication.processEvents()
    assert line.selectedText() == ""
    dialog.close()


def test_selected_name_of_chosen_category_is_selected_on_return_to_field(db, errors):
    dialog, combo = _focused_dialog(db)
    combo.setCurrentIndex(combo.findText("Dom"))
    name = dialog.table.cellWidget(0, dialog.NAME)
    name.setFocus()
    QApplication.processEvents()
    combo.setFocus()
    QApplication.processEvents()
    assert combo.lineEdit().selectedText() == "Dom"
    dialog.close()


def test_returning_to_window_keeps_cursor_in_field(db, errors):
    dialog, combo = _focused_dialog(db)
    combo.setFocus()
    QApplication.processEvents()
    line = combo.lineEdit()
    line.setCursorPosition(2)
    assert line.selectedText() == ""
    QApplication.sendEvent(combo, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.ActiveWindowFocusReason))
    QApplication.processEvents()
    assert line.selectedText() == ""
    dialog.close()


def test_results_stay_inside_window_and_on_top(db, errors):
    dialog, combo = _category_dialog(db)
    QTest.keyClicks(combo.lineEdit(), "e")
    results = combo.results
    assert results.parent() is dialog
    assert dialog.rect().contains(results.geometry())
    assert results.height() >= results.sizeHintForRow(0)
    dialog.close()


def test_enter_picks_best_match_then_second_enter_adds_product(db, errors):
    dialog, combo = _category_dialog(db)
    line = combo.lineEdit()
    QTest.keyClicks(line, "wynag")
    QTest.keyClick(line, Qt.Key.Key_Return)
    assert combo.currentText() == "Wynagrodzenie"
    assert combo.currentData() is not None
    assert dialog.table.rowCount() == 1
    assert not combo.results.isVisible()

    QTest.keyClick(line, Qt.Key.Key_Return)
    assert dialog.table.rowCount() == 2
    assert dialog.result() != QDialog.DialogCode.Accepted
    dialog.close()


def test_arrows_choose_another_match_and_wrap(db, errors):
    dialog, combo = _category_dialog(db)
    line = combo.lineEdit()
    QTest.keyClicks(line, "r")
    names = combo.match_names()
    QTest.keyClick(line, Qt.Key.Key_Down)
    assert combo.results.currentItem().text() == names[1]
    assert line.text() == "r"  # strzałki też nie zmieniają tekstu
    QTest.keyClick(line, Qt.Key.Key_Up)
    QTest.keyClick(line, Qt.Key.Key_Up)
    assert combo.results.currentItem().text() == names[-1]
    QTest.keyClick(line, Qt.Key.Key_Return)
    assert combo.currentText() == names[-1]
    dialog.close()


def test_down_on_closed_field_lists_all_and_escape_closes_only_list(db, errors):
    dialog, combo = _category_dialog(db)
    line = combo.lineEdit()
    QTest.keyClick(line, Qt.Key.Key_Down)
    assert combo.results.isVisible() and len(combo.match_names()) == combo.count()
    QTest.keyClick(line, Qt.Key.Key_Escape)
    assert not combo.results.isVisible()
    assert dialog.isVisible()
    QTest.keyClick(line, Qt.Key.Key_Escape)
    assert not dialog.isVisible()


def test_clicking_a_result_chooses_it(db, errors):
    dialog, combo = _category_dialog(db)
    line = combo.lineEdit()
    QTest.keyClicks(line, "r")
    item = combo.results.item(1)
    name = item.text()
    QTest.mouseClick(
        combo.results.viewport(),
        Qt.MouseButton.LeftButton,
        pos=combo.results.visualItemRect(item).center(),
    )
    assert combo.currentText() == name
    assert not combo.results.isVisible()
    assert QApplication.focusWidget() is combo  # pole tekstowe przekazuje fokus listy
    dialog.close()


def test_shift_enter_with_open_list_saves_highlighted_category(db, errors):
    dialog, combo = _category_dialog(db)
    line = combo.lineEdit()
    QTest.keyClicks(line, "r")
    second = combo.match_names()[1]
    QTest.keyClick(line, Qt.Key.Key_Down)
    QTest.keyClick(line, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert _saved_category(db, dialog) == second


def test_saving_with_unconfirmed_text_uses_best_match(db, errors):
    dialog, combo = _category_dialog(db)
    QTest.keyClicks(combo.lineEdit(), "zdrowe")  # literówka
    QTest.keyClick(combo.lineEdit(), Qt.Key.Key_Escape)  # bez wyboru z listy
    assert combo.lineEdit().text() == "zdrowe"
    QTest.keyClick(combo.lineEdit(), Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert _saved_category(db, dialog) == "Zdrowie"


def test_unknown_text_blocks_saving_instead_of_guessing(db, errors):
    dialog, combo = _category_dialog(db)
    QTest.keyClicks(combo.lineEdit(), "qqqqqq")
    assert not combo.results.isVisible()
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert any("niepoprawna kategoria" in error for error in errors)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    dialog.close()


def test_leaving_field_shows_match_or_restores_previous(db, errors):
    dialog, combo = _category_dialog(db)
    combo.setCurrentIndex(combo.findText("Dom"))
    combo.setEditText("jedz")
    combo.resolve()
    assert (combo.currentText(), combo.currentIndex()) == ("Jedzenie", combo.findText("Jedzenie"))

    combo.setEditText("qqqqqq")
    combo.resolve()
    assert combo.currentText() == "Jedzenie"

    combo.setEditText("")
    combo.resolve()
    assert combo.currentText() == "Bez kategorii"
    assert combo.selected_category() is None
    dialog.close()


def test_category_list_is_still_complete_and_keeps_warning(db, errors):
    wallet = create_wallet(db, "A")
    dialog = TransactionDialog(db, get_wallet(db, wallet))
    combo = dialog.table.cellWidget(0, dialog.CATEGORY)
    assert combo.count() == 10  # bez kategorii i 9 domyślnych
    assert combo.palette().color(QPalette.ColorRole.Base) == common.warning_background()
    combo.setCurrentIndex(combo.findText("Dom"))
    assert combo.palette().color(QPalette.ColorRole.Base) != common.warning_background()


def test_fuzzy_category_works_in_edit_and_recurring_dialogs(db, errors):
    wallet = create_wallet(db, "A")
    transaction = add(db, wallet)
    edit = TransactionDialog(db, get_wallet(db, wallet), transaction)
    combo = edit.table.cellWidget(0, edit.CATEGORY)
    combo.setEditText("dom")
    edit.accept()
    assert get_transaction(db, transaction)["rows"][0]["category"] is not None

    template = RecurringDialog(db)
    assert template.table.cellWidget(0, template.CATEGORY).isEditable()


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
    assert not hasattr(dialog, "amount") and not hasattr(dialog, "category")
    dialog.accept()
    assert any("Podaj opis" in error for error in errors)
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog.description.setText("Czynsz")
    dialog.remaining.setText("3")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    saved = get_recurring(db, dialog.recurring_id)
    assert (saved["wallet_id"], saved["remaining"]) == (wallet, 3)
    assert saved["rows"] == []

    dialog = RecurringDialog(db, dialog.recurring_id)
    assert dialog.remaining.text() == "3"
    dialog.table.cellWidget(0, dialog.NAME).setText("Woda")
    dialog.table.cellWidget(0, dialog.PRICE).setText("70")
    dialog.accept()
    saved = get_recurring(db, dialog.recurring_id)
    assert [row["name"] for row in saved["rows"]] == ["Woda"]
    assert "amount_cents" not in saved and "category_id" not in saved


def test_pay_button_moves_recurring_to_transactions_and_counts_down(
    db, errors, monkeypatch
):
    wallet = create_wallet(db, "A", "PLN", "100")
    create_recurring(db, wallet, "expense", "Czynsz", remaining="2", rows=priced("Czynsz", "10"))
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
    create_recurring(db, wallet, "expense", "Czynsz", remaining="2", rows=priced("Czynsz", "10"))
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
