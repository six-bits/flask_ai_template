"""Integration tests for the Chat Service API layer interacting with the stubbed manager."""

from unittest.mock import patch
from app.manager.exceptions import UserNotMemberError


def test_health(client):
    """Test health check returns status ok."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_join_room_success(client):
    """Test joining a room returns 200 and stub response."""
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


def test_send_message_success(client):
    """Test sending a message returns 201 and stub message details."""
    payload = {"user_id": "alice", "content": "Hello team!"}
    res = client.post("/rooms/general/messages", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["id"] == 1
    assert data["room_id"] == "general"
    assert data["user_id"] == "alice"
    assert data["content"] == "Hello team!"
    assert "timestamp" in data


def test_send_message_missing_content(client):
    """Test send message fails when content is missing."""
    res = client.post("/rooms/general/messages", json={"user_id": "alice"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"
    assert "content" in data["message"]


def test_send_message_empty_content(client):
    """Test send message fails when content is empty."""
    res = client.post("/rooms/general/messages", json={"user_id": "alice", "content": ""})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_send_message_user_not_member_returns_403(client):
    """Test UserNotMemberError from manager is translated to HTTP 403 Forbidden."""
    with patch(
        "app.service.api.chat_manager.send_message",
        side_effect=UserNotMemberError("general", "bob", "sending messages"),
    ):
        res = client.post("/rooms/general/messages", json={"user_id": "bob", "content": "Sneak"})
        assert res.status_code == 403
        data = res.get_json()
        assert data["error"] == "Forbidden"
        assert "User 'bob' must join room 'general' before sending messages" in data["message"]


def test_get_messages_success(client):
    """Test retrieving messages with user_id query param returns 200."""
    res = client.get("/rooms/general/messages?user_id=alice")
    assert res.status_code == 200
    messages = res.get_json()
    assert isinstance(messages, list)
    assert len(messages) >= 1
    assert messages[0]["room_id"] == "general"
    assert messages[0]["user_id"] == "alice"
    assert "content" in messages[0]


def test_get_messages_missing_user_id_query_param(client):
    """Test retrieve messages returns 400 if user_id query param is omitted."""
    res = client.get("/rooms/general/messages")
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Bad Request"
    assert "user_id" in data["message"]


def test_get_messages_user_not_member_returns_403(client):
    """Test UserNotMemberError on get_messages is translated to HTTP 403 Forbidden."""
    with patch(
        "app.service.api.chat_manager.get_messages",
        side_effect=UserNotMemberError("general", "charlie", "retrieving messages"),
    ):
        res = client.get("/rooms/general/messages?user_id=charlie")
        assert res.status_code == 403
        data = res.get_json()
        assert data["error"] == "Forbidden"
        assert "User 'charlie' must join room 'general' before retrieving messages" in data["message"]


def test_leave_room_success(client):
    """Test leaving a room returns 200 and status left."""
    res = client.post("/rooms/general/leave", json={"user_id": "alice"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["room_id"] == "general"
    assert data["user_id"] == "alice"
    assert data["status"] == "left"


def test_leave_room_missing_user_id(client):
    """Test leave room validation fails when user_id is missing."""
    res = client.post("/rooms/general/leave", json={})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


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
