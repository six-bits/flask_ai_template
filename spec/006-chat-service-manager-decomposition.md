# 006 - Chat Service Manager Layer Decomposition Specification

**Scope**: `Manager Layer Refactoring & Decomposition`  
**Status**: `Implemented`  
**Problem Reference**: [`spec/problem.md`](problem.md)  
**Prerequisite Specs**: [`spec/004-chat-service-manager-adapter.md`](004-chat-service-manager-adapter.md), [`spec/005-chat-service-e2e-integration.md`](005-chat-service-e2e-integration.md)

---

## 1. Overview & Architectural Scope

This specification defines the decomposition of the unified `ChatManager` into three focused, single-responsibility managers:

1. **`UserManager`** (`app/manager/user_manager.py`):
   - **Responsibility**: Manages user registration, user existence checks, and user lifecycle validation.
   - Interacts with: [`UserAdapter`](app/adapter/user_adapter.py).
2. **`ChatManager`** (`app/manager/chat_manager.py`):
   - **Responsibility**: Manages chat room lifecycle and room membership operations (`create_room`, `join`, `leave`, membership verification).
   - Interacts with: [`ChatAdapter`](app/adapter/chat_adapter.py) and [`UserManager`](app/manager/user_manager.py).
3. **`MessagesManager`** (`app/manager/messages_manager.py`):
   - **Responsibility**: Manages message operations within rooms (`send_message`, `get_messages`).
   - Interacts with: [`ChatAdapter`](app/adapter/chat_adapter.py), [`UserManager`](app/manager/user_manager.py), and [`ChatManager`](app/manager/chat_manager.py).

### Architectural Benefits
- **Single Responsibility Principle (SRP)**: Separates user identity, room membership state, and message timeline management into distinct domain boundaries.
- **Independent Testability**: Each manager can be unit-tested in isolation with its specific dependencies mocked or injected.
- **Clean Service Consumption**: The HTTP Service layer (`api.py`) routes requests to the exact manager responsible for that domain concern (`chat_manager` for room membership, `messages_manager` for messages).

---

## 2. Manager Specifications

```
app/manager/
├── __init__.py               # Exports user_manager, chat_manager, messages_manager, entities, exceptions
├── entities.py               # Shared Service <-> Manager contract dataclasses
├── exceptions.py             # Shared domain exceptions
├── user_manager.py           # UserManager: user registration & existence verification
├── chat_manager.py           # ChatManager: room lifecycle & room memberships
└── messages_manager.py       # MessagesManager: message publishing & retrieval
```

---

### 2.1 User Manager (`app/manager/user_manager.py`)

Handles user registration and existence validations:

```python
"""User Manager handling user lifecycle and existence verification."""

from datetime import datetime, timezone
from typing import Optional

from app.adapter.entities import UserRecordEntity
from app.adapter.user_adapter import UserAdapter, user_adapter as default_user_adapter
from app.manager.entities import (
    RegisterUserRequestEntity,
    RegisterUserResponseEntity,
)
from app.manager.exceptions import (
    UserAlreadyExistsError,
    UserNotFoundError,
)


class UserManager:
    """Manager handling user lifecycle and existence validations."""

    def __init__(self, user_adapter: Optional[UserAdapter] = None) -> None:
        self.user_adapter = user_adapter or default_user_adapter

    def register_user(self, request: RegisterUserRequestEntity) -> RegisterUserResponseEntity:
        """Register a new user in the user store.
        
        Raises:
            UserAlreadyExistsError: If user_id is already registered.
        """
        existing = self.user_adapter.get_user(request.user_id)
        if existing is not None:
            raise UserAlreadyExistsError(request.user_id)

        now = datetime.now(timezone.utc).isoformat()
        record = UserRecordEntity(user_id=request.user_id, created_at=now)
        saved = self.user_adapter.add_user(record)
        return RegisterUserResponseEntity(user_id=saved.user_id, created_at=saved.created_at)

    def ensure_user_exists(self, user_id: str) -> None:
        """Validate user existence, raising UserNotFoundError if not registered."""
        if self.user_adapter.get_user(user_id) is None:
            raise UserNotFoundError(user_id)

    def user_exists(self, user_id: str) -> bool:
        """Check whether a user is registered."""
        return self.user_adapter.get_user(user_id) is not None


# Default singleton instance
user_manager = UserManager()
```

---

### 2.2 Chat Manager (`app/manager/chat_manager.py`)

Handles chat room creation, room existence, and room membership operations (`join`, `leave`, `is_member`):

```python
"""Chat Manager handling room lifecycle and membership operations."""

from datetime import datetime, timezone
from typing import Optional

from app.adapter.chat_adapter import ChatAdapter, chat_adapter as default_chat_adapter
from app.adapter.entities import ChatRoomRecordEntity, RoomMembershipRecordEntity
from app.manager.entities import (
    CreateRoomRequestEntity,
    CreateRoomResponseEntity,
    JoinRoomRequestEntity,
    JoinRoomResponseEntity,
    LeaveRoomRequestEntity,
    LeaveRoomResponseEntity,
)
from app.manager.exceptions import (
    RoomAlreadyExistsError,
    RoomNotFoundError,
)
from app.manager.user_manager import UserManager, user_manager as default_user_manager


class ChatManager:
    """Manager coordinating chat room lifecycle and membership operations."""

    def __init__(
        self,
        chat_adapter: Optional[ChatAdapter] = None,
        user_manager: Optional[UserManager] = None,
    ) -> None:
        self.chat_adapter = chat_adapter or default_chat_adapter
        self.user_manager = user_manager or default_user_manager

    def create_room(self, request: CreateRoomRequestEntity) -> CreateRoomResponseEntity:
        """Create a new chat room.
        
        Raises:
            RoomAlreadyExistsError: If room_id already exists.
        """
        if self.chat_adapter.room_exists(request.room_id):
            raise RoomAlreadyExistsError(request.room_id)

        now = datetime.now(timezone.utc).isoformat()
        record = ChatRoomRecordEntity(room_id=request.room_id, created_at=now)
        saved = self.chat_adapter.create_room(record)
        return CreateRoomResponseEntity(room_id=saved.room_id, created_at=saved.created_at)

    def join(self, request: JoinRoomRequestEntity) -> JoinRoomResponseEntity:
        """Join an existing chat room.
        
        Preconditions:
        - User must exist in UserManager.
        - Room must exist in ChatAdapter.
        
        Raises:
            UserNotFoundError: If user_id is not registered.
            RoomNotFoundError: If room_id does not exist.
        """
        self.user_manager.ensure_user_exists(request.user_id)
        self.ensure_room_exists(request.room_id)

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
        - User must exist in UserManager.
        - Room must exist in ChatAdapter.
        
        Raises:
            UserNotFoundError: If user_id is not registered.
            RoomNotFoundError: If room_id does not exist.
        """
        self.user_manager.ensure_user_exists(request.user_id)
        self.ensure_room_exists(request.room_id)

        self.chat_adapter.remove_member(request.room_id, request.user_id)
        return LeaveRoomResponseEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            status="left",
        )

    def is_member(self, room_id: str, user_id: str) -> bool:
        """Check if a user is a member of an existing room."""
        return self.chat_adapter.is_member(room_id, user_id)

    def ensure_room_exists(self, room_id: str) -> None:
        """Validate room existence, raising RoomNotFoundError if not found."""
        if not self.chat_adapter.room_exists(room_id):
            raise RoomNotFoundError(room_id)


# Default singleton instance
chat_manager = ChatManager()
```

---

### 2.3 Messages Manager (`app/manager/messages_manager.py`)

Handles sending and retrieving messages in chat rooms:

```python
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
```

---

## 3. Package Exports (`app/manager/__init__.py`)

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
```

---

## 4. Service Layer Wiring (`app/service/api.py`)

In `api.py`, endpoints map directly to their specialized manager:

```python
from app.manager import chat_manager, messages_manager

# Join Room -> ChatManager
@app.route("/rooms/<room_id>/join", methods=["POST"])
def join_room(room_id: str):
    ...
    response_entity = chat_manager.join(request_entity)
    return jsonify(response_entity.to_dict()), 200

# Leave Room -> ChatManager
@app.route("/rooms/<room_id>/leave", methods=["POST"])
def leave_room(room_id: str):
    ...
    response_entity = chat_manager.leave(request_entity)
    return jsonify(response_entity.to_dict()), 200

# Send Message -> MessagesManager
@app.route("/rooms/<room_id>/messages", methods=["POST"])
def send_message(room_id: str):
    ...
    response_entity = messages_manager.send_message(request_entity)
    return jsonify(response_entity.to_dict()), 201

# Get Messages -> MessagesManager
@app.route("/rooms/<room_id>/messages", methods=["GET"])
def get_messages(room_id: str):
    ...
    messages = messages_manager.get_messages(request_entity)
    return jsonify([m.to_dict() for m in messages]), 200
```

---

## 5. Test Environment Provisioning (`tests/conftest.py`)

Test setup uses `user_manager` for users and `chat_manager` for rooms:

```python
@pytest.fixture
def client():
    """Create Flask test client with pre-provisioned users and rooms."""
    app.config["TESTING"] = True

    # 1. Reset state
    user_manager.user_adapter.clear()
    chat_manager.chat_adapter.clear()

    # 2. Provision test users via UserManager
    user_manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    user_manager.register_user(RegisterUserRequestEntity(user_id="bob"))
    user_manager.register_user(RegisterUserRequestEntity(user_id="charlie"))

    # 3. Provision test rooms via ChatManager
    chat_manager.create_room(CreateRoomRequestEntity(room_id="general"))
    chat_manager.create_room(CreateRoomRequestEntity(room_id="random"))
    chat_manager.create_room(CreateRoomRequestEntity(room_id="dev"))

    with app.test_client() as client:
        yield client
```

---

## 6. Test Plan (`tests/test_manager.py`)

Unit tests verifying each manager in isolation with fresh adapters:

### 6.1 `UserManager` Tests
1. **`test_register_user_success`**: Registers new user; returns entity.
2. **`test_register_user_already_exists_raises_error`**: Duplicate user raises `UserAlreadyExistsError`.
3. **`test_ensure_user_exists_success`**: Passes when user exists.
4. **`test_ensure_user_exists_raises_user_not_found`**: Raises `UserNotFoundError` when user does not exist.

### 6.2 `ChatManager` Tests
5. **`test_create_room_success`**: Creates room; returns entity.
6. **`test_create_room_already_exists_raises_error`**: Duplicate room raises `RoomAlreadyExistsError`.
7. **`test_join_user_not_found_raises_error`**: Unregistered user joining raises `UserNotFoundError`.
8. **`test_join_room_not_found_raises_error`**: Joining non-existent room raises `RoomNotFoundError`.
9. **`test_join_room_success`**: Registered user joining existing room returns `status="joined"`.
10. **`test_join_room_idempotent`**: Joining existing room twice succeeds without duplicate error.
11. **`test_leave_room_user_not_found_raises_error`**: Unregistered user leaving raises `UserNotFoundError`.
12. **`test_leave_room_room_not_found_raises_error`**: Leaving non-existent room raises `RoomNotFoundError`.
13. **`test_leave_room_success`**: Joined user leaves room; returns `status="left"`.

### 6.3 `MessagesManager` Tests
14. **`test_send_message_user_not_found_raises_error`**: Unregistered user sending message raises `UserNotFoundError`.
15. **`test_send_message_room_not_found_raises_error`**: Sending message to non-existent room raises `RoomNotFoundError`.
16. **`test_send_message_user_not_member_raises_error`**: Non-member sending message raises `UserNotMemberError`.
17. **`test_send_message_success`**: Joined member sending message returns `MessageResponseEntity` with monotonic ID.
18. **`test_get_messages_user_not_found_raises_error`**: Unregistered user reading messages raises `UserNotFoundError`.
19. **`test_get_messages_room_not_found_raises_error`**: Reading messages from non-existent room raises `RoomNotFoundError`.
20. **`test_get_messages_user_not_member_raises_error`**: Non-member reading messages raises `UserNotMemberError`.
21. **`test_get_messages_success`**: Joined member reading messages receives chronological list.
22. **`test_send_message_after_leave_raises_user_not_member`**: Cannot send messages after leaving room.
23. **`test_get_messages_after_leave_raises_user_not_member`**: Cannot read messages after leaving room.
24. **`test_multi_room_isolation_via_messages_manager`**: Messages in `room-1` do not leak into `room-2`.
