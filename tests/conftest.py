"""Pytest fixtures for the Flash Sale Inventory Reservation API."""

import pytest

from app.adapter.db import in_memory_db
from app.service.api import app


@pytest.fixture
def client():
    """Create Flask test client and reset in-memory database before each test."""
    app.config["TESTING"] = True
    in_memory_db.reset()
    return app.test_client()
