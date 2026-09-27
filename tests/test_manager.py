"""Unit tests for the ChatManager layer."""

import pytest
from app.manager.chat_manager import ChatManager
from app.manager.entities import (
    GetMessagesRequestEntity,
    JoinRoomRequestEntity,
    LeaveRoomRequestEntity,
    SendMessageRequestEntity,
)
from app.manager.exceptions import UserNotMemberError


@pytest.fixture
def manager():
    """Create a fresh ChatManager instance for each test."""
    return ChatManager()


def test_join_room_success(manager):
    """Test user can join a room successfully."""
    req = JoinRoomRequestEntity(room_id="dev", user_id="alice")
    resp = manager.join(req)

    assert resp.room_id == "dev"
    assert resp.user_id == "alice"
    assert resp.status == "joined"


def test_join_room_idempotent(manager):
    """Test joining an already joined room succeeds without duplicate error."""
    req = JoinRoomRequestEntity(room_id="dev", user_id="alice")
    manager.join(req)
    resp = manager.join(req)

    assert resp.status == "joined"


def test_send_message_as_member(manager):
    """Test a joined user can send a message."""
    manager.join(JoinRoomRequestEntity(room_id="dev", user_id="alice"))

    msg_req = SendMessageRequestEntity(
        room_id="dev",
        user_id="alice",
        content="Hello dev room!",
    )
    msg_resp = manager.send_message(msg_req)

    assert msg_resp.id == 1
    assert msg_resp.room_id == "dev"
    assert msg_resp.user_id == "alice"
    assert msg_resp.content == "Hello dev room!"
    assert msg_resp.timestamp is not None


def test_send_message_not_member_raises_user_not_member_error(manager):
    """Test sending message without joining raises UserNotMemberError."""
    msg_req = SendMessageRequestEntity(
        room_id="dev",
        user_id="bob",
        content="Sneak message",
    )
    with pytest.raises(UserNotMemberError) as exc_info:
        manager.send_message(msg_req)

    assert "User 'bob' must join room 'dev' before sending messages" in str(exc_info.value)
    assert exc_info.value.room_id == "dev"
    assert exc_info.value.user_id == "bob"


def test_get_messages_as_member(manager):
    """Test a joined member can retrieve messages."""
    manager.join(JoinRoomRequestEntity(room_id="dev", user_id="alice"))
    manager.send_message(
        SendMessageRequestEntity(room_id="dev", user_id="alice", content="First message")
    )

    get_req = GetMessagesRequestEntity(room_id="dev", user_id="alice")
    messages = manager.get_messages(get_req)

    assert len(messages) == 1
    assert messages[0].content == "First message"


def test_get_messages_not_member_raises_user_not_member_error(manager):
    """Test retrieving messages without joining raises UserNotMemberError."""
    get_req = GetMessagesRequestEntity(room_id="dev", user_id="charlie")
    with pytest.raises(UserNotMemberError) as exc_info:
        manager.get_messages(get_req)

    assert "User 'charlie' must join room 'dev' before retrieving messages" in str(exc_info.value)


def test_leave_room_success(manager):
    """Test user leaving a room."""
    manager.join(JoinRoomRequestEntity(room_id="dev", user_id="alice"))
    leave_resp = manager.leave(LeaveRoomRequestEntity(room_id="dev", user_id="alice"))

    assert leave_resp.status == "left"
    assert leave_resp.room_id == "dev"
    assert leave_resp.user_id == "alice"


def test_send_message_after_leave_raises_user_not_member_error(manager):
    """Test user cannot send messages after leaving the room."""
    manager.join(JoinRoomRequestEntity(room_id="dev", user_id="alice"))
    manager.leave(LeaveRoomRequestEntity(room_id="dev", user_id="alice"))

    with pytest.raises(UserNotMemberError):
        manager.send_message(
            SendMessageRequestEntity(room_id="dev", user_id="alice", content="Post leave")
        )


def test_get_messages_after_leave_raises_user_not_member_error(manager):
    """Test user cannot retrieve messages after leaving the room."""
    manager.join(JoinRoomRequestEntity(room_id="dev", user_id="alice"))
    manager.leave(LeaveRoomRequestEntity(room_id="dev", user_id="alice"))

    with pytest.raises(UserNotMemberError):
        manager.get_messages(GetMessagesRequestEntity(room_id="dev", user_id="alice"))


def test_multi_room_isolation(manager):
    """Test that memberships and messages in Room A do not leak into Room B."""
    # Alice joins Room A, Bob joins Room B
    manager.join(JoinRoomRequestEntity(room_id="room-a", user_id="alice"))
    manager.join(JoinRoomRequestEntity(room_id="room-b", user_id="bob"))

    manager.send_message(
        SendMessageRequestEntity(room_id="room-a", user_id="alice", content="Message in A")
    )
    manager.send_message(
        SendMessageRequestEntity(room_id="room-b", user_id="bob", content="Message in B")
    )

    # Alice cannot read Room B without joining
    with pytest.raises(UserNotMemberError):
        manager.get_messages(GetMessagesRequestEntity(room_id="room-b", user_id="alice"))

    # Alice can read Room A and only sees Room A's messages
    msgs_a = manager.get_messages(GetMessagesRequestEntity(room_id="room-a", user_id="alice"))
    assert len(msgs_a) == 1
    assert msgs_a[0].content == "Message in A"
