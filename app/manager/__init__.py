"""Manager package exports."""

from app.manager.chat_manager import ChatManager, chat_manager
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
    ChatManagerError,
    RoomAlreadyExistsError,
    RoomNotFoundError,
    UserAlreadyExistsError,
    UserNotFoundError,
    UserNotMemberError,
)
from app.manager.messages_manager import MessagesManager, messages_manager
from app.manager.user_manager import UserManager, user_manager

__all__ = [
    "UserManager",
    "user_manager",
    "ChatManager",
    "chat_manager",
    "MessagesManager",
    "messages_manager",
    "CreateRoomRequestEntity",
    "CreateRoomResponseEntity",
    "RegisterUserRequestEntity",
    "RegisterUserResponseEntity",
    "JoinRoomRequestEntity",
    "JoinRoomResponseEntity",
    "SendMessageRequestEntity",
    "MessageResponseEntity",
    "GetMessagesRequestEntity",
    "LeaveRoomRequestEntity",
    "LeaveRoomResponseEntity",
    "ChatManagerError",
    "UserNotFoundError",
    "RoomNotFoundError",
    "RoomAlreadyExistsError",
    "UserAlreadyExistsError",
    "UserNotMemberError",
]
