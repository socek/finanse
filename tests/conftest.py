import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from finanse.db import connect, init_db


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    init_db(str(path))
    connection = connect(str(path))
    yield connection
    connection.close()


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def forget_transaction_date():
    from finanse.gui.dialogs import TransactionDialog

    TransactionDialog.remembered_date = None
    yield
    TransactionDialog.remembered_date = None


@pytest.fixture(autouse=True)
def restore_system_theme():
    yield
    from finanse.gui.themes import apply_theme

    if QApplication.instance():
        apply_theme("system")


@pytest.fixture(autouse=True)
def default_shortcuts():
    from finanse.gui import shortcuts

    shortcuts.forget()
    yield
    shortcuts.forget()
