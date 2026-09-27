# 002 - Chat Service Manager Layer Specification

**Scope**: `Manager Layer Only`  
**Status**: `Draft / For Review`  
**Problem Reference**: [`spec/problem.md`](problem.md)  
**Prerequisite Spec**: [`spec/001-chat-service-apis.md`](001-chat-service-apis.md)

---

## 1. Overview & Architecture Scope

This specification defines the **Manager Layer** (`app/manager/`) for the Chat Service. The manager layer coordinates the business logic, enforces business rules (such as room membership validation), and mediates between the **Service Layer** and the **Adapter Layer**.

### Architectural Principles
- **Unified Manager Design**: A single `ChatManager` class encapsulates all room operations (`join`, `send_message`, `get_messages`, `leave`).
- **Contract & Stub Strategy**: For this phase, the manager layer defines the complete entity contracts and interfaces with stubbed responses. Deep business rules (membership persistence/state tracking) are deferred to subsequent adapter integration.
- **Entity Contracts**: Interacts with the Service layer strictly via dataclass entities defined in `app/manager/entities.py`.
- **Domain Exceptions**: Defines explicit exceptions in `app/manager/exceptions.py` that map directly to HTTP status codes (e.g. `UserNotMemberError` &rarr; `403 Forbidden`, generic &rarr; `500 Internal Server Error`).

---

## 2. Service &harr; Manager Contract Entities (`app/manager/entities.py`)

These dataclass entities define the contract exchanged between the **Service Layer** and the **Manager Layer**:

```python
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class JoinRoomRequestEntity:
    """Request entity to join a room."""
    room_id: str
    user_id: str


@dataclass
class JoinRoomResponseEntity:
    """Response entity after joining a room."""
    room_id: str
    user_id: str
    status: str = "joined"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SendMessageRequestEntity:
    """Request entity to send a message."""
    room_id: str
    user_id: str
    content: str


@dataclass
class MessageResponseEntity:
    """Response entity for a sent or retrieved message."""
    id: int
    room_id: str
    user_id: str
    content: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GetMessagesRequestEntity:
    """Request entity to retrieve room messages."""
    room_id: str
    user_id: str


@dataclass
class LeaveRoomRequestEntity:
    """Request entity to leave a room."""
    room_id: str
    user_id: str


@dataclass
class LeaveRoomResponseEntity:
    """Response entity after leaving a room."""
    room_id: str
    user_id: str
    status: str = "left"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

---

## 3. Domain Exceptions & HTTP Translation (`app/manager/exceptions.py`)

Custom domain exceptions decouple business failure scenarios from HTTP transport details:

```python
class ChatManagerError(Exception):
    """Base exception for all Chat Manager errors."""
    pass


class UserNotMemberError(ChatManagerError):
    """Raised when a user attempts to send or read messages in a room they haven't joined."""
    def __init__(self, room_id: str, user_id: str, action: str = "access"):
        self.room_id = room_id
        self.user_id = user_id
        self.action = action
        super().__init__(
            f"User '{user_id}' must join room '{room_id}' before {action}"
        )


class RoomNotFoundError(ChatManagerError):
    """Raised when an operation targets a non-existent room (if room validation is active)."""
    def __init__(self, room_id: str):
        self.room_id = room_id
        super().__init__(f"Room '{room_id}' was not found")
```

### Exception &rarr; HTTP Status Code Mapping

| Domain Exception | HTTP Status Code | Response Body Schema |
| :--- | :--- | :--- |
| `UserNotMemberError` | `403 Forbidden` | `{"error": "Forbidden", "message": "<exception message>"}` |
| `RoomNotFoundError` | `404 Not Found` | `{"error": "Not Found", "message": "<exception message>"}` |
| `ChatManagerError` (general) | `400 Bad Request` | `{"error": "Bad Request", "message": "<exception message>"}` |
| `Exception` (unhandled / generic) | `500 Internal Server Error` | `{"error": "Internal Server Error", "message": "An unexpected error occurred"}` |

#### Service Layer Error Handlers (`app/service/api.py`)
```python
@app.errorhandler(UserNotMemberError)
def handle_user_not_member(err: UserNotMemberError):
    return jsonify({"error": "Forbidden", "message": str(err)}), 403

@app.errorhandler(RoomNotFoundError)
def handle_room_not_found(err: RoomNotFoundError):
    return jsonify({"error": "Not Found", "message": str(err)}), 404

@app.errorhandler(500)
@app.errorhandler(Exception)
def handle_generic_exception(err: Exception):
    app.logger.exception(err)
    return jsonify({
        "error": "Internal Server Error",
        "message": "An unexpected error occurred while processing the request",
    }), 500
```

---

## 4. Unified Manager Implementation (`app/manager/chat_manager.py`)

A single cohesive `ChatManager` class handles all chat domain workflows:

```python
from datetime import datetime, timezone
from typing import Any, List, Optional

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

    def join(self, request: JoinRoomRequestEntity) -> JoinRoomResponseEntity:
        """Register user membership in a chat room (idempotent)."""
        # Call adapter to persist membership
        ...
        return JoinRoomResponseEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            status="joined",
        )

    def send_message(self, request: SendMessageRequestEntity) -> MessageResponseEntity:
        """Send a message to a chat room after verifying membership."""
        # Check membership
        if not self._is_member(request.room_id, request.user_id):
            raise UserNotMemberError(
                room_id=request.room_id,
                user_id=request.user_id,
                action="sending messages",
            )

        # Call adapter to save message
        ...
        return MessageResponseEntity(
            id=...,
            room_id=request.room_id,
            user_id=request.user_id,
            content=request.content,
            timestamp=...,
        )

    def get_messages(self, request: GetMessagesRequestEntity) -> List[MessageResponseEntity]:
        """Retrieve all messages from a chat room after verifying membership."""
        # Check membership
        if not self._is_member(request.room_id, request.user_id):
            raise UserNotMemberError(
                room_id=request.room_id,
                user_id=request.user_id,
                action="retrieving messages",
            )

        # Call adapter to fetch messages
        ...
        return [...]

    def leave(self, request: LeaveRoomRequestEntity) -> LeaveRoomResponseEntity:
        """Remove user membership from a chat room."""
        # Call adapter to remove membership
        ...
        return LeaveRoomResponseEntity(
            room_id=request.room_id,
            user_id=request.user_id,
            status="left",
        )

    def _is_member(self, room_id: str, user_id: str) -> bool:
        """Helper to verify room membership via adapter or internal state."""
        ...
```

---

## 5. Mock Adapter for Manager Testing

During this phase, `ChatManager` unit tests can use an in-memory test double:

```python
class MockChatAdapter:
    """In-memory test double for testing ChatManager in isolation."""
    def __init__(self):
        self.memberships = set()  # set of (room_id, user_id)
        self.messages = []       # list of stored message dicts/records
        self.next_id = 1

    def add_member(self, room_id: str, user_id: str):
        self.memberships.add((room_id, user_id))

    def is_member(self, room_id: str, user_id: str) -> bool:
        return (room_id, user_id) in self.memberships

    def remove_member(self, room_id: str, user_id: str):
        self.memberships.discard((room_id, user_id))

    def save_message(self, room_id: str, user_id: str, content: str):
        msg = {
            "id": self.next_id,
            "room_id": room_id,
            "user_id": user_id,
            "content": content,
            "timestamp": "2026-09-27T17:35:00Z",
        }
        self.next_id += 1
        self.messages.append(msg)
        return msg

    def get_messages(self, room_id: str):
        return [m for m in self.messages if m["room_id"] == room_id]
```

---

## 6. Manager Layer Test Plan (`tests/test_manager.py`)

Unit tests verifying `ChatManager` logic in isolation:

1. **Join Flow**:
   - `test_join_room_success`: User joins room; returns `status: joined`.
   - `test_join_room_idempotent`: Joining multiple times succeeds without error.
2. **Send Message Flow**:
   - `test_send_message_as_member`: Successfully returns `MessageResponseEntity` with assigned ID and timestamp.
   - `test_send_message_non_member_raises_user_not_member_error`: Raises `UserNotMemberError` with descriptive message.
3. **Retrieve Messages Flow**:
   - `test_get_messages_as_member`: Successfully returns list of messages.
   - `test_get_messages_non_member_raises_user_not_member_error`: Raises `UserNotMemberError`.
4. **Leave Room Flow**:
   - `test_leave_room_success`: User leaves room; returns `status: left`.
   - `test_send_message_after_leave_raises_user_not_member_error`: User cannot send message after leaving.
   - `test_get_messages_after_leave_raises_user_not_member_error`: User cannot retrieve messages after leaving.
5. **Multi-Room Isolation**:
   - `test_multi_room_membership`: User in Room A is not automatically a member of Room B.
   - `test_multi_room_message_isolation`: Messages in Room A do not appear in Room B.
