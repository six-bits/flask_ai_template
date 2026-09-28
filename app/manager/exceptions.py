"""Domain exceptions for the Chat Service manager layer."""


class ChatManagerError(Exception):
    """Base exception for all chat manager errors."""
    pass


class UserNotFoundError(ChatManagerError):
    """Raised when an operation references a user that does not exist."""
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"User '{user_id}' was not found")


class RoomNotFoundError(ChatManagerError):
    """Raised when an operation targets a room that does not exist."""
    def __init__(self, room_id: str):
        self.room_id = room_id
        super().__init__(f"Room '{room_id}' was not found")


class RoomAlreadyExistsError(ChatManagerError):
    """Raised when attempting to create a room that already exists."""
    def __init__(self, room_id: str):
        self.room_id = room_id
        super().__init__(f"Room '{room_id}' already exists")


class UserAlreadyExistsError(ChatManagerError):
    """Raised when attempting to register a user that already exists."""
    def __init__(self, user_id: str):
        self.user_id = user_id
        super().__init__(f"User '{user_id}' already exists")


class UserNotMemberError(ChatManagerError):
    """Raised when a user attempts an operation in a room they have not joined."""
    def __init__(self, room_id: str, user_id: str, action: str = "access"):
        self.room_id = room_id
        self.user_id = user_id
        self.action = action
        super().__init__(f"User '{user_id}' must join room '{room_id}' before {action}")
