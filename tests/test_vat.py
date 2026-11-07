import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from finanse.db import connect, init_db
from finanse.errors import ValidationError
from finanse.gui import common
from finanse.gui.dialogs import PaymentDialog, RecurringDialog, TransactionDialog, WalletDialog
from finanse.gui.products_tab import ProductsTab
from finanse.gui.reports_tab import ReportsTab
from finanse.gui.wallets_tab import WalletsTab
from finanse.history import history_text
from finanse.money import gross_from_net, net_from_gross, vat_from_gross
from finanse.recurring import create_recurring, get_recurring, payment_draft, pay_recurring
from finanse.reports import build_report
from finanse.transactions import create_transaction, get_transaction, update_transaction
from finanse.wallets import VAT, create_wallet, get_wallet, list_wallets, update_wallet


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    return collected


def product(price="123", rate=23, name="Towar", quantity="1", total=""):
    return {"name": name, "category": None, "quantity": quantity, "price": price,
            "total": total, "vat_rate": rate}  # fmt: skip


def add(db, wallet, *products, kind="expense", on="2026-10-05"):
    return create_transaction(db, wallet, kind, on, "Faktura", list(products) or [product()])


def plain(text):
    return text.replace("\xa0", " ")


def test_vat_calculations():
    assert net_from_gross(12300, 23) == 10000
    assert gross_from_net(10000, 23) == 12300
    assert net_from_gross(10000, None) == 10000
    assert gross_from_net(10000, None) == 10000
    assert net_from_gross(10000, 0) == 10000
    assert vat_from_gross(10000, 23) == 1870  # 81,30 netto, jak w fakturze za telefon
    assert vat_from_gross(184500, 23) == 34500
    assert vat_from_gross(10000, None) == 0
    assert vat_from_gross(10000, 0) == 0


@pytest.mark.parametrize("gross", [1, 99, 100, 101, 999, 12345, 184500])
@pytest.mark.parametrize("rate", [23, 8, 5, 0, None])
def test_net_and_vat_always_add_up_to_gross(gross, rate):
    assert net_from_gross(gross, rate) + vat_from_gross(gross, rate) == gross


def test_wallet_type_is_saved_and_kept_by_default(db):
    plain_wallet = create_wallet(db, "A")
    vat_wallet = create_wallet(db, "B", "PLN", "0", VAT)
    assert get_wallet(db, plain_wallet)["wallet_type"] == "plain"
    assert get_wallet(db, vat_wallet)["wallet_type"] == "vat"
    update_wallet(db, vat_wallet, "B2", "PLN", "0")
    assert get_wallet(db, vat_wallet)["wallet_type"] == "vat"
    update_wallet(db, vat_wallet, "B2", "PLN", "0", "plain")
    assert get_wallet(db, vat_wallet)["wallet_type"] == "plain"
    with pytest.raises(ValidationError, match="typ portfela"):
        create_wallet(db, "C", "PLN", "0", "inny")


def test_wallet_dialog_sets_type(db, errors):
    dialog = WalletDialog(db)
    assert dialog.wallet_type.currentData() == "plain"
    dialog.name.setText("Firma")
    dialog.wallet_type.setCurrentIndex(dialog.wallet_type.findData(VAT))
    dialog.accept()
    assert get_wallet(db, dialog.wallet_id)["wallet_type"] == "vat"
    edit = WalletDialog(db, get_wallet(db, dialog.wallet_id))
    assert edit.wallet_type.currentData() == "vat"


def test_vat_is_stored_and_balance_uses_gross(db):
    wallet = create_wallet(db, "F", "PLN", "1000", VAT)
    transaction = add(db, wallet, product("123", 23), product("100", None, "Zwolniony"))
    rows = db.execute(
        "SELECT total_cents, vat_rate, vat_cents FROM products ORDER BY position"
    ).fetchall()
    assert [tuple(row) for row in rows] == [(12300, 23, 2300), (10000, None, 0)]
    assert get_wallet(db, wallet)["balance_cents"] == 100000 - 22300
    saved = get_transaction(db, transaction)["rows"]
    assert (saved[0]["vat_rate"], saved[1]["vat_rate"]) == (23, None)

    # Ponowny zapis zachowuje stawki, a zmiana stawki przelicza VAT.
    update_transaction(db, transaction, "expense", "2026-10-05", "Faktura", saved)
    assert db.execute("SELECT vat_cents FROM products ORDER BY position").fetchone()[0] == 2300
    saved[0]["vat_rate"] = 8
    update_transaction(db, transaction, "expense", "2026-10-05", "Faktura", saved)
    assert db.execute("SELECT vat_cents FROM products ORDER BY position").fetchone()[0] == 911


def test_plain_wallet_ignores_vat_and_bad_rate_is_rejected(db):
    plain_wallet = create_wallet(db, "A")
    add(db, plain_wallet, product("123", 23))
    row = db.execute("SELECT vat_rate, vat_cents FROM products").fetchone()
    assert tuple(row) == (None, 0)
    vat_wallet = create_wallet(db, "F", "PLN", "0", VAT)
    with pytest.raises(ValidationError, match="niepoprawna stawka VAT"):
        add(db, vat_wallet, product("1", 7))


def test_recurring_keeps_vat_for_payment(db):
    wallet = create_wallet(db, "F", "PLN", "0", VAT)
    recurring = create_recurring(db, wallet, "expense", "Biuro", rows=[product("1845", 23, "Biuro")])
    stored = db.execute("SELECT vat_rate, vat_cents FROM recurring_products").fetchone()
    assert tuple(stored) == (23, 34500)
    assert get_recurring(db, recurring)["rows"][0]["vat_rate"] == 23
    draft = payment_draft(db, recurring)
    pay_recurring(db, recurring, "expense", "2026-10-05", "Biuro", draft["rows"])
    assert db.execute("SELECT vat_cents FROM products").fetchone()[0] == 34500


def test_report_sums_vat_by_rate(db):
    wallet = create_wallet(db, "F", "PLN", "0", VAT)
    add(db, wallet, product("12300", 23), kind="income")
    add(db, wallet, product("1230", 23), product("108", 8), product("50", None, "Zus"))
    add(db, wallet, product("123", 23), on="2026-11-01")  # inny miesiąc
    report = build_report(db, month="2026-10")
    vat = report["vat"]
    assert [row["label"] for row in vat["by_rate"]] == ["23%", "8%", "zw."]
    first = vat["by_rate"][0]
    assert (first["sales_net"], first["sales_vat"]) == (1000000, 230000)
    assert (first["purchases_net"], first["purchases_vat"]) == (100000, 23000)
    assert vat["by_rate"][1]["purchases_vat"] == 800
    assert vat["by_rate"][2]["purchases_net"] == 5000
    assert vat["sales_vat"] == 230000 and vat["purchases_vat"] == 23800
    assert vat["balance"] == 206200


def test_report_uses_only_selected_vat_wallets(db):
    firm = create_wallet(db, "F", "PLN", "0", VAT)
    other = create_wallet(db, "G", "PLN", "0", VAT)
    private = create_wallet(db, "P")
    add(db, firm, product("123", 23))
    add(db, other, product("246", 23))
    add(db, private, product("999", None))
    assert build_report(db, "PLN", {firm}, "2026-10")["vat"]["purchases_vat"] == 2300
    assert build_report(db, "PLN", {firm, other}, "2026-10")["vat"]["purchases_vat"] == 6900
    assert build_report(db, "PLN", {firm, private}, "2026-10")["vat"]["purchases_net"] == 10000
    assert build_report(db, "PLN", {private}, "2026-10")["vat"] is None


def test_reports_tab_shows_vat_section_only_for_vat_wallet(db, errors):
    firm = create_wallet(db, "F", "PLN", "0", VAT)
    create_wallet(db, "P")
    add(db, firm, product("12300", 23), kind="income")
    add(db, firm, product("123", 23))
    tab = ReportsTab(db)
    tab.show_month("2026-10")
    assert not tab.vat_table.isHidden()
    assert tab.vat_table.item(0, 0).text() == "23%"
    assert tab.vat_table.item(1, 0).text() == "Razem"
    assert plain(tab.vat_table.item(1, 2).text()) == "2 300,00 PLN"
    assert plain(tab.vat_balance.text()) == "VAT do zapłaty: 2 277,00 PLN"

    tab.wallet_list.findItems("F", Qt.MatchFlag.MatchExactly)[0].setCheckState(Qt.CheckState.Unchecked)
    assert tab.vat_table.isHidden() and tab.vat_balance.isHidden()


def test_report_shows_excess_when_more_vat_was_paid(db, errors):
    firm = create_wallet(db, "F", "PLN", "0", VAT)
    add(db, firm, product("123", 23))
    tab = ReportsTab(db)
    tab.show_month("2026-10")
    assert plain(tab.vat_balance.text()) == "Nadwyżka VAT naliczonego: 23,00 PLN"


def _vat_dialog(db):
    wallet = create_wallet(db, "F", "PLN", "0", VAT)
    dialog = TransactionDialog(db, get_wallet(db, wallet))
    dialog.description.setText("Faktura")
    dialog.table.cellWidget(0, dialog.NAME).setText("Towar")
    return dialog


def _cells(dialog, row=0):
    return tuple(
        dialog.table.cellWidget(row, getattr(dialog, name))
        for name in ("QUANTITY", "VAT_RATE", "NET_PRICE", "PRICE", "NET_VALUE", "VALUE")
    )


def test_form_has_vat_columns_only_in_vat_wallet(db, errors):
    plain_wallet = create_wallet(db, "A")
    vat_wallet = create_wallet(db, "F", "PLN", "0", VAT)
    dialog = TransactionDialog(db, get_wallet(db, plain_wallet))
    columns = (dialog.VAT_RATE, dialog.NET_PRICE, dialog.NET_VALUE)
    assert all(dialog.table.isColumnHidden(c) for c in columns)
    assert dialog.table.horizontalHeaderItem(dialog.PRICE).text() == "Cena"

    dialog.wallet_combo.setCurrentIndex(dialog.wallet_combo.findData(vat_wallet))
    assert not any(dialog.table.isColumnHidden(c) for c in columns)
    assert dialog.table.horizontalHeaderItem(dialog.PRICE).text() == "Cena brutto"
    assert dialog.table.horizontalHeaderItem(dialog.VALUE).text() == "Wartość brutto"
    assert dialog.width() >= 1060  # nazwa produktu nadal ma miejsce
    dialog.wallet_combo.setCurrentIndex(dialog.wallet_combo.findData(plain_wallet))
    assert all(dialog.table.isColumnHidden(c) for c in columns)


def test_entering_gross_price_calculates_net(db, errors):
    dialog = _vat_dialog(db)
    quantity, rate, net_price, price, net_value, value = _cells(dialog)
    assert rate.currentData() == 23
    price.setText("123")
    assert net_price.text() == "100,00"
    assert value.text() == "123,00"
    assert net_value.text() == "100,00"
    quantity.setText("2")
    assert value.text() == "246,00"
    assert net_value.text() == "200,00"
    assert net_price.text() == "100,00"


def test_entering_net_price_calculates_gross_and_keeps_typed_text(db, errors):
    dialog = _vat_dialog(db)
    quantity, rate, net_price, price, net_value, value = _cells(dialog)
    quantity.setText("2")
    net_price.setText("100")
    assert net_price.text() == "100"  # pole, które wpisujesz, nie jest nadpisywane
    assert price.text() == "123,00"
    assert value.text() == "246,00"
    assert net_value.text() == "200,00"
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    row = db.execute("SELECT total_cents, vat_rate, vat_cents FROM products").fetchone()
    assert tuple(row) == (24600, 23, 4600)


def test_entering_net_value_calculates_gross_and_price(db, errors):
    dialog = _vat_dialog(db)
    quantity, rate, net_price, price, net_value, value = _cells(dialog)
    quantity.setText("4")
    net_value.setText("1000")
    assert value.text() == "1230,00"
    assert price.text() == "307,50"
    assert net_price.text() == "250,00"
    assert net_value.text() == "1000"
    assert "1 230,00" in plain(dialog.total.text())


def test_entering_gross_value_calculates_net_value(db, errors):
    dialog = _vat_dialog(db)
    quantity, rate, net_price, price, net_value, value = _cells(dialog)
    quantity.setText("2")
    value.setText("246")
    assert price.text() == "123,00"
    assert net_value.text() == "200,00"
    assert net_price.text() == "100,00"


def test_changing_rate_keeps_gross_after_gross_entry(db, errors):
    dialog = _vat_dialog(db)
    quantity, rate, net_price, price, net_value, value = _cells(dialog)
    price.setText("108")
    rate.setCurrentIndex(rate.findData(8))
    assert price.text() == "108"
    assert net_price.text() == "100,00"
    rate.setCurrentIndex(rate.findData(None))
    assert net_price.text() == "108,00"


def test_changing_rate_keeps_net_after_net_entry(db, errors):
    dialog = _vat_dialog(db)
    quantity, rate, net_price, price, net_value, value = _cells(dialog)
    net_price.setText("100")
    assert price.text() == "123,00"
    rate.setCurrentIndex(rate.findData(8))
    assert price.text() == "108,00"
    assert net_price.text() == "100"

    # Po wpisaniu brutto znów liczy się brutto.
    price.setText("200")
    rate.setCurrentIndex(rate.findData(23))
    assert price.text() == "200"


def test_changing_rate_keeps_net_value_after_net_value_entry(db, errors):
    dialog = _vat_dialog(db)
    quantity, rate, net_price, price, net_value, value = _cells(dialog)
    quantity.setText("3")
    net_value.setText("100")
    rate.setCurrentIndex(rate.findData(8))
    assert value.text() == "108,00"
    assert net_value.text() == "100"


def test_invalid_net_changes_nothing_and_minus_is_removed(db, errors):
    from PySide6.QtTest import QTest

    dialog = _vat_dialog(db)
    quantity, rate, net_price, price, net_value, value = _cells(dialog)
    price.setText("123")
    net_price.setText("abc")
    assert price.text() == "123"
    net_value.clear()
    QTest.keyClicks(net_value, "-100")
    assert net_value.text() == "100"
    assert value.text() == "123,00"


def test_saved_rate_and_nets_are_loaded_for_edit(db, errors):
    wallet = create_wallet(db, "F", "PLN", "0", VAT)
    transaction = add(db, wallet, product("108", 8), product("50", None, "Zus"))
    dialog = TransactionDialog(db, get_wallet(db, wallet), transaction)
    _quantity, rate, net_price, _price, net_value, _value = _cells(dialog)
    assert rate.currentData() == 8
    assert (net_price.text(), net_value.text()) == ("100,00", "100,00")
    second = _cells(dialog, 1)
    assert second[1].currentData() is None
    assert second[2].text() == "50,00"
    dialog.accept()
    assert get_transaction(db, transaction)["rows"][0]["vat_rate"] == 8


def test_payment_and_recurring_dialogs_support_vat(db, errors):
    wallet = create_wallet(db, "F", "PLN", "0", VAT)
    recurring = create_recurring(db, wallet, "expense", "Biuro", rows=[product("123", 8, "Biuro")])
    payment = PaymentDialog(db, get_wallet(db, wallet), recurring)
    assert not payment.table.isColumnHidden(payment.VAT_RATE)
    assert _cells(payment)[1].currentData() == 8

    template = RecurringDialog(db, recurring)
    assert not template.table.isColumnHidden(template.NET_PRICE)
    assert _cells(template)[1].currentData() == 8


def test_lists_show_net_and_vat_only_with_vat_wallet(db, errors):
    firm = create_wallet(db, "F", "PLN", "0", VAT)
    private = create_wallet(db, "P")
    add(db, firm, product("123", 23))
    add(db, private, product("10", None, "Prywatne"))
    wallets = WalletsTab(db)
    tree = wallets.tree
    net, vat = 7, 8
    assert tree.headerItem().text(net) == "Netto" and tree.headerItem().text(vat) == "VAT"
    assert not tree.isColumnHidden(net)
    rows = {tree.topLevelItem(0).child(i).text(2): tree.topLevelItem(0).child(i) for i in range(2)}
    assert plain(rows["F"].text(net)) == "100,00 PLN"
    assert plain(rows["F"].text(vat)) == "23,00 PLN"
    assert rows["P"].text(net) == ""  # portfel bez VAT
    # Na ekranie netto i VAT są przed kwotą.
    header = tree.header()
    assert header.visualIndex(net) < header.visualIndex(vat) < header.visualIndex(4)

    item = wallets.wallet_list.findItems("F\n", Qt.MatchFlag.MatchStartsWith)[0]
    item.setCheckState(Qt.CheckState.Unchecked)
    assert tree.isColumnHidden(net) and tree.isColumnHidden(vat)


def test_products_list_shows_rate_net_and_vat(db, errors):
    firm = create_wallet(db, "F", "PLN", "0", VAT)
    add(db, firm, product("123", 23), product("50", None, "Zus"))
    tab = ProductsTab(db)
    tree = tab.tree
    rows = {tree.topLevelItem(0).child(i).text(1): tree.topLevelItem(0).child(i) for i in range(2)}
    assert rows["Towar"].text(10) == "23%"
    assert plain(rows["Towar"].text(11)) == "100,00"
    assert plain(rows["Towar"].text(12)) == "23,00"
    assert rows["Zus"].text(10) == "zw."
    assert plain(rows["Zus"].text(12)) == "0,00"
    assert plain(tree.topLevelItem(0).text(9)) == "−173,00 PLN"  # suma dnia zostaje brutto


def test_plain_wallet_lists_hide_vat_columns(db, errors):
    wallet = create_wallet(db, "A")
    add(db, wallet, product("10", None))
    assert WalletsTab(db).tree.isColumnHidden(7)
    tab = ProductsTab(db)
    assert all(tab.tree.isColumnHidden(c) for c in (10, 11, 12))


def test_switching_wallet_to_vat_treats_old_products_as_exempt(db, errors):
    wallet = create_wallet(db, "A", "PLN", "100")
    add(db, wallet, product("10", None))
    update_wallet(db, wallet, "A", "PLN", "100", VAT)
    assert get_wallet(db, wallet)["balance_cents"] == 9000
    assert build_report(db, month="2026-10")["vat"]["by_rate"][0]["label"] == "zw."


def test_history_mentions_vat_only_where_it_applies(db):
    firm = create_wallet(db, "F", "PLN", "0", VAT)
    private = create_wallet(db, "P")
    add(db, firm, product("123", 23, "Towar"))
    add(db, private, product("10", None, "Prywatne"))
    text = plain(history_text(db))
    firm_line = next(line for line in text.splitlines() if "„Towar”" in line)
    assert "VAT: 23%" in firm_line and "kwota VAT: 23,00" in firm_line
    private_line = next(line for line in text.splitlines() if "„Prywatne”" in line)
    assert "VAT" not in private_line
    assert "typ: z VAT" in next(line for line in text.splitlines() if "portfel „F”" in line)
    assert "typ" not in next(line for line in text.splitlines() if "portfel „P”" in line)


def test_vat_migration_keeps_data_and_logs_new_columns(tmp_path):
    import sqlite3
    from importlib import resources

    path = str(tmp_path / "old.db")
    connection = sqlite3.connect(path)
    names = sorted(
        file.name
        for file in resources.files("finanse").joinpath("migrations").iterdir()
        if file.name.endswith(".sql") and int(file.name[:3]) <= 7
    )
    for name in names:
        connection.executescript(
            resources.files("finanse").joinpath(f"migrations/{name}").read_text("utf-8")
        )
    connection.executescript(
        """
        INSERT INTO wallets (id, name) VALUES (1, 'A');
        INSERT INTO transactions (id, wallet_id, kind, occurred_on, description)
            VALUES (1, 1, 'expense', '2026-10-05', 'Zakupy');
        INSERT INTO products (id, transaction_id, position, name, quantity_e5,
                              unit_price_e5, total_e5, total_cents)
            VALUES (1, 1, 0, 'Chleb', 100000, 500000, 500000, 500);
        PRAGMA user_version = 7;
        """
    )
    connection.commit()
    connection.close()
    init_db(path)
    db = connect(path)
    assert list_wallets(db)[0]["wallet_type"] == "plain"
    assert tuple(db.execute("SELECT vat_rate, vat_cents, total_cents FROM products").fetchone()) == (None, 0, 500)
    update_wallet(db, 1, "A", "PLN", "0", VAT)
    assert '"wallet_type":"vat"' in db.execute(
        "SELECT new_values FROM change_log ORDER BY id DESC LIMIT 1"
    ).fetchone()[0].replace(" ", "")
    db.close()
