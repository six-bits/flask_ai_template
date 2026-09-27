"""Manager package for Chat Service."""

from app.manager.chat_manager import ChatManager, chat_manager
from app.manager.entities import (
    GetMessagesRequestEntity,
    JoinRoomRequestEntity,
    JoinRoomResponseEntity,
    LeaveRoomRequestEntity,
    LeaveRoomResponseEntity,
    MessageResponseEntity,
    SendMessageRequestEntity,
)
from app.manager.exceptions import (
    ChatManagerError,
    RoomNotFoundError,
    UserNotMemberError,
)

__all__ = [
    "ChatManager",
    "chat_manager",
    "JoinRoomRequestEntity",
    "JoinRoomResponseEntity",
    "SendMessageRequestEntity",
    "MessageResponseEntity",
    "GetMessagesRequestEntity",
    "LeaveRoomRequestEntity",
    "LeaveRoomResponseEntity",
    "ChatManagerError",
    "UserNotMemberError",
    "RoomNotFoundError",
]
