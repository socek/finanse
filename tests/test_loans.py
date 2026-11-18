import sqlite3

import pytest
from PySide6.QtWidgets import QDialog

from finanse import db as database
from finanse.db import connect, init_db
from finanse.errors import ValidationError
from finanse.gui import common
from finanse.gui.dialogs import TransactionDialog
from finanse.gui.loan_dialogs import (
    LinkLoanDialog,
    LinkTransactionDialog,
    LoanDialog,
    LoanItemDialog,
)
from finanse.gui.loans_tab import (
    I_BALANCE,
    I_WALLET,
    OUTSTANDING,
    PAY,
    PERSON,
    PRINCIPAL_AMOUNT,
    LoansTab,
)
from finanse.gui.main_window import MainWindow
from finanse.gui.wallets_tab import ENTRY_ROLE, WalletsTab
from finanse.history import history_text
from finanse.loans import (
    BORROWED,
    LENT,
    PRINCIPAL,
    REPAYMENT,
    add_loan_item,
    create_loan,
    delete_loan,
    delete_loan_item,
    get_loan,
    link_transaction,
    linkable_transactions,
    list_loans,
    loan_items,
    loan_of_transaction,
    loan_totals,
    repay_loan,
    transaction_summary,
    unlink_transaction,
    update_loan,
    update_loan_item,
)
from finanse.money import NBSP
from finanse.reports import build_report
from finanse.transactions import create_transaction, delete_transaction, update_transaction
from finanse.wallets import create_wallet, get_wallet


def entry_item(tab, transaction_id):
    """Wiersz transakcji na liście zakładki Portfele."""
    tab.tree.expandAll()
    for day_index in range(tab.tree.topLevelItemCount()):
        day = tab.tree.topLevelItem(day_index)
        for index in range(day.childCount()):
            item = day.child(index)
            if item.data(0, ENTRY_ROLE) == ("transaction", transaction_id):
                return item
    raise AssertionError(transaction_id)


def add(db, wallet, kind="expense", price="100", on="2026-11-05", name="Zakupy"):
    return create_transaction(
        db, wallet, kind, on, name,
        [{"name": name, "quantity": "1", "price": price, "category": None}],
    )  # fmt: skip


def money(text):
    """Kwota tak, jak ją formatuje aplikacja: z twardą spacją przed walutą."""
    return text.replace(" PLN", f"{NBSP}PLN")


@pytest.fixture
def errors(monkeypatch, qapp):
    collected = []
    monkeypatch.setattr(common, "show_errors", lambda _p, e: collected.extend(e))
    monkeypatch.setattr(common, "show_info", lambda _p, text: collected.append(text))
    monkeypatch.setattr(common, "confirm", lambda *_a, **_k: True)
    return collected


# Pozycje


def test_loan_is_made_of_items_lent_100_then_50(db):
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", None, "PLN")
    add_loan_item(db, loan_id, PRINCIPAL, "2026-11-10", "50")
    repay_loan(db, loan_id, "2026-11-20", "30", "gotówką")
    loan = get_loan(db, loan_id)
    assert (loan["principal_cents"], loan["repaid_cents"], loan["outstanding_cents"]) == (
        15000, 3000, 12000,
    )  # fmt: skip
    assert loan["item_count"] == 3
    items = loan_items(db, loan_id)
    assert [(i["occurred_on"], i["role"], i["amount_cents"], i["balance_cents"]) for i in items] == [
        ("2026-11-01", PRINCIPAL, 10000, 10000),
        ("2026-11-10", PRINCIPAL, 5000, 15000),
        ("2026-11-20", REPAYMENT, 3000, 12000),
    ]  # fmt: skip
    assert items[2]["description"] == "gotówką"
    assert all(item["wallet_name"] is None for item in items)


def test_items_in_wallet_are_transactions(db):
    wallet = create_wallet(db, "Konto", "PLN", "5000")
    loan_id = create_loan(db, LENT, "Jan", "na remont", "2026-11-01", "100", wallet)
    add_loan_item(db, loan_id, PRINCIPAL, "2026-11-10", "50", wallet_id=wallet)
    repay_loan(db, loan_id, "2026-11-18", "20", wallet_id=wallet)
    assert get_wallet(db, wallet)["balance_cents"] == 500000 - 15000 + 2000
    items = loan_items(db, loan_id)
    assert [(i["kind"], i["role"], i["wallet_name"]) for i in items] == [
        ("expense", PRINCIPAL, "Konto"),
        ("expense", PRINCIPAL, "Konto"),
        ("income", REPAYMENT, "Konto"),
    ]  # fmt: skip
    assert [i["description"] for i in items] == [
        "na remont", "Pożyczka dla Jan", "Spłata pożyczki – Jan",
    ]  # fmt: skip
    assert get_loan(db, loan_id)["outstanding_cents"] == 13000


def test_borrowed_loan_items_have_opposite_kinds(db):
    wallet = create_wallet(db, "Konto")
    loan_id = create_loan(db, BORROWED, "Bank", "", "2026-11-01", "500", wallet)
    add_loan_item(db, loan_id, PRINCIPAL, "2026-11-02", "100", wallet_id=wallet)
    repay_loan(db, loan_id, "2026-11-03", "600", wallet_id=wallet)
    assert [i["kind"] for i in loan_items(db, loan_id)] == ["income", "income", "expense"]
    assert get_wallet(db, wallet)["balance_cents"] == 0
    assert get_loan(db, loan_id)["outstanding_cents"] == 0


def test_repayment_cannot_exceed_what_is_left(db):
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", None, "PLN")
    with pytest.raises(ValidationError) as error:
        repay_loan(db, loan_id, "2026-11-02", "100,01")
    assert "większa niż pozostało" in error.value.errors[0]
    with pytest.raises(ValidationError):
        repay_loan(db, loan_id, "2026-11-02", "0")
    assert len(loan_items(db, loan_id)) == 1


def test_item_wallet_must_match_loan_currency(db):
    eur = create_wallet(db, "EUR", "EUR")
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", None, "PLN")
    with pytest.raises(ValidationError) as error:
        repay_loan(db, loan_id, "2026-11-02", "10", wallet_id=eur)
    assert "walucie pożyczki (PLN)" in error.value.errors[0]


def test_editing_own_item_checks_the_rest_of_the_loan(db):
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", None, "PLN")
    repay_loan(db, loan_id, "2026-11-02", "60")
    first, repayment = loan_items(db, loan_id)
    # Spłatę można zwiększyć do całości, bo jej obecna kwota się zwalnia.
    update_loan_item(db, repayment["id"], REPAYMENT, "2026-11-03", "100", "całość")
    assert get_loan(db, loan_id)["outstanding_cents"] == 0
    with pytest.raises(ValidationError):
        update_loan_item(db, repayment["id"], REPAYMENT, "2026-11-03", "100,01")
    update_loan_item(db, first["id"], PRINCIPAL, "2026-11-01", "150")
    assert get_loan(db, loan_id)["outstanding_cents"] == 5000


def test_items_with_transaction_are_edited_in_the_wallet(db):
    wallet = create_wallet(db, "Konto")
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", wallet)
    [item] = loan_items(db, loan_id)
    with pytest.raises(ValidationError) as error:
        update_loan_item(db, item["id"], PRINCIPAL, "2026-11-01", "5")
    assert "zakładce Portfele" in error.value.errors[0]
    update_transaction(db, item["transaction_id"], "expense", "2026-11-04", "Więcej",
                       [{"name": "x", "quantity": "1", "price": "120", "category": None}])  # fmt: skip
    [item] = loan_items(db, loan_id)
    assert (item["occurred_on"], item["description"], item["amount_cents"]) == (
        "2026-11-04", "Więcej", 12000,
    )  # fmt: skip


def test_deleting_items_and_loans_keeps_transactions(db):
    wallet = create_wallet(db, "Konto")
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", wallet)
    add_loan_item(db, loan_id, PRINCIPAL, "2026-11-02", "50")
    first, own = loan_items(db, loan_id)
    delete_loan_item(db, own["id"])
    delete_loan_item(db, first["id"])
    assert loan_items(db, loan_id) == []
    assert transaction_summary(db, first["transaction_id"])["total_cents"] == 10000

    repayment = add_loan_item(db, loan_id, PRINCIPAL, "2026-11-03", "40", wallet_id=wallet)
    transaction_id = loan_items(db, loan_id)[0]["transaction_id"]
    assert repayment
    delete_transaction(db, transaction_id)
    assert loan_items(db, loan_id) == []

    link_transaction(db, loan_id, first["transaction_id"])
    delete_loan(db, loan_id)
    assert get_loan(db, loan_id) is None
    assert loan_of_transaction(db, first["transaction_id"]) is None
    assert transaction_summary(db, first["transaction_id"]) is not None


def test_create_loan_validates_everything_at_once(db):
    with pytest.raises(ValidationError) as error:
        create_loan(db, "inny", " ", "", "zła data", "-5", None, "PLN")
    assert len(error.value.errors) == 4
    with pytest.raises(ValidationError):
        create_loan(db, LENT, "Jan", "", "2026-11-01", "10", None, "ZŁOTE")
    assert list_loans(db) == []


def test_update_loan_changes_only_its_own_fields(db):
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", None, "PLN")
    update_loan(db, loan_id, "Jan Nowak", "remont", "2026-10-01")
    loan = get_loan(db, loan_id)
    assert (loan["person"], loan["description"], loan["opened_on"]) == (
        "Jan Nowak", "remont", "2026-10-01",
    )  # fmt: skip
    assert loan["principal_cents"] == 10000


def test_linking_existing_transactions(db):
    wallet = create_wallet(db, "Konto")
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "1000", None, "PLN")
    returned = add(db, wallet, "income", "200", name="Przelew od Jana")
    other = add(db, wallet, "expense", "30")
    assert [row["id"] for row in linkable_transactions(db, loan_id)] == [other, returned]

    link_transaction(db, loan_id, returned)
    link_transaction(db, loan_id, returned)  # drugi raz niczego nie zmienia
    assert get_loan(db, loan_id)["outstanding_cents"] == 80000
    assert loan_of_transaction(db, returned)["id"] == loan_id
    assert [row["id"] for row in linkable_transactions(db, loan_id)] == [other]

    second = create_loan(db, BORROWED, "Ola", "", "2026-11-01", "10", None, "PLN")
    with pytest.raises(ValidationError) as error:
        link_transaction(db, second, returned)
    assert "już powiązana z pożyczką „Jan”" in error.value.errors[0]

    unlink_transaction(db, returned)
    assert get_loan(db, loan_id)["outstanding_cents"] == 100000
    assert loan_of_transaction(db, returned) is None


def test_linking_needs_the_same_currency(db):
    eur = create_wallet(db, "EUR", "EUR")
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "10", None, "PLN")
    with pytest.raises(ValidationError) as error:
        link_transaction(db, loan_id, add(db, eur))
    assert "w EUR, a pożyczka w PLN" in error.value.errors[0]


def test_list_shows_open_loans_first_and_totals_skip_settled(db):
    settled = create_loan(db, LENT, "Stary", "", "2026-11-10", "10", None, "PLN")
    repay_loan(db, settled, "2026-11-11", "10")
    lent = create_loan(db, LENT, "Jan", "", "2026-01-01", "100", None, "PLN")
    borrowed = create_loan(db, BORROWED, "Bank", "", "2026-02-01", "300", None, "EUR")
    loans = list_loans(db)
    assert [loan["id"] for loan in loans] == [borrowed, lent, settled]
    assert loan_totals(loans) == {LENT: {"PLN": 10000}, BORROWED: {"EUR": 30000}}


def test_loan_transactions_are_left_out_of_reports(db):
    wallet = create_wallet(db, "Konto", "PLN", "5000")
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "1000", wallet)
    repay_loan(db, loan_id, "2026-11-10", "200", wallet_id=wallet)
    repay_loan(db, loan_id, "2026-11-11", "100")  # poza portfelami
    add(db, wallet, "expense", "30")
    report = build_report(db, month="2026-11")
    assert (report["expense_total"], report["income_total"]) == (3000, 0)
    assert report["wallet_totals"][0]["net"] == -3000
    november = next(m for m in report["trend"]["months"] if m["key"] == "2026-11")
    assert (november["income"], november["expense"]) == (0, 3000)


def test_history_describes_loan_items(db):
    wallet = create_wallet(db, "Konto")
    loan_id = create_loan(db, LENT, "Jan", "remont", "2026-11-01", "100", wallet)
    add_loan_item(db, loan_id, PRINCIPAL, "2026-11-02", "50", "gotówka")
    text = history_text(db)
    assert "Dodano pożyczkę „Jan”" in text
    assert "Dodano pozycję pożyczki „Jan” (transakcja: „remont”)" in text
    assert (
        "Dodano pozycję pożyczki „Jan” (transakcja: poza portfelami, rola: pożyczenie,"
        " data: 2026-11-02, kwota: 50,00, opis: „gotówka”)"
    ) in text


def test_migration_turns_old_loans_into_items(tmp_path):
    path = tmp_path / "old.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = OFF")
    for number, sql in database._migrations():
        if number > 14:
            break
        connection.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};COMMIT;")
    connection.executescript(
        """
        INSERT INTO wallets (id, name) VALUES (1, 'Konto');
        INSERT INTO transactions (id, wallet_id, kind, occurred_on, description)
            VALUES (7, 1, 'income', '2026-11-05', 'Zwrot');
        INSERT INTO products (transaction_id, position, name, quantity_e5, unit_price_e5,
                              total_e5, total_cents)
            VALUES (7, 0, 'Zwrot', 100000, 3000000, 3000000, 3000);
        INSERT INTO loans (id, direction, person, currency, opened_on, initial_cents)
            VALUES (1, 'lent', 'Jan', 'PLN', '2026-11-01', 10000),
                   (2, 'borrowed', 'Bank', 'PLN', '2026-11-02', 0);
        INSERT INTO loan_transactions (loan_id, transaction_id) VALUES (1, 7);
        """
    )
    connection.close()
    init_db(str(path))
    db = connect(str(path))
    items = loan_items(db, 1)
    assert [(i["role"], i["amount_cents"], i["transaction_id"]) for i in items] == [
        (PRINCIPAL, 10000, None), (REPAYMENT, 3000, 7),
    ]  # fmt: skip
    assert get_loan(db, 1)["outstanding_cents"] == 7000
    assert loan_items(db, 2) == []
    assert "initial_cents" not in {row["name"] for row in db.execute("PRAGMA table_info(loans)")}
    db.close()


# Okna


def test_loan_dialog_creates_loan_in_wallet(db, errors):
    wallet = create_wallet(db, "Konto")
    dialog = LoanDialog(db, wallet_id=wallet)
    assert not dialog.currency.isEnabled()
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert any("osobę" in error for error in errors)

    dialog.person.setText("Jan")
    dialog.amount.setText("1000")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert get_loan(db, dialog.loan_id)["outstanding_cents"] == 100000
    assert get_wallet(db, wallet)["balance_cents"] == -100000


def test_loan_dialog_outside_wallets_uses_typed_currency(db, errors):
    create_wallet(db, "Konto")
    dialog = LoanDialog(db)
    dialog.direction.setCurrentIndex(dialog.direction.findData(BORROWED))
    dialog.wallet.setCurrentIndex(dialog.wallet.findData(None))
    assert dialog.currency.isEnabled()
    dialog.currency.setText("EUR")
    dialog.person.setText("Mama")
    dialog.amount.setText("250")
    dialog.accept()
    loan = get_loan(db, dialog.loan_id)
    assert (loan["direction"], loan["currency"], loan["principal_cents"]) == (
        BORROWED, "EUR", 25000,
    )  # fmt: skip


def test_edit_dialog_has_no_amount(db, errors):
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "10", None, "PLN")
    dialog = LoanDialog(db, loan_id)
    assert not dialog.direction.isEnabled()
    assert dialog.wallet is None
    dialog.person.setText("Janek")
    dialog.accept()
    assert get_loan(db, loan_id)["person"] == "Janek"


def test_repay_dialog_picks_part_of_the_amount(db, errors):
    wallet = create_wallet(db, "Konto")
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "1000", wallet)
    repay_loan(db, loan_id, "2026-11-02", "200")
    dialog = LoanItemDialog(db, loan_id)
    assert dialog.amount.text() == "800,00"
    assert dialog.slider.value() == 100
    assert dialog.after.text().endswith("(spłacona)")
    # Ostatnia pozycja była poza portfelami, więc nowa domyślnie też.
    assert dialog.wallet.currentData() is None

    dialog.set_share(25)
    assert dialog.amount.text() == "200,00"
    dialog.slider.setValue(50)
    assert dialog.amount.text() == "400,00"
    assert dialog.after.text() == money("400,00 PLN")
    dialog.amount.setText("80")
    dialog._amount_edited("80")
    assert dialog.slider.value() == 10

    dialog.amount.setText("900")
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "większa niż pozostało" in errors[0]

    dialog.set_share(100)
    dialog.wallet.setCurrentIndex(dialog.wallet.findData(wallet))
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert get_loan(db, loan_id)["outstanding_cents"] == 0
    assert loan_items(db, loan_id)[-1]["wallet_name"] == "Konto"


def test_lend_more_dialog_adds_principal(db, errors):
    loan_id = create_loan(db, BORROWED, "Bank", "", "2026-11-01", "100", None, "PLN")
    dialog = LoanItemDialog(db, loan_id, PRINCIPAL)
    assert dialog.slider is None and dialog.amount.text() == ""
    dialog.amount.setText("50")
    dialog._amount_edited("50")
    assert dialog.after.text() == money("150,00 PLN")
    dialog.accept()
    assert get_loan(db, loan_id)["principal_cents"] == 15000


def test_item_dialog_edits_own_item(db, errors):
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", None, "PLN")
    repay_loan(db, loan_id, "2026-11-02", "40")
    item = loan_items(db, loan_id)[-1]
    dialog = LoanItemDialog(db, loan_id, item_id=item["id"])
    assert dialog.wallet is None
    assert dialog.amount.text() == "40,00"
    assert dialog.slider.value() == 40
    dialog.set_share(100)
    dialog.accept()
    assert get_loan(db, loan_id)["outstanding_cents"] == 0
    assert len(loan_items(db, loan_id)) == 2


def test_loans_tab_lists_loans_and_items(db, errors, monkeypatch):
    wallet = create_wallet(db, "Konto")
    lent = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", wallet)
    create_loan(db, BORROWED, "Bank", "", "2026-10-01", "50", None, "PLN")
    tab = LoansTab(db)
    assert tab.table.rowCount() == 2
    summary = tab.summary.text()
    assert money("Do oddania tobie: 100,00 PLN") in summary
    assert money("Do oddania przez ciebie: 50,00 PLN") in summary
    assert tab.items.rowCount() == 0
    assert not tab.repay_button.isEnabled()

    tab.table.setCurrentCell(0, PERSON)
    assert tab.selected_id() == lent
    assert tab.items.rowCount() == 1

    def exec_lending_50(dialog):
        dialog.amount.setText("50")
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(LoanItemDialog, "exec", exec_lending_50)
    tab.lend_more()
    assert tab.table.item(0, PRINCIPAL_AMOUNT).text() == money("150,00 PLN")
    assert tab.items.rowCount() == 2
    assert tab.items.item(1, I_BALANCE).text() == money("150,00 PLN")
    assert tab.items.item(1, I_WALLET).text() == "Konto"

    def exec_paying_half(dialog):
        dialog.set_share(50)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(LoanItemDialog, "exec", exec_paying_half)
    tab.table.cellWidget(0, PAY).click()
    assert tab.table.item(0, OUTSTANDING).text() == money("75,00 PLN")
    assert tab.items.rowCount() == 3

    tab.table.selectAll()
    assert tab.selection_summary() == money("Zaznaczone: 2 · Pozostało: +25,00 PLN")


def test_loans_tab_edits_and_deletes_items(db, errors, monkeypatch):
    wallet = create_wallet(db, "Konto")
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", wallet)
    repay_loan(db, loan_id, "2026-11-02", "100")
    tab = LoansTab(db)
    assert tab.table.item(0, OUTSTANDING).text() == "spłacona"
    assert not tab.table.cellWidget(0, PAY).isEnabled()
    tab.hide_settled.setChecked(True)
    assert tab.table.rowCount() == 0
    assert tab.empty.text() == "Wszystkie pożyczki są spłacone."
    tab.hide_settled.setChecked(False)
    tab.table.setCurrentCell(0, PERSON)

    opened = []
    monkeypatch.setattr(TransactionDialog, "exec", lambda d: opened.append("transakcja") or 0)
    monkeypatch.setattr(LoanItemDialog, "exec", lambda d: opened.append("pozycja") or 0)
    tab.items.setCurrentCell(0, 0)
    tab.edit_item()
    tab.items.setCurrentCell(1, 0)
    tab.edit_item()
    assert opened == ["transakcja", "pozycja"]

    tab.items.selectAll()
    assert tab.delete_item_button.text() == "Usuń pozycje (2)"
    tab.delete_items()
    assert tab.items.rowCount() == 0
    assert get_wallet(db, wallet)["balance_cents"] == -10000

    tab.delete()
    assert list_loans(db) == []


def test_link_transaction_dialog_filters_and_links(db, errors):
    wallet = create_wallet(db, "Konto")
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "1000", None, "PLN")
    returned = add(db, wallet, "income", "200", name="Zwrot od Jana")
    add(db, wallet, "expense", "30", name="Chleb")
    dialog = LinkTransactionDialog(db, loan_id)
    assert dialog.table.rowCount() == 2
    dialog.search.setText("jana")
    dialog.table.selectAll()
    assert dialog.selected_ids() == [returned]
    dialog.accept()
    assert dialog.linked == 1
    assert get_loan(db, loan_id)["outstanding_cents"] == 80000


def test_wallets_tab_links_transaction_to_loan(db, errors, monkeypatch):
    wallet = create_wallet(db, "Konto")
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "1000", None, "PLN")
    returned = add(db, wallet, "income", "200", name="Zwrot")
    tab = WalletsTab(db)
    tab.tree.setCurrentItem(entry_item(tab, returned))
    assert tab.can_link_loan() and not tab.can_unlink_loan()

    def exec_linking(dialog):
        assert dialog.role.text() == "spłata pożyczki"
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(LinkLoanDialog, "exec", exec_linking)
    tab.link_to_loan()
    assert loan_of_transaction(db, returned)["id"] == loan_id
    item = entry_item(tab, returned)
    assert item.text(1).endswith("· pożyczka: Jan")

    tab.tree.setCurrentItem(item)
    assert tab.can_unlink_loan()
    tab.unlink_from_loan()
    assert loan_of_transaction(db, returned) is None


def test_wallets_tab_without_matching_loan_explains(db, errors):
    wallet = create_wallet(db, "Konto")
    returned = add(db, wallet, "income", "200")
    tab = WalletsTab(db)
    tab.tree.setCurrentItem(entry_item(tab, returned))
    tab.link_to_loan()
    assert "Nie ma pożyczek w PLN" in errors[0]


def test_main_window_loans_tab_and_pay_shortcut(db, errors, monkeypatch):
    loan_id = create_loan(db, LENT, "Jan", "", "2026-11-01", "100", None, "PLN")
    window = MainWindow(db)
    window.tabs.setCurrentWidget(window.loans)
    window.loans.table.setCurrentCell(0, PERSON)
    assert window._can_pay() and window._selected("edit")

    opened = []
    monkeypatch.setattr(LoanItemDialog, "exec", lambda d: opened.append(d.loan["id"]) or 0)
    window.commands["pay_selected"]()
    assert opened == [loan_id]
    window.commands["tab_6"]()
    assert window.tabs.currentWidget() is window.loans
