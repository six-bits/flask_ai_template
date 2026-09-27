"""Unit tests for the Chat Service Stub API layer."""


def test_health(client):
    """Test health check returns status ok."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_join_room_success(client):
    """Test joining a room returns expected stub response."""
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
    """Test sending a message returns 201 and message details."""
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
    """Test send message fails when content is an empty string."""
    res = client.post("/rooms/general/messages", json={"user_id": "alice", "content": ""})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_get_messages_success(client):
    """Test retrieving messages with valid user_id query param."""
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


def test_leave_room_success(client):
    """Test leaving a room returns 200 and status left."""
    payload = {"user_id": "alice"}
    res = client.post("/rooms/general/leave", json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data["room_id"] == "general"
    assert data["user_id"] == "alice"
    assert data["status"] == "left"


def test_leave_room_missing_user_id(client):
    """Test leaving a room fails when user_id is missing."""
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
