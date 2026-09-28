"""In-memory persistence adapter for chat rooms, memberships, and messages."""

from typing import Dict, List, Optional

from app.adapter.entities import (
    ChatRoomRecordEntity,
    MessageRecordEntity,
    RoomMembershipRecordEntity,
)
from app.adapter.exceptions import (
    RoomAlreadyExistsError,
    RoomNotFoundError,
    UserNotMemberError,
)


class ChatAdapter:
    """In-memory adapter managing chat room aggregates."""

    def __init__(self) -> None:
        self._rooms: Dict[str, ChatRoomRecordEntity] = {}
        self._next_message_id: int = 1

    # ==========================================================================
    # Room Management Operations
    # ==========================================================================

    def create_room(self, record: ChatRoomRecordEntity) -> ChatRoomRecordEntity:
        """Explicitly create a new chat room.

        Raises:
            RoomAlreadyExistsError: If a room with this ID already exists.
        """
        if record.room_id in self._rooms:
            raise RoomAlreadyExistsError(record.room_id)
        self._rooms[record.room_id] = record
        return record

    def get_room(self, room_id: str) -> Optional[ChatRoomRecordEntity]:
        """Retrieve room entity if it exists, otherwise None."""
        return self._rooms.get(room_id)

    def room_exists(self, room_id: str) -> bool:
        """Check whether a chat room currently exists."""
        return room_id in self._rooms

    # ==========================================================================
    # Room Membership Operations (Room Must Exist)
    # ==========================================================================

    def add_member(self, record: RoomMembershipRecordEntity) -> RoomMembershipRecordEntity:
        """Add a user to an existing room (idempotent).

        Raises:
            RoomNotFoundError: If the room does not exist.
        """
        room = self.get_room(record.room_id)
        if room is None:
            raise RoomNotFoundError(record.room_id)

        if record.user_id not in room.memberships:
            room.memberships[record.user_id] = record
        return room.memberships[record.user_id]

    def is_member(self, room_id: str, user_id: str) -> bool:
        """Check if a user is a member of an existing room.

        Raises:
            RoomNotFoundError: If the room does not exist.
        """
        room = self.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        return user_id in room.memberships

    def remove_member(self, room_id: str, user_id: str) -> bool:
        """Remove a user from an existing room.

        Raises:
            RoomNotFoundError: If the room does not exist.
        """
        room = self.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)

        if user_id in room.memberships:
            del room.memberships[user_id]
            return True
        return False

    def get_members(self, room_id: str) -> List[RoomMembershipRecordEntity]:
        """Retrieve all active member records for an existing room.

        Raises:
            RoomNotFoundError: If the room does not exist.
        """
        room = self.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        return list(room.memberships.values())

    # ==========================================================================
    # Message Operations (Room Must Exist & User Must Be Member)
    # ==========================================================================

    def save_message(self, record: MessageRecordEntity) -> MessageRecordEntity:
        """Persist a message to the room's message history.

        Preconditions:
        - The room MUST exist (does NOT auto-create rooms).
        - The user MUST be a current member of the room.

        Raises:
            RoomNotFoundError: If the room does not exist.
            UserNotMemberError: If the user is not a member of the room.
        """
        room = self.get_room(record.room_id)
        if room is None:
            raise RoomNotFoundError(record.room_id)

        if record.user_id not in room.memberships:
            raise UserNotMemberError(
                room_id=record.room_id,
                user_id=record.user_id,
                action="sending messages",
            )

        if record.id is None:
            record.id = self._next_message_id
            self._next_message_id += 1

        room.messages.append(record)
        return record

    def get_messages(self, room_id: str) -> List[MessageRecordEntity]:
        """Retrieve all messages for a specific room in chronological order.

        Raises:
            RoomNotFoundError: If the room does not exist.
        """
        room = self.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        return list(room.messages)

    # ==========================================================================
    # State Reset
    # ==========================================================================

    def clear(self) -> None:
        """Clear all stored rooms, memberships, and messages, resetting ID counter."""
        self._rooms.clear()
        self._next_message_id = 1


# Default singleton instance
chat_adapter = ChatAdapter()
