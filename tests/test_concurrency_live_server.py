"""Live HTTP server E2E concurrency tests for Flash Sale Inventory Reservation Service.

Starts a real live Werkzeug HTTP server on an ephemeral port and tests concurrency,
reclamation, anti-hoarding, and race condition invariants via real socket HTTP requests.
"""

import concurrent.futures
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

import pytest
from werkzeug.serving import make_server

from app.adapter.db import in_memory_db
from app.manager.inventory_manager import inventory_manager
from app.service.api import app


# ---------------------------------------------------------------------------
# HTTP Client Helper (Zero-dependency via standard urllib)
# ---------------------------------------------------------------------------


def http_request(
    method: str, url: str, data: Optional[Dict[str, Any]] = None
) -> Tuple[int, Dict[str, Any]]:
    """Execute real HTTP request against live server and return (status_code, json_dict)."""
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")

    encoded_body = json.dumps(data).encode("utf-8") if data is not None else None

    try:
        with urllib.request.urlopen(req, data=encoded_body, timeout=5) as response:
            status = response.status
            content = response.read().decode("utf-8")
            parsed = json.loads(content) if content else {}
            return status, parsed
    except urllib.error.HTTPError as err:
        status = err.code
        content = err.read().decode("utf-8")
        try:
            parsed = json.loads(content) if content else {}
        except Exception:
            parsed = {"raw": content}
        return status, parsed


def find_free_port() -> int:
    """Find an available ephemeral port on loopback."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_server_url():
    """Start real Flask HTTP server in daemon thread and yield its base URL."""
    port = find_free_port()
    server = make_server("127.0.0.1", port, app, threaded=True)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"

    # Poll /health until server responds
    for _ in range(50):
        try:
            status, data = http_request("GET", f"{base_url}/health")
            if status == 200 and data.get("status") == "ok":
                break
        except Exception:
            time.sleep(0.05)
    else:
        raise RuntimeError("Live server failed to initialize")

    yield base_url

    server.shutdown()


@pytest.fixture(autouse=True)
def reset_db_state():
    """Reset in-memory database and default lease duration before each test."""
    in_memory_db.reset()
    inventory_manager.LEASE_DURATION_SECONDS = 30.0
    yield
    in_memory_db.reset()
    inventory_manager.LEASE_DURATION_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Concurrency Tests
# ---------------------------------------------------------------------------


def test_cross_item_parallelism_no_contention(live_server_url):
    """Test 1: Requests across different items execute in parallel without cross-blocking."""
    # item_vip_ticket: total 10, max_per_user 2
    # item_ga_ticket: total 50, max_per_user 4
    # item_merch_hoodie: total 5, max_per_user 1

    tasks = []
    # 5 buyers for VIP tickets (1 unit each -> 5 units)
    for i in range(5):
        tasks.append(("item_vip_ticket", f"buyer_{i}", 1))

    # 10 buyers for GA tickets (2 units each -> 20 units)
    for i in range(5, 15):
        tasks.append(("item_ga_ticket", f"buyer_{i}", 2))

    # 5 buyers for Hoodie (1 unit each -> 5 units)
    for i in range(15, 20):
        tasks.append(("item_merch_hoodie", f"buyer_{i}", 1))

    def make_reservation(item_id, user_id, qty):
        url = f"{live_server_url}/reservations"
        return http_request("POST", url, {"item_id": item_id, "user_id": user_id, "quantity": qty})

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        futures = [executor.submit(make_reservation, item_id, user_id, qty) for item_id, user_id, qty in tasks]
        results = [f.result() for f in futures]

    # Every request should succeed with 201 Created
    for status, data in results:
        assert status == 201, f"Expected 201, got {status}: {data}"
        assert data["status"] == "PENDING"

    # Verify inventory consistency across each SKU
    _, vip_stock = http_request("GET", f"{live_server_url}/items/item_vip_ticket")
    assert vip_stock["total_stock"] == 10
    assert vip_stock["held_stock"] == 5
    assert vip_stock["available_stock"] == 5

    _, ga_stock = http_request("GET", f"{live_server_url}/items/item_ga_ticket")
    assert ga_stock["total_stock"] == 50
    assert ga_stock["held_stock"] == 20
    assert ga_stock["available_stock"] == 30

    _, hoodie_stock = http_request("GET", f"{live_server_url}/items/item_merch_hoodie")
    assert hoodie_stock["total_stock"] == 5
    assert hoodie_stock["held_stock"] == 5
    assert hoodie_stock["available_stock"] == 0

    # Invariants strictly preserved
    for stock in [vip_stock, ga_stock, hoodie_stock]:
        assert stock["total_stock"] == stock["available_stock"] + stock["held_stock"] + stock["confirmed_stock"]


def test_same_item_heavy_contention_and_quota_breaches(live_server_url):
    """Test 2: High contention on same item rejects over-capacity and quota breaches with zero overselling."""
    # item_vip_ticket: total 10, max_per_user 2

    tasks = []
    # Group A: 10 distinct users attempt to reserve 2 units each (total demand 20, supply 10)
    for i in range(10):
        tasks.append((f"buyer_{i}", 2))

    # Group B: 5 users attempt to reserve 3 units each (deliberately exceeds max_per_user = 2)
    for i in range(10, 15):
        tasks.append((f"buyer_{i}", 3))

    # Group C: Duplicate parallel requests from buyer_0 attempting to hoard
    for _ in range(5):
        tasks.append(("buyer_0", 2))

    # Group D: 10 more users attempt to reserve 1 unit each
    for i in range(15, 25):
        tasks.append((f"buyer_{i}", 1))

    # Total 30 concurrent racing requests
    def attempt_reserve(user_id, qty):
        url = f"{live_server_url}/reservations"
        return http_request("POST", url, {"item_id": "item_vip_ticket", "user_id": user_id, "quantity": qty})

    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = [executor.submit(attempt_reserve, user_id, qty) for user_id, qty in tasks]
        results = [f.result() for f in futures]

    successes = [r for r in results if r[0] == 201]
    conflicts = [r for r in results if r[0] == 409]

    # Every response is either 201 Created or 409 Conflict
    assert len(successes) + len(conflicts) == len(tasks)

    # Sum of held units across successful reservations must not exceed 10
    total_units_held = sum(data["quantity"] for _, data in successes)
    assert total_units_held == 10

    # Verify live stock: exactly 0 available, exactly 10 held
    _, stock = http_request("GET", f"{live_server_url}/items/item_vip_ticket")
    assert stock["total_stock"] == 10
    assert stock["available_stock"] == 0
    assert stock["held_stock"] == 10
    assert stock["confirmed_stock"] == 0
    assert stock["total_stock"] == stock["available_stock"] + stock["held_stock"] + stock["confirmed_stock"]


def test_jit_reclamation_under_concurrency(live_server_url):
    """Test 3: Expired reservations are reclaimed JIT and re-allocated under concurrent requests."""
    # Set short lease TTL for fast, crisp test execution
    inventory_manager.LEASE_DURATION_SECONDS = 0.5
    # item_merch_hoodie: total 5, max_per_user 1

    # 1. First 5 buyers exhaust all 5 units
    for i in range(5):
        status, data = http_request(
            "POST",
            f"{live_server_url}/reservations",
            {"item_id": "item_merch_hoodie", "user_id": f"buyer_{i}", "quantity": 1},
        )
        assert status == 201
    old_res_id = data["reservation_id"]

    # Overflow request is rejected
    status, err = http_request(
        "POST",
        f"{live_server_url}/reservations",
        {"item_id": "item_merch_hoodie", "user_id": "buyer_5", "quantity": 1},
    )
    assert status == 409
    assert err["error"] == "Insufficient stock"

    # Wait for the 0.5s lease duration to expire
    time.sleep(0.65)

    # 2. Concurrently fire:
    # - 5 new buyers attempting to reserve the 5 reclaimed units
    # - 5 concurrent readers hitting GET /items/item_merch_hoodie
    def new_reserve(user_idx):
        return http_request(
            "POST",
            f"{live_server_url}/reservations",
            {"item_id": "item_merch_hoodie", "user_id": f"buyer_{user_idx}", "quantity": 1},
        )

    def read_stock():
        return http_request("GET", f"{live_server_url}/items/item_merch_hoodie")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        reserve_futures = [executor.submit(new_reserve, idx) for idx in range(10, 15)]
        read_futures = [executor.submit(read_stock) for _ in range(5)]

        reserve_results = [f.result() for f in reserve_futures]
        read_results = [f.result() for f in read_futures]

    # All 5 new buyers must successfully acquire the reclaimed inventory
    for status, data in reserve_results:
        assert status == 201, f"Expected 201, got {status}: {data}"
        assert data["status"] == "PENDING"

    # All reads must return 200 OK
    for status, _ in read_results:
        assert status == 200

    # Old buyer attempting confirmation after expiration receives 410 Gone
    late_status, late_err = http_request(
        "POST",
        f"{live_server_url}/reservations/{old_res_id}/confirm",
        {"user_id": "buyer_4"},
    )
    assert late_status == 410
    assert late_err["error"] == "Reservation expired"

    # Final stock check: still 0 available, 5 held by the new buyers
    _, final_stock = http_request("GET", f"{live_server_url}/items/item_merch_hoodie")
    assert final_stock["available_stock"] == 0
    assert final_stock["held_stock"] == 5


def test_confirm_vs_expiry_collision_race(live_server_url):
    """Test 4: Race condition between payment confirmation and lease expiration is mutually exclusive."""
    inventory_manager.LEASE_DURATION_SECONDS = 0.4
    # Reserve 5 units of hoodie to exhaust stock
    first_res_ids = []
    for i in range(5):
        _, data = http_request(
            "POST",
            f"{live_server_url}/reservations",
            {"item_id": "item_merch_hoodie", "user_id": f"buyer_{i}", "quantity": 1},
        )
        first_res_ids.append(data["reservation_id"])

    target_res_id = first_res_ids[0]

    # Sleep close to TTL expiration
    time.sleep(0.38)

    # Concurrently fire:
    # - Thread 1: buyer_0 attempts to confirm target_res_id
    # - Thread 2: buyer_10 attempts to reserve the potentially expired unit
    def confirm_action():
        return http_request(
            "POST",
            f"{live_server_url}/reservations/{target_res_id}/confirm",
            {"user_id": "buyer_0"},
        )

    def reserve_action():
        return http_request(
            "POST",
            f"{live_server_url}/reservations",
            {"item_id": "item_merch_hoodie", "user_id": "buyer_10", "quantity": 1},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_confirm = executor.submit(confirm_action)
        f_reserve = executor.submit(reserve_action)
        confirm_status, confirm_data = f_confirm.result()
        reserve_status, reserve_data = f_reserve.result()

    # Invariant: Mutually exclusive outcome under item lock
    # Outcome A: Confirmation arrived just in time (200 OK), new reservation rejected (409 Conflict)
    # Outcome B: Confirmation arrived after expiry (410 Gone), new reservation claimed reclaimed stock (201 Created)
    if confirm_status == 200:
        assert confirm_data["status"] == "CONFIRMED"
        assert reserve_status == 409
    else:
        assert confirm_status == 410
        assert confirm_data["error"] == "Reservation expired"
        assert reserve_status == 201

    # Total stock invariant holds
    _, stock = http_request("GET", f"{live_server_url}/items/item_merch_hoodie")
    assert stock["total_stock"] == stock["available_stock"] + stock["held_stock"] + stock["confirmed_stock"]


def test_concurrent_cancellation_and_immediate_reallocation(live_server_url):
    """Test 5: Explicit lease cancellation releases inventory atomically and allows immediate re-reservation."""
    # Exhaust hoodie inventory (5 units)
    res_ids = []
    for i in range(5):
        _, data = http_request(
            "POST",
            f"{live_server_url}/reservations",
            {"item_id": "item_merch_hoodie", "user_id": f"buyer_{i}", "quantity": 1},
        )
        res_ids.append(data["reservation_id"])

    res_to_cancel = res_ids[0]

    # Concurrently fire:
    # - Thread 1: buyer_0 cancels reservation
    # - Thread 2: buyer_10 attempts to reserve 1 unit
    def cancel_task():
        return http_request(
            "POST",
            f"{live_server_url}/reservations/{res_to_cancel}/cancel",
            {"user_id": "buyer_0"},
        )

    def reserve_task():
        return http_request(
            "POST",
            f"{live_server_url}/reservations",
            {"item_id": "item_merch_hoodie", "user_id": "buyer_10", "quantity": 1},
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f_cancel = executor.submit(cancel_task)
        f_reserve = executor.submit(reserve_task)
        cancel_status, cancel_data = f_cancel.result()
        reserve_status, reserve_data = f_reserve.result()

    assert cancel_status == 200
    assert cancel_data["status"] == "CANCELLED"

    # If cancellation completed before or during reservation under lock, reservation claims the freed unit
    assert reserve_status in (201, 409)

    # In either case, the stock count is completely consistent
    _, stock = http_request("GET", f"{live_server_url}/items/item_merch_hoodie")
    assert stock["total_stock"] == stock["available_stock"] + stock["held_stock"] + stock["confirmed_stock"]
