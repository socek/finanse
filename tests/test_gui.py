import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QDialog
from test_csv_import import BANK_CSV

from finanse.gui import common
from finanse.gui.categories_tab import CategoriesTab
from finanse.gui.dialogs import TransactionDialog, TransferDialog, WalletDialog
from finanse.gui.import_dialog import ImportDialog
from finanse.gui.main_window import MainWindow
from finanse.gui.reports_tab import ReportsTab
from finanse.gui.wallets_tab import WalletsTab
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
    assert tab.tree.topLevelItem(0).text(2) == "Przelew"
    assert "→ B" in tab.tree.topLevelItem(0).text(1)
    assert tab.tree.topLevelItem(1).child(0).text(1) == "Chleb"

    tab.date_from.setDate(QDate(2026, 10, 15))
    tab.use_from.setChecked(True)
    assert tab.tree.topLevelItemCount() == 1
    assert not tab.summary.isHidden()

    tab.date_to.setDate(QDate(2026, 10, 16))
    tab.use_to.setChecked(True)
    assert tab.tree.topLevelItemCount() == 0
    assert "Brak operacji" in tab.empty.text()


def test_wallets_tab_delete_entry_and_wallet(db, errors):
    wallet = create_wallet(db, "A")
    other = create_wallet(db, "B")
    transfer = create_transfer(db, wallet, other, "2026-11-01", "", "1")
    add(db, wallet, on="2026-10-01")
    tab = WalletsTab(db)

    tab.delete_wallet()
    assert "ma przelewy" in errors[0]
    assert len(list_wallets(db)) == 2

    tab.tree.setCurrentItem(tab.tree.topLevelItem(1).child(0))
    assert tab.selected_entry()[0] == "transaction"
    tab.delete_entry()
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0

    tab.tree.setCurrentItem(tab.tree.topLevelItem(0))
    assert tab.selected_entry() == ("transfer", transfer)
    tab.delete_entry()
    tab.delete_wallet()
    assert len(list_wallets(db)) == 1
    assert tab.wallet_list.count() == 1


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
    assert tab.tree.topLevelItemCount() == 4

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


def test_main_window_refreshes_tab_on_switch(db, errors):
    window = MainWindow(db)
    assert window.tabs.count() == 3
    create_wallet(db, "Nowy")
    window.tabs.setCurrentWidget(window.reports)
    assert window.reports.report is not None
    window.tabs.setCurrentWidget(window.wallets)
    assert window.wallets.wallet_list.count() == 1
