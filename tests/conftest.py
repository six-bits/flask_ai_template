"""Pytest fixtures for the greeting API."""

import pytest
from app.adapter.greeting_adapter import greeting_adapter
from app.service.api import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    greeting_adapter.storage.clear()
    with app.test_client() as client:
        yield client
