from PySide6.QtWidgets import QMainWindow, QTabWidget

from .categories_tab import CategoriesTab
from .products_tab import ProductsTab
from .recurring_tab import RecurringTab
from .reports_tab import ReportsTab
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

        self.tabs = QTabWidget()
        self.tabs.addTab(self.wallets, "Portfele")
        self.tabs.addTab(self.products, "Produkty")
        self.tabs.addTab(self.recurring, "Cykliczne")
        self.tabs.addTab(self.reports, "Raporty")
        self.tabs.addTab(self.categories, "Kategorie")
        # Każda zakładka czyta z bazy przy wejściu, więc widzi zmiany z pozostałych.
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().refresh())
        self.setCentralWidget(self.tabs)
