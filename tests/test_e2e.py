"""End-to-end live server tests for card authorization and multi-clearing service."""

import concurrent.futures
import socket
import threading
import time
import uuid
import pytest
import requests
from werkzeug.serving import make_server

from app.adapter.db import db
from app.service.api import app


def find_free_port():
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server_url():
    """Start Flask live server in a background daemon thread for true HTTP testing."""
    port = find_free_port()
    server = make_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    time.sleep(0.1)
    yield base_url

    server.shutdown()
    thread.join(timeout=2.0)


@pytest.fixture(autouse=True)
def reset_database():
    """Reset the database before each test."""
    db.reset()


def test_e2e_health(live_server_url):
    """Verify live server health endpoint."""
    res = requests.get(f"{live_server_url}/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_e2e_authorization_lifecycle(live_server_url):
    """Test full authorization placement and balance reflection."""
    headers = {"Idempotency-Key": f"auth-{uuid.uuid4()}"}
    payload = {"card_id": "card_seed_1", "amount": 100.0, "merchant": "Amazon"}

    res = requests.post(f"{live_server_url}/authorizations", headers=headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "APPROVED"
    assert data["amount"] == 100.0
    auth_id = data["authorization_id"]

    # Check balance: limit 1000, held 100, available 900
    bal_res = requests.get(f"{live_server_url}/cards/card_seed_1/balance")
    assert bal_res.status_code == 200
    bal = bal_res.json()
    assert bal["credit_limit"] == 1000.0
    assert bal["held_balance"] == 100.0
    assert bal["settled_balance"] == 0.0
    assert bal["available_limit"] == 900.0


def test_e2e_authorization_insufficient_funds(live_server_url):
    """Test authorization is declined when exceeding credit limit."""
    headers = {"Idempotency-Key": f"auth-{uuid.uuid4()}"}
    payload = {"card_id": "card_seed_2", "amount": 600.0, "merchant": "Target"}  # limit is 500

    res = requests.post(f"{live_server_url}/authorizations", headers=headers, json=payload)
    assert res.status_code == 422
    data = res.json()
    assert data["error"] == "INSUFFICIENT_FUNDS"
    assert data["status"] == "DECLINED"
    assert data["available_limit"] == 500.0

    # Ensure no hold was placed
    bal = requests.get(f"{live_server_url}/cards/card_seed_2/balance").json()
    assert bal["held_balance"] == 0.0
    assert bal["available_limit"] == 500.0


def test_e2e_seed_validations(live_server_url):
    """Test validations against seeded cards, merchants, and headers."""
    # 1. Missing Idempotency-Key
    res = requests.post(
        f"{live_server_url}/authorizations",
        json={"card_id": "card_seed_1", "amount": 50.0, "merchant": "Amazon"},
    )
    assert res.status_code == 400
    assert "Idempotency-Key" in res.json()["message"]

    # 2. Unknown Merchant
    res = requests.post(
        f"{live_server_url}/authorizations",
        headers={"Idempotency-Key": f"auth-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 50.0, "merchant": "UnknownVendor"},
    )
    assert res.status_code == 400
    assert "not recognized" in res.json()["message"]

    # 3. Unknown Card
    res = requests.post(
        f"{live_server_url}/authorizations",
        headers={"Idempotency-Key": f"auth-{uuid.uuid4()}"},
        json={"card_id": "card_unknown", "amount": 50.0, "merchant": "Amazon"},
    )
    assert res.status_code == 404
    assert "not found" in res.json()["message"]


def test_e2e_idempotency_replay_and_conflict(live_server_url):
    """Test idempotent replay returns cached response with no-op, while mismatched hash conflicts."""
    idemp_key = f"idemp-test-{uuid.uuid4()}"
    headers = {"Idempotency-Key": idemp_key}
    payload = {"card_id": "card_seed_1", "amount": 100.0, "merchant": "Amazon"}

    # First attempt: approved (201)
    res1 = requests.post(f"{live_server_url}/authorizations", headers=headers, json=payload)
    assert res1.status_code == 201
    assert "Idempotent-Replay" not in res1.headers
    data1 = res1.json()

    # Retry exact same request: should return identical response with Idempotent-Replay: true
    res2 = requests.post(f"{live_server_url}/authorizations", headers=headers, json=payload)
    assert res2.status_code == 201
    assert res2.headers.get("Idempotent-Replay") == "true"
    assert res2.json() == data1

    # Check balance: held balance is still only 100, not 200 (no-op)
    bal = requests.get(f"{live_server_url}/cards/card_seed_1/balance").json()
    assert bal["held_balance"] == 100.0
    assert bal["available_limit"] == 900.0

    # Resend same key with DIFFERENT payload (amount = 200) -> 409 Conflict
    diff_payload = {"card_id": "card_seed_1", "amount": 200.0, "merchant": "Amazon"}
    res3 = requests.post(f"{live_server_url}/authorizations", headers=headers, json=diff_payload)
    assert res3.status_code == 409
    assert res3.json()["error"] == "Conflict"


def test_e2e_multi_clearing_partial_settlement(live_server_url):
    """Test Amazon multi-clearing: auth $100 -> clear $40 -> clear $30."""
    # 1. Authorize $100
    auth_res = requests.post(
        f"{live_server_url}/authorizations",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 100.0, "merchant": "Amazon"},
    )
    assert auth_res.status_code == 201
    auth_id = auth_res.json()["authorization_id"]

    # 2. Clear Box 1 ($40)
    clr1 = requests.post(
        f"{live_server_url}/clearings",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 40.0, "merchant": "Amazon", "authorization_id": auth_id},
    )
    assert clr1.status_code == 201
    assert clr1.json()["is_force_post"] is False

    bal1 = requests.get(f"{live_server_url}/cards/card_seed_1/balance").json()
    assert bal1["settled_balance"] == 40.0
    assert bal1["held_balance"] == 60.0
    assert bal1["available_limit"] == 900.0

    # 3. Clear Box 2 ($30)
    clr2 = requests.post(
        f"{live_server_url}/clearings",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 30.0, "merchant": "Amazon", "authorization_id": auth_id},
    )
    assert clr2.status_code == 201

    bal2 = requests.get(f"{live_server_url}/cards/card_seed_1/balance").json()
    assert bal2["settled_balance"] == 70.0
    assert bal2["held_balance"] == 30.0
    assert bal2["available_limit"] == 900.0


def test_e2e_over_capture_restaurant_tip(live_server_url):
    """Test over-capture: auth $50 meal -> clear $60 (meal + $10 tip)."""
    # 1. Authorize $50
    auth_res = requests.post(
        f"{live_server_url}/authorizations",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 50.0, "merchant": "Restaurant"},
    )
    auth_id = auth_res.json()["authorization_id"]

    # 2. Clear $60
    clr = requests.post(
        f"{live_server_url}/clearings",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 60.0, "merchant": "Restaurant", "authorization_id": auth_id},
    )
    assert clr.status_code == 201

    # Entire $50 hold is released; settled is $60; available limit absorbs extra $10
    bal = requests.get(f"{live_server_url}/cards/card_seed_1/balance").json()
    assert bal["held_balance"] == 0.0
    assert bal["settled_balance"] == 60.0
    assert bal["available_limit"] == 940.0


def test_e2e_force_post_exceeding_credit_limit(live_server_url):
    """Test force-post clears without prior auth and drives available limit negative."""
    # Force-post of $1200 on card_seed_1 (credit limit $1000)
    res = requests.post(
        f"{live_server_url}/clearings",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 1200.0, "merchant": "Airline Offline"},
    )
    assert res.status_code == 201
    assert res.json()["is_force_post"] is True

    bal = requests.get(f"{live_server_url}/cards/card_seed_1/balance").json()
    assert bal["settled_balance"] == 1200.0
    assert bal["held_balance"] == 0.0
    assert bal["available_limit"] == -200.0


def test_e2e_reversal_lifecycle(live_server_url):
    """Test partial reversal, full reversal, and reject on already reversed hold."""
    # 1. Authorize $100
    auth_res = requests.post(
        f"{live_server_url}/authorizations",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 100.0, "merchant": "Amazon"},
    )
    auth_id = auth_res.json()["authorization_id"]

    # 2. Partial reversal of $30
    rev1 = requests.post(
        f"{live_server_url}/authorizations/{auth_id}/reversals",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 30.0},
    )
    assert rev1.status_code == 200
    assert rev1.json()["reversed_amount"] == 30.0
    assert rev1.json()["remaining_held_amount"] == 70.0

    bal1 = requests.get(f"{live_server_url}/cards/card_seed_1/balance").json()
    assert bal1["held_balance"] == 70.0
    assert bal1["available_limit"] == 930.0

    # 3. Full remaining reversal (omit amount)
    rev2 = requests.post(
        f"{live_server_url}/authorizations/{auth_id}/reversals",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1"},
    )
    assert rev2.status_code == 200
    assert rev2.json()["reversed_amount"] == 70.0
    assert rev2.json()["remaining_held_amount"] == 0.0

    bal2 = requests.get(f"{live_server_url}/cards/card_seed_1/balance").json()
    assert bal2["held_balance"] == 0.0
    assert bal2["available_limit"] == 1000.0

    # 4. Attempt reversal when no held balance left -> 422
    rev3 = requests.post(
        f"{live_server_url}/authorizations/{auth_id}/reversals",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1"},
    )
    assert rev3.status_code == 422


def test_e2e_hold_expiration_and_reversal_rejection(live_server_url):
    """Test 60-second hold expiration dynamically restores available limit and rejects reversals."""
    auth_res = requests.post(
        f"{live_server_url}/authorizations",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 100.0, "merchant": "Amazon"},
    )
    auth_id = auth_res.json()["authorization_id"]

    # Fast forward: set expires_at to the past
    auth_record = db.get_authorization(auth_id)
    auth_record.expires_at = time.time() - 10.0

    # Balance check: hold is recognized as expired, available limit is back to 1000
    bal = requests.get(f"{live_server_url}/cards/card_seed_1/balance").json()
    assert bal["held_balance"] == 0.0
    assert bal["available_limit"] == 1000.0

    # Attempting to reverse an expired hold fails with 422
    rev = requests.post(
        f"{live_server_url}/authorizations/{auth_id}/reversals",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1"},
    )
    assert rev.status_code == 422
    assert "expired" in rev.json()["message"]


def test_e2e_transaction_ledger_audit_trail(live_server_url):
    """Test GET /cards/<id>/transactions returns immutable audit trail."""
    auth_res = requests.post(
        f"{live_server_url}/authorizations",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 100.0, "merchant": "Amazon"},
    )
    auth_id = auth_res.json()["authorization_id"]

    requests.post(
        f"{live_server_url}/clearings",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 40.0, "merchant": "Amazon", "authorization_id": auth_id},
    )

    requests.post(
        f"{live_server_url}/authorizations/{auth_id}/reversals",
        headers={"Idempotency-Key": f"k-{uuid.uuid4()}"},
        json={"card_id": "card_seed_1", "amount": 60.0},
    )

    tx_res = requests.get(f"{live_server_url}/cards/card_seed_1/transactions")
    assert tx_res.status_code == 200
    txs = tx_res.json()["transactions"]

    assert len(txs) == 3
    assert txs[0]["type"] == "AUTHORIZATION"
    assert txs[0]["amount"] == 100.0
    assert txs[1]["type"] == "CLEARING"
    assert txs[1]["amount"] == 40.0
    assert txs[2]["type"] == "REVERSAL"
    assert txs[2]["amount"] == 60.0


def test_e2e_concurrent_granular_locking_stress(live_server_url):
    """Stress test: 30 concurrent threads hitting authorizations and clearings on same & different cards.

    Verifies granular locking ensures no deadlocks, race conditions, or balance inconsistencies.
    """
    num_requests = 30

    def make_auth_request(card_id, amount):
        headers = {"Idempotency-Key": f"stress-{uuid.uuid4()}"}
        payload = {"card_id": card_id, "amount": amount, "merchant": "Amazon"}
        return requests.post(f"{live_server_url}/authorizations", headers=headers, json=payload)

    def make_force_post(card_id, amount):
        headers = {"Idempotency-Key": f"stress-{uuid.uuid4()}"}
        payload = {"card_id": card_id, "amount": amount, "merchant": "Target"}
        return requests.post(f"{live_server_url}/clearings", headers=headers, json=payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for i in range(num_requests):
            target_card = "card_seed_1" if i % 2 == 0 else "card_seed_3"
            if i % 3 == 0:
                futures.append(executor.submit(make_force_post, target_card, 10.0))
            else:
                futures.append(executor.submit(make_auth_request, target_card, 20.0))

        results = [f.result(timeout=10.0) for f in concurrent.futures.as_completed(futures)]

    # All requests should return valid responses without timing out or deadlocking
    assert len(results) == num_requests
    for res in results:
        assert res.status_code in (201, 422)

    # Balance check: verify mathematical consistency for card_seed_3 (credit limit 2000)
    bal3 = requests.get(f"{live_server_url}/cards/card_seed_3/balance").json()
    calc_avail = bal3["credit_limit"] - bal3["settled_balance"] - bal3["held_balance"]
    assert round(bal3["available_limit"], 2) == round(calc_avail, 2)
