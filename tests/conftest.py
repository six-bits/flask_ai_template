"""Pytest fixtures for the Chat Service E2E tests."""

import pytest
from app.manager import chat_manager, user_manager
from app.manager.entities import CreateRoomRequestEntity, RegisterUserRequestEntity
from app.service.api import app


@pytest.fixture
def client():
    """Create Flask test client with pre-provisioned users and rooms via Managers."""
    app.config["TESTING"] = True

    # 1. Reset state
    user_manager.user_adapter.clear()
    chat_manager.chat_adapter.clear()

    # 2. Provision test users via UserManager
    user_manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    user_manager.register_user(RegisterUserRequestEntity(user_id="bob"))
    user_manager.register_user(RegisterUserRequestEntity(user_id="charlie"))

    # 3. Provision test rooms via ChatManager
    chat_manager.create_room(CreateRoomRequestEntity(room_id="general"))
    chat_manager.create_room(CreateRoomRequestEntity(room_id="random"))
    chat_manager.create_room(CreateRoomRequestEntity(room_id="dev"))

    with app.test_client() as client:
        yield client
