"""Pytest fixtures for the Chat Service API."""

import pytest
from app.manager.chat_manager import chat_manager
from app.service.api import app


@pytest.fixture
def client():
    """Create Flask test client and reset manager state."""
    app.config["TESTING"] = True
    chat_manager.clear()
    with app.test_client() as client:
        yield client
