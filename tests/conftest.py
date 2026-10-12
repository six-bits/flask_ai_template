import pytest
from app.adapter.db import db
from app.adapter.greeting_adapter import greeting_adapter
from app.service.api import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    greeting_adapter.storage.clear()
    db.reset()
    with app.test_client() as client:
        yield client

