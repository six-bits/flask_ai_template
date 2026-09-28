# 005 - Chat Service E2E Integration & API Layer Specification

**Scope**: `Full Stack E2E Integration (Service -> Manager -> Adapter)`  
**Status**: `Draft / For Review`  
**Problem Reference**: [`spec/problem.md`](problem.md)  
**Prerequisite Specs**: [`spec/001-chat-service-apis.md`](001-chat-service-apis.md), [`spec/002-chat-service-manager.md`](002-chat-service-manager.md), [`spec/003-chat-service-adapter.md`](003-chat-service-adapter.md), [`spec/004-chat-service-manager-adapter.md`](004-chat-service-manager-adapter.md)

---

## 1. Overview & Architectural Scope

This specification defines the complete **End-to-End (E2E) Integration** wiring the HTTP API layer (`app/service/api.py`) directly to the unified `ChatManager` (`app/manager/chat_manager.py`), which orchestrates persistence through `UserAdapter` and `ChatAdapter`.

### Key Constraints & Principles
1. **Strict API Surface**: Only the required chat APIs will be exposed via HTTP:
   - `POST /rooms/<room_id>/join`
   - `POST /rooms/<room_id>/messages`
   - `GET /rooms/<room_id>/messages?user_id=<user_id>`
   - `POST /rooms/<room_id>/leave`
   - `GET /health`
   - **No extra APIs** (such as HTTP room creation or user registration endpoints) will be added to the service layer.
2. **Manager-Driven Test Environment Provisioning**: The test environment is seeded in advance using **Manager Layer functions** (`chat_manager.register_user`, `chat_manager.create_room`) to provision test users and rooms before executing HTTP requests.
3. **Comprehensive Error Code Translation**:
   - `RoomNotFoundError` &rarr; `404 Not Found`
   - `UserNotFoundError` &rarr; `404 Not Found`
   - `UserNotMemberError` &rarr; `403 Forbidden`
   - `ValidationError` (schema failure) &rarr; `400 Bad Request`
   - `ChatManagerError` (general business logic failure) &rarr; `400 Bad Request`
   - `Exception` (unhandled server error) &rarr; `500 Internal Server Error`
4. **Full Stack Orchestration**: Testing validates complete end-to-end flows from HTTP JSON payloads through manager validation down to in-memory adapter persistence and back.

---

## 2. Service Layer Implementation (`app/service/api.py`)

### 2.1 Route Handlers & Manager Invocations

All routes construct domain entities from requests, delegate directly to `chat_manager`, and serialize response entities:

```python
"""Chat Service HTTP API layer."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.manager.chat_manager import chat_manager
from app.manager.entities import (
    GetMessagesRequestEntity,
    JoinRoomRequestEntity,
    LeaveRoomRequestEntity,
    SendMessageRequestEntity,
)
from app.manager.exceptions import (
    ChatManagerError,
    RoomNotFoundError,
    UserNotFoundError,
    UserNotMemberError,
)
from app.service.schema import (
    JOIN_ROOM_SCHEMA,
    LEAVE_ROOM_SCHEMA,
    SEND_MESSAGE_SCHEMA,
)

app = Flask(__name__)


# ==============================================================================
# Error Handlers
# ==============================================================================

@app.errorhandler(ValidationError)
def handle_validation_error(err: ValidationError):
    """Handle JSON Schema validation errors."""
    return jsonify({"error": "Validation error", "message": err.message}), 400


@app.errorhandler(UserNotFoundError)
def handle_user_not_found(err: UserNotFoundError):
    """Handle unregistered user reference."""
    return jsonify({"error": "Not Found", "message": str(err)}), 404


@app.errorhandler(RoomNotFoundError)
def handle_room_not_found(err: RoomNotFoundError):
    """Handle non-existent room reference."""
    return jsonify({"error": "Not Found", "message": str(err)}), 404


@app.errorhandler(UserNotMemberError)
def handle_user_not_member(err: UserNotMemberError):
    """Handle forbidden operation by non-member."""
    return jsonify({"error": "Forbidden", "message": str(err)}), 403


@app.errorhandler(ChatManagerError)
def handle_chat_manager_error(err: ChatManagerError):
    """Handle general domain errors."""
    return jsonify({"error": "Bad Request", "message": str(err)}), 400


@app.errorhandler(500)
@app.errorhandler(Exception)
def handle_generic_exception(err: Exception):
    """Handle unexpected server errors with sanitized 500 JSON."""
    app.logger.exception(err)
    return jsonify({
        "error": "Internal Server Error",
        "message": "An unexpected error occurred while processing the request",
    }), 500


# ==============================================================================
# Routes
# ==============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/rooms/<room_id>/join", methods=["POST"])
def join_room(room_id: str):
    """Join a chat room."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=JOIN_ROOM_SCHEMA)

    request_entity = JoinRoomRequestEntity(
        room_id=room_id,
        user_id=data["user_id"],
    )
    response_entity = chat_manager.join(request_entity)
    return jsonify(response_entity.to_dict()), 200


@app.route("/rooms/<room_id>/messages", methods=["POST"])
def send_message(room_id: str):
    """Send a message to a chat room."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=SEND_MESSAGE_SCHEMA)

    request_entity = SendMessageRequestEntity(
        room_id=room_id,
        user_id=data["user_id"],
        content=data["content"],
    )
    response_entity = chat_manager.send_message(request_entity)
    return jsonify(response_entity.to_dict()), 201


@app.route("/rooms/<room_id>/messages", methods=["GET"])
def get_messages(room_id: str):
    """Retrieve messages from a chat room."""
    user_id = request.args.get("user_id")
    if not user_id or not user_id.strip():
        return jsonify({
            "error": "Bad Request",
            "message": "Query parameter 'user_id' is required",
        }), 400

    request_entity = GetMessagesRequestEntity(
        room_id=room_id,
        user_id=user_id.strip(),
    )
    messages = chat_manager.get_messages(request_entity)
    return jsonify([m.to_dict() for m in messages]), 200


@app.route("/rooms/<room_id>/leave", methods=["POST"])
def leave_room(room_id: str):
    """Leave a chat room."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=LEAVE_ROOM_SCHEMA)

    request_entity = LeaveRoomRequestEntity(
        room_id=room_id,
        user_id=data["user_id"],
    )
    response_entity = chat_manager.leave(request_entity)
    return jsonify(response_entity.to_dict()), 200


if __name__ == "__main__":
    app.run(port=5001, debug=True)
```

---

## 3. Test Environment Provisioning (`tests/conftest.py`)

Using the Manager layer methods to provision the test environment in advance:

```python
"""Pytest fixtures for the Chat Service E2E tests."""

import pytest
from app.manager.chat_manager import chat_manager
from app.manager.entities import CreateRoomRequestEntity, RegisterUserRequestEntity
from app.service.api import app


@pytest.fixture
def client():
    """Create Flask test client with pre-provisioned users and rooms via ChatManager."""
    app.config["TESTING"] = True

    # 1. Reset state
    chat_manager.user_adapter.clear()
    chat_manager.chat_adapter.clear()

    # 2. Provision test users via Manager
    chat_manager.register_user(RegisterUserRequestEntity(user_id="alice"))
    chat_manager.register_user(RegisterUserRequestEntity(user_id="bob"))
    chat_manager.register_user(RegisterUserRequestEntity(user_id="charlie"))

    # 3. Provision test rooms via Manager
    chat_manager.create_room(CreateRoomRequestEntity(room_id="general"))
    chat_manager.create_room(CreateRoomRequestEntity(room_id="random"))
    chat_manager.create_room(CreateRoomRequestEntity(room_id="dev"))

    with app.test_client() as client:
        yield client
```

---

## 4. E2E Test Suite Orchestration (`tests/test_api.py`)

The test suite exercises all operations and business invariants over HTTP:

### 4.1 Room Joining Flow
1. **`test_join_room_success`**:
   - `POST /rooms/general/join` with `user_id="alice"`.
   - Returns `200 OK` with `{"room_id": "general", "user_id": "alice", "status": "joined"}`.
2. **`test_join_room_idempotent`**:
   - Joining `general` twice with `"alice"` returns `200 OK` without error.
3. **`test_join_room_user_not_found`**:
   - `POST /rooms/general/join` with `user_id="ghost"` (unregistered).
   - Returns `404 Not Found` with `{"error": "Not Found", "message": "User 'ghost' was not found"}`.
4. **`test_join_room_room_not_found`**:
   - `POST /rooms/unknown-room/join` with `user_id="alice"`.
   - Returns `404 Not Found` with `{"error": "Not Found", "message": "Room 'unknown-room' was not found"}`.
5. **`test_join_room_validation_errors`**:
   - Missing `user_id` or extra properties &rarr; `400 Bad Request`.

### 4.2 Send Message Flow
6. **`test_send_message_success`**:
   - Alice joins `general`, posts `"Hello everyone!"`.
   - Returns `201 Created` with `id=1`, `content="Hello everyone!"`, `timestamp`.
7. **`test_send_message_user_not_found`**:
   - `POST /rooms/general/messages` with `user_id="ghost"`.
   - Returns `404 Not Found`.
8. **`test_send_message_room_not_found`**:
   - `POST /rooms/unknown-room/messages` with `user_id="alice"`.
   - Returns `404 Not Found`.
9. **`test_send_message_user_not_member`**:
   - Bob tries to post to `general` without joining.
   - Returns `403 Forbidden` with `"User 'bob' must join room 'general' before sending messages"`.
10. **`test_send_message_validation_errors`**:
    - Empty content, missing content, extra fields &rarr; `400 Bad Request`.

### 4.3 Get Messages Flow
11. **`test_get_messages_success`**:
    - Alice joins `general`, posts message, calls `GET /rooms/general/messages?user_id=alice`.
    - Returns `200 OK` with list containing the posted message.
12. **`test_get_messages_user_not_found`**:
    - `GET /rooms/general/messages?user_id=ghost`.
    - Returns `404 Not Found`.
13. **`test_get_messages_room_not_found`**:
    - `GET /rooms/unknown-room/messages?user_id=alice`.
    - Returns `404 Not Found`.
14. **`test_get_messages_user_not_member`**:
    - Bob calls `GET /rooms/general/messages?user_id=bob` without joining.
    - Returns `403 Forbidden`.
15. **`test_get_messages_missing_query_param`**:
    - Missing `user_id` query parameter &rarr; `400 Bad Request`.

### 4.4 Leave Room Flow
16. **`test_leave_room_success`**:
    - Alice joins `general`, then calls `POST /rooms/general/leave`.
    - Returns `200 OK` with `status="left"`.
17. **`test_send_message_after_leave_returns_403`**:
    - After leaving `general`, Alice attempts to send a message &rarr; `403 Forbidden`.
18. **`test_get_messages_after_leave_returns_403`**:
    - After leaving `general`, Alice attempts to read messages &rarr; `403 Forbidden`.

### 4.5 Multi-Room Isolation
19. **`test_multi_room_isolation_e2e`**:
    - Alice joins `general` and sends `"General chat"`.
    - Bob joins `random` and sends `"Random chat"`.
    - Alice retrieves `general` &rarr; only sees `"General chat"`.
    - Bob retrieves `random` &rarr; only sees `"Random chat"`.
    - Alice cannot read `random` without joining &rarr; `403 Forbidden`.

### 4.6 Infrastructure & Health
20. **`test_health`**: Returns `200 OK` with `{"status": "ok"}`.
21. **`test_malformed_json_payload`**: Sending non-JSON raw string body returns `400 Bad Request`.
22. **`test_generic_exception_returns_500`**: Simulating unhandled exception returns clean `500 Internal Server Error`.
