"""Messages Manager handling message persistence and retrieval."""

from datetime import datetime, timezone
from typing import List, Optional

from app.adapter.chat_adapter import ChatAdapter, chat_adapter as default_chat_adapter
from app.adapter.entities import MessageRecordEntity
from app.manager.chat_manager import ChatManager, chat_manager as default_chat_manager
from app.manager.entities import (
    GetMessagesRequestEntity,
    MessageResponseEntity,
    SendMessageRequestEntity,
)
from app.manager.exceptions import (
    UserNotMemberError,
)
from app.manager.user_manager import UserManager, user_manager as default_user_manager


class MessagesManager:
    """Manager coordinating message posting and retrieval operations."""

    def __init__(
        self,
        chat_adapter: Optional[ChatAdapter] = None,
        user_manager: Optional[UserManager] = None,
        chat_manager: Optional[ChatManager] = None,
    ) -> None:
        self.chat_adapter = chat_adapter or default_chat_adapter
        self.user_manager = user_manager or default_user_manager
        self.chat_manager = chat_manager or default_chat_manager

    def send_message(self, request: SendMessageRequestEntity) -> MessageResponseEntity:
        """Post a message to a chat room.

        Preconditions:
        - User must exist (UserManager).
        - Room must exist (ChatManager).
        - User must be an active member of the room (ChatManager).

        Raises:
            UserNotFoundError: If user_id is not registered.
            RoomNotFoundError: If room_id does not exist.
            UserNotMemberError: If user has not joined the room.
        """
        self.user_manager.ensure_user_exists(request.user_id)
        self.chat_manager.ensure_room_exists(request.room_id)

        if not self.chat_manager.is_member(request.room_id, request.user_id):
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
        """Retrieve all messages from a chat room in chronological order.

        Preconditions:
        - User must exist (UserManager).
        - Room must exist (ChatManager).
        - User must be an active member of the room (ChatManager).

        Raises:
            UserNotFoundError: If user_id is not registered.
            RoomNotFoundError: If room_id does not exist.
            UserNotMemberError: If user has not joined the room.
        """
        self.user_manager.ensure_user_exists(request.user_id)
        self.chat_manager.ensure_room_exists(request.room_id)

        if not self.chat_manager.is_member(request.room_id, request.user_id):
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


# Default singleton instance
messages_manager = MessagesManager()
