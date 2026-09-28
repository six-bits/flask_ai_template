"""Unit tests for UserAdapter and ChatAdapter."""

import pytest

from app.adapter.chat_adapter import ChatAdapter
from app.adapter.entities import (
    ChatRoomRecordEntity,
    MessageRecordEntity,
    RoomMembershipRecordEntity,
    UserRecordEntity,
)
from app.adapter.exceptions import (
    RoomAlreadyExistsError,
    RoomNotFoundError,
    UserNotMemberError,
)
from app.adapter.user_adapter import UserAdapter


@pytest.fixture
def user_adp():
    """Create a fresh UserAdapter instance."""
    return UserAdapter()


@pytest.fixture
def chat_adp():
    """Create a fresh ChatAdapter instance."""
    return ChatAdapter()


# ==============================================================================
# UserAdapter Tests
# ==============================================================================

def test_add_user_success(user_adp):
    """Test adding a user returns entity and can be retrieved."""
    record = UserRecordEntity(user_id="alice", created_at="2026-09-28T00:00:00Z")
    saved = user_adp.add_user(record)

    assert saved.user_id == "alice"
    assert user_adp.get_user("alice") is not None
    assert user_adp.get_user("alice").user_id == "alice"


def test_add_user_idempotent(user_adp):
    """Test adding the same user twice returns existing record."""
    r1 = UserRecordEntity(user_id="alice", created_at="2026-09-28T00:00:00Z")
    r2 = UserRecordEntity(user_id="alice", created_at="2026-09-28T01:00:00Z")

    saved1 = user_adp.add_user(r1)
    saved2 = user_adp.add_user(r2)

    assert saved1 is saved2
    assert saved2.created_at == "2026-09-28T00:00:00Z"


def test_get_user_found_and_not_found(user_adp):
    """Test get_user returns entity when user exists, and None otherwise."""
    assert user_adp.get_user("bob") is None

    user_adp.add_user(UserRecordEntity(user_id="bob", created_at="2026-09-28T00:00:00Z"))
    assert user_adp.get_user("bob") is not None


def test_user_adapter_clear(user_adp):
    """Test clear removes all stored users."""
    user_adp.add_user(UserRecordEntity(user_id="alice", created_at="2026-09-28T00:00:00Z"))
    user_adp.clear()

    assert user_adp.get_user("alice") is None


# ==============================================================================
# ChatAdapter Tests - Room Creation & Existence
# ==============================================================================

def test_create_room_success(chat_adp):
    """Test creating a room succeeds and sets room_exists to True."""
    room = ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z")
    saved = chat_adp.create_room(room)

    assert saved.room_id == "general"
    assert chat_adp.room_exists("general") is True
    assert chat_adp.get_room("general") is not None


def test_create_room_already_exists_raises_error(chat_adp):
    """Test creating duplicate room ID raises RoomAlreadyExistsError."""
    room1 = ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z")
    room2 = ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T01:00:00Z")

    chat_adp.create_room(room1)
    with pytest.raises(RoomAlreadyExistsError) as exc_info:
        chat_adp.create_room(room2)

    assert "Room 'general' already exists" in str(exc_info.value)


def test_get_room_non_existent_returns_none(chat_adp):
    """Test get_room on uncreated room returns None and room_exists is False."""
    assert chat_adp.get_room("non-existent") is None
    assert chat_adp.room_exists("non-existent") is False


# ==============================================================================
# ChatAdapter Tests - Strict Room Existence Preconditions
# ==============================================================================

def test_add_member_room_not_found_raises_error(chat_adp):
    """Test add_member raises RoomNotFoundError if room does not exist."""
    record = RoomMembershipRecordEntity(
        room_id="ghost-room",
        user_id="alice",
        joined_at="2026-09-28T00:00:00Z",
    )
    with pytest.raises(RoomNotFoundError) as exc_info:
        chat_adp.add_member(record)

    assert "Room 'ghost-room' was not found" in str(exc_info.value)
    assert chat_adp.room_exists("ghost-room") is False


def test_is_member_room_not_found_raises_error(chat_adp):
    """Test is_member raises RoomNotFoundError if room does not exist."""
    with pytest.raises(RoomNotFoundError) as exc_info:
        chat_adp.is_member("ghost-room", "alice")

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


def test_remove_member_room_not_found_raises_error(chat_adp):
    """Test remove_member raises RoomNotFoundError if room does not exist."""
    with pytest.raises(RoomNotFoundError) as exc_info:
        chat_adp.remove_member("ghost-room", "alice")

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


def test_get_members_room_not_found_raises_error(chat_adp):
    """Test get_members raises RoomNotFoundError if room does not exist."""
    with pytest.raises(RoomNotFoundError) as exc_info:
        chat_adp.get_members("ghost-room")

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


def test_save_message_room_not_found_raises_error(chat_adp):
    """Test save_message raises RoomNotFoundError if room does not exist."""
    msg = MessageRecordEntity(
        room_id="ghost-room",
        user_id="alice",
        content="Hello?",
        timestamp="2026-09-28T00:00:00Z",
    )
    with pytest.raises(RoomNotFoundError) as exc_info:
        chat_adp.save_message(msg)

    assert "Room 'ghost-room' was not found" in str(exc_info.value)
    assert chat_adp.room_exists("ghost-room") is False


def test_get_messages_room_not_found_raises_error(chat_adp):
    """Test get_messages raises RoomNotFoundError if room does not exist."""
    with pytest.raises(RoomNotFoundError) as exc_info:
        chat_adp.get_messages("ghost-room")

    assert "Room 'ghost-room' was not found" in str(exc_info.value)


# ==============================================================================
# ChatAdapter Tests - Membership & Messages in Existing Rooms
# ==============================================================================

def test_add_member_to_existing_room_success(chat_adp):
    """Test adding member to an existing room."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z"))

    record = RoomMembershipRecordEntity(
        room_id="general",
        user_id="alice",
        joined_at="2026-09-28T00:00:00Z",
    )
    saved = chat_adp.add_member(record)

    assert saved.user_id == "alice"
    assert chat_adp.is_member("general", "alice") is True
    assert chat_adp.is_member("general", "bob") is False


def test_add_member_idempotent(chat_adp):
    """Test adding the same member multiple times succeeds idempotently."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z"))

    r1 = RoomMembershipRecordEntity(room_id="general", user_id="alice", joined_at="2026-09-28T00:00:00Z")
    r2 = RoomMembershipRecordEntity(room_id="general", user_id="alice", joined_at="2026-09-28T01:00:00Z")

    chat_adp.add_member(r1)
    chat_adp.add_member(r2)

    members = chat_adp.get_members("general")
    assert len(members) == 1
    assert members[0].joined_at == "2026-09-28T00:00:00Z"


def test_remove_member_from_existing_room(chat_adp):
    """Test removing a member from an existing room."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z"))
    chat_adp.add_member(RoomMembershipRecordEntity(room_id="general", user_id="alice", joined_at="2026-09-28T00:00:00Z"))

    assert chat_adp.is_member("general", "alice") is True
    removed = chat_adp.remove_member("general", "alice")

    assert removed is True
    assert chat_adp.is_member("general", "alice") is False


def test_remove_member_not_member_returns_false(chat_adp):
    """Test removing a non-member from an existing room returns False."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z"))
    assert chat_adp.remove_member("general", "ghost") is False


def test_get_members_by_room(chat_adp):
    """Test get_members returns all registered members in the room."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z"))
    chat_adp.add_member(RoomMembershipRecordEntity(room_id="general", user_id="alice", joined_at="2026-09-28T00:00:00Z"))
    chat_adp.add_member(RoomMembershipRecordEntity(room_id="general", user_id="bob", joined_at="2026-09-28T00:00:01Z"))

    members = chat_adp.get_members("general")
    assert len(members) == 2
    uids = {m.user_id for m in members}
    assert uids == {"alice", "bob"}


def test_save_message_user_not_member_raises_error(chat_adp):
    """Test sending message to an existing room without membership raises UserNotMemberError."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z"))

    msg = MessageRecordEntity(
        room_id="general",
        user_id="alice",
        content="Sneaky message",
        timestamp="2026-09-28T00:00:00Z",
    )
    with pytest.raises(UserNotMemberError) as exc_info:
        chat_adp.save_message(msg)

    assert "User 'alice' must join room 'general' before sending messages" in str(exc_info.value)


def test_save_message_as_member_success(chat_adp):
    """Test sending message as a joined member assigns monotonic ID."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z"))
    chat_adp.add_member(RoomMembershipRecordEntity(room_id="general", user_id="alice", joined_at="2026-09-28T00:00:00Z"))

    m1 = MessageRecordEntity(
        room_id="general",
        user_id="alice",
        content="First message",
        timestamp="2026-09-28T00:01:00Z",
    )
    m2 = MessageRecordEntity(
        room_id="general",
        user_id="alice",
        content="Second message",
        timestamp="2026-09-28T00:02:00Z",
    )

    saved1 = chat_adp.save_message(m1)
    saved2 = chat_adp.save_message(m2)

    assert saved1.id == 1
    assert saved2.id == 2
    assert len(chat_adp.get_messages("general")) == 2


def test_save_message_preserves_attributes(chat_adp):
    """Test saved message attributes match original input."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="dev", created_at="2026-09-28T00:00:00Z"))
    chat_adp.add_member(RoomMembershipRecordEntity(room_id="dev", user_id="bob", joined_at="2026-09-28T00:00:00Z"))

    msg = MessageRecordEntity(
        room_id="dev",
        user_id="bob",
        content="Build passing!",
        timestamp="2026-09-28T12:00:00Z",
    )
    saved = chat_adp.save_message(msg)

    assert saved.id == 1
    assert saved.room_id == "dev"
    assert saved.user_id == "bob"
    assert saved.content == "Build passing!"
    assert saved.timestamp == "2026-09-28T12:00:00Z"


def test_get_messages_chronological_order(chat_adp):
    """Test messages are returned in insertion order."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z"))
    chat_adp.add_member(RoomMembershipRecordEntity(room_id="general", user_id="alice", joined_at="2026-09-28T00:00:00Z"))

    for i in range(1, 4):
        chat_adp.save_message(
            MessageRecordEntity(
                room_id="general",
                user_id="alice",
                content=f"Message {i}",
                timestamp=f"2026-09-28T00:0{i}:00Z",
            )
        )

    messages = chat_adp.get_messages("general")
    assert len(messages) == 3
    assert [m.content for m in messages] == ["Message 1", "Message 2", "Message 3"]


def test_get_messages_empty_room(chat_adp):
    """Test get_messages on an existing room with no messages returns empty list."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="empty-room", created_at="2026-09-28T00:00:00Z"))
    assert chat_adp.get_messages("empty-room") == []


def test_multi_room_isolation(chat_adp):
    """Test memberships and messages in room-1 are completely isolated from room-2."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="room-1", created_at="2026-09-28T00:00:00Z"))
    chat_adp.create_room(ChatRoomRecordEntity(room_id="room-2", created_at="2026-09-28T00:00:00Z"))

    chat_adp.add_member(RoomMembershipRecordEntity(room_id="room-1", user_id="alice", joined_at="2026-09-28T00:00:00Z"))
    chat_adp.add_member(RoomMembershipRecordEntity(room_id="room-2", user_id="bob", joined_at="2026-09-28T00:00:00Z"))

    assert chat_adp.is_member("room-1", "alice") is True
    assert chat_adp.is_member("room-1", "bob") is False
    assert chat_adp.is_member("room-2", "bob") is True
    assert chat_adp.is_member("room-2", "alice") is False

    chat_adp.save_message(MessageRecordEntity(room_id="room-1", user_id="alice", content="Msg in 1", timestamp="2026-09-28T00:00:00Z"))
    chat_adp.save_message(MessageRecordEntity(room_id="room-2", user_id="bob", content="Msg in 2", timestamp="2026-09-28T00:00:00Z"))

    msgs_1 = chat_adp.get_messages("room-1")
    msgs_2 = chat_adp.get_messages("room-2")

    assert len(msgs_1) == 1
    assert msgs_1[0].content == "Msg in 1"
    assert len(msgs_2) == 1
    assert msgs_2[0].content == "Msg in 2"


def test_chat_adapter_clear(chat_adp):
    """Test clear erases all rooms and resets message sequence."""
    chat_adp.create_room(ChatRoomRecordEntity(room_id="general", created_at="2026-09-28T00:00:00Z"))
    chat_adp.add_member(RoomMembershipRecordEntity(room_id="general", user_id="alice", joined_at="2026-09-28T00:00:00Z"))
    chat_adp.save_message(MessageRecordEntity(room_id="general", user_id="alice", content="Hello", timestamp="2026-09-28T00:00:00Z"))

    chat_adp.clear()

    assert chat_adp.room_exists("general") is False
    assert chat_adp.get_room("general") is None
