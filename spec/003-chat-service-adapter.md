# 003 - Chat Service Adapter Layer Specification

**Scope**: `Adapter Layer Only`  
**Status**: `Draft / For Review`  
**Problem Reference**: [`spec/problem.md`](problem.md)  
**Prerequisite Specs**: [`spec/001-chat-service-apis.md`](001-chat-service-apis.md), [`spec/002-chat-service-manager.md`](002-chat-service-manager.md)

---

## 1. Overview & Architectural Scope

This specification defines the **Adapter Layer** (`app/adapter/`) and the **Manager &harr; Adapter Contract** (`app/adapter/entities.py`) for the Chat Service.

### Core Architectural Invariant: Explicit Room Lifecycle
- **No Auto-Creation of Rooms**: Chat rooms are **never** implicitly created by joining or posting a message. Rooms must be explicitly created beforehand via a dedicated room creation API.
- **Strict Existence Precondition**: If a room does not exist, **any operation** on that room (`add_member`, `is_member`, `remove_member`, `get_members`, `save_message`, `get_messages`) MUST immediately raise `RoomNotFoundError`.

### Storage Decomposition: `UserAdapter` & `ChatAdapter`
1. **`UserAdapter`** (`app/adapter/user_adapter.py`):
   - **Sole Responsibility**: Stores all available users in the system (`add_user`, `get_user`).
   - Completely decoupled from rooms, memberships, and messages.
2. **`ChatAdapter`** (`app/adapter/chat_adapter.py`):
   - **Sole Responsibility**: Manages all chat rooms, memberships, and messages.
   - Organizes storage around **`ChatRoomRecordEntity`** aggregate roots.
   - Enforces room existence invariants across all operations.

### Layer Scope Breakdown
- **Service Layer (`app/service/`)**: *Deferred* (Will add `POST /rooms` endpoint in Service layer update).
- **Service &harr; Manager Contract (`app/manager/entities.py`)**: *Deferred* (Will add `CreateRoomRequestEntity` / `CreateRoomResponseEntity`).
- **Manager Layer (`app/manager/`)**: *Deferred* (Will add `create_room` coordination).
- **Manager &harr; Adapter Contract (`app/adapter/entities.py`)**: **In Scope**.
- **Adapter Exceptions (`app/adapter/exceptions.py`)**: **In Scope**.
- **Adapter Layer (`app/adapter/user_adapter.py`, `app/adapter/chat_adapter.py`)**: **In Scope**.
- **Adapter Tests (`tests/test_adapter.py`)**: **In Scope**.

---

## 2. Structural Architecture: `ChatRoomRecordEntity` Aggregate

Chat rooms are modeled as self-contained aggregates:

```
ChatAdapter
 └── _rooms: Dict[room_id, ChatRoomRecordEntity]
      ├── "general"
      │    ├── room_id: "general"
      │    ├── created_at: "2026-09-28T00:00:00Z"
      │    ├── memberships: Dict[user_id, RoomMembershipRecordEntity]  (O(1) lookups)
      │    └── messages: List[MessageRecordEntity]                    (Chronological timeline)
      └── "dev"
           ├── room_id: "dev"
           ├── created_at: "2026-09-28T00:05:00Z"
           ├── memberships: Dict[user_id, RoomMembershipRecordEntity]
           └── messages: List[MessageRecordEntity]
```

---

## 3. Manager &harr; Adapter Contracts & Exceptions

### 3.1 Entities (`app/adapter/entities.py`)

```python
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class UserRecordEntity:
    """Storage entity representing an available user in UserAdapter."""
    user_id: str
    created_at: str  # ISO 8601 UTC timestamp

    def to_dict(self) -> Dict[str, Any]:
        """Convert user record to dictionary."""
        return asdict(self)


@dataclass
class RoomMembershipRecordEntity:
    """Storage entity representing a user's membership in a chat room."""
    room_id: str
    user_id: str
    joined_at: str  # ISO 8601 UTC timestamp

    def to_dict(self) -> Dict[str, Any]:
        """Convert membership record to dictionary."""
        return asdict(self)


@dataclass
class MessageRecordEntity:
    """Storage entity representing a message posted in a chat room."""
    room_id: str
    user_id: str
    content: str
    timestamp: str  # ISO 8601 UTC timestamp
    id: Optional[int] = None  # Assigned by ChatAdapter upon persistence

    def to_dict(self) -> Dict[str, Any]:
        """Convert message record to dictionary."""
        return asdict(self)


@dataclass
class ChatRoomRecordEntity:
    """Storage aggregate entity representing a chat room, its members, and messages."""
    room_id: str
    created_at: str  # ISO 8601 UTC timestamp
    # Key: user_id -> RoomMembershipRecordEntity for O(1) membership checks
    memberships: Dict[str, RoomMembershipRecordEntity] = field(default_factory=dict)
    # Ordered message history
    messages: List[MessageRecordEntity] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert chat room aggregate to dictionary."""
        return {
            "room_id": self.room_id,
            "created_at": self.created_at,
            "memberships": {uid: m.to_dict() for uid, m in self.memberships.items()},
            "messages": [msg.to_dict() for msg in self.messages],
        }
```

### 3.2 Adapter Layer Exceptions (`app/adapter/exceptions.py`)

```python
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
```

---

## 4. Adapter Implementations

### 4.1 User Adapter (`app/adapter/user_adapter.py`)

Stores all available users in the system.

```python
"""In-memory persistence adapter for available users."""

from typing import Dict, Optional
from app.adapter.entities import UserRecordEntity


class UserAdapter:
    """In-memory adapter storing available users."""

    def __init__(self) -> None:
        # Key: user_id -> Value: UserRecordEntity
        self._users: Dict[str, UserRecordEntity] = {}

    def add_user(self, record: UserRecordEntity) -> UserRecordEntity:
        """Register an available user (idempotent).
        
        If user already exists, returns the existing record.
        """
        if record.user_id not in self._users:
            self._users[record.user_id] = record
        return self._users[record.user_id]

    def get_user(self, user_id: str) -> Optional[UserRecordEntity]:
        """Retrieve user by user_id, or None if not found (used for existence checks)."""
        return self._users.get(user_id)

    def clear(self) -> None:
        """Clear all stored users (useful for test resets)."""
        self._users.clear()
```

---

### 4.2 Chat Adapter (`app/adapter/chat_adapter.py`)

Manages chat rooms as aggregates. Enforces that the room must exist before any operation can proceed.

```python
"""In-memory persistence adapter for chat rooms, memberships, and messages."""

from typing import Dict, List, Optional
from app.adapter.entities import (
    ChatRoomRecordEntity,
    MessageRecordEntity,
    RoomMembershipRecordEntity,
)
from app.adapter.exceptions import (
    RoomAlreadyExistsError,
    RoomNotFoundError,
    UserNotMemberError,
)


class ChatAdapter:
    """In-memory adapter managing chat room aggregates."""

    def __init__(self) -> None:
        # Key: room_id -> Value: ChatRoomRecordEntity
        self._rooms: Dict[str, ChatRoomRecordEntity] = {}
        self._next_message_id: int = 1

    # ==========================================================================
    # Room Management Operations
    # ==========================================================================

    def create_room(self, record: ChatRoomRecordEntity) -> ChatRoomRecordEntity:
        """Explicitly create a new chat room.
        
        Raises:
            RoomAlreadyExistsError: If a room with this ID already exists.
        """
        if record.room_id in self._rooms:
            raise RoomAlreadyExistsError(record.room_id)
        self._rooms[record.room_id] = record
        return record

    def get_room(self, room_id: str) -> Optional[ChatRoomRecordEntity]:
        """Retrieve room entity if it exists, otherwise None."""
        return self._rooms.get(room_id)

    def room_exists(self, room_id: str) -> bool:
        """Check whether a chat room currently exists."""
        return room_id in self._rooms

    # ==========================================================================
    # Room Membership Operations (Room Must Exist)
    # ==========================================================================

    def add_member(self, record: RoomMembershipRecordEntity) -> RoomMembershipRecordEntity:
        """Add a user to an existing room (idempotent).
        
        Raises:
            RoomNotFoundError: If the room does not exist.
        """
        room = self.get_room(record.room_id)
        if room is None:
            raise RoomNotFoundError(record.room_id)

        if record.user_id not in room.memberships:
            room.memberships[record.user_id] = record
        return room.memberships[record.user_id]

    def is_member(self, room_id: str, user_id: str) -> bool:
        """Check if a user is a member of an existing room.
        
        Raises:
            RoomNotFoundError: If the room does not exist.
        """
        room = self.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        return user_id in room.memberships

    def remove_member(self, room_id: str, user_id: str) -> bool:
        """Remove a user from an existing room.
        
        Raises:
            RoomNotFoundError: If the room does not exist.
        """
        room = self.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)

        if user_id in room.memberships:
            del room.memberships[user_id]
            return True
        return False

    def get_members(self, room_id: str) -> List[RoomMembershipRecordEntity]:
        """Retrieve all active member records for an existing room.
        
        Raises:
            RoomNotFoundError: If the room does not exist.
        """
        room = self.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        return list(room.memberships.values())

    # ==========================================================================
    # Message Operations (Room Must Exist & User Must Be Member)
    # ==========================================================================

    def save_message(self, record: MessageRecordEntity) -> MessageRecordEntity:
        """Persist a message to the room's message history.
        
        Preconditions:
        - The room MUST exist (does NOT auto-create rooms).
        - The user MUST be a current member of the room.
        
        Raises:
            RoomNotFoundError: If the room does not exist.
            UserNotMemberError: If the user is not a member of the room.
        """
        room = self.get_room(record.room_id)
        if room is None:
            raise RoomNotFoundError(record.room_id)

        if record.user_id not in room.memberships:
            raise UserNotMemberError(
                room_id=record.room_id,
                user_id=record.user_id,
                action="sending messages",
            )

        if record.id is None:
            record.id = self._next_message_id
            self._next_message_id += 1

        room.messages.append(record)
        return record

    def get_messages(self, room_id: str) -> List[MessageRecordEntity]:
        """Retrieve all messages for a specific room in chronological order.
        
        Raises:
            RoomNotFoundError: If the room does not exist.
        """
        room = self.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        return list(room.messages)

    # ==========================================================================
    # State Reset
    # ==========================================================================

    def clear(self) -> None:
        """Clear all stored rooms, memberships, and messages, resetting ID counter."""
        self._rooms.clear()
        self._next_message_id = 1
```

---

## 5. Package Exports (`app/adapter/__init__.py`)

```python
"""Adapter package exports."""

from app.adapter.chat_adapter import ChatAdapter
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
from app.adapter.user_adapter import UserAdapter

# Default singletons
user_adapter = UserAdapter()
chat_adapter = ChatAdapter()

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
```

---

## 6. How Service & Manager Layers Will Integrate (Preview)

### 6.1 Service Layer: Dedicated Room Creation Route (`app/service/api.py`)
```python
@app.route("/rooms", methods=["POST"])
def create_room():
    data = request.get_json(silent=True)
    if data is None or "room_id" not in data:
        return jsonify({"error": "Bad Request", "message": "'room_id' is required"}), 400

    request_entity = CreateRoomRequestEntity(room_id=data["room_id"])
    response_entity = chat_manager.create_room(request_entity)
    return jsonify(response_entity.to_dict()), 201
```

### 6.2 Manager Layer Orchestration (`app/manager/chat_manager.py`)
```python
class ChatManager:
    def __init__(
        self,
        user_adapter: Optional[UserAdapter] = None,
        chat_adapter: Optional[ChatAdapter] = None,
    ) -> None:
        self.user_adapter = user_adapter or UserAdapter()
        self.chat_adapter = chat_adapter or ChatAdapter()

    def create_room(self, req: CreateRoomRequestEntity) -> CreateRoomResponseEntity:
        record = ChatRoomRecordEntity(
            room_id=req.room_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        saved = self.chat_adapter.create_room(record)
        return CreateRoomResponseEntity(room_id=saved.room_id, created_at=saved.created_at)

    def join(self, req: JoinRoomRequestEntity) -> JoinRoomResponseEntity:
        # Precondition: Room must exist
        if not self.chat_adapter.room_exists(req.room_id):
            raise RoomNotFoundError(req.room_id)

        # Register user in user store if new
        if self.user_adapter.get_user(req.user_id) is None:
            self.user_adapter.add_user(
                UserRecordEntity(user_id=req.user_id, created_at=datetime.now(timezone.utc).isoformat())
            )

        # Add member to room
        record = RoomMembershipRecordEntity(
            room_id=req.room_id,
            user_id=req.user_id,
            joined_at=datetime.now(timezone.utc).isoformat(),
        )
        self.chat_adapter.add_member(record)
        return JoinRoomResponseEntity(room_id=req.room_id, user_id=req.user_id, status="joined")

    def send_message(self, req: SendMessageRequestEntity) -> MessageResponseEntity:
        # Preconditions: Room must exist & user must be a member
        if not self.chat_adapter.room_exists(req.room_id):
            raise RoomNotFoundError(req.room_id)
        if not self.chat_adapter.is_member(req.room_id, req.user_id):
            raise UserNotMemberError(req.room_id, req.user_id, action="sending messages")

        record = MessageRecordEntity(
            room_id=req.room_id,
            user_id=req.user_id,
            content=req.content,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        saved = self.chat_adapter.save_message(record)
        return MessageResponseEntity(
            id=saved.id,
            room_id=saved.room_id,
            user_id=saved.user_id,
            content=saved.content,
            timestamp=saved.timestamp,
        )

    def get_messages(self, req: GetMessagesRequestEntity) -> List[MessageResponseEntity]:
        if not self.chat_adapter.room_exists(req.room_id):
            raise RoomNotFoundError(req.room_id)
        if not self.chat_adapter.is_member(req.room_id, req.user_id):
            raise UserNotMemberError(req.room_id, req.user_id, action="retrieving messages")

        messages = self.chat_adapter.get_messages(req.room_id)
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

    def leave(self, req: LeaveRoomRequestEntity) -> LeaveRoomResponseEntity:
        if not self.chat_adapter.room_exists(req.room_id):
            raise RoomNotFoundError(req.room_id)

        self.chat_adapter.remove_member(req.room_id, req.user_id)
        return LeaveRoomResponseEntity(room_id=req.room_id, user_id=req.user_id, status="left")
```

---

## 7. Adapter Layer Test Plan (`tests/test_adapter.py`)

### 7.1 `UserAdapter` Tests
1. **`test_add_user_success`**: Adds a user; returns `UserRecordEntity` and `get_user` returns the stored entity.
2. **`test_add_user_idempotent`**: Adding existing user returns existing record without duplicating.
3. **`test_get_user_found_and_not_found`**: Returns entity if present, `None` if absent (used for existence verification).
4. **`test_user_adapter_clear`**: Clears user store; subsequent `get_user` returns `None`.

### 7.2 `ChatAdapter` Tests
#### Room Creation & Existence
1. **`test_create_room_success`**: Explicitly creates a `ChatRoomRecordEntity`; `room_exists` returns `True`.
2. **`test_create_room_already_exists_raises_error`**: Creating a room with existing ID raises `RoomAlreadyExistsError`.
3. **`test_get_room_non_existent_returns_none`**: `get_room` returns `None` for uncreated rooms.

#### Room Existence Invariant Enforced Across All Operations
4. **`test_add_member_room_not_found_raises_error`**: `add_member` to a non-existent room raises `RoomNotFoundError` (does NOT auto-create).
5. **`test_is_member_room_not_found_raises_error`**: `is_member` on a non-existent room raises `RoomNotFoundError`.
6. **`test_remove_member_room_not_found_raises_error`**: `remove_member` on a non-existent room raises `RoomNotFoundError`.
7. **`test_get_members_room_not_found_raises_error`**: `get_members` on a non-existent room raises `RoomNotFoundError`.
8. **`test_save_message_room_not_found_raises_error`**: `save_message` on a non-existent room raises `RoomNotFoundError` (does NOT auto-create).
9. **`test_get_messages_room_not_found_raises_error`**: `get_messages` on a non-existent room raises `RoomNotFoundError`.

#### Membership & Messaging in Existing Rooms
10. **`test_add_member_to_existing_room_success`**: In created room, `add_member` adds user; `is_member` returns `True`.
11. **`test_add_member_idempotent`**: Adding member twice succeeds without duplicate entries.
12. **`test_remove_member_from_existing_room`**: Joined member is removed; returns `True` and `is_member` becomes `False`.
13. **`test_get_members_by_room`**: Returns all members in an existing room.
14. **`test_save_message_user_not_member_raises_error`**: In existing room, saving message by non-member raises `UserNotMemberError`.
15. **`test_save_message_as_member_success`**: Joined member successfully posts; auto-increment ID (`1`, `2`) is assigned.
16. **`test_get_messages_chronological_order`**: Messages are returned in exact insertion order.
17. **`test_get_messages_empty_room`**: Empty list `[]` returned for an existing room with no messages.
18. **`test_multi_room_isolation`**: Memberships and messages in `room-1` do not leak into `room-2`.
19. **`test_chat_adapter_clear`**: Clears all rooms, memberships, messages, and resets ID counter.
