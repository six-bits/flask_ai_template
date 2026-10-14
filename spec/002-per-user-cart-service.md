# Specification: Per-User Carts & Pre-Seeded Locks

**Spec Number**: 002  
**Scope**: Full Stack (`Service -> Manager -> Adapter`)  
**Status**: Ready for Review  

---

## 1. Overview & Scope

### 1.1 Purpose
Augment the Food Delivery Service to support **multiple users** with **per-user active carts**, **pre-seeded user accounts**, and **pre-seeded per-user locks**. 

### 1.2 Core Architectural Principles
- **Scope**: Full Stack implementation covering Service Layer routes and headers (`app/service/`), Manager business orchestration (`app/manager/`), and Adapter multi-cart storage & hierarchical locking (`app/adapter/`).
- **User Identity in Requests**: 
  - Cart operations and order creation identify the acting user via the `X-User-Id` HTTP header (with fallback to query param `?user_id=<id>` or payload field `"user_id"`).
  - Unauthenticated requests (missing user ID) receive `400 Bad Request`.
  - Non-existent user IDs receive `404 Not Found`.
- **Pre-Seeded Users**:
  - `user_1`: "Alice"
  - `user_2`: "Bob"
  - `user_3`: "Charlie"
- **Per-User Cart Isolation**:
  - Each pre-seeded user has their own distinct active cart in memory.
  - Adding, updating, or clearing items in User A's cart has zero effect on User B's cart.
  - Placing an accepted order empties **only** the ordering user's cart.
- **Pre-Seeded Per-User Locks & Two-Level Locking Hierarchy**:
  - Dedicated `threading.RLock()` instances are pre-seeded for each registered user in `_user_locks`.
  - A global `_inventory_lock` (`threading.RLock`) protects shared dish portion counters.
  - **Deadlock-Free Lock Hierarchy**:
    $$\text{User Lock } (U_i) \longrightarrow \text{Inventory Lock}$$
    Any multi-resource operation (e.g. order placement) always acquires the specific user's lock first, then acquires the shared inventory lock.
- **Portion Invariant (Global)**:
  $$\text{total\_portions} = \text{total\_available\_portions} + \text{total\_reserved\_portions} + \text{total\_sold\_portions}$$
  Maintained strictly across all users.

---

## 2. Service Layer (`app/service/`)

### 2.1 HTTP Routes & User Identification

User identity is extracted via a helper function:
```python
def get_request_user_id() -> Optional[str]:
    # 1. Primary: HTTP Header
    user_id = request.headers.get("X-User-Id")
    if user_id:
        return user_id.strip()
    # 2. Fallback: Query parameter
    user_id = request.args.get("user_id")
    if user_id:
        return user_id.strip()
    # 3. Fallback: JSON body
    if request.is_json:
        data = request.get_json(silent=True)
        if isinstance(data, dict) and "user_id" in data:
            return str(data["user_id"]).strip()
    return None
```

### 2.2 Endpoints Specification

| Method | Path | User Context | Description | Status Codes |
|---|---|---|---|---|
| `GET` | `/users` | None | List all pre-seeded users | `200 OK` |
| `GET` | `/dishes` | None | List restaurant dishes & global portions | `200 OK` |
| `POST` | `/dishes` | None | Seed/add dish to catalog | `201 Created`, `400 Bad Request` |
| `GET` | `/cart` | **Required (`X-User-Id`)** | View user's active cart & total | `200 OK`, `400 Bad Request`, `404 Not Found` |
| `POST` | `/cart/items` | **Required (`X-User-Id`)** | Add/increment items in user's cart (rejects if requested units exceed available portions) | `200 OK`, `400 Bad Request` (exceeds portions / validation error), `404 Not Found` |
| `DELETE` | `/cart/items/<dish_id>` | **Required (`X-User-Id`)** | Decrement/remove items in user's cart | `200 OK`, `400 Bad Request`, `404 Not Found` |
| `DELETE` | `/cart` | **Required (`X-User-Id`)** | Clear user's active cart | `200 OK`, `400 Bad Request`, `404 Not Found` |
| `POST` | `/orders` | **Required (`X-User-Id`)** + `Idempotency-Key` | Place order from user's cart | `201 Created` (Accepted), `200 OK` (Replay), `400 Bad Request` (Empty cart / missing params), `404 Not Found` (Unknown user), `409 Conflict` (Hash mismatch), `422 Unprocessable Entity` (Rejected) |
| `GET` | `/orders` | Optional (`X-User-Id`) | List orders (filtered if user specified) | `200 OK` |
| `GET` | `/orders/<order_id>` | None | Retrieve order details | `200 OK`, `404 Not Found` |
| `POST` | `/orders/<order_id>/transitions` | None | Advance order status | `200 OK`, `400 Bad Request`, `404 Not Found` |

### 2.3 JSON Schema Updates (`app/service/schema.py`)

```python
ADD_CART_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "dish_id": {"type": "string", "minLength": 1},
        "units": {"type": "integer", "minimum": 1},
        "user_id": {"type": "string", "minLength": 1},
    },
    "required": ["dish_id", "units"],
    "additionalProperties": False,
}

PLACE_ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "idempotency_key": {"type": "string", "minLength": 1},
        "user_id": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}
```

---

## 3. Service &harr; Manager Contract (`app/manager/entities.py`)

```python
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


@dataclass
class UserEntity:
    user_id: str
    name: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CartItemEntity:
    dish_id: str
    name: str
    units: int
    price_per_unit: int
    total_price: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CartResponseEntity:
    user_id: str
    items: List[CartItemEntity]
    total_amount: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "items": [item.to_dict() for item in self.items],
            "total_amount": self.total_amount,
        }


@dataclass
class AddToCartRequestEntity:
    user_id: str
    dish_id: str
    units: int


@dataclass
class PlaceOrderRequestEntity:
    user_id: str
    idempotency_key: str


@dataclass
class OrderResponseEntity:
    order_id: str
    user_id: str
    items: List[OrderLineItemEntity]
    order_status: OrderStatus
    total_amount: int
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "user_id": self.user_id,
            "items": [item.to_dict() for item in self.items],
            "order_status": (
                self.order_status.value
                if isinstance(self.order_status, OrderStatus)
                else self.order_status
            ),
            "total_amount": self.total_amount,
            "rejection_reason": self.rejection_reason,
        }
```

---

## 4. Manager Layer (`app/manager/food_delivery_manager.py`)

### 4.1 Responsibilities
- Validates user existence against registered pre-seeded users.
- Routes cart operations (`get_cart`, `add_to_cart`, `remove_from_cart`, `clear_cart`) to the user's specific cart.
- Enforces available portion limits upon adding to cart: validates that `(existing_cart_units + requested_units) <= dish.total_available_portions`; rejects with `400 Bad Request` if exceeded.
- Dispatches order creation with `user_id` and computes deterministic payload hash based on that user's cart contents.
- Supports filtering orders by `user_id` in `list_orders(user_id: Optional[str] = None)`.

---

## 5. Manager &harr; Adapter Contract (`app/adapter/entities.py`)

```python
@dataclass
class UserRecordEntity:
    user_id: str
    name: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CartRecordEntity:
    user_id: str
    items: List[CartItemRecordEntity]
    total_amount: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "items": [item.to_dict() for item in self.items],
            "total_amount": self.total_amount,
        }


@dataclass
class OrderRecordEntity:
    order_id: str
    user_id: str
    items: List[OrderLineItemRecordEntity]
    order_status: str
    total_amount: int
    rejection_reason: Optional[str] = None


@dataclass
class IdempotencyRecordEntity:
    idempotency_key: str
    user_id: str
    request_hash: str
    order_id: str
```

---

## 6. Adapter Layer (`app/adapter/food_delivery_adapter.py`)

### 6.1 State Storage & Pre-Seeding
```python
class FoodDeliveryAdapter:

    def __init__(self):
        # Global locks
        self._inventory_lock = threading.RLock()
        self._global_state_lock = threading.RLock()

        # Pre-seeded users & user locks
        self._users: Dict[str, UserRecordEntity] = {}
        self._user_locks: Dict[str, threading.RLock] = {}

        # Per-user carts: user_id -> CartRecordEntity
        self._carts: Dict[str, CartRecordEntity] = {}

        # Shared restaurant state
        self._dishes: Dict[str, DishRecordEntity] = {}
        self._orders: Dict[str, OrderRecordEntity] = {}
        self._idempotency_records: Dict[str, IdempotencyRecordEntity] = {}

        self._seed_default_data()
```

### 6.2 Pre-Seeded Users
1. `user_1`: Alice (`_user_locks["user_1"] = threading.RLock()`, empty cart initialized)
2. `user_2`: Bob (`_user_locks["user_2"] = threading.RLock()`, empty cart initialized)
3. `user_3`: Charlie (`_user_locks["user_3"] = threading.RLock()`, empty cart initialized)

---

## 7. Concurrency & Locking Architecture (Per-User Locks + Inventory Lock)

### 7.1 Lock Granularity
1. **User Lock (`self._user_locks[user_id]`)**:
   - Pre-seeded per user.
   - Guarded during cart reads, cart additions/removals/clearing, and user idempotency check.
   - Operations on User 1's cart run fully concurrent with operations on User 2's cart without blocking each other.
2. **Global Inventory Lock (`self._inventory_lock`)**:
   - Guards portion checks, allocations (`available -> reserved`), releases (`reserved -> available`), and completion (`reserved -> sold`).
   - Guards restaurant dish catalog changes.

### 7.2 Order Placement Two-Phase Lock Acquisition

To place an order from a user's cart:
```python
def atomic_place_order(
    self, user_id: str, order_id: str, idempotency_key: str, request_hash: str
):
    user_lock = self._get_user_lock(user_id)

    # Phase 1: Lock user context (cart & user idempotency)
    with user_lock:
        cart = self._carts.get(user_id)
        if not cart or not cart.items:
            raise EmptyCartError("Cannot place an order with an empty cart.")

        # Phase 2: Lock global inventory
        with self._inventory_lock:
            # Check dish portions
            portions_sufficient = all(
                self._dishes[i.dish_id].total_available_portions >= i.units
                for i in cart.items
            )

            if portions_sufficient:
                for i in cart.items:
                    self._dishes[i.dish_id].total_available_portions -= i.units
                    self._dishes[i.dish_id].total_reserved_portions += i.units

                order = OrderRecordEntity(
                    order_id=order_id,
                    user_id=user_id,
                    items=[...],
                    order_status="ORDER_ACCEPTED",
                    total_amount=cart.total_amount,
                )
                # Empty only this user's cart
                self._carts[user_id] = CartRecordEntity(
                    user_id=user_id, items=[], total_amount=0
                )
            else:
                order = OrderRecordEntity(
                    order_id=order_id,
                    user_id=user_id,
                    items=[...],
                    order_status="ORDER_REJECTED",
                    total_amount=cart.total_amount,
                )

            self._orders[order_id] = order
            self._idempotency_records[idempotency_key] = IdempotencyRecordEntity(...)
            return order, False
```

### 7.3 Deadlock Prevention Guarantee
- Lock acquisition order is strictly **`User Lock -> Inventory Lock`**.
- An operation never acquires another user's lock.
- Reverse acquisition (`Inventory Lock -> User Lock`) is strictly forbidden.
- Result: **Provably deadlock-free concurrency**.

---

## 8. Test Plan (`tests/test_food_delivery.py`)

Integration tests will verify:
1. **User Pre-seeding**:
   - `GET /users` returns `user_1`, `user_2`, `user_3`.
2. **Missing & Unknown User Validation**:
   - Cart request without `X-User-Id` returns `400 Bad Request`.
   - Cart request with unknown `X-User-Id: user_999` returns `404 Not Found`.
3. **Per-User Cart Isolation**:
   - User 1 adds 2 Pizzas to their cart.
   - User 2 adds 1 Pasta to their cart.
   - User 1's `GET /cart` contains only Pizzas ($25.00).
   - User 2's `GET /cart` contains only Pasta ($15.00).
4. **Order Placement Clears Only Ordering User's Cart**:
   - User 1 places their order.
   - User 1's order is `ORDER_ACCEPTED`.
   - User 1's cart is verified empty.
   - User 2's cart is verified still containing Pasta ($15.00).
5. **Cross-User Concurrent Order Placement for Limited Portions**:
   - Dish seeded with 1 available portion.
   - User 1 and User 2 concurrently place orders for 1 portion each.
   - Exactly one user gets `ORDER_ACCEPTED`, the other gets `ORDER_REJECTED`.
   - No overselling occurs; inventory invariant strictly holds.
6. **Concurrent Independent Cart Operations**:
   - User 1 and User 2 performing rapid concurrent cart additions/removals execute in parallel without contention on user locks.
