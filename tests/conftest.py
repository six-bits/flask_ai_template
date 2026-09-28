"""Pytest fixtures for the Chat Service API."""

import pytest
from app.adapter.chat_adapter import chat_adapter
from app.adapter.entities import (
    ChatRoomRecordEntity,
    MessageRecordEntity,
    RoomMembershipRecordEntity,
    UserRecordEntity,
)

from app.adapter.user_adapter import user_adapter
from app.service.api import app


@pytest.fixture
def client():
    """Create Flask test client with pre-seeded test data for API compatibility."""
    app.config["TESTING"] = True

    # Seed default room and user so API route tests pass before API spec update
    user_adapter.clear()
    chat_adapter.clear()

    user_adapter.add_user(UserRecordEntity(user_id="alice", created_at="2026-09-28T00:00:00Z"))
    user_adapter.add_user(UserRecordEntity(user_id="bob", created_at="2026-09-28T00:00:00Z"))
    chat_adapter.create_room(ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z"))
    chat_adapter.add_member(
        RoomMembershipRecordEntity(room_id="general", user_id="alice", joined_at="2026-09-28T00:00:00Z")
    )

    with app.test_client() as client:


        yield client
