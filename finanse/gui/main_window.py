from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QTabWidget

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
        self.setCentralWidget(self.tabs)

        self.new_transaction_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        self.new_transaction_shortcut.activated.connect(self.new_transaction)

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
