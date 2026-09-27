"""Unified Chat Manager coordinating room memberships and messages."""

from datetime import datetime, timezone
from typing import Any, List, Optional, Set, Tuple

from app.manager.entities import (
    GetMessagesRequestEntity,
    JoinRoomRequestEntity,
    JoinRoomResponseEntity,
    LeaveRoomRequestEntity,
    LeaveRoomResponseEntity,
    MessageResponseEntity,
    SendMessageRequestEntity,
)
from app.manager.exceptions import UserNotMemberError


class ChatManager:
    """Unified manager coordinating all chat domain operations."""

    def __init__(self, adapter: Optional[Any] = None) -> None:
        self.adapter = adapter
        # In-memory storage fallback used when adapter is not provided
        self._memberships: Set[Tuple[str, str]] = set()
        self._messages: List[dict] = []
        self._next_id: int = 1

    def join(self, request: JoinRoomRequestEntity) -> JoinRoomResponseEntity:
        """Register user membership in a chat room (idempotent)."""
        if self.adapter and hasattr(self.adapter, "add_member"):
            self.adapter.add_member(request.room_id, request.user_id)
        else:
            self._memberships.add((request.room_id, request.user_id))

        return JoinRoomResponseEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            status="joined",
        )

    def send_message(self, request: SendMessageRequestEntity) -> MessageResponseEntity:
        """Send a message to a chat room after verifying room membership."""
        if not self._is_member(request.room_id, request.user_id):
            raise UserNotMemberError(
                room_id=request.room_id,
                user_id=request.user_id,
                action="sending messages",
            )

        timestamp = datetime.now(timezone.utc).isoformat()

        if self.adapter and hasattr(self.adapter, "save_message"):
            saved = self.adapter.save_message(request.room_id, request.user_id, request.content)
            return MessageResponseEntity(
                id=saved["id"],
                room_id=saved["room_id"],
                user_id=saved["user_id"],
                content=saved["content"],
                timestamp=saved["timestamp"],
            )
        else:
            msg_id = self._next_id
            self._next_id += 1
            msg = {
                "id": msg_id,
                "room_id": request.room_id,
                "user_id": request.user_id,
                "content": request.content,
                "timestamp": timestamp,
            }
            self._messages.append(msg)
            return MessageResponseEntity(**msg)

    def get_messages(self, request: GetMessagesRequestEntity) -> List[MessageResponseEntity]:
        """Retrieve all messages from a chat room after verifying room membership."""
        if not self._is_member(request.room_id, request.user_id):
            raise UserNotMemberError(
                room_id=request.room_id,
                user_id=request.user_id,
                action="retrieving messages",
            )

        if self.adapter and hasattr(self.adapter, "get_messages"):
            raw_messages = self.adapter.get_messages(request.room_id)
            return [MessageResponseEntity(**m) for m in raw_messages]
        else:
            room_msgs = [m for m in self._messages if m["room_id"] == request.room_id]
            return [MessageResponseEntity(**m) for m in room_msgs]

    def leave(self, request: LeaveRoomRequestEntity) -> LeaveRoomResponseEntity:
        """Remove user membership from a chat room."""
        if self.adapter and hasattr(self.adapter, "remove_member"):
            self.adapter.remove_member(request.room_id, request.user_id)
        else:
            self._memberships.discard((request.room_id, request.user_id))

        return LeaveRoomResponseEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            status="left",
        )

    def _is_member(self, room_id: str, user_id: str) -> bool:
        """Check if user has joined the chat room."""
        if self.adapter and hasattr(self.adapter, "is_member"):
            return self.adapter.is_member(room_id, user_id)
        return (room_id, user_id) in self._memberships

    def clear(self) -> None:
        """Reset in-memory storage (useful for testing)."""
        self._memberships.clear()
        self._messages.clear()
        self._next_id = 1


# Default singleton instance
chat_manager = ChatManager()
