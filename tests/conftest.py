"""Pytest fixtures for the greeting and wallet API."""

import pytest
from app.adapter.database import default_db
from app.adapter.greeting_adapter import greeting_adapter
from app.adapter.quote_adapter import quote_adapter
from app.adapter.wallet_adapter import wallet_adapter
from app.service.api import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    greeting_adapter.storage.clear()
    default_db.reset()
    with app.test_client() as client:
        yield client


@pytest.fixture
def db():
    default_db.reset()
    return default_db


@pytest.fixture
def adapters(db):
    return {
        "wallet_adapter": wallet_adapter,
        "quote_adapter": quote_adapter,
        "db": db,
    }
