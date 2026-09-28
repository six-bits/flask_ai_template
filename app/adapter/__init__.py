"""Adapter package exports."""

from app.adapter.chat_adapter import ChatAdapter, chat_adapter
from app.adapter.entities import (
    ChatRoomRecordEntity,
    GreetingRecordEntity,
    MessageRecordEntity,
    RoomMembershipRecordEntity,
    UserRecordEntity,
)
from app.adapter.exceptions import (
    AdapterError,
    RoomAlreadyExistsError,
    RoomNotFoundError,
    UserNotMemberError,
)
from app.adapter.greeting_adapter import GreetingAdapter, greeting_adapter
from app.adapter.user_adapter import UserAdapter, user_adapter

__all__ = [
    "UserRecordEntity",
    "RoomMembershipRecordEntity",
    "MessageRecordEntity",
    "ChatRoomRecordEntity",
    "GreetingRecordEntity",
    "UserAdapter",
    "ChatAdapter",
    "GreetingAdapter",
    "AdapterError",
    "RoomNotFoundError",
    "RoomAlreadyExistsError",
    "UserNotMemberError",
    "user_adapter",
    "chat_adapter",
    "greeting_adapter",
]
