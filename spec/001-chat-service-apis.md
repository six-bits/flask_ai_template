# 001 - Chat Service Stub API Specification

**Scope**: `Stub API Layer Only`  
**Status**: `Draft / For Review`  
**Problem Reference**: [`spec/problem.md`](problem.md)

---

## 1. Overview & Goals

This specification defines the **Stub API Layer** for the Chat Service. The goal is to stand up the HTTP routes, input validation schemas, and realistic stubbed JSON responses so that clients (e.g., cURL, Postman, or frontend chat UIs) can immediately interact with the API surface.

All business logic, manager coordination, and adapter persistence are explicitly **deferred** to subsequent specifications.

---

## 2. API Endpoints Table

| # | Endpoint | Method | Path Params | Query Params | Request Body | Status Code | Description |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `/rooms/<room_id>/join` | `POST` | `room_id: str` | - | `{"user_id": str}` | `200 OK` | Stub user joining room |
| **2** | `/rooms/<room_id>/messages` | `POST` | `room_id: str` | - | `{"user_id": str, "content": str}` | `201 Created` | Stub posting a message |
| **3** | `/rooms/<room_id>/messages` | `GET` | `room_id: str` | `user_id: str` | - | `200 OK` | Stub retrieving room messages |
| **4** | `/rooms/<room_id>/leave` | `POST` | `room_id: str` | - | `{"user_id": str}` | `200 OK` | Stub user leaving room |
| **5** | `/health` | `GET` | - | - | - | `200 OK` | Health check |

---

## 3. Detailed Stub Endpoint Specifications

### 1. Join Chat Room
- **URL**: `POST /rooms/<room_id>/join`
- **Headers**: `Content-Type: application/json`
- **Request Body**:
  ```json
  {
    "user_id": "alice"
  }
  ```
- **Stub Response (`200 OK`)**:
  ```json
  {
    "room_id": "general",
    "user_id": "alice",
    "status": "joined"
  }
  ```
- **Error Response (`400 Bad Request`)**:
  ```json
  {
    "error": "Validation error",
    "message": "'user_id' is a required property"
  }
  ```

---

### 2. Send Message to Chat Room
- **URL**: `POST /rooms/<room_id>/messages`
- **Headers**: `Content-Type: application/json`
- **Request Body**:
  ```json
  {
    "user_id": "alice",
    "content": "Hello team, welcome to the channel!"
  }
  ```
- **Stub Response (`201 Created`)**:
  ```json
  {
    "id": 1,
    "room_id": "general",
    "user_id": "alice",
    "content": "Hello team, welcome to the channel!",
    "timestamp": "2026-09-27T17:35:00Z"
  }
  ```
- **Error Response (`400 Bad Request`)**:
  ```json
  {
    "error": "Validation error",
    "message": "'' should be non-empty"
  }
  ```

---

### 3. Retrieve Messages from Chat Room
- **URL**: `GET /rooms/<room_id>/messages?user_id=alice`
- **Query Parameters**:
  - `user_id` *(required)*: Identifier of the requesting user.
- **Stub Response (`200 OK`)**:
  ```json
  [
    {
      "id": 1,
      "room_id": "general",
      "user_id": "alice",
      "content": "Hello team, welcome to the channel!",
      "timestamp": "2026-09-27T17:35:00Z"
    }
  ]
  ```
- **Error Response (`400 Bad Request`)**:
  ```json
  {
    "error": "Bad Request",
    "message": "Query parameter 'user_id' is required"
  }
  ```

---

### 4. Leave Chat Room
- **URL**: `POST /rooms/<room_id>/leave`
- **Headers**: `Content-Type: application/json`
- **Request Body**:
  ```json
  {
    "user_id": "alice"
  }
  ```
- **Stub Response (`200 OK`)**:
  ```json
  {
    "room_id": "general",
    "user_id": "alice",
    "status": "left"
  }
  ```
- **Error Response (`400 Bad Request`)**:
  ```json
  {
    "error": "Validation error",
    "message": "'user_id' is a required property"
  }
  ```

---

### 5. Health Check
- **URL**: `GET /health`
- **Stub Response (`200 OK`)**:
  ```json
  {
    "status": "ok"
  }
  ```

---

## 4. JSON Validation Schemas (`app/service/schema.py`)

All payloads are validated using standard `jsonschema` (Draft 2020-12):

```python
JOIN_ROOM_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1, "maxLength": 50},
    },
    "required": ["user_id"],
    "additionalProperties": False,
}

SEND_MESSAGE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1, "maxLength": 50},
        "content": {"type": "string", "minLength": 1, "maxLength": 2000},
    },
    "required": ["user_id", "content"],
    "additionalProperties": False,
}

LEAVE_ROOM_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1, "maxLength": 50},
    },
    "required": ["user_id"],
    "additionalProperties": False,
}
```

---

## 5. Test Plan (`tests/test_api.py`)

Unit tests verifying the stub API endpoints and schema validation:

1. **Health Check**:
   - `GET /health` returns `200 OK` with `{"status": "ok"}`.
2. **Join Room Stub**:
   - `POST /rooms/general/join` with `{"user_id": "alice"}` returns `200 OK` and stub payload.
   - `POST /rooms/general/join` with `{}` returns `400 Bad Request`.
3. **Send Message Stub**:
   - `POST /rooms/general/messages` with valid body returns `201 Created` and stub message.
   - Missing `content` or `user_id` returns `400 Bad Request`.
4. **Retrieve Messages Stub**:
   - `GET /rooms/general/messages?user_id=alice` returns `200 OK` and stub message array.
   - Missing `user_id` query param returns `400 Bad Request`.
5. **Leave Room Stub**:
   - `POST /rooms/general/leave` with `{"user_id": "alice"}` returns `200 OK` and stub status.
   - Missing `user_id` returns `400 Bad Request`.
6. **Malformed Payloads**:
   - Non-JSON payload returns `400 Bad Request`.

---

## 6. Open Items / Next Steps

- **Manager Layer Integration**: Implement `JoinRoomManager`, `SendMessageManager`, `GetMessagesManager`, and `LeaveRoomManager` to replace stub responses with real business logic and room membership checks.
- **Adapter Layer Integration**: Implement in-memory storage for room memberships and message persistence.
- **Message Pagination**: Parked as an optional future enhancement for `GET /rooms/<room_id>/messages`.
