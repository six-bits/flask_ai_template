"""Contract tests for the stubbed ChatManager layer."""

from app.manager.chat_manager import chat_manager
from app.manager.entities import (
    GetMessagesRequestEntity,
    JoinRoomRequestEntity,
    JoinRoomResponseEntity,
    LeaveRoomRequestEntity,
    LeaveRoomResponseEntity,
    MessageResponseEntity,
    SendMessageRequestEntity,
)


def test_join_room_contract():
    """Verify join contract returns JoinRoomResponseEntity."""
    req = JoinRoomRequestEntity(room_id="general", user_id="alice")
    resp = chat_manager.join(req)

    assert isinstance(resp, JoinRoomResponseEntity)
    assert resp.room_id == "general"
    assert resp.user_id == "alice"
    assert resp.status == "joined"


def test_send_message_contract():
    """Verify send_message contract returns MessageResponseEntity."""
    req = SendMessageRequestEntity(
        room_id="general",
        user_id="alice",
        content="Hello!",
    )
    resp = chat_manager.send_message(req)

    assert isinstance(resp, MessageResponseEntity)
    assert resp.id == 1
    assert resp.room_id == "general"
    assert resp.user_id == "alice"
    assert resp.content == "Hello!"
    assert resp.timestamp is not None


def test_get_messages_contract():
    """Verify get_messages contract returns list of MessageResponseEntity."""
    req = GetMessagesRequestEntity(room_id="general", user_id="alice")
    messages = chat_manager.get_messages(req)

    assert isinstance(messages, list)
    assert len(messages) >= 1
    assert isinstance(messages[0], MessageResponseEntity)
    assert messages[0].room_id == "general"


def test_leave_room_contract():
    """Verify leave contract returns LeaveRoomResponseEntity."""
    req = LeaveRoomRequestEntity(room_id="general", user_id="alice")
    resp = chat_manager.leave(req)

    assert isinstance(resp, LeaveRoomResponseEntity)
    assert resp.room_id == "general"
    assert resp.user_id == "alice"
    assert resp.status == "left"
