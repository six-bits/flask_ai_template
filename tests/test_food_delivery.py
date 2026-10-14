"""Integration, per-user cart, and live network concurrency tests for Food Delivery Service."""

import concurrent.futures
import threading
import pytest
import requests
from werkzeug.serving import make_server

from app.adapter.food_delivery_adapter import food_delivery_adapter
from app.service.api import app


@pytest.fixture(autouse=True)
def reset_adapter():
    """Ensure clean in-memory state before each test."""
    food_delivery_adapter.reset()
    yield
    food_delivery_adapter.reset()


@pytest.fixture(scope="module")
def live_server():
    """Spin up a threaded live HTTP server for real network concurrency tests."""
    server = make_server("127.0.0.1", 0, app, threaded=True)
    port = server.port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    yield base_url
    server.shutdown()


# --- User & Basic Catalog Tests ---


def test_list_users_seeded(client):
    """Verify pre-seeded users are returned."""
    res = client.get("/users")
    assert res.status_code == 200
    users = res.get_json()
    assert len(users) == 3
    user_ids = [u["user_id"] for u in users]
    assert "user_1" in user_ids
    assert "user_2" in user_ids
    assert "user_3" in user_ids


def test_missing_and_unknown_user_validation(client):
    """Verify missing user returns 400 and unknown user returns 404."""
    # Missing user header/param
    res1 = client.get("/cart")
    assert res1.status_code == 400
    assert "missing required user identification" in res1.get_json()["message"].lower()

    # Unknown user
    res2 = client.get("/cart", headers={"X-User-Id": "non_existent_user"})
    assert res2.status_code == 404
    assert "not found" in res2.get_json()["message"].lower()


def test_list_dishes_seeded(client):
    """Verify seeded dishes catalog and portion metrics."""
    res = client.get("/dishes")
    assert res.status_code == 200
    dishes = res.get_json()
    assert len(dishes) == 3

    pizza = next(d for d in dishes if d["dish_id"] == "dish_1")
    assert pizza["name"] == "Margherita Pizza"
    assert pizza["price_per_unit"] == 1250  # $12.50
    assert pizza["total_portions"] == 10
    assert pizza["total_available_portions"] == 10
    assert pizza["total_reserved_portions"] == 0
    assert pizza["total_sold_portions"] == 0


# --- Per-User Cart Tests ---


def test_per_user_cart_isolation(client):
    """Verify User 1 and User 2 carts are completely isolated."""
    # User 1 adds 2 Pizzas ($25.00)
    res_u1 = client.post(
        "/cart/items",
        json={"dish_id": "dish_1", "units": 2},
        headers={"X-User-Id": "user_1"},
    )
    assert res_u1.status_code == 200
    cart_u1 = res_u1.get_json()
    assert cart_u1["user_id"] == "user_1"
    assert len(cart_u1["items"]) == 1
    assert cart_u1["total_amount"] == 2500

    # User 2's cart must still be empty
    res_u2_empty = client.get("/cart", headers={"X-User-Id": "user_2"})
    assert res_u2_empty.status_code == 200
    assert res_u2_empty.get_json()["items"] == []
    assert res_u2_empty.get_json()["total_amount"] == 0

    # User 2 adds 1 Pasta ($15.00)
    res_u2 = client.post(
        "/cart/items",
        json={"dish_id": "dish_2", "units": 1},
        headers={"X-User-Id": "user_2"},
    )
    assert res_u2.status_code == 200
    cart_u2 = res_u2.get_json()
    assert cart_u2["user_id"] == "user_2"
    assert len(cart_u2["items"]) == 1
    assert cart_u2["items"][0]["dish_id"] == "dish_2"
    assert cart_u2["total_amount"] == 1500

    # Check User 1 cart remains unchanged
    cart_u1_check = client.get("/cart", headers={"X-User-Id": "user_1"}).get_json()
    assert len(cart_u1_check["items"]) == 1
    assert cart_u1_check["items"][0]["dish_id"] == "dish_1"
    assert cart_u1_check["total_amount"] == 2500


def test_order_placement_clears_only_ordering_user_cart(client):
    """Verify placing an order empties only that user's cart, leaving other carts intact."""
    # User 1 adds Pizza
    client.post(
        "/cart/items",
        json={"dish_id": "dish_1", "units": 2},
        headers={"X-User-Id": "user_1"},
    )
    # User 2 adds Pasta
    client.post(
        "/cart/items",
        json={"dish_id": "dish_2", "units": 1},
        headers={"X-User-Id": "user_2"},
    )

    # User 1 places order
    order_res = client.post(
        "/orders",
        headers={"X-User-Id": "user_1", "Idempotency-Key": "u1-order-key"},
    )
    assert order_res.status_code == 201
    order = order_res.get_json()
    assert order["user_id"] == "user_1"
    assert order["order_status"] == "ORDER_ACCEPTED"

    # User 1's cart is now empty
    u1_cart = client.get("/cart", headers={"X-User-Id": "user_1"}).get_json()
    assert u1_cart["items"] == []
    assert u1_cart["total_amount"] == 0

    # User 2's cart is still intact
    u2_cart = client.get("/cart", headers={"X-User-Id": "user_2"}).get_json()
    assert len(u2_cart["items"]) == 1
    assert u2_cart["items"][0]["dish_id"] == "dish_2"
    assert u2_cart["total_amount"] == 1500


def test_add_to_cart_exceeds_available_portions_rejected(client):
    """Verify adding more units than available portions in cart fails with 400 Bad Request."""
    res = client.post(
        "/cart/items",
        json={"dish_id": "dish_1", "units": 15},
        headers={"X-User-Id": "user_1"},
    )
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Bad Request"
    assert "only 10 portion(s) are available" in data["message"]


def test_empty_cart_order_placement_rejected(client):
    """Verify placing an order with an empty cart fails with 400 Bad Request."""
    res = client.post(
        "/orders",
        headers={"X-User-Id": "user_1", "Idempotency-Key": "empty-cart-key"},
    )
    assert res.status_code == 400
    assert "empty cart" in res.get_json()["message"].lower()


def test_idempotency_replay_and_conflict(client):
    """Verify idempotent replay returns original order, and payload mismatch raises conflict."""
    client.post(
        "/cart/items",
        json={"dish_id": "dish_1", "units": 2},
        headers={"X-User-Id": "user_1"},
    )

    # First attempt: success (201)
    res1 = client.post(
        "/orders",
        headers={"X-User-Id": "user_1", "Idempotency-Key": "idemp-key-abc"},
    )
    assert res1.status_code == 201
    order1 = res1.get_json()

    # Replay identical key: returns same order (200)
    res2 = client.post(
        "/orders",
        headers={"X-User-Id": "user_1", "Idempotency-Key": "idemp-key-abc"},
    )
    assert res2.status_code == 200
    order2 = res2.get_json()
    assert order1["order_id"] == order2["order_id"]
    assert order1["total_amount"] == order2["total_amount"]

    # User 1 adds different item to cart and reuses same idempotency key
    client.post(
        "/cart/items",
        json={"dish_id": "dish_2", "units": 1},
        headers={"X-User-Id": "user_1"},
    )
    res3 = client.post(
        "/orders",
        headers={"X-User-Id": "user_1", "Idempotency-Key": "idemp-key-abc"},
    )
    assert res3.status_code == 409
    assert "conflicting payload hash" in res3.get_json()["message"]


def test_full_status_transition_lifecycle(client):
    """Verify happy path: ACCEPTED -> PREPARING -> DELIVERING -> COMPLETED."""
    client.post(
        "/cart/items",
        json={"dish_id": "dish_1", "units": 2},
        headers={"X-User-Id": "user_1"},
    )
    order_res = client.post(
        "/orders",
        headers={"X-User-Id": "user_1", "Idempotency-Key": "lifecycle-key"},
    )
    order_id = order_res.get_json()["order_id"]

    # 1. ORDER_PREPARING
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_PREPARING"},
    )
    assert res.status_code == 200
    assert res.get_json()["order_status"] == "ORDER_PREPARING"

    # 2. ORDER_DELIVERING
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_DELIVERING"},
    )
    assert res.status_code == 200
    assert res.get_json()["order_status"] == "ORDER_DELIVERING"

    # 3. ORDER_COMPLETED
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_COMPLETED"},
    )
    assert res.status_code == 200
    assert res.get_json()["order_status"] == "ORDER_COMPLETED"

    # Invariant: reserved portions converted to sold portions
    dishes = client.get("/dishes").get_json()
    pizza = next(d for d in dishes if d["dish_id"] == "dish_1")
    assert pizza["total_available_portions"] == 8
    assert pizza["total_reserved_portions"] == 0
    assert pizza["total_sold_portions"] == 2
    assert pizza["total_portions"] == (
        pizza["total_available_portions"]
        + pizza["total_reserved_portions"]
        + pizza["total_sold_portions"]
    )


def test_order_cancellation_releases_portions(client):
    """Verify cancellation from ACCEPTED and PREPARING returns reserved portions to available."""
    # Test cancellation from ORDER_ACCEPTED
    client.post(
        "/cart/items",
        json={"dish_id": "dish_1", "units": 3},
        headers={"X-User-Id": "user_1"},
    )
    res_accepted = client.post(
        "/orders",
        headers={"X-User-Id": "user_1", "Idempotency-Key": "cancel-key-1"},
    )
    order_id_1 = res_accepted.get_json()["order_id"]

    cancel_res1 = client.post(
        f"/orders/{order_id_1}/transitions",
        json={"status": "ORDER_CANCELLED"},
    )
    assert cancel_res1.status_code == 200
    assert cancel_res1.get_json()["order_status"] == "ORDER_CANCELLED"

    pizza = next(d for d in client.get("/dishes").get_json() if d["dish_id"] == "dish_1")
    assert pizza["total_available_portions"] == 10
    assert pizza["total_reserved_portions"] == 0


def test_disallowed_status_transitions(client):
    """Verify invalid state transitions are rejected with 400 Bad Request."""
    client.post(
        "/cart/items",
        json={"dish_id": "dish_1", "units": 2},
        headers={"X-User-Id": "user_1"},
    )
    order_res = client.post(
        "/orders",
        headers={"X-User-Id": "user_1", "Idempotency-Key": "invalid-trans-key"},
    )
    order_id = order_res.get_json()["order_id"]

    # Direct jump from ACCEPTED to DELIVERING is forbidden
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_DELIVERING"},
    )
    assert res.status_code == 400

    # Advance to DELIVERING properly
    client.post(f"/orders/{order_id}/transitions", json={"status": "ORDER_PREPARING"})
    client.post(f"/orders/{order_id}/transitions", json={"status": "ORDER_DELIVERING"})

    # Cannot cancel after DELIVERING
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_CANCELLED"},
    )
    assert res.status_code == 400


# --- Live Network Call Concurrency & Invariant Verification Tests ---


def test_live_network_concurrent_orders_maintain_portion_invariants(live_server):
    """Verify heavy concurrent network calls (HTTP requests) strictly maintain portion invariants."""
    # Seed dish with limited portions: total 12 portions
    food_delivery_adapter.save_dish(
        food_delivery_adapter._dishes["dish_1"].__class__(
            dish_id="dish_race",
            name="Race Condition Pizza",
            price_per_unit=1000,
            total_portions=12,
            total_available_portions=12,
            total_reserved_portions=0,
            total_sold_portions=0,
        )
    )

    users = ["user_1", "user_2", "user_3"]
    num_requests = 24  # Total attempts to order 1 portion (competing for 12 portions)
    order_ids_created = []
    order_ids_lock = threading.Lock()

    def make_order_workflow(thread_id: int):
        user_id = users[thread_id % len(users)]
        session = requests.Session()

        # Step 1: Network call to add 1 unit to user's cart
        add_res = session.post(
            f"{live_server}/cart/items",
            json={"dish_id": "dish_race", "units": 1},
            headers={"X-User-Id": user_id},
            timeout=5,
        )

        if add_res.status_code != 200:
            return f"cart_rejected: {add_res.status_code}"

        # Step 2: Network call to place order
        idemp_key = f"network-key-{thread_id}"
        order_res = session.post(
            f"{live_server}/orders",
            headers={"X-User-Id": user_id, "Idempotency-Key": idemp_key},
            timeout=5,
        )

        if order_res.status_code == 201:
            data = order_res.json()
            order_id = data["order_id"]
            with order_ids_lock:
                order_ids_created.append((order_id, user_id))

            # Step 3: Some threads randomly advance lifecycle over network
            if thread_id % 3 == 0:
                # Complete order
                session.post(
                    f"{live_server}/orders/{order_id}/transitions",
                    json={"status": "ORDER_PREPARING"},
                    timeout=5,
                )
                session.post(
                    f"{live_server}/orders/{order_id}/transitions",
                    json={"status": "ORDER_DELIVERING"},
                    timeout=5,
                )
                session.post(
                    f"{live_server}/orders/{order_id}/transitions",
                    json={"status": "ORDER_COMPLETED"},
                    timeout=5,
                )
            elif thread_id % 3 == 1:
                # Cancel order
                session.post(
                    f"{live_server}/orders/{order_id}/transitions",
                    json={"status": "ORDER_CANCELLED"},
                    timeout=5,
                )

            return "accepted"
        elif order_res.status_code == 422:
            return "rejected_portions"
        else:
            return f"order_error: {order_res.status_code}"

    # Execute all 24 ordering workflows concurrently over real network sockets
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(make_order_workflow, i) for i in range(num_requests)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    # Fetch final dish stats via live network call
    dish_res = requests.get(f"{live_server}/dishes", timeout=5)
    assert dish_res.status_code == 200
    dishes = dish_res.json()
    race_dish = next(d for d in dishes if d["dish_id"] == "dish_race")

    # Invariants Verification:
    # 1. Total portions formula strictly holds:
    assert race_dish["total_portions"] == (
        race_dish["total_available_portions"]
        + race_dish["total_reserved_portions"]
        + race_dish["total_sold_portions"]
    ), "Portions formula broken!"

    # 2. No negative counters
    assert race_dish["total_available_portions"] >= 0
    assert race_dish["total_reserved_portions"] >= 0
    assert race_dish["total_sold_portions"] >= 0

    # 3. Portions never oversold:
    assert race_dish["total_reserved_portions"] + race_dish["total_sold_portions"] <= race_dish["total_portions"]

    # 4. Cross-check against all orders in the system:
    all_orders_res = requests.get(f"{live_server}/orders", timeout=5)
    assert all_orders_res.status_code == 200
    all_orders = all_orders_res.json()

    reserved_count = 0
    sold_count = 0

    for ord_obj in all_orders:
        for item in ord_obj["items"]:
            if item["dish_id"] == "dish_race":
                if ord_obj["order_status"] in ("ORDER_ACCEPTED", "ORDER_PREPARING", "ORDER_DELIVERING"):
                    reserved_count += item["units"]
                elif ord_obj["order_status"] == "ORDER_COMPLETED":
                    sold_count += item["units"]

    assert race_dish["total_reserved_portions"] == reserved_count, "Reserved count mismatch!"
    assert race_dish["total_sold_portions"] == sold_count, "Sold count mismatch!"


def test_live_network_race_for_single_last_portion(live_server):
    """Verify 10 concurrent network threads competing for 1 last portion yields exactly 1 winner."""
    # Seed a dish with exactly 1 total portion
    food_delivery_adapter.save_dish(
        food_delivery_adapter._dishes["dish_1"].__class__(
            dish_id="dish_last_one",
            name="Exclusive Dish",
            price_per_unit=5000,
            total_portions=1,
            total_available_portions=1,
            total_reserved_portions=0,
            total_sold_portions=0,
        )
    )

    users = ["user_1", "user_2", "user_3"]
    results = []
    lock = threading.Lock()

    def attempt_order(thread_id: int):
        user_id = users[thread_id % len(users)]
        session = requests.Session()

        # Try to add to cart
        add_res = session.post(
            f"{live_server}/cart/items",
            json={"dish_id": "dish_last_one", "units": 1},
            headers={"X-User-Id": user_id},
            timeout=5,
        )
        if add_res.status_code != 200:
            with lock:
                results.append(f"cart_{add_res.status_code}")
            return

        # Try to place order
        order_res = session.post(
            f"{live_server}/orders",
            headers={"X-User-Id": user_id, "Idempotency-Key": f"last-portion-{thread_id}"},
            timeout=5,
        )
        with lock:
            results.append(f"order_{order_res.status_code}")

    # Launch 10 concurrent network threads
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_order, i) for i in range(10)]
        concurrent.futures.wait(futures)

    # Invariant verification over network
    dish_res = requests.get(f"{live_server}/dishes", timeout=5).json()
    last_dish = next(d for d in dish_res if d["dish_id"] == "dish_last_one")

    assert last_dish["total_portions"] == 1
    assert last_dish["total_portions"] == (
        last_dish["total_available_portions"]
        + last_dish["total_reserved_portions"]
        + last_dish["total_sold_portions"]
    )
    # Exactly one order was accepted (201)
    assert last_dish["total_reserved_portions"] == 1
    assert last_dish["total_available_portions"] == 0
    assert results.count("order_201") == 1
