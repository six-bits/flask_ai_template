"""Integration and API tests for the Chat Service."""

from unittest.mock import patch


def test_health(client):
    """Test health check returns status ok."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_join_room_success(client):
    """Test joining a room successfully."""
    payload = {"user_id": "alice"}
    res = client.post("/rooms/general/join", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["room_id"] == "general"
    assert data["user_id"] == "alice"
    assert data["status"] == "joined"


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


def test_send_message_success_when_joined(client):
    """Test sending a message after joining succeeds with 201."""
    # First join
    client.post("/rooms/general/join", json={"user_id": "alice"})

    # Send message
    payload = {"user_id": "alice", "content": "Hello team!"}
    res = client.post("/rooms/general/messages", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["id"] == 1
    assert data["room_id"] == "general"
    assert data["user_id"] == "alice"
    assert data["content"] == "Hello team!"
    assert "timestamp" in data


def test_send_message_without_joining_returns_403(client):
    """Test sending message without joining returns 403 Forbidden."""
    payload = {"user_id": "bob", "content": "Sneak message"}
    res = client.post("/rooms/general/messages", json=payload)
    assert res.status_code == 403
    data = res.get_json()
    assert data["error"] == "Forbidden"
    assert "User 'bob' must join room 'general' before sending messages" in data["message"]


def test_send_message_missing_content(client):
    """Test send message fails when content is missing."""
    client.post("/rooms/general/join", json={"user_id": "alice"})
    res = client.post("/rooms/general/messages", json={"user_id": "alice"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"
    assert "content" in data["message"]


def test_send_message_empty_content(client):
    """Test send message fails when content is empty."""
    client.post("/rooms/general/join", json={"user_id": "alice"})
    res = client.post("/rooms/general/messages", json={"user_id": "alice", "content": ""})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_get_messages_success_when_joined(client):
    """Test retrieving messages when user is a member returns 200."""
    client.post("/rooms/general/join", json={"user_id": "alice"})
    client.post("/rooms/general/messages", json={"user_id": "alice", "content": "Msg 1"})

    res = client.get("/rooms/general/messages?user_id=alice")
    assert res.status_code == 200
    messages = res.get_json()
    assert len(messages) == 1
    assert messages[0]["content"] == "Msg 1"
    assert messages[0]["user_id"] == "alice"


def test_get_messages_without_joining_returns_403(client):
    """Test retrieving messages without joining returns 403 Forbidden."""
    res = client.get("/rooms/general/messages?user_id=charlie")
    assert res.status_code == 403
    data = res.get_json()
    assert data["error"] == "Forbidden"
    assert "User 'charlie' must join room 'general' before retrieving messages" in data["message"]


def test_get_messages_missing_user_id_query_param(client):
    """Test retrieve messages returns 400 if user_id query param is omitted."""
    res = client.get("/rooms/general/messages")
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Bad Request"
    assert "user_id" in data["message"]


def test_leave_room_success(client):
    """Test leaving a room returns 200 and status left."""
    client.post("/rooms/general/join", json={"user_id": "alice"})
    res = client.post("/rooms/general/leave", json={"user_id": "alice"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["room_id"] == "general"
    assert data["user_id"] == "alice"
    assert data["status"] == "left"


def test_send_message_after_leave_returns_403(client):
    """Test user cannot send messages after leaving the room."""
    client.post("/rooms/general/join", json={"user_id": "alice"})
    client.post("/rooms/general/leave", json={"user_id": "alice"})

    res = client.post("/rooms/general/messages", json={"user_id": "alice", "content": "Post leave"})
    assert res.status_code == 403
    assert res.get_json()["error"] == "Forbidden"


def test_multi_room_isolation_via_api(client):
    """Test messages in Room A do not leak into Room B."""
    client.post("/rooms/general/join", json={"user_id": "alice"})
    client.post("/rooms/random/join", json={"user_id": "bob"})

    client.post("/rooms/general/messages", json={"user_id": "alice", "content": "General message"})
    client.post("/rooms/random/messages", json={"user_id": "bob", "content": "Random message"})

    res_general = client.get("/rooms/general/messages?user_id=alice")
    assert res_general.status_code == 200
    assert len(res_general.get_json()) == 1
    assert res_general.get_json()[0]["content"] == "General message"

    res_random = client.get("/rooms/random/messages?user_id=bob")
    assert res_random.status_code == 200
    assert len(res_random.get_json()) == 1
    assert res_random.get_json()[0]["content"] == "Random message"


def test_malformed_json_payload(client):
    """Test sending malformed JSON returns 400 Bad Request."""
    res = client.post(
        "/rooms/general/join",
        data="{malformed json",
        content_type="application/json",
    )
    assert res.status_code == 400
    data = res.get_json()
    assert "valid JSON" in data["error"]


def test_generic_exception_returns_500(client):
    """Test unhandled generic exception returns clean 500 JSON."""
    with patch("app.service.api.chat_manager.join", side_effect=RuntimeError("Unexpected server crash")):
        res = client.post("/rooms/general/join", json={"user_id": "alice"})
        assert res.status_code == 500
        data = res.get_json()
        assert data["error"] == "Internal Server Error"
        assert "unexpected error" in data["message"].lower()
