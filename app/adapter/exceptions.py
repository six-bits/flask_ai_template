"""Adapter exceptions for persistence errors."""


class AdapterError(Exception):
    """Base exception for all adapter errors."""
    pass


class RoomNotFoundError(AdapterError):
    """Raised when an operation targets a room that does not exist."""
    def __init__(self, room_id: str):
        self.room_id = room_id
        super().__init__(f"Room '{room_id}' was not found")


class RoomAlreadyExistsError(AdapterError):
    """Raised when attempting to create a room that already exists."""
    def __init__(self, room_id: str):
        self.room_id = room_id
        super().__init__(f"Room '{room_id}' already exists")


class UserNotMemberError(AdapterError):
    """Raised when an operation requires room membership that is missing."""
    def __init__(self, room_id: str, user_id: str, action: str = "access"):
        self.room_id = room_id
        self.user_id = user_id
        self.action = action
        super().__init__(f"User '{user_id}' must join room '{room_id}' before {action}")
