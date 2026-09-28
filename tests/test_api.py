"""End-to-end integration tests for the Chat Service HTTP API layer."""

from unittest.mock import patch


# ==============================================================================
# Health Endpoint
# ==============================================================================

def test_health(client):
    """Test health check returns status ok."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


# ==============================================================================
# 4.1 Room Joining Flow
# ==============================================================================

def test_join_room_success(client):
    """Test registered user joining an existing room returns 200."""
    res = client.post("/rooms/general/join", json={"user_id": "alice"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["room_id"] == "general"
    assert data["user_id"] == "alice"
    assert data["status"] == "joined"


def test_join_room_idempotent(client):
    """Test joining the same room multiple times succeeds idempotently."""
    res1 = client.post("/rooms/general/join", json={"user_id": "alice"})
    res2 = client.post("/rooms/general/join", json={"user_id": "alice"})

    assert res1.status_code == 200
    assert res2.status_code == 200
    assert res2.get_json()["status"] == "joined"


def test_join_room_user_not_found(client):
    """Test joining with an unregistered user returns 404 Not Found."""
    res = client.post("/rooms/general/join", json={"user_id": "ghost"})
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Not Found"
    assert "User 'ghost' was not found" in data["message"]


def test_join_room_room_not_found(client):
    """Test joining a non-existent room returns 404 Not Found."""
    res = client.post("/rooms/unknown-room/join", json={"user_id": "alice"})
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Not Found"
    assert "Room 'unknown-room' was not found" in data["message"]


def test_join_room_missing_user_id(client):
    """Test join room validation fails when user_id is missing."""
    res = client.post("/rooms/general/join", json={})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"
    assert "user_id" in data["message"]


def test_join_room_extra_fields_rejected(client):
    """Test join room rejects unexpected properties."""
    res = client.post("/rooms/general/join", json={"user_id": "alice", "role": "admin"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


# ==============================================================================
# 4.2 Send Message Flow
# ==============================================================================

def test_send_message_success(client):
    """Test joined user sending a message returns 201 Created."""
    client.post("/rooms/general/join", json={"user_id": "alice"})

    res = client.post(
        "/rooms/general/messages",
        json={"user_id": "alice", "content": "Hello team!"},
    )
    assert res.status_code == 201
    data = res.get_json()
    assert data["id"] == 1
    assert data["room_id"] == "general"
    assert data["user_id"] == "alice"
    assert data["content"] == "Hello team!"
    assert "timestamp" in data


def test_send_message_user_not_found(client):
    """Test sending message with unregistered user returns 404 Not Found."""
    res = client.post(
        "/rooms/general/messages",
        json={"user_id": "ghost", "content": "Hello"},
    )
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Not Found"
    assert "User 'ghost' was not found" in data["message"]


def test_send_message_room_not_found(client):
    """Test sending message to non-existent room returns 404 Not Found."""
    res = client.post(
        "/rooms/unknown-room/messages",
        json={"user_id": "alice", "content": "Hello"},
    )
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Not Found"
    assert "Room 'unknown-room' was not found" in data["message"]


def test_send_message_user_not_member_returns_403(client):
    """Test registered user sending message without joining returns 403 Forbidden."""
    res = client.post(
        "/rooms/general/messages",
        json={"user_id": "bob", "content": "Sneak message"},
    )
    assert res.status_code == 403
    data = res.get_json()
    assert data["error"] == "Forbidden"
    assert "User 'bob' must join room 'general' before sending messages" in data["message"]


def test_send_message_missing_content(client):
    """Test send message fails when content is missing."""
    res = client.post("/rooms/general/messages", json={"user_id": "alice"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_send_message_empty_content(client):
    """Test send message fails when content is empty."""
    res = client.post("/rooms/general/messages", json={"user_id": "alice", "content": ""})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


# ==============================================================================
# 4.3 Get Messages Flow
# ==============================================================================

def test_get_messages_success(client):
    """Test joined user retrieving messages returns 200 with chronological list."""
    client.post("/rooms/general/join", json={"user_id": "alice"})
    client.post("/rooms/general/messages", json={"user_id": "alice", "content": "First message"})
    client.post("/rooms/general/messages", json={"user_id": "alice", "content": "Second message"})

    res = client.get("/rooms/general/messages?user_id=alice")
    assert res.status_code == 200
    messages = res.get_json()
    assert isinstance(messages, list)
    assert len(messages) == 2
    assert messages[0]["content"] == "First message"
    assert messages[1]["content"] == "Second message"


def test_get_messages_user_not_found(client):
    """Test retrieving messages with unregistered user returns 404 Not Found."""
    res = client.get("/rooms/general/messages?user_id=ghost")
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Not Found"
    assert "User 'ghost' was not found" in data["message"]


def test_get_messages_room_not_found(client):
    """Test retrieving messages from non-existent room returns 404 Not Found."""
    res = client.get("/rooms/unknown-room/messages?user_id=alice")
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Not Found"
    assert "Room 'unknown-room' was not found" in data["message"]


def test_get_messages_user_not_member_returns_403(client):
    """Test retrieving messages without joining returns 403 Forbidden."""
    res = client.get("/rooms/general/messages?user_id=bob")
    assert res.status_code == 403
    data = res.get_json()
    assert data["error"] == "Forbidden"
    assert "User 'bob' must join room 'general' before retrieving messages" in data["message"]


def test_get_messages_missing_user_id_query_param(client):
    """Test retrieve messages returns 400 if user_id query param is omitted."""
    res = client.get("/rooms/general/messages")
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Bad Request"
    assert "user_id" in data["message"]


# ==============================================================================
# 4.4 Leave Room Flow
# ==============================================================================

def test_leave_room_success(client):
    """Test joined user leaving a room returns 200 and status left."""
    client.post("/rooms/general/join", json={"user_id": "alice"})

    res = client.post("/rooms/general/leave", json={"user_id": "alice"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["room_id"] == "general"
    assert data["user_id"] == "alice"
    assert data["status"] == "left"


def test_leave_room_user_not_found(client):
    """Test leaving room with unregistered user returns 404 Not Found."""
    res = client.post("/rooms/general/leave", json={"user_id": "ghost"})
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Not Found"
    assert "User 'ghost' was not found" in data["message"]


def test_leave_room_room_not_found(client):
    """Test leaving non-existent room returns 404 Not Found."""
    res = client.post("/rooms/unknown-room/leave", json={"user_id": "alice"})
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Not Found"
    assert "Room 'unknown-room' was not found" in data["message"]


def test_send_message_after_leave_returns_403(client):
    """Test user cannot send messages after leaving the room."""
    client.post("/rooms/general/join", json={"user_id": "alice"})
    client.post("/rooms/general/leave", json={"user_id": "alice"})

    res = client.post(
        "/rooms/general/messages",
        json={"user_id": "alice", "content": "Post-leave message"},
    )
    assert res.status_code == 403
    data = res.get_json()
    assert data["error"] == "Forbidden"


def test_get_messages_after_leave_returns_403(client):
    """Test user cannot retrieve messages after leaving the room."""
    client.post("/rooms/general/join", json={"user_id": "alice"})
    client.post("/rooms/general/leave", json={"user_id": "alice"})

    res = client.get("/rooms/general/messages?user_id=alice")
    assert res.status_code == 403
    data = res.get_json()
    assert data["error"] == "Forbidden"


def test_leave_room_missing_user_id(client):
    """Test leave room validation fails when user_id is missing."""
    res = client.post("/rooms/general/leave", json={})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


# ==============================================================================
# 4.5 Multi-Room Isolation E2E
# ==============================================================================

def test_multi_room_isolation_e2e(client):
    """Test that room data is strictly isolated across multiple chat rooms."""
    # Alice joins general, Bob joins random
    client.post("/rooms/general/join", json={"user_id": "alice"})
    client.post("/rooms/random/join", json={"user_id": "bob"})

    # Post messages to respective rooms
    client.post("/rooms/general/messages", json={"user_id": "alice", "content": "Message in general"})
    client.post("/rooms/random/messages", json={"user_id": "bob", "content": "Message in random"})

    # Alice reads general -> only general message present
    res_gen = client.get("/rooms/general/messages?user_id=alice")
    assert res_gen.status_code == 200
    msgs_gen = res_gen.get_json()
    assert len(msgs_gen) == 1
    assert msgs_gen[0]["content"] == "Message in general"

    # Bob reads random -> only random message present
    res_rand = client.get("/rooms/random/messages?user_id=bob")
    assert res_rand.status_code == 200
    msgs_rand = res_rand.get_json()
    assert len(msgs_rand) == 1
    assert msgs_rand[0]["content"] == "Message in random"

    # Alice cannot read random without joining -> 403 Forbidden
    res_cross = client.get("/rooms/random/messages?user_id=alice")
    assert res_cross.status_code == 403


# ==============================================================================
# 4.6 Infrastructure & Error Handlers
# ==============================================================================

def test_malformed_json_payload(client):
    """Test malformed raw string body returns 400 Bad Request."""
    res = client.post(
        "/rooms/general/join",
        data="this is not json",
        content_type="application/json",
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Request body must be valid JSON"


def test_generic_exception_returns_500(client):
    """Test unhandled exception is caught and returns sanitized 500 JSON."""
    with patch("app.service.api.chat_manager.join") as mock_join:
        mock_join.side_effect = RuntimeError("Database disk full")
        res = client.post("/rooms/general/join", json={"user_id": "alice"})

        assert res.status_code == 500
        data = res.get_json()
        assert data["error"] == "Internal Server Error"
        assert "unexpected error" in data["message"]
