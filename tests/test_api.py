"""Tests for the greeting API, manager, and adapter layers."""

from app.adapter.entities import GreetingRecordEntity
from app.adapter.greeting_adapter import GreetingAdapter
from app.manager.entities import GreetingRequestEntity, GreetingResponseEntity
from app.manager.greeting_manager import GreetingManager


def test_health(client):
    """Test health check returns status ok."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_hello_default_salutation(client):
    """Test greeting with default salutation."""
    res = client.post("/hello", json={"name": "John Doe"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["id"] == 1
    assert data["message"] == "Hello, John Doe!"
    assert data["salutation"] == "Hello"
    assert data["name"] == "John Doe"


def test_hello_custom_salutation(client):
    """Test greeting with custom query parameter salutation."""
    res = client.post("/hello?salutation=Welcome", json={"name": "Jane Smith"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["message"] == "Welcome, Jane Smith!"
    assert data["salutation"] == "Welcome"
    assert data["name"] == "Jane Smith"


def test_hello_with_full_name_field(client):
    """Test greeting when body provides 'full_name' instead of 'name'."""
    res = client.post("/hello?salutation=Good morning", json={"full_name": "Alice Wonderland"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["message"] == "Good morning, Alice Wonderland!"
    assert data["name"] == "Alice Wonderland"


def test_hello_missing_name_in_body(client):
    """Test validation fails when name is missing in body."""
    res = client.post("/hello", json={})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_hello_invalid_type_in_body(client):
    """Test validation fails when name is not a string."""
    res = client.post("/hello", json={"name": 12345})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_hello_empty_string_name(client):
    """Test validation fails when name is an empty string."""
    res = client.post("/hello", json={"name": ""})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_hello_extra_fields_rejected(client):
    """Test validation rejects unexpected additional properties."""
    res = client.post("/hello", json={"name": "John Doe", "age": 30})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Validation error"


def test_hello_malformed_json(client):
    """Test malformed JSON payload returns 400."""
    res = client.post("/hello", data="{not json", content_type="application/json")
    assert res.status_code == 400
    data = res.get_json()
    assert "valid JSON" in data["error"]


def test_layer_entity_flow():
    """Unit test verifying Service -> Manager -> Adapter flow using single functions and contracts."""
    test_adapter = GreetingAdapter()
    test_manager = GreetingManager(adapter=test_adapter)

    # 1. Service -> Manager contract (GreetingRequestEntity)
    request_entity = GreetingRequestEntity(name="Charlie", salutation="Greetings")
    response_entity = test_manager.greet(request_entity)

    assert isinstance(response_entity, GreetingResponseEntity)
    assert response_entity.id == 1
    assert response_entity.message == "Greetings, Charlie!"

    # 2. Manager -> Adapter contract (GreetingRecordEntity)
    assert len(test_adapter.storage) == 1
    record = test_adapter.storage[0]
    assert isinstance(record, GreetingRecordEntity)
    assert record.id == response_entity.id
    assert record.name == response_entity.name
    assert record.message == response_entity.message
