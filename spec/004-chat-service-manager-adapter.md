# 004 - Chat Service Manager Layer & Adapter Interaction Specification

**Scope**: `Manager Layer Only (Manager <-> Adapter Integration)`  
**Status**: `Draft / For Review`  
**Problem Reference**: [`spec/problem.md`](problem.md)  
**Prerequisite Specs**: [`spec/001-chat-service-apis.md`](001-chat-service-apis.md), [`spec/002-chat-service-manager.md`](002-chat-service-manager.md), [`spec/003-chat-service-adapter.md`](003-chat-service-adapter.md)

---

## 1. Overview & Architectural Scope

This specification defines the complete business logic and validation coordination in the **Manager Layer** (`app/manager/chat_manager.py`) and its interaction with the **Adapter Layer** (`UserAdapter` and `ChatAdapter`).

### Core Responsibilities of the Manager Layer
1. **API Requirements Fulfillment**: Expose high-level domain operations (`create_room`, `register_user`, `join`, `send_message`, `get_messages`, `leave`).
2. **Strict Validation & Failure Handling**: Validate all preconditions before performing any state modification:
   - Validate that the referenced user exists in `UserAdapter` (or raise `UserNotFoundError`).
   - Validate that the referenced room exists in `ChatAdapter` (or raise `RoomNotFoundError`).
   - Validate that duplicate rooms or users are prevented on creation (or raise `RoomAlreadyExistsError` / `UserAlreadyExistsError`).
   - Validate that the user is an active member of the room before sending or retrieving messages (or raise `UserNotMemberError`).
3. **Layer Decoupling**:
   - Accepts dataclass request entities from the Service layer (`app/manager/entities.py`).
   - Maps to/from Adapter contract entities (`app/adapter/entities.py`).
   - Returns dataclass response entities to the Service layer (`app/manager/entities.py`).
   - Throws explicit domain exceptions (`app/manager/exceptions.py`).

### Layer Scope Breakdown
- **Service Layer (`app/service/`)**: *Deferred* (Updating `api.py` and translating new exceptions to HTTP error codes will be handled in a separate subsequent spec).
- **Service &harr; Manager Contract (`app/manager/entities.py`)**: **In Scope** (Adding `CreateRoomRequestEntity`, `CreateRoomResponseEntity`, `RegisterUserRequestEntity`, `RegisterUserResponseEntity`).
- **Domain Exceptions (`app/manager/exceptions.py`)**: **In Scope** (Adding `UserNotFoundError`, `RoomAlreadyExistsError`, `UserAlreadyExistsError`).
- **Manager Layer (`app/manager/chat_manager.py`)**: **In Scope** (Implementing full business logic and validation).
- **Adapter Layer (`app/adapter/`)**: *Deferred / Referenced* (Already implemented in Spec 003).
- **Manager Tests (`tests/test_manager.py`)**: **In Scope** (Integration tests verifying manager logic with real adapters).

---

## 2. Domain Exceptions (`app/manager/exceptions.py`)

The manager defines explicit exceptions for every business rule violation:

```python
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
```

---

## 3. Service &harr; Manager Contract Entities (`app/manager/entities.py`)

The contract between Service and Manager is extended with room creation and user registration entities:

```python
from dataclasses import asdict, dataclass
from typing import Any, Dict


# --- Room Creation ---

@dataclass
class CreateRoomRequestEntity:
    """Request entity to explicitly create a chat room."""
    room_id: str


@dataclass
class CreateRoomResponseEntity:
    """Response entity after creating a chat room."""
    room_id: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --- User Registration ---

@dataclass
class RegisterUserRequestEntity:
    """Request entity to register an available user."""
    user_id: str


@dataclass
class RegisterUserResponseEntity:
    """Response entity after registering an available user."""
    user_id: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --- Room Membership & Messaging ---

@dataclass
class JoinRoomRequestEntity:
    room_id: str
    user_id: str


@dataclass
class JoinRoomResponseEntity:
    room_id: str
    user_id: str
    status: str = "joined"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SendMessageRequestEntity:
    room_id: str
    user_id: str
    content: str


@dataclass
class MessageResponseEntity:
    id: int
    room_id: str
    user_id: str
    content: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GetMessagesRequestEntity:
    room_id: str
    user_id: str


@dataclass
class LeaveRoomRequestEntity:
    room_id: str
    user_id: str


@dataclass
class LeaveRoomResponseEntity:
    room_id: str
    user_id: str
    status: str = "left"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

---

## 4. Manager Layer Implementation (`app/manager/chat_manager.py`)

The `ChatManager` coordinates the two adapters (`UserAdapter` and `ChatAdapter`) while enforcing all business constraints:

```python
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
```

---

## 5. Package Exports (`app/manager/__init__.py`)

```python
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

__all__ = [
    "ChatManager",
    "chat_manager",
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
```

---

## 6. Manager Layer Test Plan (`tests/test_manager.py`)

Unit/integration tests verifying `ChatManager` coordinating with fresh `UserAdapter` and `ChatAdapter` instances:

### 6.1 User & Room Management Tests
1. **`test_register_user_success`**: Registers a new user; returns `RegisterUserResponseEntity`.
2. **`test_register_user_already_exists_raises_error`**: Attempting to register existing user raises `UserAlreadyExistsError`.
3. **`test_create_room_success`**: Creates a new room; returns `CreateRoomResponseEntity`.
4. **`test_create_room_already_exists_raises_error`**: Creating duplicate room ID raises `RoomAlreadyExistsError`.

### 6.2 Precondition Failures (User & Room Validations)
5. **`test_join_user_not_found_raises_error`**: Joining with unregistered user raises `UserNotFoundError`.
6. **`test_join_room_not_found_raises_error`**: Registered user joining non-existent room raises `RoomNotFoundError`.
7. **`test_send_message_user_not_found_raises_error`**: Unregistered user sending message raises `UserNotFoundError`.
8. **`test_send_message_room_not_found_raises_error`**: Registered user sending message to non-existent room raises `RoomNotFoundError`.
9. **`test_send_message_user_not_member_raises_error`**: Registered user sending message to existing room without joining raises `UserNotMemberError`.
10. **`test_get_messages_user_not_found_raises_error`**: Unregistered user retrieving messages raises `UserNotFoundError`.
11. **`test_get_messages_room_not_found_raises_error`**: Registered user retrieving messages from non-existent room raises `RoomNotFoundError`.
12. **`test_get_messages_user_not_member_raises_error`**: Registered user retrieving messages from existing room without joining raises `UserNotMemberError`.
13. **`test_leave_room_user_not_found_raises_error`**: Unregistered user leaving raises `UserNotFoundError`.
14. **`test_leave_room_room_not_found_raises_error`**: Registered user leaving non-existent room raises `RoomNotFoundError`.

### 6.3 Happy Path & Full Domain Workflow
15. **`test_join_room_success`**: Registered user successfully joins existing room; returns `status="joined"`.
16. **`test_join_room_idempotent`**: Joining an already joined room succeeds without error.
17. **`test_send_message_success`**: Joined user sends message; returns `MessageResponseEntity` with monotonic ID and timestamp.
18. **`test_get_messages_success`**: Joined user retrieves message list in chronological order.
19. **`test_leave_room_success`**: Joined user leaves room; returns `status="left"`.
20. **`test_send_message_after_leave_raises_user_not_member`**: User cannot send messages after leaving room.
21. **`test_get_messages_after_leave_raises_user_not_member`**: User cannot retrieve messages after leaving room.
22. **`test_multi_room_isolation_via_manager`**: User in `room-1` cannot read or write to `room-2` without joining; messages in `room-1` do not appear in `room-2`.
