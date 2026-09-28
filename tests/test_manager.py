"""Unit tests for the ChatManager layer coordinating with adapters."""

import pytest

from app.adapter.chat_adapter import ChatAdapter
from app.adapter.user_adapter import UserAdapter
from app.manager.chat_manager import ChatManager
from app.manager.entities import (
    CreateRoomRequestEntity,
    CreateRoomResponseEntity,
    GetMessagesRequestEntity,
    JoinRoomRequestEntity,
    JoinRoomResponseEntity,
    LeaveRoomRequestEntity,
    LeaveRoomResponseEntity,
    MessageResponseEntity,
    RegisterUserRequestEntity,
    RegisterUserResponseEntity,
    SendMessageRequestEntity,
)
from app.manager.exceptions import (
    RoomAlreadyExistsError,
    RoomNotFoundError,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserNotMemberError,
)


@pytest.fixture
def manager():
    """Create a fresh ChatManager instance with isolated adapters."""
    user_adp = UserAdapter()
    chat_adp = ChatAdapter()
    return ChatManager(user_adapter=user_adp, chat_adapter=chat_adp)


# ==============================================================================
# 6.1 User & Room Management Tests
# ==============================================================================

def test_register_user_success(manager):
    """Test registering a new user succeeds."""
    req = RegisterUserRequestEntity(user_id="alice")
    resp = manager.register_user(req)

    assert isinstance(resp, RegisterUserResponseEntity)
    assert resp.user_id == "alice"
    assert resp.created_at is not None


def test_register_user_already_exists_raises_error(manager):
    """Test registering duplicate user raises UserAlreadyExistsError."""
    req = RegisterUserRequestEntity(user_id="alice")
    manager.register_user(req)

    with pytest.raises(UserAlreadyExistsError) as exc_info:
        manager.register_user(req)

    assert "User 'alice' already exists" in str(exc_info.value)


def test_create_room_success(manager):
    """Test creating a new room succeeds."""
    req = CreateRoomRequestEntity(room_id="general")
    resp = manager.create_room(req)

    assert isinstance(resp, CreateRoomResponseEntity)
    assert resp.room_id == "general"
    assert resp.created_at is not None


def test_create_room_already_exists_raises_error(manager):
    """Test creating duplicate room ID raises RoomAlreadyExistsError."""
    req = CreateRoomRequestEntity(room_id="general")
    manager.create_room(req)

    with pytest.raises(RoomAlreadyExistsError) as exc_info:
        manager.create_room(req)

    assert "Room 'general' already exists" in str(exc_info.value)


# ==============================================================================
# 6.2 Precondition Failures (User & Room Validations)
# ==============================================================================

def test_join_user_not_found_raises_error(manager):
    """Test join raises UserNotFoundError when user is not registered."""
    manager.create_room(CreateRoomRequestEntity(room_id="general"))

    with pytest.raises(UserNotFoundError) as exc_info:
        manager.join(JoinRoomRequestEntity(room_id="general", user_id="ghost"))

    assert "User 'ghost' was not found" in str(exc_info.value)


def test_join_room_not_found_raises_error(manager):
    """Test join raises RoomNotFoundError when room does not exist."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))

    with pytest.raises(RoomNotFoundError) as exc_info:
        manager.join(JoinRoomRequestEntity(room_id="ghost-room", user_id="alice"))

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


def test_send_message_user_not_found_raises_error(manager):
    """Test send_message raises UserNotFoundError when user is not registered."""
    manager.create_room(CreateRoomRequestEntity(room_id="general"))

    req = SendMessageRequestEntity(room_id="general", user_id="ghost", content="Hi")
    with pytest.raises(UserNotFoundError) as exc_info:
        manager.send_message(req)

    assert "User 'ghost' was not found" in str(exc_info.value)


def test_send_message_room_not_found_raises_error(manager):
    """Test send_message raises RoomNotFoundError when room does not exist."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))

    req = SendMessageRequestEntity(room_id="ghost-room", user_id="alice", content="Hi")
    with pytest.raises(RoomNotFoundError) as exc_info:
        manager.send_message(req)

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


def test_send_message_user_not_member_raises_error(manager):
    """Test send_message raises UserNotMemberError when user hasn't joined room."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    manager.create_room(CreateRoomRequestEntity(room_id="general"))

    req = SendMessageRequestEntity(room_id="general", user_id="alice", content="Sneak message")
    with pytest.raises(UserNotMemberError) as exc_info:
        manager.send_message(req)

    assert "User 'alice' must join room 'general' before sending messages" in str(exc_info.value)


def test_get_messages_user_not_found_raises_error(manager):
    """Test get_messages raises UserNotFoundError when user is not registered."""
    manager.create_room(CreateRoomRequestEntity(room_id="general"))

    req = GetMessagesRequestEntity(room_id="general", user_id="ghost")
    with pytest.raises(UserNotFoundError) as exc_info:
        manager.get_messages(req)

    assert "User 'ghost' was not found" in str(exc_info.value)


def test_get_messages_room_not_found_raises_error(manager):
    """Test get_messages raises RoomNotFoundError when room does not exist."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))

    req = GetMessagesRequestEntity(room_id="ghost-room", user_id="alice")
    with pytest.raises(RoomNotFoundError) as exc_info:
        manager.get_messages(req)

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


def test_get_messages_user_not_member_raises_error(manager):
    """Test get_messages raises UserNotMemberError when user hasn't joined room."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    manager.create_room(CreateRoomRequestEntity(room_id="general"))

    req = GetMessagesRequestEntity(room_id="general", user_id="alice")
    with pytest.raises(UserNotMemberError) as exc_info:
        manager.get_messages(req)

    assert "User 'alice' must join room 'general' before retrieving messages" in str(exc_info.value)


def test_leave_room_user_not_found_raises_error(manager):
    """Test leave raises UserNotFoundError when user is not registered."""
    manager.create_room(CreateRoomRequestEntity(room_id="general"))

    req = LeaveRoomRequestEntity(room_id="general", user_id="ghost")
    with pytest.raises(UserNotFoundError) as exc_info:
        manager.leave(req)

    assert "User 'ghost' was not found" in str(exc_info.value)


def test_leave_room_room_not_found_raises_error(manager):
    """Test leave raises RoomNotFoundError when room does not exist."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))

    req = LeaveRoomRequestEntity(room_id="ghost-room", user_id="alice")
    with pytest.raises(RoomNotFoundError) as exc_info:
        manager.leave(req)

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


# ==============================================================================
# 6.3 Happy Path & Full Domain Workflow
# ==============================================================================

def test_join_room_success(manager):
    """Test registered user joining an existing room."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    manager.create_room(CreateRoomRequestEntity(room_id="general"))

    resp = manager.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))
    assert isinstance(resp, JoinRoomResponseEntity)
    assert resp.room_id == "general"
    assert resp.user_id == "alice"
    assert resp.status == "joined"


def test_join_room_idempotent(manager):
    """Test joining multiple times succeeds idempotently."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    manager.create_room(CreateRoomRequestEntity(room_id="general"))

    req = JoinRoomRequestEntity(room_id="general", user_id="alice")
    manager.join(req)
    resp = manager.join(req)

    assert resp.status == "joined"


def test_send_message_success(manager):
    """Test joined user sending a message assigns monotonic ID."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    manager.create_room(CreateRoomRequestEntity(room_id="general"))
    manager.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))

    msg_req = SendMessageRequestEntity(
        room_id="general",
        user_id="alice",
        content="Hello general room!",
    )
    resp = manager.send_message(msg_req)

    assert isinstance(resp, MessageResponseEntity)
    assert resp.id == 1
    assert resp.room_id == "general"
    assert resp.user_id == "alice"
    assert resp.content == "Hello general room!"
    assert resp.timestamp is not None


def test_get_messages_success(manager):
    """Test joined user retrieving messages in order."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    manager.create_room(CreateRoomRequestEntity(room_id="general"))
    manager.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))

    manager.send_message(SendMessageRequestEntity(room_id="general", user_id="alice", content="Message 1"))
    manager.send_message(SendMessageRequestEntity(room_id="general", user_id="alice", content="Message 2"))

    messages = manager.get_messages(GetMessagesRequestEntity(room_id="general", user_id="alice"))

    assert len(messages) == 2
    assert messages[0].content == "Message 1"
    assert messages[1].content == "Message 2"


def test_leave_room_success(manager):
    """Test joined user leaving a room."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    manager.create_room(CreateRoomRequestEntity(room_id="general"))
    manager.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))

    resp = manager.leave(LeaveRoomRequestEntity(room_id="general", user_id="alice"))

    assert isinstance(resp, LeaveRoomResponseEntity)
    assert resp.room_id == "general"
    assert resp.user_id == "alice"
    assert resp.status == "left"


def test_send_message_after_leave_raises_user_not_member(manager):
    """Test user cannot send messages after leaving the room."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    manager.create_room(CreateRoomRequestEntity(room_id="general"))
    manager.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))
    manager.leave(LeaveRoomRequestEntity(room_id="general", user_id="alice"))

    with pytest.raises(UserNotMemberError):
        manager.send_message(
            SendMessageRequestEntity(room_id="general", user_id="alice", content="Post leave")
        )


def test_get_messages_after_leave_raises_user_not_member(manager):
    """Test user cannot retrieve messages after leaving the room."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    manager.create_room(CreateRoomRequestEntity(room_id="general"))
    manager.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))
    manager.leave(LeaveRoomRequestEntity(room_id="general", user_id="alice"))

    with pytest.raises(UserNotMemberError):
        manager.get_messages(GetMessagesRequestEntity(room_id="general", user_id="alice"))


def test_multi_room_isolation_via_manager(manager):
    """Test room isolation through the manager layer."""
    manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    manager.register_user(RegisterUserRequestEntity(user_id="bob"))

    manager.create_room(CreateRoomRequestEntity(room_id="room-1"))
    manager.create_room(CreateRoomRequestEntity(room_id="room-2"))

    manager.join(JoinRoomRequestEntity(room_id="room-1", user_id="alice"))
    manager.join(JoinRoomRequestEntity(room_id="room-2", user_id="bob"))

    manager.send_message(SendMessageRequestEntity(room_id="room-1", user_id="alice", content="Only in 1"))

    # Alice cannot read room-2 without joining
    with pytest.raises(UserNotMemberError):
        manager.get_messages(GetMessagesRequestEntity(room_id="room-2", user_id="alice"))

    # Bob cannot read room-1 without joining
    with pytest.raises(UserNotMemberError):
        manager.get_messages(GetMessagesRequestEntity(room_id="room-1", user_id="bob"))

    # Alice reads room-1
    msgs = manager.get_messages(GetMessagesRequestEntity(room_id="room-1", user_id="alice"))
    assert len(msgs) == 1
    assert msgs[0].content == "Only in 1"
