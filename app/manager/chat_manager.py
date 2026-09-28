"""Chat Manager layer coordinating business rules and adapter persistence."""

from datetime import datetime, timezone
from typing import List, Optional

from app.adapter.chat_adapter import ChatAdapter, chat_adapter as default_chat_adapter
from app.adapter.entities import (
    ChatRoomRecordEntity,
    MessageRecordEntity,
    RoomMembershipRecordEntity,
    UserRecordEntity,
)
from app.adapter.user_adapter import UserAdapter, user_adapter as default_user_adapter
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


class ChatManager:
    """Unified manager implementing business logic and coordinating adapters."""

    def __init__(
        self,
        user_adapter: Optional[UserAdapter] = None,
        chat_adapter: Optional[ChatAdapter] = None,
    ) -> None:
        self.user_adapter = user_adapter or default_user_adapter
        self.chat_adapter = chat_adapter or default_chat_adapter

    # ==========================================================================
    # User Management
    # ==========================================================================

    def register_user(self, request: RegisterUserRequestEntity) -> RegisterUserResponseEntity:
        """Register a user in the user store.

        Raises:
            UserAlreadyExistsError: If the user_id is already registered.
        """
        existing = self.user_adapter.get_user(request.user_id)
        if existing is not None:
            raise UserAlreadyExistsError(request.user_id)

        now = datetime.now(timezone.utc).isoformat()
        record = UserRecordEntity(user_id=request.user_id, created_at=now)
        saved = self.user_adapter.add_user(record)
        return RegisterUserResponseEntity(user_id=saved.user_id, created_at=saved.created_at)

    # ==========================================================================
    # Room Management
    # ==========================================================================

    def create_room(self, request: CreateRoomRequestEntity) -> CreateRoomResponseEntity:
        """Create a new chat room.

        Raises:
            RoomAlreadyExistsError: If a room with this ID already exists.
        """
        if self.chat_adapter.room_exists(request.room_id):
            raise RoomAlreadyExistsError(request.room_id)

        now = datetime.now(timezone.utc).isoformat()
        record = ChatRoomRecordEntity(room_id=request.room_id, created_at=now)
        saved = self.chat_adapter.create_room(record)
        return CreateRoomResponseEntity(room_id=saved.room_id, created_at=saved.created_at)

    # ==========================================================================
    # Membership Operations
    # ==========================================================================

    def join(self, request: JoinRoomRequestEntity) -> JoinRoomResponseEntity:
        """Join an existing chat room.

        Preconditions:
        - User must exist in UserAdapter.
        - Room must exist in ChatAdapter.

        Raises:
            UserNotFoundError: If user_id is not registered.
            RoomNotFoundError: If room_id does not exist.
        """
        self._ensure_user_exists(request.user_id)
        self._ensure_room_exists(request.room_id)

        now = datetime.now(timezone.utc).isoformat()
        record = RoomMembershipRecordEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            joined_at=now,
        )
        self.chat_adapter.add_member(record)
        return JoinRoomResponseEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            status="joined",
        )

    def leave(self, request: LeaveRoomRequestEntity) -> LeaveRoomResponseEntity:
        """Leave a chat room.

        Preconditions:
        - User must exist in UserAdapter.
        - Room must exist in ChatAdapter.

        Raises:
            UserNotFoundError: If user_id is not registered.
            RoomNotFoundError: If room_id does not exist.
        """
        self._ensure_user_exists(request.user_id)
        self._ensure_room_exists(request.room_id)

        self.chat_adapter.remove_member(request.room_id, request.user_id)
        return LeaveRoomResponseEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            status="left",
        )

    # ==========================================================================
    # Message Operations
    # ==========================================================================

    def send_message(self, request: SendMessageRequestEntity) -> MessageResponseEntity:
        """Post a message to a chat room.

        Preconditions:
        - User must exist.
        - Room must exist.
        - User must be a member of the room.

        Raises:
            UserNotFoundError: If user_id is not registered.
            RoomNotFoundError: If room_id does not exist.
            UserNotMemberError: If user has not joined the room.
        """
        self._ensure_user_exists(request.user_id)
        self._ensure_room_exists(request.room_id)

        if not self.chat_adapter.is_member(request.room_id, request.user_id):
            raise UserNotMemberError(
                room_id=request.room_id,
                user_id=request.user_id,
                action="sending messages",
            )

        now = datetime.now(timezone.utc).isoformat()
        record = MessageRecordEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            content=request.content,
            timestamp=now,
        )
        saved = self.chat_adapter.save_message(record)
        return MessageResponseEntity(
            id=saved.id,
            room_id=saved.room_id,
            user_id=saved.user_id,
            content=saved.content,
            timestamp=saved.timestamp,
        )

    def get_messages(self, request: GetMessagesRequestEntity) -> List[MessageResponseEntity]:
        """Retrieve all messages from a chat room.

        Preconditions:
        - User must exist.
        - Room must exist.
        - User must be a member of the room.

        Raises:
            UserNotFoundError: If user_id is not registered.
            RoomNotFoundError: If room_id does not exist.
            UserNotMemberError: If user has not joined the room.
        """
        self._ensure_user_exists(request.user_id)
        self._ensure_room_exists(request.room_id)

        if not self.chat_adapter.is_member(request.room_id, request.user_id):
            raise UserNotMemberError(
                room_id=request.room_id,
                user_id=request.user_id,
                action="retrieving messages",
            )

        messages = self.chat_adapter.get_messages(request.room_id)
        return [
            MessageResponseEntity(
                id=m.id,
                room_id=m.room_id,
                user_id=m.user_id,
                content=m.content,
                timestamp=m.timestamp,
            )
            for m in messages
        ]

    # ==========================================================================
    # Validation Helpers
    # ==========================================================================

    def _ensure_user_exists(self, user_id: str) -> None:
        """Validate user existence via UserAdapter."""
        if self.user_adapter.get_user(user_id) is None:
            raise UserNotFoundError(user_id)

    def _ensure_room_exists(self, room_id: str) -> None:
        """Validate room existence via ChatAdapter."""
        if not self.chat_adapter.room_exists(room_id):
            raise RoomNotFoundError(room_id)


# Default singleton instance
chat_manager = ChatManager()
