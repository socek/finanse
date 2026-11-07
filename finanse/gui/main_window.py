"""Okno główne: pasek menu, pięć zakładek z danymi i rzadziej używane strony w oknach."""

from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QMainWindow,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from ..recurring import count_due
from ..settings import load_settings
from ..storage import database_path
from . import common, shortcuts, title_bar
from .about_tab import AboutTab
from .categories_tab import CategoriesTab
from .files_tab import FilesTab
from .history_tab import HistoryTab
from .products_tab import ProductsTab
from .recurring_tab import PAY, RecurringTab
from .reports_tab import ReportsTab
from .settings_tab import SettingsTab
from .themes import current_theme, theme_choices
from .wallets_tab import WalletsTab


class PageDialog(QDialog):
    """Strona w osobnym oknie, np. Historia; przy każdym otwarciu czyta dane od nowa."""

    def __init__(self, page, title, size, parent=None):
        super().__init__(parent)
        self.page = page
        self.setWindowTitle(title)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Zamknij")
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(page, 1)
        layout.addWidget(buttons)
        self.resize(*size)

    def open_page(self):
        self.page.refresh()
        self.show()
        self.raise_()
        self.activateWindow()


class ShortcutsDialog(QDialog):
    """Lista skrótów do odczytu; zmienia się je w ustawieniach."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Skróty klawiszowe")
        self.table = QTableWidget(len(shortcuts.ACTIONS), 2)
        self.table.setHorizontalHeaderLabels(["Działanie", "Skrót"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        for row, action in enumerate(shortcuts.ACTIONS):
            text = shortcuts.sequence_text(action.key)
            self.table.setItem(row, 0, QTableWidgetItem(action.label))
            self.table.setItem(row, 1, QTableWidgetItem(shortcuts.display_text(text) or "–"))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Zamknij")
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(common.plain_label("Skróty zmienisz w oknie ustawień."))
        layout.addWidget(self.table, 1)
        layout.addWidget(buttons)
        self.resize(560, 640)


class MainWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.setWindowTitle("Finanse")
        self.resize(1120, 760)
        shortcuts.load(load_settings(database_path(db)).get("shortcuts"))

        self.wallets = WalletsTab(db)
        self.products = ProductsTab(db)
        self.recurring = RecurringTab(db)
        self.reports = ReportsTab(db)
        self.categories = CategoriesTab(db)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.wallets, "Portfele")
        self.tabs.addTab(self.products, "Produkty")
        self.tabs.addTab(self.recurring, "Cykliczne")
        self.tabs.addTab(self.reports, "Raporty")
        self.tabs.addTab(self.categories, "Kategorie i tagi")
        # Każda zakładka czyta z bazy przy wejściu, więc widzi zmiany z pozostałych.
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().refresh())
        # Liczba zaległych płatności w nazwie zakładki; data mogła się zmienić od startu.
        self.recurring.due_count_changed.connect(self.show_due_count)
        self.tabs.currentChanged.connect(lambda _: self.show_due_count(count_due(db)))
        self.show_due_count(count_due(db))
        self.setCentralWidget(self.tabs)

        # Rzadziej używane strony mają własne okna, otwierane z menu.
        self.history = HistoryTab(db)
        self.files = FilesTab(db)
        self.settings = SettingsTab(db, self.refresh_all_tabs)
        self.about = AboutTab()
        self.history_dialog = PageDialog(self.history, "Historia zmian danych", (900, 640), self)
        self.files_dialog = PageDialog(self.files, "Kopie i pliki danych", (760, 520), self)
        self.settings_dialog = PageDialog(self.settings, "Ustawienia", (720, 680), self)
        self.about_dialog = PageDialog(self.about, "O programie", (720, 640), self)

        self.commands = {
            "new_transaction": self.new_transaction,
            "new_transfer": lambda: self._after(self.wallets.create_transfer),
            "new_wallet": lambda: self._after(self.wallets.create_wallet),
            "new_recurring": lambda: self._after(self.recurring.create),
            "import_csv": lambda: self._wallet_action(self.wallets.import_csv),
            "edit_wallet": lambda: self._wallet_action(self.wallets.edit_wallet),
            "delete_wallet": lambda: self._wallet_action(self.wallets.delete_wallet),
            "edit_selected": lambda: self._on_current_tab("edit_selected"),
            "duplicate_selected": lambda: self._on_current_tab("duplicate_selected"),
            "pay_selected": lambda: self._on_current_tab("pay_selected"),
            "search": lambda: self._on_current_tab("focus_search"),
            "clear_filters": lambda: self._on_current_tab("clear_filters"),
            "expand_all": lambda: self._on_current_tab("expand_all"),
            "collapse_all": lambda: self._on_current_tab("collapse_all"),
            "check_all": lambda: self._on_current_tab("check_all"),
            "uncheck_all": lambda: self._on_current_tab("uncheck_all"),
            "previous_month": lambda: self._on_current_tab("previous_month"),
            "next_month": lambda: self._on_current_tab("next_month"),
            "refresh": lambda: self.tabs.currentWidget().refresh(),
            "open_settings": self.settings_dialog.open_page,
            "quit": self.close,
        }
        for index in range(self.tabs.count()):
            self.commands[f"tab_{index + 1}"] = lambda _=False, i=index: self.tabs.setCurrentIndex(i)
        self.action_shortcuts = {
            key: shortcuts.bind(key, self, callback) for key, callback in self.commands.items()
        }
        self.new_transaction_shortcut = self.action_shortcuts["new_transaction"]
        self._build_menus()

    # Menu

    def _item(self, menu, label, callback, key=None, enabled=None):
        """Pozycja menu. Skrót obsługuje QShortcut okna, a menu tylko go pokazuje."""
        action = menu.addAction(label)
        action.triggered.connect(lambda _=False: callback())
        self.menu_items.append((action, label, key, enabled))
        return action

    def _build_menus(self):
        self.menu_items = []
        bar = self.menuBar()
        act = self.commands

        file_menu = bar.addMenu("&Plik")
        self._item(file_menu, "Nowa transakcja…", act["new_transaction"], "new_transaction")
        self._item(file_menu, "Nowy przelew…", act["new_transfer"], "new_transfer")
        self._item(file_menu, "Nowa transakcja cykliczna…", act["new_recurring"], "new_recurring")
        self._item(file_menu, "Nowy portfel…", act["new_wallet"], "new_wallet")
        file_menu.addSeparator()
        self._item(file_menu, "Import CSV do portfela…", act["import_csv"], "import_csv",
                   self._has_wallet)  # fmt: skip
        file_menu.addSeparator()
        self._item(file_menu, "Kopie i pliki danych…", self.files_dialog.open_page)
        file_menu.addSeparator()
        self._item(file_menu, "Zakończ", act["quit"], "quit")

        edit_menu = bar.addMenu("&Edycja")
        self._item(edit_menu, "Edytuj zaznaczone", act["edit_selected"], "edit_selected",
                   lambda: self._selected("edit"))  # fmt: skip
        self._item(edit_menu, "Duplikuj transakcję", act["duplicate_selected"],
                   "duplicate_selected", lambda: self._selected("duplicate"))  # fmt: skip
        self._item(edit_menu, "Usuń zaznaczone", self.delete_selected, "delete_selected",
                   lambda: self._selected("delete"))  # fmt: skip
        edit_menu.addSeparator()
        self._item(edit_menu, "Szukaj", act["search"], "search",
                   lambda: self._current_has("focus_search"))  # fmt: skip
        self._item(edit_menu, "Wyczyść filtry", act["clear_filters"], "clear_filters",
                   lambda: self._current_has("clear_filters"))  # fmt: skip
        edit_menu.addSeparator()
        self._item(edit_menu, "Ustawienia…", act["open_settings"], "open_settings")

        view_menu = bar.addMenu("&Widok")
        for index in range(self.tabs.count()):
            action = self._item(view_menu, self.tabs.tabText(index).split(" (")[0],
                                act[f"tab_{index + 1}"], f"tab_{index + 1}")  # fmt: skip
            action.setCheckable(True)
        self.view_actions = [item[0] for item in self.menu_items[-self.tabs.count():]]
        self.view_group = QActionGroup(self)
        for action in self.view_actions:
            self.view_group.addAction(action)
        view_menu.addSeparator()
        for label, key, method in (
            ("Rozwiń wszystko", "expand_all", "expand_all"),
            ("Zwiń wszystko", "collapse_all", "collapse_all"),
            ("Zaznacz wszystkie portfele", "check_all", "check_all"),
            ("Odznacz wszystkie portfele", "uncheck_all", "uncheck_all"),
        ):
            self._item(view_menu, label, act[key], key, lambda m=method: self._current_has(m))
        view_menu.addSeparator()
        theme_menu = view_menu.addMenu("Motyw")
        self.theme_group = QActionGroup(self)
        self.theme_actions = {}
        for key, name in theme_choices():
            action = theme_menu.addAction(name)
            action.setCheckable(True)
            self.theme_group.addAction(action)
            action.triggered.connect(lambda _=False, k=key: self.select_theme(k))
            self.theme_actions[key] = action
        self.title_bar_action = view_menu.addAction("Pasek tytułowy w oknach")
        self.title_bar_action.setCheckable(True)
        self.title_bar_action.triggered.connect(
            lambda checked: self.settings.title_bar.setChecked(checked)
        )
        view_menu.addSeparator()
        self._item(view_menu, "Odśwież", act["refresh"], "refresh")

        wallet_menu = bar.addMenu("P&ortfel")
        self._item(wallet_menu, "Edytuj portfel…", act["edit_wallet"], "edit_wallet",
                   self._has_wallet)  # fmt: skip
        self._item(wallet_menu, "Usuń portfel", act["delete_wallet"], "delete_wallet",
                   self._has_wallet)  # fmt: skip
        wallet_menu.addSeparator()
        self._item(wallet_menu, "Prognoza salda…", self.show_forecast, enabled=self._has_wallet)

        transaction_menu = bar.addMenu("&Transakcja")
        self._item(transaction_menu, "Zapłać transakcję cykliczną", act["pay_selected"],
                   "pay_selected", self._can_pay)  # fmt: skip
        self._item(transaction_menu, "Pomiń termin transakcji cyklicznej", self.recurring.skip,
                   enabled=self._can_skip)  # fmt: skip
        transaction_menu.addSeparator()
        self._item(transaction_menu, "Historia ceny produktu…",
                   self.products.show_price_history, enabled=self._has_product)  # fmt: skip

        report_menu = bar.addMenu("&Raport")
        in_reports = lambda: self.tabs.currentWidget() is self.reports  # noqa: E731
        self._item(report_menu, "Poprzedni okres", act["previous_month"], "previous_month",
                   in_reports)  # fmt: skip
        self._item(report_menu, "Następny okres", act["next_month"], "next_month", in_reports)
        report_menu.addSeparator()
        period_menu = report_menu.addMenu("Okres")
        self.period_group = QActionGroup(self)
        self.period_actions = {}
        for key, name in (("month", "Miesiąc"), ("year", "Rok"), ("range", "Zakres dat")):
            action = period_menu.addAction(name)
            action.setCheckable(True)
            self.period_group.addAction(action)
            action.triggered.connect(lambda _=False, k=key: self.select_period(k))
            self.period_actions[key] = action

        help_menu = bar.addMenu("Pomo&c")
        self._item(help_menu, "Historia zmian danych…", self.history_dialog.open_page)
        self._item(help_menu, "Skróty klawiszowe…", self.show_shortcuts)
        help_menu.addSeparator()
        self._item(help_menu, "O programie…", self.about_dialog.open_page)

        for menu in (file_menu, edit_menu, view_menu, wallet_menu, transaction_menu,
                     report_menu, help_menu):  # fmt: skip
            menu.aboutToShow.connect(self.update_menus)
        self.update_menus()

    def update_menus(self):
        """Skróty w podpisach, wyszarzenie i zaznaczenia według bieżącego stanu."""
        for action, label, key, enabled in self.menu_items:
            text = shortcuts.display_text(shortcuts.sequence_text(key)) if key else ""
            # Tekst po tabulatorze menu pokazuje jako skrót, nie rejestrując go drugi raz.
            action.setText(f"{label}\t{text}" if text else label)
            action.setEnabled(enabled() if enabled else True)
        for index, action in enumerate(self.view_actions):
            action.setChecked(index == self.tabs.currentIndex())
        self.theme_actions[current_theme()].setChecked(True)
        self.title_bar_action.setChecked(title_bar.is_enabled())
        self.period_actions[self.reports.period["period"]].setChecked(True)
        self.period_group.setEnabled(self.tabs.currentWidget() is self.reports)

    # Stan zaznaczenia w bieżącej zakładce

    def _has_wallet(self):
        return self.wallets.wallet_id() is not None

    def _current_has(self, method):
        return hasattr(self.tabs.currentWidget(), method)

    def _selected(self, action):
        """Czy działanie z menu Edycja ma czego dotyczyć w bieżącej zakładce."""
        tab = self.tabs.currentWidget()
        if tab is self.wallets:
            entry = self.wallets.selected_entry()
            if action == "duplicate":
                return entry is not None and entry[0] == "transaction"
            return entry is not None
        if tab is self.products:
            return action in ("edit", "duplicate") and self._has_product()
        if tab is self.recurring:
            return action in ("edit", "delete") and self.recurring.selected_id() is not None
        if tab is self.categories:
            return action in ("edit", "delete") and self.categories.table.currentRow() >= 0
        return False

    def _has_product(self):
        return self.tabs.currentWidget() is self.products and (
            self.products.selected_transaction() is not None
        )

    def _can_pay(self):
        row = self.recurring.table.currentRow()
        return (
            self.tabs.currentWidget() is self.recurring
            and row >= 0
            and self.recurring.table.cellWidget(row, PAY).isEnabled()
        )

    def _can_skip(self):
        return (
            self.tabs.currentWidget() is self.recurring
            and self.recurring.skip_button.isEnabled()
        )

    # Działania

    def delete_selected(self):
        tab = self.tabs.currentWidget()
        if tab is self.wallets:
            self.wallets.delete_entry()
        elif tab is self.recurring:
            self.recurring.delete()
        elif tab is self.categories:
            self.categories.delete()

    def show_forecast(self):
        self.tabs.setCurrentWidget(self.wallets)
        self.wallets.show_forecast()

    def show_shortcuts(self):
        ShortcutsDialog(self).exec()

    def select_theme(self, key):
        combo = self.settings.theme
        combo.setCurrentIndex(combo.findData(key))

    def select_period(self, key):
        combo = self.reports.period_combo
        combo.setCurrentIndex(combo.findData(key))

    def show_due_count(self, count):
        index = self.tabs.indexOf(self.recurring)
        self.tabs.setTabText(index, f"Cykliczne ({count})" if count else "Cykliczne")
        self.tabs.setTabToolTip(
            index, f"Płatności po terminie lub na dzisiaj: {count}" if count else ""
        )

    def _on_current_tab(self, method):
        """Działanie dotyczy widocznej zakładki; pozostałe zakładki je pomijają."""
        action = getattr(self.tabs.currentWidget(), method, None)
        if action:
            action()

    def _after(self, action):
        """Odświeża widoczną zakładkę, chyba że działanie zrobiło to samo."""
        action()
        if self.tabs.currentWidget() not in (self.wallets, self.recurring):
            self.tabs.currentWidget().refresh()

    def _wallet_action(self, action):
        if self.wallets.wallet_id() is None:
            common.show_errors(self, ["Dodaj najpierw portfel."])
            return
        self._after(action)

    def refresh_all_tabs(self):
        """Po zmianie motywu lub skrótów widoki i menu muszą pokazać nowe wartości."""
        for index in range(self.tabs.count()):
            self.tabs.widget(index).refresh()
        if hasattr(self, "menu_items"):
            self.update_menus()

    def new_transaction(self):
        """Działa z każdej zakładki, a po zapisie odświeża tę, która jest widoczna."""
        transaction_id = self.wallets.create_transaction()
        current = self.tabs.currentWidget()
        # Lista transakcji jest już odświeżona, a ponowne odświeżenie cofnęłoby jej widok
        # do góry i ukryło migający wiersz.
        if current is not self.wallets:
            current.refresh()
        if transaction_id is not None and current is self.products:
            self.products.flash_transaction(transaction_id)
