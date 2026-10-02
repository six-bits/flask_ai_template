"""Idempotency tests for Multi-Currency Wallet transfers and quotes."""

import pytest

from app.adapter.idempotency_adapter import idempotency_adapter
from app.adapter.quote_adapter import quote_adapter
from app.adapter.transaction_adapter import transaction_adapter
from app.adapter.user_wallet_adapter import user_wallet_adapter
from app.manager.lock_manager import lock_manager


@pytest.fixture(autouse=True)
def reset_all():
    """Reset all state before each idempotency test."""
    user_wallet_adapter.reset()
    quote_adapter.reset()
    transaction_adapter.reset()
    idempotency_adapter.reset()
    lock_manager.reset()


def test_transfer_idempotent_replay(client):
    """Test that repeating a transfer with the same Idempotency-Key replays the cached response

    without re-debiting or creating duplicate ledger / outbox entries.
    """
    payload = {
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 5000,
    }
    headers = {"Idempotency-Key": "key_tx_1"}

    # First attempt: executes transfer
    res1 = client.post("/transfers", json=payload, headers=headers)
    assert res1.status_code == 200
    data1 = res1.get_json()
    assert "Idempotent-Replayed" not in res1.headers
    assert data1["from_user_balance"] == 95000

    # Second attempt: replays cached response
    res2 = client.post("/transfers", json=payload, headers=headers)
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert res2.headers.get("Idempotent-Replayed") == "true"
    assert data2["transfer_id"] == data1["transfer_id"]
    assert data2["from_user_balance"] == 95000

    # User balance must be debited only once
    bal_res = client.get("/users/user_1/balances")
    assert bal_res.get_json()["balances"]["USD"] == 95000

    # Ledger must have only 1 sent transaction for Alice
    tx_res = client.get("/users/user_1/transactions")
    txs = tx_res.get_json()["transactions"]
    assert len(txs) == 1

    # Outbox scraper must have only 3 events total (sender, pool hop, recipient)
    outbox_res = client.get("/outbox/events")
    assert outbox_res.get_json()["total"] == 3


def test_transfer_idempotency_payload_mismatch(client):
    """Test that reusing an Idempotency-Key with different payload parameters is rejected with 422."""
    headers = {"Idempotency-Key": "key_tx_2"}

    # First request: 5,000 USD
    res1 = client.post("/transfers", json={
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 5000,
    }, headers=headers)
    assert res1.status_code == 200

    # Second request: same key, but altered amount (6,000 USD)
    res2 = client.post("/transfers", json={
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 6000,
    }, headers=headers)
    assert res2.status_code == 422
    data2 = res2.get_json()
    assert data2["error"] == "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"


def test_concurrent_duplicate_idempotency_key_conflict(client):
    """Test that a concurrent in-flight request with the same Idempotency-Key is rejected with 409."""
    # Simulate an active in-progress reservation in the adapter
    idempotency_adapter.reserve(
        key="key_in_progress",
        user_id="user_1",
        endpoint="/transfers",
        request_hash="some_hash",
    )

    res = client.post("/transfers", json={
        "from_user_id": "user_1",
        "to_user_id": "user_2",
        "currency": "USD",
        "amount": 5000,
    }, headers={"Idempotency-Key": "key_in_progress"})

    assert res.status_code == 409
    data = res.get_json()
    assert data["error"] == "CONCURRENT_REQUEST_IN_PROGRESS"


def test_quote_acceptance_idempotent_replay(client):
    """Test that accepting a quote with an Idempotency-Key replays the response without double conversion."""
    q_res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    })
    quote_id = q_res.get_json()["quote_id"]
    headers = {"Idempotency-Key": "key_quote_1"}

    # First accept
    res1 = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1"}, headers=headers)
    assert res1.status_code == 200
    data1 = res1.get_json()
    assert "Idempotent-Replayed" not in res1.headers
    assert data1["status"] == "ACCEPTED"

    # Replay accept
    res2 = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1"}, headers=headers)
    assert res2.status_code == 200
    assert res2.headers.get("Idempotent-Replayed") == "true"
    data2 = res2.get_json()
    assert data2["quote_id"] == data1["quote_id"]
    assert data2["status"] == "ACCEPTED"

    # Alice was debited only once for 10,000 USD
    bal_res = client.get("/users/user_1/balances")
    assert bal_res.get_json()["balances"]["USD"] == 90000


def test_quote_acceptance_payload_mismatch(client):
    """Test that accepting a quote with same key but altered payload fails with 422."""
    q_res = client.post("/quotes", json={
        "user_id": "user_1",
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
    })
    quote_id = q_res.get_json()["quote_id"]
    headers = {"Idempotency-Key": "key_quote_2"}

    # First accept
    res1 = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1"}, headers=headers)
    assert res1.status_code == 200

    # Second accept with altered payload
    res2 = client.post(f"/quotes/{quote_id}/accept", json={"user_id": "user_1", "extra": "tampered"}, headers=headers)
    # The JSON schema validation or hash check will catch this
    assert res2.status_code in (400, 422)
