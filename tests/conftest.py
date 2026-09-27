"""Pytest fixtures for the Chat Service API."""

import pytest
from app.service.api import app


@pytest.fixture
def client():
    """Create Flask test client."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client
