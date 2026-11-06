import pytest
from helpers import sign_up

from finanse import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "test.db"),
        }
    )


@pytest.fixture
def client(app):
    client = app.test_client()
    sign_up(client)
    return client
