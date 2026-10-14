"""Integration and unit tests for the Food Delivery Service."""

import concurrent.futures
import pytest
from app.adapter.food_delivery_adapter import food_delivery_adapter


@pytest.fixture(autouse=True)
def reset_adapter():
    """Ensure clean in-memory state before each test."""
    food_delivery_adapter.reset()
    yield
    food_delivery_adapter.reset()


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


def test_cart_operations_and_calculations(client):
    """Verify cart addition, increment, decrement, and clear operations."""
    # 1. Cart initially empty
    res = client.get("/cart")
    assert res.status_code == 200
    cart = res.get_json()
    assert cart["items"] == []
    assert cart["total_amount"] == 0

    # 2. Add 2 Margherita Pizzas ($12.50 * 2 = 2500 cents)
    res = client.post("/cart/items", json={"dish_id": "dish_1", "units": 2})
    assert res.status_code == 200
    cart = res.get_json()
    assert len(cart["items"]) == 1
    assert cart["items"][0]["dish_id"] == "dish_1"
    assert cart["items"][0]["units"] == 2
    assert cart["items"][0]["total_price"] == 2500
    assert cart["total_amount"] == 2500

    # 3. Increment Pizza by 1 ($12.50 * 3 = 3750 cents)
    res = client.post("/cart/items", json={"dish_id": "dish_1", "units": 1})
    assert res.status_code == 200
    cart = res.get_json()
    assert cart["items"][0]["units"] == 3
    assert cart["total_amount"] == 3750

    # 4. Add 1 Tiramisu ($6.00 = 600 cents)
    res = client.post("/cart/items", json={"dish_id": "dish_3", "units": 1})
    assert res.status_code == 200
    cart = res.get_json()
    assert len(cart["items"]) == 2
    assert cart["total_amount"] == 4350  # 3750 + 600

    # 5. Decrement Pizza by 1 unit
    res = client.delete("/cart/items/dish_1?units=1")
    assert res.status_code == 200
    cart = res.get_json()
    pizza_item = next(i for i in cart["items"] if i["dish_id"] == "dish_1")
    assert pizza_item["units"] == 2
    assert cart["total_amount"] == 3100  # 2500 + 600

    # 6. Remove Tiramisu completely
    res = client.delete("/cart/items/dish_3")
    assert res.status_code == 200
    cart = res.get_json()
    assert len(cart["items"]) == 1
    assert cart["total_amount"] == 2500

    # 7. Clear cart
    res = client.delete("/cart")
    assert res.status_code == 200
    cart = res.get_json()
    assert cart["items"] == []
    assert cart["total_amount"] == 0


def test_empty_cart_order_placement_rejected(client):
    """Verify placing an order with an empty cart fails with 400 Bad Request."""
    res = client.post("/orders", headers={"Idempotency-Key": "empty-cart-key"})
    assert res.status_code == 400
    assert "empty cart" in res.get_json()["message"].lower()


def test_order_placement_success_and_cart_emptied(client):
    """Verify order placement: accepted status, inventory portion reserve, and empty cart."""
    # Add items to cart: 2 Pizzas (total available: 10)
    client.post("/cart/items", json={"dish_id": "dish_1", "units": 2})

    # Place order
    res = client.post("/orders", headers={"Idempotency-Key": "test-key-1"})
    assert res.status_code == 201
    order = res.get_json()
    assert order["order_status"] == "ORDER_ACCEPTED"
    assert order["total_amount"] == 2500
    assert len(order["items"]) == 1
    order_id = order["order_id"]

    # In-memory cart must now be completely emptied
    cart_res = client.get("/cart")
    assert cart_res.status_code == 200
    assert cart_res.get_json()["items"] == []
    assert cart_res.get_json()["total_amount"] == 0

    # Inventory must reflect portion reservation and invariant must hold
    dishes_res = client.get("/dishes")
    pizza = next(d for d in dishes_res.get_json() if d["dish_id"] == "dish_1")
    assert pizza["total_available_portions"] == 8
    assert pizza["total_reserved_portions"] == 2
    assert pizza["total_sold_portions"] == 0
    assert pizza["total_portions"] == (
        pizza["total_available_portions"]
        + pizza["total_reserved_portions"]
        + pizza["total_sold_portions"]
    )

    # Order details fetchable
    order_res = client.get(f"/orders/{order_id}")
    assert order_res.status_code == 200
    assert order_res.get_json()["order_id"] == order_id


def test_add_to_cart_exceeds_available_portions_rejected(client):
    """Verify adding more units than available portions in cart fails with 400 Bad Request."""
    res = client.post("/cart/items", json={"dish_id": "dish_1", "units": 15})
    assert res.status_code == 400
    data = res.get_json()
    assert data["error"] == "Bad Request"
    assert "only 10 portion(s) are available" in data["message"]


def test_order_placement_insufficient_portions_rejected_and_cart_retained(client):
    """Verify order is rejected when available portions drop before checkout, and cart is retained."""
    # Add 8 Pizzas to cart (10 available at the time)
    client.post("/cart/items", json={"dish_id": "dish_1", "units": 8})

    # Simulate portions being reduced (e.g., competing order accepted or inventory adjustment)
    dish = food_delivery_adapter._dishes["dish_1"]
    dish.total_available_portions = 5

    res = client.post("/orders", headers={"Idempotency-Key": "excess-portions-key"})
    assert res.status_code == 422
    order = res.get_json()
    assert order["order_status"] == "ORDER_REJECTED"
    assert "only has 5 portions available" in order["rejection_reason"]

    # Active cart must be retained for user adjustment
    cart_res = client.get("/cart")
    assert len(cart_res.get_json()["items"]) == 1
    assert cart_res.get_json()["items"][0]["units"] == 8

    # Inventory portions remain untouched
    dishes_res = client.get("/dishes")
    pizza = next(d for d in dishes_res.get_json() if d["dish_id"] == "dish_1")
    assert pizza["total_available_portions"] == 5
    assert pizza["total_reserved_portions"] == 0


def test_idempotency_replay_and_conflict(client):
    """Verify idempotent replay returns original order, and payload mismatch raises conflict."""
    client.post("/cart/items", json={"dish_id": "dish_1", "units": 2})

    # First attempt: success (201)
    res1 = client.post("/orders", headers={"Idempotency-Key": "idemp-key-abc"})
    assert res1.status_code == 201
    order1 = res1.get_json()

    # Replay identical key: returns same order (200)
    res2 = client.post("/orders", headers={"Idempotency-Key": "idemp-key-abc"})
    assert res2.status_code == 200
    order2 = res2.get_json()
    assert order1["order_id"] == order2["order_id"]
    assert order1["total_amount"] == order2["total_amount"]

    # Add different items to cart and reuse same idempotency key
    client.post("/cart/items", json={"dish_id": "dish_2", "units": 1})
    res3 = client.post("/orders", headers={"Idempotency-Key": "idemp-key-abc"})
    assert res3.status_code == 409
    assert "conflicting payload hash" in res3.get_json()["message"]


def test_full_status_transition_lifecycle(client):
    """Verify happy path: ACCEPTED -> PREPARING -> DELIVERING -> COMPLETED."""
    client.post("/cart/items", json={"dish_id": "dish_1", "units": 2})
    order_res = client.post("/orders", headers={"Idempotency-Key": "lifecycle-key"})
    order_id = order_res.get_json()["order_id"]

    # 1. Transition to ORDER_PREPARING
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_PREPARING"},
    )
    assert res.status_code == 200
    assert res.get_json()["order_status"] == "ORDER_PREPARING"

    # 2. Transition to ORDER_DELIVERING
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_DELIVERING"},
    )
    assert res.status_code == 200
    assert res.get_json()["order_status"] == "ORDER_DELIVERING"

    # 3. Transition to ORDER_COMPLETED
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_COMPLETED"},
    )
    assert res.status_code == 200
    assert res.get_json()["order_status"] == "ORDER_COMPLETED"

    # Portions check: reserved moved to sold!
    dishes = client.get("/dishes").get_json()
    pizza = next(d for d in dishes if d["dish_id"] == "dish_1")
    assert pizza["total_available_portions"] == 8
    assert pizza["total_reserved_portions"] == 0
    assert pizza["total_sold_portions"] == 2
    assert pizza["total_portions"] == 10


def test_order_cancellation_releases_portions(client):
    """Verify cancellation from ACCEPTED and PREPARING returns reserved portions to available."""
    # Test cancellation from ORDER_ACCEPTED
    client.post("/cart/items", json={"dish_id": "dish_1", "units": 3})
    res_accepted = client.post("/orders", headers={"Idempotency-Key": "cancel-key-1"})
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

    # Test cancellation from ORDER_PREPARING
    client.post("/cart/items", json={"dish_id": "dish_1", "units": 4})
    res_prep = client.post("/orders", headers={"Idempotency-Key": "cancel-key-2"})
    order_id_2 = res_prep.get_json()["order_id"]

    client.post(f"/orders/{order_id_2}/transitions", json={"status": "ORDER_PREPARING"})
    cancel_res2 = client.post(
        f"/orders/{order_id_2}/transitions",
        json={"status": "ORDER_CANCELLED"},
    )
    assert cancel_res2.status_code == 200
    assert cancel_res2.get_json()["order_status"] == "ORDER_CANCELLED"

    pizza = next(d for d in client.get("/dishes").get_json() if d["dish_id"] == "dish_1")
    assert pizza["total_available_portions"] == 10
    assert pizza["total_reserved_portions"] == 0


def test_disallowed_status_transitions(client):
    """Verify invalid state transitions are rejected with 400 Bad Request."""
    client.post("/cart/items", json={"dish_id": "dish_1", "units": 2})
    order_res = client.post("/orders", headers={"Idempotency-Key": "invalid-trans-key"})
    order_id = order_res.get_json()["order_id"]

    # 1. Direct jump from ACCEPTED to DELIVERING is forbidden
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_DELIVERING"},
    )
    assert res.status_code == 400
    assert "allowed targets" in res.get_json()["message"].lower()

    # Move to DELIVERING properly
    client.post(f"/orders/{order_id}/transitions", json={"status": "ORDER_PREPARING"})
    client.post(f"/orders/{order_id}/transitions", json={"status": "ORDER_DELIVERING"})

    # 2. Cannot cancel after DELIVERING
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_CANCELLED"},
    )
    assert res.status_code == 400

    # Complete order
    client.post(f"/orders/{order_id}/transitions", json={"status": "ORDER_COMPLETED"})

    # 3. Cannot transition out of terminal COMPLETED state
    res = client.post(
        f"/orders/{order_id}/transitions",
        json={"status": "ORDER_CANCELLED"},
    )
    assert res.status_code == 400
    assert "terminal status" in res.get_json()["message"].lower()


def test_concurrency_race_condition_no_overselling():
    """Verify multiple concurrent threads competing for last portion never oversell."""
    # Seed a limited dish with exactly 1 portion
    food_delivery_adapter.save_dish(
        food_delivery_adapter._dishes["dish_1"].__class__(
            dish_id="dish_limited",
            name="Limited Edition Dish",
            price_per_unit=2000,
            total_portions=1,
            total_available_portions=1,
            total_reserved_portions=0,
            total_sold_portions=0,
        )
    )

    results = []

    def attempt_order(thread_id: int):
        # Each thread performs atomic adapter place order directly
        order, is_replay = food_delivery_adapter.atomic_place_order(
            order_id=f"concurrent_ord_{thread_id}",
            idempotency_key=f"concurrent_key_{thread_id}",
            request_hash=f"hash_{thread_id}",
        )
        return order.order_status

    # Prepare cart with 1 limited dish
    food_delivery_adapter.add_to_cart("dish_limited", 1)

    # Launch 8 concurrent threads attempting to place the order
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # Note: Since the cart is emptied by the winner, subsequent threads see empty cart or insufficient portions
        futures = []
        for i in range(5):
            futures.append(executor.submit(attempt_order, i))

        for f in futures:
            try:
                status = f.result()
                results.append(status)
            except Exception as e:
                results.append(str(e))

    # Dish portions check: total_available_portions must be 0, total_reserved_portions must be 1, never < 0!
    dish = food_delivery_adapter.get_dish("dish_limited")
    assert dish.total_available_portions >= 0
    assert dish.total_portions == (
        dish.total_available_portions + dish.total_reserved_portions + dish.total_sold_portions
    )
    # Exactly one thread succeeded in accepting the order
    accepted_count = sum(1 for r in results if r == "ORDER_ACCEPTED")
    assert accepted_count == 1
