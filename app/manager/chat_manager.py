"""Chat Manager handling room lifecycle and membership operations."""

from datetime import datetime, timezone
from typing import Optional

from app.adapter.chat_adapter import ChatAdapter, chat_adapter as default_chat_adapter
from app.adapter.entities import ChatRoomRecordEntity, RoomMembershipRecordEntity
from app.manager.entities import (
    CreateRoomRequestEntity,
    CreateRoomResponseEntity,
    JoinRoomRequestEntity,
    JoinRoomResponseEntity,
    LeaveRoomRequestEntity,
    LeaveRoomResponseEntity,
)
from app.manager.exceptions import (
    RoomAlreadyExistsError,
    RoomNotFoundError,
)
from app.manager.user_manager import UserManager, user_manager as default_user_manager


class ChatManager:
    """Manager coordinating chat room lifecycle and membership operations."""

    def __init__(
        self,
        chat_adapter: Optional[ChatAdapter] = None,
        user_manager: Optional[UserManager] = None,
    ) -> None:
        self.chat_adapter = chat_adapter or default_chat_adapter
        self.user_manager = user_manager or default_user_manager

    def create_room(self, request: CreateRoomRequestEntity) -> CreateRoomResponseEntity:
        """Create a new chat room.

        Raises:
            RoomAlreadyExistsError: If room_id already exists.
        """
        if self.chat_adapter.room_exists(request.room_id):
            raise RoomAlreadyExistsError(request.room_id)

        now = datetime.now(timezone.utc).isoformat()
        record = ChatRoomRecordEntity(room_id=request.room_id, created_at=now)
        saved = self.chat_adapter.create_room(record)
        return CreateRoomResponseEntity(room_id=saved.room_id, created_at=saved.created_at)

    def join(self, request: JoinRoomRequestEntity) -> JoinRoomResponseEntity:
        """Join an existing chat room.

        Preconditions:
        - User must exist in UserManager.
        - Room must exist in ChatAdapter.

        Raises:
            UserNotFoundError: If user_id is not registered.
            RoomNotFoundError: If room_id does not exist.
        """
        self.user_manager.ensure_user_exists(request.user_id)
        self.ensure_room_exists(request.room_id)

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
        - User must exist in UserManager.
        - Room must exist in ChatAdapter.

        Raises:
            UserNotFoundError: If user_id is not registered.
            RoomNotFoundError: If room_id does not exist.
        """
        self.user_manager.ensure_user_exists(request.user_id)
        self.ensure_room_exists(request.room_id)

        self.chat_adapter.remove_member(request.room_id, request.user_id)
        return LeaveRoomResponseEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            status="left",
        )

    def is_member(self, room_id: str, user_id: str) -> bool:
        """Check if a user is a member of an existing room."""
        return self.chat_adapter.is_member(room_id, user_id)

    def ensure_room_exists(self, room_id: str) -> None:
        """Validate room existence, raising RoomNotFoundError if not found."""
        if not self.chat_adapter.room_exists(room_id):
            raise RoomNotFoundError(room_id)


# Default singleton instance
chat_manager = ChatManager()
