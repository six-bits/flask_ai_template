"""Unit tests for the decomposed Manager layer (UserManager, ChatManager, MessagesManager)."""

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
from app.manager.messages_manager import MessagesManager
from app.manager.user_manager import UserManager


@pytest.fixture
def user_adp():
    """Create isolated UserAdapter instance."""
    return UserAdapter()


@pytest.fixture
def chat_adp():
    """Create isolated ChatAdapter instance."""
    return ChatAdapter()


@pytest.fixture
def user_mgr(user_adp):
    """Create isolated UserManager instance."""
    return UserManager(user_adapter=user_adp)


@pytest.fixture
def chat_mgr(chat_adp, user_mgr):
    """Create isolated ChatManager instance."""
    return ChatManager(chat_adapter=chat_adp, user_manager=user_mgr)


@pytest.fixture
def messages_mgr(chat_adp, user_mgr, chat_mgr):
    """Create isolated MessagesManager instance."""
    return MessagesManager(
        chat_adapter=chat_adp,
        user_manager=user_mgr,
        chat_manager=chat_mgr,
    )


# ==============================================================================
# 1. UserManager Tests
# ==============================================================================

def test_register_user_success(user_mgr):
    """Test registering a new user succeeds."""
    req = RegisterUserRequestEntity(user_id="alice")
    resp = user_mgr.register_user(req)

    assert isinstance(resp, RegisterUserResponseEntity)
    assert resp.user_id == "alice"
    assert resp.created_at is not None


def test_register_user_already_exists_raises_error(user_mgr):
    """Test registering duplicate user raises UserAlreadyExistsError."""
    req = RegisterUserRequestEntity(user_id="alice")
    user_mgr.register_user(req)

    with pytest.raises(UserAlreadyExistsError) as exc_info:
        user_mgr.register_user(req)

    assert "User 'alice' already exists" in str(exc_info.value)


def test_ensure_user_exists_success(user_mgr):
    """Test ensure_user_exists passes when user is registered."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    # Should not raise
    user_mgr.ensure_user_exists("alice")


def test_ensure_user_exists_raises_user_not_found(user_mgr):
    """Test ensure_user_exists raises UserNotFoundError when user is missing."""
    with pytest.raises(UserNotFoundError) as exc_info:
        user_mgr.ensure_user_exists("ghost")

    assert "User 'ghost' was not found" in str(exc_info.value)


def test_user_exists(user_mgr):
    """Test user_exists returns boolean existence."""
    assert not user_mgr.user_exists("alice")
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    assert user_mgr.user_exists("alice")


# ==============================================================================
# 2. ChatManager Tests
# ==============================================================================

def test_create_room_success(chat_mgr):
    """Test creating a new room succeeds."""
    req = CreateRoomRequestEntity(room_id="general")
    resp = chat_mgr.create_room(req)

    assert isinstance(resp, CreateRoomResponseEntity)
    assert resp.room_id == "general"
    assert resp.created_at is not None


def test_create_room_already_exists_raises_error(chat_mgr):
    """Test creating duplicate room ID raises RoomAlreadyExistsError."""
    req = CreateRoomRequestEntity(room_id="general")
    chat_mgr.create_room(req)

    with pytest.raises(RoomAlreadyExistsError) as exc_info:
        chat_mgr.create_room(req)

    assert "Room 'general' already exists" in str(exc_info.value)


def test_join_user_not_found_raises_error(chat_mgr):
    """Test join raises UserNotFoundError when user is not registered."""
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))

    with pytest.raises(UserNotFoundError) as exc_info:
        chat_mgr.join(JoinRoomRequestEntity(room_id="general", user_id="ghost"))

    assert "User 'ghost' was not found" in str(exc_info.value)


def test_join_room_not_found_raises_error(chat_mgr, user_mgr):
    """Test join raises RoomNotFoundError when room does not exist."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))

    with pytest.raises(RoomNotFoundError) as exc_info:
        chat_mgr.join(JoinRoomRequestEntity(room_id="ghost-room", user_id="alice"))

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


def test_join_room_success(chat_mgr, user_mgr):
    """Test registered user joining an existing room."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))

    resp = chat_mgr.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))
    assert isinstance(resp, JoinRoomResponseEntity)
    assert resp.room_id == "general"
    assert resp.user_id == "alice"
    assert resp.status == "joined"


def test_join_room_idempotent(chat_mgr, user_mgr):
    """Test joining multiple times succeeds idempotently."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))

    req = JoinRoomRequestEntity(room_id="general", user_id="alice")
    chat_mgr.join(req)
    resp = chat_mgr.join(req)

    assert resp.status == "joined"


def test_leave_room_user_not_found_raises_error(chat_mgr):
    """Test leave raises UserNotFoundError when user is not registered."""
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))

    req = LeaveRoomRequestEntity(room_id="general", user_id="ghost")
    with pytest.raises(UserNotFoundError) as exc_info:
        chat_mgr.leave(req)

    assert "User 'ghost' was not found" in str(exc_info.value)


def test_leave_room_room_not_found_raises_error(chat_mgr, user_mgr):
    """Test leave raises RoomNotFoundError when room does not exist."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))

    req = LeaveRoomRequestEntity(room_id="ghost-room", user_id="alice")
    with pytest.raises(RoomNotFoundError) as exc_info:
        chat_mgr.leave(req)

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


def test_leave_room_success(chat_mgr, user_mgr):
    """Test joined user leaving a room."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))
    chat_mgr.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))

    resp = chat_mgr.leave(LeaveRoomRequestEntity(room_id="general", user_id="alice"))

    assert isinstance(resp, LeaveRoomResponseEntity)
    assert resp.room_id == "general"
    assert resp.user_id == "alice"
    assert resp.status == "left"


def test_chat_manager_is_member_and_ensure_room_exists(chat_mgr, user_mgr):
    """Test is_member and ensure_room_exists methods."""
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))

    assert not chat_mgr.is_member("general", "alice")
    chat_mgr.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))
    assert chat_mgr.is_member("general", "alice")

    chat_mgr.ensure_room_exists("general")
    with pytest.raises(RoomNotFoundError):
        chat_mgr.ensure_room_exists("non-existent")


# ==============================================================================
# 3. MessagesManager Tests
# ==============================================================================

def test_send_message_user_not_found_raises_error(messages_mgr, chat_mgr):
    """Test send_message raises UserNotFoundError when user is not registered."""
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))

    req = SendMessageRequestEntity(room_id="general", user_id="ghost", content="Hi")
    with pytest.raises(UserNotFoundError) as exc_info:
        messages_mgr.send_message(req)

    assert "User 'ghost' was not found" in str(exc_info.value)


def test_send_message_room_not_found_raises_error(messages_mgr, user_mgr):
    """Test send_message raises RoomNotFoundError when room does not exist."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))

    req = SendMessageRequestEntity(room_id="ghost-room", user_id="alice", content="Hi")
    with pytest.raises(RoomNotFoundError) as exc_info:
        messages_mgr.send_message(req)

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


def test_send_message_user_not_member_raises_error(messages_mgr, user_mgr, chat_mgr):
    """Test send_message raises UserNotMemberError when user hasn't joined room."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))

    req = SendMessageRequestEntity(room_id="general", user_id="alice", content="Sneak message")
    with pytest.raises(UserNotMemberError) as exc_info:
        messages_mgr.send_message(req)

    assert "User 'alice' must join room 'general' before sending messages" in str(exc_info.value)


def test_send_message_success(messages_mgr, user_mgr, chat_mgr):
    """Test joined user sending a message assigns monotonic ID."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))
    chat_mgr.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))

    msg_req = SendMessageRequestEntity(
        room_id="general",
        user_id="alice",
        content="Hello general room!",
    )
    resp = messages_mgr.send_message(msg_req)

    assert isinstance(resp, MessageResponseEntity)
    assert resp.id == 1
    assert resp.room_id == "general"
    assert resp.user_id == "alice"
    assert resp.content == "Hello general room!"
    assert resp.timestamp is not None


def test_get_messages_user_not_found_raises_error(messages_mgr, chat_mgr):
    """Test get_messages raises UserNotFoundError when user is not registered."""
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))

    req = GetMessagesRequestEntity(room_id="general", user_id="ghost")
    with pytest.raises(UserNotFoundError) as exc_info:
        messages_mgr.get_messages(req)

    assert "User 'ghost' was not found" in str(exc_info.value)


def test_get_messages_room_not_found_raises_error(messages_mgr, user_mgr):
    """Test get_messages raises RoomNotFoundError when room does not exist."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))

    req = GetMessagesRequestEntity(room_id="ghost-room", user_id="alice")
    with pytest.raises(RoomNotFoundError) as exc_info:
        messages_mgr.get_messages(req)

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


def test_get_messages_user_not_member_raises_error(messages_mgr, user_mgr, chat_mgr):
    """Test get_messages raises UserNotMemberError when user hasn't joined room."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))

    req = GetMessagesRequestEntity(room_id="general", user_id="alice")
    with pytest.raises(UserNotMemberError) as exc_info:
        messages_mgr.get_messages(req)

    assert "User 'alice' must join room 'general' before retrieving messages" in str(exc_info.value)


def test_get_messages_success(messages_mgr, user_mgr, chat_mgr):
    """Test joined user retrieving messages in order."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))
    chat_mgr.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))

    messages_mgr.send_message(SendMessageRequestEntity(room_id="general", user_id="alice", content="Message 1"))
    messages_mgr.send_message(SendMessageRequestEntity(room_id="general", user_id="alice", content="Message 2"))

    messages = messages_mgr.get_messages(GetMessagesRequestEntity(room_id="general", user_id="alice"))

    assert len(messages) == 2
    assert messages[0].content == "Message 1"
    assert messages[1].content == "Message 2"


def test_send_message_after_leave_raises_user_not_member(messages_mgr, user_mgr, chat_mgr):
    """Test user cannot send messages after leaving the room."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))
    chat_mgr.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))
    chat_mgr.leave(LeaveRoomRequestEntity(room_id="general", user_id="alice"))

    with pytest.raises(UserNotMemberError):
        messages_mgr.send_message(
            SendMessageRequestEntity(room_id="general", user_id="alice", content="Post leave")
        )


def test_get_messages_after_leave_raises_user_not_member(messages_mgr, user_mgr, chat_mgr):
    """Test user cannot retrieve messages after leaving the room."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="general"))
    chat_mgr.join(JoinRoomRequestEntity(room_id="general", user_id="alice"))
    chat_mgr.leave(LeaveRoomRequestEntity(room_id="general", user_id="alice"))

    with pytest.raises(UserNotMemberError):
        messages_mgr.get_messages(GetMessagesRequestEntity(room_id="general", user_id="alice"))


def test_multi_room_isolation_via_messages_manager(messages_mgr, user_mgr, chat_mgr):
    """Test room isolation through the messages manager layer."""
    user_mgr.register_user(RegisterUserRequestEntity(user_id="alice"))
    user_mgr.register_user(RegisterUserRequestEntity(user_id="bob"))

    chat_mgr.create_room(CreateRoomRequestEntity(room_id="room-1"))
    chat_mgr.create_room(CreateRoomRequestEntity(room_id="room-2"))

    chat_mgr.join(JoinRoomRequestEntity(room_id="room-1", user_id="alice"))
    chat_mgr.join(JoinRoomRequestEntity(room_id="room-2", user_id="bob"))

    messages_mgr.send_message(SendMessageRequestEntity(room_id="room-1", user_id="alice", content="Only in 1"))

    # Alice cannot read room-2 without joining
    with pytest.raises(UserNotMemberError):
        messages_mgr.get_messages(GetMessagesRequestEntity(room_id="room-2", user_id="alice"))

    # Bob cannot read room-1 without joining
    with pytest.raises(UserNotMemberError):
        messages_mgr.get_messages(GetMessagesRequestEntity(room_id="room-1", user_id="bob"))

    # Alice reads room-1
    msgs = messages_mgr.get_messages(GetMessagesRequestEntity(room_id="room-1", user_id="alice"))
    assert len(msgs) == 1
    assert msgs[0].content == "Only in 1"
