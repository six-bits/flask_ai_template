"""End-to-end multi-threaded concurrency and invariant verification tests."""

import concurrent.futures
import random
import socket
import threading
import time
import uuid
import pytest
import requests
from werkzeug.serving import make_server

from app.adapter.db import db
from app.manager.payment_manager import payment_manager
from app.service.api import app


def find_free_port():
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server_url():
    """Start live Werkzeug server in daemon thread for HTTP concurrency testing."""
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
    """Reset database and default hold TTL before each test."""
    payment_manager.hold_ttl_seconds = 60.0
    db.reset()


def test_e2e_concurrent_idempotent_duplicate_storm(live_server_url):
    """Scenario A: 40 concurrent threads hammering 4 unique idempotency keys simultaneously.

    Verifies idempotent singularity: money is deducted strictly once per key (4 debits),
    remaining 36 requests receive Idempotent-Replay: true, and ledger contains exactly 4 entries.
    """
    card_id = "card_seed_1"  # Limit: 1000.0
    keys = [f"storm-key-{i}-{uuid.uuid4()}" for i in range(4)]
    total_workers = 40

    def send_auth(key):
        headers = {"Idempotency-Key": key}
        payload = {"card_id": card_id, "amount": 50.0, "merchant": "Amazon"}
        return requests.post(f"{live_server_url}/authorizations", headers=headers, json=payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        # Distribute the 4 keys across 40 threads (10 threads per key)
        futures = [executor.submit(send_auth, keys[i % len(keys)]) for i in range(total_workers)]
        responses = [f.result(timeout=10.0) for f in concurrent.futures.as_completed(futures)]

    assert len(responses) == total_workers
    for r in responses:
        assert r.status_code == 201

    replayed_count = sum(1 for r in responses if r.headers.get("Idempotent-Replay") == "true")
    original_count = sum(1 for r in responses if r.headers.get("Idempotent-Replay") != "true")

    assert original_count == 4, f"Expected 4 original requests, got {original_count}"
    assert replayed_count == 36, f"Expected 36 replayed requests, got {replayed_count}"

    # Invariant Verification on card balance
    bal = requests.get(f"{live_server_url}/cards/{card_id}/balance").json()
    assert bal["held_balance"] == 200.0, f"Expected held 200.0, got {bal['held_balance']}"
    assert bal["settled_balance"] == 0.0
    assert bal["available_limit"] == 800.0
    assert round(bal["credit_limit"] - bal["settled_balance"] - bal["held_balance"], 2) == bal["available_limit"]

    # Transaction ledger must have exactly 4 entries
    txs = requests.get(f"{live_server_url}/cards/{card_id}/transactions").json()["transactions"]
    assert len(txs) == 4, f"Expected exactly 4 ledger transactions, found {len(txs)}"


def test_e2e_concurrent_limit_depletion_race(live_server_url):
    """Scenario B: 50 concurrent threads racing to authorize $50 on a $500 limit card.

    Verifies over-subscription boundary: exactly 10 succeed, 40 decline with 422,
    held balance is exactly $500, available limit is exactly $0, and zero over-authorization occurs.
    """
    card_id = "card_seed_2"  # Limit: 500.0
    num_threads = 50
    amount_per_request = 50.0

    def make_auth():
        headers = {"Idempotency-Key": f"deplete-{uuid.uuid4()}"}
        payload = {"card_id": card_id, "amount": amount_per_request, "merchant": "Target"}
        return requests.post(f"{live_server_url}/authorizations", headers=headers, json=payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        futures = [executor.submit(make_auth) for _ in range(num_threads)]
        responses = [f.result(timeout=10.0) for f in concurrent.futures.as_completed(futures)]

    status_201 = sum(1 for r in responses if r.status_code == 201)
    status_422 = sum(1 for r in responses if r.status_code == 422)

    assert status_201 == 10, f"Expected exactly 10 approvals, got {status_201}"
    assert status_422 == 40, f"Expected exactly 40 declines, got {status_422}"

    # Balance check: limit completely saturated to $0
    bal = requests.get(f"{live_server_url}/cards/{card_id}/balance").json()
    assert bal["held_balance"] == 500.0
    assert bal["settled_balance"] == 0.0
    assert bal["available_limit"] == 0.0
    assert round(bal["credit_limit"] - bal["settled_balance"] - bal["held_balance"], 2) == 0.0


def test_e2e_concurrent_fast_expiration_race(live_server_url):
    """Scenario C: Fast 200ms hold TTL testing.

    10 authorizations placed ($50 each = $500 held). 4 are immediately cleared ($200 settled).
    After 250ms, remaining 6 holds expire. Held balance drops to $0, available limit restored to $800.
    """
    payment_manager.hold_ttl_seconds = 0.2  # 200 milliseconds TTL
    card_id = "card_seed_1"  # Limit: 1000.0

    # Step 1: Create 10 authorizations
    auth_ids = []
    for _ in range(10):
        res = requests.post(
            f"{live_server_url}/authorizations",
            headers={"Idempotency-Key": f"ttl-{uuid.uuid4()}"},
            json={"card_id": card_id, "amount": 50.0, "merchant": "Amazon"},
        )
        assert res.status_code == 201
        auth_ids.append(res.json()["authorization_id"])

    # Immediate balance: 10 * 50 = $500 held, $500 available
    bal_initial = requests.get(f"{live_server_url}/cards/{card_id}/balance").json()
    assert bal_initial["held_balance"] == 500.0
    assert bal_initial["available_limit"] == 500.0

    # Step 2: Concurrently clear 4 authorizations within 50ms (before expiry)
    def clear_auth(auth_id):
        headers = {"Idempotency-Key": f"ttl-clr-{uuid.uuid4()}"}
        payload = {"card_id": card_id, "amount": 50.0, "merchant": "Amazon", "authorization_id": auth_id}
        return requests.post(f"{live_server_url}/clearings", headers=headers, json=payload)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        clear_futures = [executor.submit(clear_auth, auth_ids[i]) for i in range(4)]
        clear_responses = [f.result(timeout=5.0) for f in concurrent.futures.as_completed(clear_futures)]

    for r in clear_responses:
        assert r.status_code == 201

    # Step 3: Wait 250ms for the remaining 6 authorizations to expire
    time.sleep(0.25)

    # Step 4: Check balance: remaining 6 holds expired ($0 held), $200 settled, $800 available
    bal_after = requests.get(f"{live_server_url}/cards/{card_id}/balance").json()
    assert bal_after["settled_balance"] == 200.0
    assert bal_after["held_balance"] == 0.0, f"Expected 0.0 held after expiry, got {bal_after['held_balance']}"
    assert bal_after["available_limit"] == 800.0

    # Invariant verified
    assert round(bal_after["credit_limit"] - bal_after["settled_balance"] - bal_after["held_balance"], 2) == 800.0

    # Step 5: Late reversal on an expired authorization must be rejected with 422
    expired_auth_id = auth_ids[5]
    late_rev = requests.post(
        f"{live_server_url}/authorizations/{expired_auth_id}/reversals",
        headers={"Idempotency-Key": f"late-rev-{uuid.uuid4()}"},
        json={"card_id": card_id},
    )
    assert late_rev.status_code == 422
    assert "expired" in late_rev.json()["message"]


def test_e2e_multi_card_concurrency_chaos_and_invariants(live_server_url):
    """Scenario D: 120 concurrent mixed requests across all seed cards with random duplicate replays.

    Verifies mathematical invariant preservation across all cards:
    Available Limit == Credit Limit - Settled Balance - Held Balance
    with zero deadlocks and zero exceptions under heavy multi-card contention.
    """
    card_limits = {
        "card_seed_1": 1000.0,
        "card_seed_2": 500.0,
        "card_seed_3": 2000.0,
    }
    cards = list(card_limits.keys())
    merchants = ["Amazon", "Restaurant", "Target", "Starbucks", "Airline Offline"]

    created_auths = []
    auths_lock = threading.Lock()
    reusable_keys = [f"reuse-key-{i}" for i in range(10)]

    def execute_random_operation(worker_id):
        target_card = random.choice(cards)
        target_merchant = random.choice(merchants)
        op_type = random.choice(["auth", "force_post", "clear_existing", "reverse_existing", "retry"])

        if op_type == "retry":
            key = random.choice(reusable_keys)
            payload = {"card_id": target_card, "amount": 25.0, "merchant": "Amazon"}
            return requests.post(f"{live_server_url}/authorizations", headers={"Idempotency-Key": key}, json=payload)

        elif op_type == "auth":
            key = f"chaos-auth-{worker_id}-{uuid.uuid4()}"
            amt = random.choice([20.0, 50.0, 100.0])
            payload = {"card_id": target_card, "amount": amt, "merchant": target_merchant}
            res = requests.post(f"{live_server_url}/authorizations", headers={"Idempotency-Key": key}, json=payload)
            if res.status_code == 201:
                with auths_lock:
                    created_auths.append((target_card, res.json()["authorization_id"], target_merchant))
            return res

        elif op_type == "force_post":
            key = f"chaos-fp-{worker_id}-{uuid.uuid4()}"
            amt = random.choice([15.0, 40.0])
            payload = {"card_id": target_card, "amount": amt, "merchant": target_merchant}
            return requests.post(f"{live_server_url}/clearings", headers={"Idempotency-Key": key}, json=payload)

        elif op_type == "clear_existing":
            with auths_lock:
                item = random.choice(created_auths) if created_auths else None
            if item:
                c_id, a_id, m_name = item
                key = f"chaos-clr-{worker_id}-{uuid.uuid4()}"
                payload = {"card_id": c_id, "amount": 20.0, "merchant": m_name, "authorization_id": a_id}
                return requests.post(f"{live_server_url}/clearings", headers={"Idempotency-Key": key}, json=payload)
            else:
                key = f"chaos-fp-fallback-{worker_id}-{uuid.uuid4()}"
                return requests.post(
                    f"{live_server_url}/clearings",
                    headers={"Idempotency-Key": key},
                    json={"card_id": target_card, "amount": 10.0, "merchant": target_merchant},
                )

        else:  # reverse_existing
            with auths_lock:
                item = random.choice(created_auths) if created_auths else None
            if item:
                c_id, a_id, _ = item
                key = f"chaos-rev-{worker_id}-{uuid.uuid4()}"
                payload = {"card_id": c_id, "amount": 10.0}
                return requests.post(
                    f"{live_server_url}/authorizations/{a_id}/reversals",
                    headers={"Idempotency-Key": key},
                    json=payload,
                )
            else:
                return requests.get(f"{live_server_url}/cards/{target_card}/balance")

    total_ops = 120
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(execute_random_operation, i) for i in range(total_ops)]
        results = [f.result(timeout=15.0) for f in concurrent.futures.as_completed(futures)]

    assert len(results) == total_ops
    # Ensure no server crashed with 500
    for r in results:
        assert r.status_code in (200, 201, 400, 404, 409, 422), f"Unexpected status {r.status_code}: {r.text}"

    # MATHEMATICAL INVARIANT CHECK ACROSS ALL CARDS
    for card_id, credit_limit in card_limits.items():
        bal = requests.get(f"{live_server_url}/cards/{card_id}/balance").json()
        assert bal["credit_limit"] == credit_limit

        settled = bal["settled_balance"]
        held = bal["held_balance"]
        actual_available = bal["available_limit"]
        expected_available = round(credit_limit - settled - held, 2)

        assert round(actual_available, 2) == expected_available, (
            f"Invariant violated on {card_id}! Credit: {credit_limit}, "
            f"Settled: {settled}, Held: {held}, Actual Avail: {actual_available}, "
            f"Expected Avail: {expected_available}"
        )
