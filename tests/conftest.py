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
