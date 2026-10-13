"""Comprehensive E2E and concurrency tests for Flash Sale Inventory Reservation API."""

import concurrent.futures
import time
from app.adapter.db import in_memory_db
from app.manager.inventory_manager import inventory_manager


def test_health(client):
    """Test liveness health check."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_list_items(client):
    """Test listing catalog items with live stock metrics."""
    res = client.get("/items")
    assert res.status_code == 200
    items = res.get_json()
    assert len(items) == 3

    item_ids = {item["item_id"] for item in items}
    assert item_ids == {"item_vip_ticket", "item_ga_ticket", "item_merch_hoodie"}

    vip = next(i for i in items if i["item_id"] == "item_vip_ticket")
    assert vip["total_stock"] == 10
    assert vip["available_stock"] == 10
    assert vip["held_stock"] == 0
    assert vip["confirmed_stock"] == 0
    assert vip["max_per_user"] == 2


def test_get_single_item(client):
    """Test fetching stock metrics for a single item."""
    res = client.get("/items/item_vip_ticket")
    assert res.status_code == 200
    data = res.get_json()
    assert data["item_id"] == "item_vip_ticket"
    assert data["total_stock"] == 10
    assert data["available_stock"] == 10


def test_get_nonexistent_item(client):
    """Test fetching a non-existent item returns 404."""
    res = client.get("/items/non_existent_item")
    assert res.status_code == 404
    data = res.get_json()
    assert data["error"] == "Item not found"


def test_create_reservation_success(client):
    """Test creating a valid reservation lease."""
    payload = {
        "item_id": "item_vip_ticket",
        "user_id": "user_alice",
        "quantity": 2,
    }
    res = client.post("/reservations", json=payload)
    assert res.status_code == 201
    data = res.get_json()
    assert data["status"] == "PENDING"
    assert data["item_id"] == "item_vip_ticket"
    assert data["user_id"] == "user_alice"
    assert data["quantity"] == 2
    assert data["time_remaining_seconds"] <= 30.0
    assert data["time_remaining_seconds"] > 0

    # Stock should reflect hold
    item_res = client.get("/items/item_vip_ticket")
    stock = item_res.get_json()
    assert stock["available_stock"] == 8
    assert stock["held_stock"] == 2
    assert stock["confirmed_stock"] == 0


def test_create_reservation_validation_errors(client):
    """Test validation errors on reservation creation."""
    # Malformed / non-JSON
    res = client.post("/reservations", data="not json", content_type="application/json")
    assert res.status_code == 400

    # Missing required field
    res = client.post("/reservations", json={"item_id": "item_vip_ticket", "user_id": "u1"})
    assert res.status_code == 400
    assert res.get_json()["error"] == "Validation error"

    # Quantity <= 0
    res = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "u1", "quantity": 0},
    )
    assert res.status_code == 400

    # Unknown item
    res = client.post(
        "/reservations",
        json={"item_id": "unknown_item", "user_id": "user_alice", "quantity": 1},
    )
    assert res.status_code == 404
    assert res.get_json()["error"] == "Item not found"


def test_overselling_prevention(client):
    """Test that requesting more than available stock is rejected."""
    # hoodie has total_stock = 5, max_per_user = 1
    # ga ticket has total_stock = 50, max_per_user = 4
    # Let's reserve all stock using multiple users
    for i in range(12):
        client.post(
            "/reservations",
            json={"item_id": "item_ga_ticket", "user_id": f"buyer_{i}", "quantity": 4},
        )
    # 48 reserved, 2 available
    res = client.get("/items/item_ga_ticket")
    assert res.get_json()["available_stock"] == 2

    # Attempt to reserve 3 (exceeds available 2)
    res = client.post(
        "/reservations",
        json={"item_id": "item_ga_ticket", "user_id": "buyer_overflow", "quantity": 3},
    )
    assert res.status_code == 409
    assert res.get_json()["error"] == "Insufficient stock"


def test_anti_hoarding_purchase_limit(client):
    """Test user cannot exceed max_per_user across active holds and confirmed purchases."""
    # item_vip_ticket max_per_user = 2
    # 1. First reservation of 1 unit succeeds
    res1 = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "user_bob", "quantity": 1},
    )
    assert res1.status_code == 201

    # 2. Second reservation of 2 units would exceed max 2 (1 + 2 = 3) -> 409
    res2 = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "user_bob", "quantity": 2},
    )
    assert res2.status_code == 409
    assert res2.get_json()["error"] == "Purchase limit exceeded"

    # 3. Confirm the first reservation
    res1_id = res1.get_json()["reservation_id"]
    client.post(f"/reservations/{res1_id}/confirm", json={"user_id": "user_bob"})

    # 4. User now has 1 confirmed. Trying to reserve 2 more still exceeds max 2 -> 409
    res3 = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "user_bob", "quantity": 2},
    )
    assert res3.status_code == 409
    assert res3.get_json()["error"] == "Purchase limit exceeded"

    # 5. Reserving 1 more reaches exactly the limit (1 confirmed + 1 held = 2) -> 201
    res4 = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "user_bob", "quantity": 1},
    )
    assert res4.status_code == 201


def test_confirm_reservation_flow(client):
    """Test successful checkout confirmation within lease window."""
    res = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "user_charlie", "quantity": 2},
    )
    assert res.status_code == 201
    res_id = res.get_json()["reservation_id"]

    # Confirm reservation
    confirm_res = client.post(f"/reservations/{res_id}/confirm", json={"user_id": "user_charlie"})
    assert confirm_res.status_code == 200
    data = confirm_res.get_json()
    assert data["status"] == "CONFIRMED"
    assert data["confirmed_at"] is not None

    # Stock verification: held stock is now confirmed stock
    stock = client.get("/items/item_vip_ticket").get_json()
    assert stock["available_stock"] == 8
    assert stock["held_stock"] == 0
    assert stock["confirmed_stock"] == 2

    # Double confirmation is rejected
    confirm_again = client.post(f"/reservations/{res_id}/confirm", json={"user_id": "user_charlie"})
    assert confirm_again.status_code == 409
    assert confirm_again.get_json()["error"] == "Reservation state conflict"


def test_confirm_reservation_unauthorized(client):
    """Test confirming someone else's reservation returns 403."""
    res = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "user_owner", "quantity": 1},
    )
    res_id = res.get_json()["reservation_id"]

    confirm_res = client.post(f"/reservations/{res_id}/confirm", json={"user_id": "user_intruder"})
    assert confirm_res.status_code == 403
    assert confirm_res.get_json()["error"] == "Unauthorized access"


def test_cancel_reservation_flow(client):
    """Test cancelling an active reservation releases stock immediately."""
    res = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "user_dan", "quantity": 2},
    )
    assert res.status_code == 201
    res_id = res.get_json()["reservation_id"]

    # Stock is currently held
    stock_before = client.get("/items/item_vip_ticket").get_json()
    assert stock_before["available_stock"] == 8
    assert stock_before["held_stock"] == 2

    # Cancel reservation
    cancel_res = client.post(f"/reservations/{res_id}/cancel", json={"user_id": "user_dan"})
    assert cancel_res.status_code == 200
    assert cancel_res.get_json()["status"] == "CANCELLED"

    # Stock is immediately returned to available pool
    stock_after = client.get("/items/item_vip_ticket").get_json()
    assert stock_after["available_stock"] == 10
    assert stock_after["held_stock"] == 0

    # Cancelling again returns 409
    cancel_again = client.post(f"/reservations/{res_id}/cancel", json={"user_id": "user_dan"})
    assert cancel_again.status_code == 409
    assert cancel_again.get_json()["error"] == "Reservation state conflict"


def test_jit_reclamation_on_get_and_post(client, monkeypatch):
    """Test JIT reclamation accurately restores expired reservations upon GET /items and GET /items/<id>."""
    current_simulated_time = 1000.0
    monkeypatch.setattr(inventory_manager, "_time_provider", lambda: current_simulated_time)

    # User reserves 2 units of VIP tickets
    res = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "user_eve", "quantity": 2},
    )
    assert res.status_code == 201
    res_id = res.get_json()["reservation_id"]

    stock_held = client.get("/items/item_vip_ticket").get_json()
    assert stock_held["available_stock"] == 8
    assert stock_held["held_stock"] == 2

    # Advance time by 31 seconds (lease TTL is 30s)
    current_simulated_time = 1031.0

    # Invoking GET /items/item_vip_ticket should trigger JIT reclamation
    stock_reclaimed = client.get("/items/item_vip_ticket").get_json()
    assert stock_reclaimed["available_stock"] == 10
    assert stock_reclaimed["held_stock"] == 0

    # Invoking GET /items should also show reclaimed stock across items
    all_items = client.get("/items").get_json()
    vip_item = next(i for i in all_items if i["item_id"] == "item_vip_ticket")
    assert vip_item["available_stock"] == 10
    assert vip_item["held_stock"] == 0

    # Late confirmation attempt should return 410 Gone
    late_confirm = client.post(f"/reservations/{res_id}/confirm", json={"user_id": "user_eve"})
    assert late_confirm.status_code == 410
    assert late_confirm.get_json()["error"] == "Reservation expired"

    # Since the hold expired, user can reserve again up to quota
    new_res = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "user_eve", "quantity": 2},
    )
    assert new_res.status_code == 201


def test_concurrent_reservations_zero_overselling(client):
    """Test high concurrency race condition guaranteeing zero overselling."""
    # item_merch_hoodie has total_stock = 5, max_per_user = 1
    from app.service.api import app

    num_threads = 20
    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:

        def attempt_reservation(user_idx):
            thread_client = app.test_client()
            return thread_client.post(
                "/reservations",
                json={
                    "item_id": "item_merch_hoodie",
                    "user_id": f"racer_{user_idx}",
                    "quantity": 1,
                },
            )

        futures = [executor.submit(attempt_reservation, i) for i in range(num_threads)]
        responses = [f.result() for f in futures]

    successes = [r for r in responses if r.status_code == 201]
    conflicts = [r for r in responses if r.status_code == 409]

    # Exactly 5 should succeed (total_stock = 5), remaining 15 should conflict
    assert len(successes) == 5
    assert len(conflicts) == 15

    # Check stock invariant
    stock = client.get("/items/item_merch_hoodie").get_json()
    assert stock["total_stock"] == 5
    assert stock["available_stock"] == 0
    assert stock["held_stock"] == 5
    assert stock["confirmed_stock"] == 0
    assert stock["total_stock"] == stock["available_stock"] + stock["held_stock"] + stock["confirmed_stock"]


def test_list_users(client):
    """Test listing pre-seeded users."""
    res = client.get("/users")
    assert res.status_code == 200
    users = res.get_json()
    assert len(users) >= 6

    user_ids = {u["user_id"] for u in users}
    assert "user_101" in user_ids
    assert "user_alice" in user_ids


def test_get_user_success_and_not_found(client):
    """Test fetching user by ID, and 404 for unknown user."""
    res = client.get("/users/user_101")
    assert res.status_code == 200
    user = res.get_json()
    assert user["user_id"] == "user_101"
    assert user["name"] == "Demo User 101"
    assert user["email"] == "user101@example.com"

    # Non-existent user
    res_not_found = client.get("/users/unknown_ghost_user")
    assert res_not_found.status_code == 404
    assert res_not_found.get_json()["error"] == "User not found"


def test_reservation_unknown_user_rejected(client):
    """Test that reservation creation, confirmation, and cancellation reject unknown users with 404."""
    # 1. Unknown user creating reservation
    res = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "unknown_ghost_user", "quantity": 1},
    )
    assert res.status_code == 404
    assert res.get_json()["error"] == "User not found"

    # 2. Create valid reservation with seeded user_alice
    valid_res = client.post(
        "/reservations",
        json={"item_id": "item_vip_ticket", "user_id": "user_alice", "quantity": 1},
    )
    assert valid_res.status_code == 201
    res_id = valid_res.get_json()["reservation_id"]

    # 3. Confirm with unknown user
    confirm_res = client.post(
        f"/reservations/{res_id}/confirm",
        json={"user_id": "unknown_ghost_user"},
    )
    assert confirm_res.status_code == 404
    assert confirm_res.get_json()["error"] == "User not found"

    # 4. Cancel with unknown user
    cancel_res = client.post(
        f"/reservations/{res_id}/cancel",
        json={"user_id": "unknown_ghost_user"},
    )
    assert cancel_res.status_code == 404
    assert cancel_res.get_json()["error"] == "User not found"
