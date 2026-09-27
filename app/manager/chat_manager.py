"""Stubbed Chat Manager layer defining the interface and contract."""

from datetime import datetime, timezone
from typing import List, Optional

from app.manager.entities import (
    GetMessagesRequestEntity,
    JoinRoomRequestEntity,
    JoinRoomResponseEntity,
    LeaveRoomRequestEntity,
    LeaveRoomResponseEntity,
    MessageResponseEntity,
    SendMessageRequestEntity,
)


class ChatManager:
    """Stubbed manager implementing the contract between Service and Manager."""

    def __init__(self, adapter: Optional[object] = None) -> None:
        self.adapter = adapter

    def join(self, request: JoinRoomRequestEntity) -> JoinRoomResponseEntity:
        """Stub join operation."""
        return JoinRoomResponseEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            status="joined",
        )

    def send_message(self, request: SendMessageRequestEntity) -> MessageResponseEntity:
        """Stub send_message operation."""
        timestamp = datetime.now(timezone.utc).isoformat()
        return MessageResponseEntity(
            id=1,
            room_id=request.room_id,
            user_id=request.user_id,
            content=request.content,
            timestamp=timestamp,
        )

    def get_messages(self, request: GetMessagesRequestEntity) -> List[MessageResponseEntity]:
        """Stub get_messages operation."""
        timestamp = datetime.now(timezone.utc).isoformat()
        return [
            MessageResponseEntity(
                id=1,
                room_id=request.room_id,
                user_id=request.user_id,
                content="Hello team, welcome to the channel!",
                timestamp=timestamp,
            )
        ]

    def leave(self, request: LeaveRoomRequestEntity) -> LeaveRoomResponseEntity:
        """Stub leave operation."""
        return LeaveRoomResponseEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            status="left",
        )


# Default singleton instance
chat_manager = ChatManager()
