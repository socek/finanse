from PySide6.QtWidgets import QMainWindow, QTabWidget

from ..recurring import count_due
from ..settings import load_settings
from ..storage import database_path
from . import common, shortcuts
from .about_tab import AboutTab
from .categories_tab import CategoriesTab
from .files_tab import FilesTab
from .history_tab import HistoryTab
from .products_tab import ProductsTab
from .recurring_tab import RecurringTab
from .reports_tab import ReportsTab
from .settings_tab import SettingsTab
from .wallets_tab import WalletsTab


class MainWindow(QMainWindow):
    def __init__(self, db):
        super().__init__()
        self.setWindowTitle("Finanse")
        self.resize(1120, 760)
        shortcuts.load(load_settings(database_path(db)).get("shortcuts"))

        self.wallets = WalletsTab(db)
        self.products = ProductsTab(db)
        self.recurring = RecurringTab(db)
        self.reports = ReportsTab(db)
        self.categories = CategoriesTab(db)
        self.history = HistoryTab(db)
        self.files = FilesTab(db)
        self.settings = SettingsTab(db, self.refresh_all_tabs)
        self.about = AboutTab()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.wallets, "Portfele")
        self.tabs.addTab(self.products, "Produkty")
        self.tabs.addTab(self.recurring, "Cykliczne")
        self.tabs.addTab(self.reports, "Raporty")
        self.tabs.addTab(self.categories, "Kategorie")
        self.tabs.addTab(self.history, "Historia")
        self.tabs.addTab(self.files, "Pliki")
        self.tabs.addTab(self.settings, "Ustawienia")
        self.tabs.addTab(self.about, "O programie")
        # Każda zakładka czyta z bazy przy wejściu, więc widzi zmiany z pozostałych.
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().refresh())
        # Liczba zaległych płatności w nazwie zakładki; data mogła się zmienić od startu.
        self.recurring.due_count_changed.connect(self.show_due_count)
        self.tabs.currentChanged.connect(lambda _: self.show_due_count(count_due(db)))
        self.show_due_count(count_due(db))
        self.setCentralWidget(self.tabs)

        actions = {
            "new_transaction": self.new_transaction,
            "new_transfer": lambda: self._after(self.wallets.create_transfer),
            "new_wallet": lambda: self._after(self.wallets.create_wallet),
            "new_recurring": lambda: self._after(self.recurring.create),
            "import_csv": lambda: self._wallet_action(self.wallets.import_csv),
            "edit_wallet": lambda: self._wallet_action(self.wallets.edit_wallet),
            "delete_wallet": lambda: self._wallet_action(self.wallets.delete_wallet),
            "edit_selected": lambda: self._on_current_tab("edit_selected"),
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
            "quit": self.close,
        }
        for index in range(self.tabs.count()):
            actions[f"tab_{index + 1}"] = lambda _=False, i=index: self.tabs.setCurrentIndex(i)
        self.action_shortcuts = {
            key: shortcuts.bind(key, self, callback) for key, callback in actions.items()
        }
        self.new_transaction_shortcut = self.action_shortcuts["new_transaction"]

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
        """Po zmianie motywu tabele muszą dostać kolory z nowej palety."""
        for index in range(self.tabs.count()):
            self.tabs.widget(index).refresh()

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
