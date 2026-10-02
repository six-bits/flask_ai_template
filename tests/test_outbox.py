"""Tests for Transactional Outbox Pattern via Entity-Attached Domain Events."""

import pytest

from app.adapter.quote_adapter import quote_adapter
from app.adapter.user_wallet_adapter import user_wallet_adapter


@pytest.fixture(autouse=True)
def reset_adapters():
    """Reset all in-memory adapters before each test."""
    user_wallet_adapter.reset()
    quote_adapter.reset()


# =========================================================================
# 1. Transfer Multi-Stage State Machine & Event Placement Tests
# =========================================================================

def test_transfer_events_attached_to_respective_entities(client):
    """Verify that a 3-hop transfer attaches events strictly to sender, outbound pool, and recipient."""
    res = client.post("/transfers", json={
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 5000,
    })
    assert res.status_code == 200
    transfer_id = res.get_json()["transfer_id"]

    # 1. Sender (user_1) must host TRANSFER_OUTBOUND_COMMITTED
    user_1 = user_wallet_adapter._users["user_1"]
    sender_events = user_1.outbox_events
    assert len(sender_events) == 1
    assert sender_events[0].event_type == "TRANSFER_OUTBOUND_COMMITTED"
    assert sender_events[0].entity_type == "USER_WALLET"
    assert sender_events[0].entity_id == "user_1"
    assert sender_events[0].payload["transfer_id"] == transfer_id
    assert sender_events[0].payload["currency"] == "USD"
    assert sender_events[0].payload["amount"] == 5000
    assert sender_events[0].payload["remaining_balance"] == 95000
    assert sender_events[0].status == "PENDING"

    # 2. Outbound clearing pool must host TRANSIT_POOL_CLEARED
    outbound_pool = user_wallet_adapter._pools["SYSTEM_OUTBOUND"]
    pool_events = outbound_pool.outbox_events
    assert len(pool_events) == 1
    assert pool_events[0].event_type == "TRANSIT_POOL_CLEARED"
    assert pool_events[0].entity_type == "CLEARING_POOL"
    assert pool_events[0].entity_id == "SYSTEM_OUTBOUND"
    assert pool_events[0].payload["transfer_id"] == transfer_id
    assert pool_events[0].payload["amount"] == 5000
    assert pool_events[0].status == "PENDING"

    # 3. Recipient (user_2) must host TRANSFER_INBOUND_SETTLED
    user_2 = user_wallet_adapter._users["user_2"]
    recipient_events = user_2.outbox_events
    assert len(recipient_events) == 1
    assert recipient_events[0].event_type == "TRANSFER_INBOUND_SETTLED"
    assert recipient_events[0].entity_type == "USER_WALLET"
    assert recipient_events[0].entity_id == "user_2"
    assert recipient_events[0].payload["transfer_id"] == transfer_id
    assert recipient_events[0].payload["updated_balance"] == 30000
    assert recipient_events[0].status == "PENDING"

    # 4. Inbound pool hosts 0 events (as hop 2 is owned by outbound clearing)
    inbound_pool = user_wallet_adapter._pools["SYSTEM_INBOUND"]
    assert len(inbound_pool.outbox_events) == 0


def test_zero_phantom_events_on_failed_transfer(client):
    """Verify that a failed transfer (e.g. insufficient funds) generates zero phantom outbox events."""
    res = client.post("/transfers", json={
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 9999999,  # exceeds balance
    })
    assert res.status_code == 400
    assert res.get_json()["error"] == "INSUFFICIENT_FUNDS"

    # Verify no entity has phantom outbox events attached
    user_1 = user_wallet_adapter._users["user_1"]
    user_2 = user_wallet_adapter._users["user_2"]
    outbound_pool = user_wallet_adapter._pools["SYSTEM_OUTBOUND"]

    assert len(user_1.outbox_events) == 0
    assert len(user_2.outbox_events) == 0
    assert len(outbound_pool.outbox_events) == 0


# =========================================================================
# 2. Quote Multi-Stage State Machine & Event Placement Tests
# =========================================================================

def test_quote_creation_and_conversion_event_attachment(client):
    """Verify that quote creation and acceptance attach events to Quote, User, and Clearing Pool entities."""
    # 1. Create quote
    q_res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    })
    assert q_res.status_code == 201
    quote_id = q_res.get_json()["quote_id"]

    # Quote entity must hold QUOTE_CREATED event
    quote_record = quote_adapter.get_quote(quote_id)
    assert quote_record is not None
    assert len(quote_record.outbox_events) == 1
    assert quote_record.outbox_events[0].event_type == "QUOTE_CREATED"
    assert quote_record.outbox_events[0].entity_type == "QUOTE"
    assert quote_record.outbox_events[0].entity_id == quote_id

    # 2. Accept quote
    accept_res = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1"})
    assert accept_res.status_code == 200

    # Quote entity must now also hold QUOTE_ACCEPTED event
    assert len(quote_record.outbox_events) == 2
    assert quote_record.outbox_events[1].event_type == "QUOTE_ACCEPTED"

    # User entity must hold CONVERSION_OUTBOUND_COMMITTED and CONVERSION_INBOUND_SETTLED
    user_1 = user_wallet_adapter._users["user_1"]
    user_event_types = [e.event_type for e in user_1.outbox_events]
    assert user_event_types == ["CONVERSION_OUTBOUND_COMMITTED", "CONVERSION_INBOUND_SETTLED"]

    # Outbound pool entity must hold CONVERSION_FX_CLEARED
    outbound_pool = user_wallet_adapter._pools["SYSTEM_OUTBOUND"]
    assert len(outbound_pool.outbox_events) == 1
    assert outbound_pool.outbox_events[0].event_type == "CONVERSION_FX_CLEARED"


# =========================================================================
# 3. Outbox Scraper Endpoint Tests (GET /outbox/events)
# =========================================================================

def test_get_outbox_events_scraper(client):
    """Test scraping outbox events across entities."""
    # Trigger a transfer to create 3 events
    client.post("/transfers", json={
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 2000,
    })

    # Trigger a quote to create 1 event
    client.post("/quotes", json={
        "user_id": "user_3",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 1000,
    })

    # Scrape pending events
    res = client.get("/outbox/events")
    assert res.status_code == 200
    data = res.get_json()
    assert "events" in data
    assert "total" in data
    assert data["total"] == 4
    assert len(data["events"]) == 4

    # Verify chronological sorting
    timestamps = [e["timestamp"] for e in data["events"]]
    assert timestamps == sorted(timestamps)


def test_get_outbox_events_pagination_limit(client):
    """Test limit query parameter on outbox scraper endpoint."""
    client.post("/transfers", json={
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 1000,
    })

    res = client.get("/outbox/events?limit=2")
    assert res.status_code == 200
    data = res.get_json()
    assert len(data["events"]) == 2
    assert data["total"] == 3  # total matching pending events


# =========================================================================
# 4. Outbox Acknowledgment Endpoint Tests (POST /outbox/events/ack)
# =========================================================================

def test_ack_outbox_events(client):
    """Test acknowledging outbox events and verifying status transitions to PUBLISHED."""
    client.post("/transfers", json={
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 1000,
    })

    # Get pending events
    res = client.get("/outbox/events?status=PENDING")
    events = res.get_json()["events"]
    event_ids = [e["event_id"] for e in events]
    assert len(event_ids) == 3

    # Ack the first 2 events
    ack_res = client.post("/outbox/events/ack", json={"event_ids": event_ids[:2]})
    assert ack_res.status_code == 200
    ack_data = ack_res.get_json()
    assert ack_data["count"] == 2
    assert ack_data["acknowledged_ids"] == event_ids[:2]

    # Verify only 1 pending event remains
    pending_res = client.get("/outbox/events?status=PENDING")
    pending_events = pending_res.get_json()["events"]
    assert len(pending_events) == 1
    assert pending_events[0]["event_id"] == event_ids[2]

    # Verify 2 published events appear under ?status=PUBLISHED
    published_res = client.get("/outbox/events?status=PUBLISHED")
    published_events = published_res.get_json()["events"]
    assert len(published_events) == 2


def test_ack_outbox_events_validation(client):
    """Test validation errors on /outbox/events/ack."""
    # Empty body
    res = client.post("/outbox/events/ack", data="not json", content_type="application/json")
    assert res.status_code == 400

    # Missing event_ids
    res = client.post("/outbox/events/ack", json={})
    assert res.status_code == 400

    # Empty event_ids list
    res = client.post("/outbox/events/ack", json={"event_ids": []})
    assert res.status_code == 400
