"""Pytest fixtures for the container orchestration API."""

import pytest

from app.adapter.greeting_adapter import greeting_adapter
from app.adapter.orchestrator_adapter import orchestrator_adapter
from app.service.api import app


@pytest.fixture
def client():
    """Test client fixture resetting in-memory database and storage."""
    app.config["TESTING"] = True
    greeting_adapter.storage.clear()
    orchestrator_adapter.reset()
    with app.test_client() as test_client:
        yield test_client
