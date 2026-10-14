# Specification: Food Delivery Service with Daily Portion Limits

**Spec Number**: 001  
**Scope**: Full Stack (`Service -> Manager -> Adapter`)  
**Status**: Ready for Review  

---

## 1. Overview & Scope

### 1.1 Purpose
The Food Delivery Service allows a single user to browse dishes from one restaurant with daily portion limits, maintain an active shopping cart, place an order guaranteed against overselling, and manage the complete lifecycle of orders through terminal fulfillment or cancellation.

### 1.2 Core Guarantees & Constraints
- **Scope**: Full Stack implementation covering HTTP Routes & Schema validation (`app/service/`), Business Logic & State Machines (`app/manager/`), and In-Memory Thread-Safe Persistence (`app/adapter/`).
- **Money Handling**: Stored and calculated strictly as integer minor units (USD cents). Floating-point arithmetic is prohibited.
- **Portion Invariant**: For every dish:
  $$\text{total\_portions} = \text{total\_available\_portions} + \text{total\_reserved\_portions} + \text{total\_sold\_portions}$$
  Portions must never be oversold or undersold.
- **Lifecycle & Terminal States**:
  - Valid forward path: `ORDER_ACCEPTED -> ORDER_PREPARING -> ORDER_DELIVERING -> ORDER_COMPLETED`.
  - Allowed cancellations: `ORDER_ACCEPTED -> ORDER_CANCELLED` and `ORDER_PREPARING -> ORDER_CANCELLED`.
  - Terminal states: `ORDER_COMPLETED`, `ORDER_CANCELLED`, and `ORDER_REJECTED`.
  - Transition adjustments:
    - On `ORDER_ACCEPTED`: Portions move from `total_available_portions` $\rightarrow$ `total_reserved_portions`.
    - On `ORDER_CANCELLED`: Portions return from `total_reserved_portions` $\rightarrow$ `total_available_portions`.
    - On `ORDER_COMPLETED`: Portions convert from `total_reserved_portions` $\rightarrow$ `total_sold_portions`.
- **Single Active Cart & Automatic Emptying**:
  - The in-memory adapter maintains exactly **one active cart** at any given time.
  - When `POST /orders` is executed and an order is accepted (`ORDER_ACCEPTED`), the active cart is **atomically converted into the order and completely emptied**.
  - If an order is rejected (`ORDER_REJECTED` due to portion limits exceeded), the cart remains intact for user inspection/modification.
  - Idempotent replays return the existing order and do not alter the current active cart.
- **Typed Entity Records in Adapter**:
  - The adapter's in-memory storage strictly stores typed dataclass entities (`DishRecordEntity`, `CartRecordEntity`, `CartItemRecordEntity`, `OrderRecordEntity`, `OrderLineItemRecordEntity`, `IdempotencyRecordEntity`) rather than raw dictionaries or primitives.
- **Idempotency**: Order placement requires an `Idempotency-Key` (via header or request payload). Replaying the request with the identical hash returns the existing order. Reusing the key with a different request hash returns `409 Conflict`.
- **Concurrency**: Thread-safe in-memory operations in the adapter protected by reentrant locks (`threading.RLock`).

---

## 2. Service Layer (`app/service/`)

### 2.1 HTTP Routes & Endpoints

| Method | Path | Description | Request Body / Query Params | Status Codes |
|---|---|---|---|---|
| `GET` | `/health` | Health check endpoint | None | `200 OK` |
| `GET` | `/dishes` | List all available dishes with portion stats | None | `200 OK` |
| `POST` | `/dishes` | Seed/add a dish to catalog | `SEED_DISH_SCHEMA` | `201 Created`, `400 Bad Request` |
| `GET` | `/cart` | View current active cart and total amount | None | `200 OK` |
| `POST` | `/cart/items` | Add or increment dish units in the active cart | `ADD_CART_ITEM_SCHEMA` | `200 OK`, `400 Bad Request`, `404 Not Found` |
| `DELETE` | `/cart/items/<dish_id>` | Remove or decrement dish units from cart | Query: `?units=<int>` (optional) | `200 OK`, `404 Not Found`, `400 Bad Request` |
| `DELETE` | `/cart` | Clear all items from the active cart | None | `200 OK` |
| `POST` | `/orders` | Place order from active cart items | Header: `Idempotency-Key` (or body `idempotency_key`) | `201 Created` (Accepted), `200 OK` (Idempotent replay), `400 Bad Request` (Empty cart), `409 Conflict` (Hash mismatch), `422 Unprocessable Entity` (Order Rejected) |
| `GET` | `/orders` | List all placed orders | None | `200 OK` |
| `GET` | `/orders/<order_id>` | Retrieve specific order details | None | `200 OK`, `404 Not Found` |
| `POST` | `/orders/<order_id>/transitions` | Transition order status | `ORDER_TRANSITION_SCHEMA` | `200 OK`, `400 Bad Request` (Invalid transition), `404 Not Found` |

### 2.2 JSON Schema Definitions (`app/service/schema.py`)

```python
ADD_CART_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "dish_id": {"type": "string", "minLength": 1},
        "units": {"type": "integer", "minimum": 1},
    },
    "required": ["dish_id", "units"],
    "additionalProperties": False,
}

SEED_DISH_SCHEMA = {
    "type": "object",
    "properties": {
        "dish_id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "price_per_unit": {"type": "integer", "minimum": 0},
        "total_portions": {"type": "integer", "minimum": 1},
    },
    "required": ["dish_id", "name", "price_per_unit", "total_portions"],
    "additionalProperties": False,
}

PLACE_ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "idempotency_key": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

ORDER_TRANSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "ORDER_PREPARING",
                "ORDER_DELIVERING",
                "ORDER_COMPLETED",
                "ORDER_CANCELLED",
            ],
        },
    },
    "required": ["status"],
    "additionalProperties": False,
}
```

---

## 3. Service &harr; Manager Contract (`app/manager/entities.py`)

```python
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class OrderStatus(str, Enum):
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_ACCEPTED = "ORDER_ACCEPTED"
    ORDER_PREPARING = "ORDER_PREPARING"
    ORDER_DELIVERING = "ORDER_DELIVERING"
    ORDER_COMPLETED = "ORDER_COMPLETED"
    ORDER_CANCELLED = "ORDER_CANCELLED"


@dataclass
class DishEntity:
    dish_id: str
    name: str
    price_per_unit: int  # minor units (cents)
    total_portions: int
    total_available_portions: int
    total_reserved_portions: int
    total_sold_portions: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CartItemEntity:
    dish_id: str
    name: str
    units: int
    price_per_unit: int
    total_price: int  # minor units (units * price_per_unit)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CartResponseEntity:
    items: List[CartItemEntity]
    total_amount: int  # minor units

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total_amount": self.total_amount,
        }


@dataclass
class AddToCartRequestEntity:
    dish_id: str
    units: int


@dataclass
class PlaceOrderRequestEntity:
    idempotency_key: str


@dataclass
class OrderLineItemEntity:
    dish_id: str
    name: str
    units: int
    price_per_unit: int
    total_price: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrderResponseEntity:
    order_id: str
    items: List[OrderLineItemEntity]
    order_status: OrderStatus
    total_amount: int
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "items": [item.to_dict() for item in self.items],
            "order_status": (
                self.order_status.value
                if isinstance(self.order_status, OrderStatus)
                else self.order_status
            ),
            "total_amount": self.total_amount,
            "rejection_reason": self.rejection_reason,
        }


@dataclass
class OrderTransitionRequestEntity:
    order_id: str
    target_status: OrderStatus
```

---

## 4. Manager Layer (`app/manager/food_delivery_manager.py`)

### 4.1 Responsibilities
- Coordinates interactions between the Service layer and Adapter layer.
- Enforces core domain business logic:
  1. **Cart Pricing & Item Aggregation**: Computes line item prices and total amounts in integer cents.
  2. **Order Placement & Portions Enforcement**:
     - Computes deterministic SHA-256 payload hash based on active cart contents.
     - Checks idempotency key:
       - If key exists with same hash: returns `(existing_order, is_replay=True)`.
       - If key exists with differing hash: raises `IdempotencyConflictError`.
     - Validates portion availability:
       - If cart items exceed `total_available_portions` for any dish: creates order with `ORDER_REJECTED`, records reason, leaves active cart intact for editing.
       - If sufficient: moves portions from `available` $\rightarrow$ `reserved`, creates order with `ORDER_ACCEPTED`, and **clears the active cart**.
  3. **State Machine Validation**:
     - Allowed transitions:
       - `ORDER_ACCEPTED` &rarr; `ORDER_PREPARING`
       - `ORDER_PREPARING` &rarr; `ORDER_DELIVERING`
       - `ORDER_DELIVERING` &rarr; `ORDER_COMPLETED`
       - `ORDER_ACCEPTED` &rarr; `ORDER_CANCELLED`
       - `ORDER_PREPARING` &rarr; `ORDER_CANCELLED`
     - Forbidden transitions:
       - Any transition out of `ORDER_COMPLETED`, `ORDER_CANCELLED`, or `ORDER_REJECTED` (terminal states).
       - Direct jump from `ORDER_ACCEPTED` to `ORDER_DELIVERING` or `ORDER_COMPLETED`.
       - Cancellation once in `ORDER_DELIVERING` or `ORDER_COMPLETED`.
  4. **Inventory Portion Accounting on Transitions**:
     - When transitioned to `ORDER_COMPLETED`: converts portions from `total_reserved_portions` $\rightarrow$ `total_sold_portions`.
     - When transitioned to `ORDER_CANCELLED`: returns portions from `total_reserved_portions` $\rightarrow$ `total_available_portions`.

### 4.2 Class Signature
```python
class FoodDeliveryManager:
    def __init__(self, adapter: FoodDeliveryAdapter): ...
    def list_dishes(self) -> List[DishEntity]: ...
    def seed_dish(
        self, dish_id: str, name: str, price_per_unit: int, total_portions: int
    ) -> DishEntity: ...
    def get_cart(self) -> CartResponseEntity: ...
    def add_to_cart(self, req: AddToCartRequestEntity) -> CartResponseEntity: ...
    def remove_from_cart(
        self, dish_id: str, units: Optional[int] = None
    ) -> CartResponseEntity: ...
    def clear_cart(self) -> CartResponseEntity: ...
    def place_order(
        self, req: PlaceOrderRequestEntity
    ) -> Tuple[OrderResponseEntity, bool]: ...  # (order, is_replay)
    def list_orders(self) -> List[OrderResponseEntity]: ...
    def get_order(self, order_id: str) -> Optional[OrderResponseEntity]: ...
    def transition_order_status(
        self, req: OrderTransitionRequestEntity
    ) -> OrderResponseEntity: ...
```

---

## 5. Manager &harr; Adapter Contract (`app/adapter/entities.py`)

All in-memory store records are strictly represented as typed dataclass entity objects:

```python
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class DishRecordEntity:
    dish_id: str
    name: str
    price_per_unit: int  # minor units (cents)
    total_portions: int
    total_available_portions: int
    total_reserved_portions: int
    total_sold_portions: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CartItemRecordEntity:
    dish_id: str
    name: str
    units: int
    price_per_unit: int
    total_price: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CartRecordEntity:
    items: List[CartItemRecordEntity]
    total_amount: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "items": [item.to_dict() for item in self.items],
            "total_amount": self.total_amount,
        }


@dataclass
class OrderLineItemRecordEntity:
    dish_id: str
    name: str
    units: int
    price_per_unit: int
    total_price: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrderRecordEntity:
    order_id: str
    items: List[OrderLineItemRecordEntity]
    order_status: str
    total_amount: int
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IdempotencyRecordEntity:
    idempotency_key: str
    request_hash: str
    order_id: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

---

## 6. Adapter Layer (`app/adapter/food_delivery_adapter.py`)

### 6.1 In-Memory Persistence & Concurrency
The adapter manages the in-memory persistence using strictly typed entity record objects protected by `threading.RLock()`:
- `_dishes: Dict[str, DishRecordEntity]`
- `_cart: CartRecordEntity` (Single active cart singleton)
- `_orders: Dict[str, OrderRecordEntity]`
- `_idempotency_records: Dict[str, IdempotencyRecordEntity]`

### 6.2 Key Adapter Methods
- `get_dish(dish_id: str) -> Optional[DishRecordEntity]`
- `list_dishes() -> List[DishRecordEntity]`
- `save_dish(dish: DishRecordEntity) -> None`
- `get_cart() -> CartRecordEntity`
- `save_cart(cart: CartRecordEntity) -> None`
- `clear_cart() -> None`
- `get_idempotency_record(key: str) -> Optional[IdempotencyRecordEntity]`
- `save_idempotency_record(record: IdempotencyRecordEntity) -> None`
- `get_order(order_id: str) -> Optional[OrderRecordEntity]`
- `list_orders() -> List[OrderRecordEntity]`
- `save_order(order: OrderRecordEntity) -> None`
- `atomic_place_order(order_id, idempotency_key, request_hash)`:
  - Inside a locked context:
    1. Checks if each cart item's required units $\le$ `dish.total_available_portions`.
    2. If sufficient:
       - Decrements `total_available_portions` and increments `total_reserved_portions` for each dish.
       - Constructs `OrderRecordEntity` with status `"ORDER_ACCEPTED"`.
       - Empties `_cart` (`CartRecordEntity(items=[], total_amount=0)`).
       - Saves order and idempotency record.
    3. If insufficient:
       - Constructs `OrderRecordEntity` with status `"ORDER_REJECTED"` and reason.
       - Leaves `_cart` unchanged.
       - Saves order and idempotency record.

### 6.3 Initial Seed Catalog
1. `dish_1`: Margherita Pizza ($12.50 = 1250 cents), 10 portions.
2. `dish_2`: Pasta Carbonara ($15.00 = 1500 cents), 8 portions.
3. `dish_3`: Tiramisu ($6.00 = 600 cents), 15 portions.

---

## 7. Concurrency & Locking Architecture

### 7.1 Lock Scope & Maintenance
To prevent race conditions, overselling, and lost inventory updates across concurrent threads, locking is maintained at the **Adapter Layer** via a reentrant lock:
```python
import threading


class FoodDeliveryAdapter:

    def __init__(self):
        self._lock = threading.RLock()
        self._dishes: Dict[str, DishRecordEntity] = {}
        self._cart: CartRecordEntity = CartRecordEntity(
            items=[], total_amount=0
        )
        self._orders: Dict[str, OrderRecordEntity] = {}
        self._idempotency_records: Dict[str, IdempotencyRecordEntity] = {}
```

- **Reentrancy (`threading.RLock`)**: Enables composite operations inside the adapter (e.g., helper methods calling `get_dish` or `get_cart`) to re-enter the lock safely on the same thread without deadlocking.
- **Context Management**: All critical operations strictly use `with self._lock:` to guarantee automatic release on return or exception.

### 7.2 Why Locking is Needed Beyond Order Placement
While **Order Placement** is the most complex critical section, locking is also required for:
1. **Order State Transitions (`atomic_transition_order`)**:
   - Transitioning to `ORDER_CANCELLED` mutates inventory portions from `total_reserved_portions` back to `total_available_portions`.
   - Transitioning to `ORDER_COMPLETED` mutates inventory portions from `total_reserved_portions` to `total_sold_portions`.
   - Without a lock on transitions, a concurrent order placement and order cancellation could interleave reads/writes to `total_available_portions`, corrupting the portion invariant.
2. **Active Cart Mutations (`add_cart_item`, `remove_cart_item`, `clear_cart`)**:
   - Protects the single shared cart against interleaving writes (e.g., two rapid clicks adding items or removing items).
3. **Consistent Snapshot Reads**:
   - `list_dishes()` and `get_cart()` acquire the lock to return consistent snapshots, preventing callers from reading partial state during an ongoing order placement or transition.

### 7.3 Detailed Critical Section Lifecycles

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant Service as Service Layer
    participant Manager as Manager Layer
    participant Adapter as Adapter Layer (with self._lock)

    Note over Adapter: === Order Placement Transaction ===
    Client->>Service: POST /orders (Idempotency-Key)
    Service->>Manager: place_order(...)
    Manager->>Adapter: atomic_place_order(...)
    activate Adapter
    Adapter->>Adapter: Acquire self._lock
    Adapter->>Adapter: 1. Check idempotency key & hash
    alt Idempotency Hit (Same Hash)
        Adapter-->>Manager: Return existing order (is_replay=True)
    else Idempotency Hit (Differing Hash)
        Adapter-->>Manager: Raise IdempotencyConflictError
    else New Idempotency Key
        Adapter->>Adapter: 2. Check active cart non-empty
        Adapter->>Adapter: 3. Verify total_available_portions >= units for all cart dishes
        alt Portions Sufficient
            Adapter->>Adapter: available -= units; reserved += units
            Adapter->>Adapter: Create OrderRecord (ORDER_ACCEPTED)
            Adapter->>Adapter: Empty active cart (items=[], total=0)
            Adapter->>Adapter: Save IdempotencyRecord
        else Portions Insufficient
            Adapter->>Adapter: Create OrderRecord (ORDER_REJECTED)
            Adapter->>Adapter: Keep active cart intact
            Adapter->>Adapter: Save IdempotencyRecord
        end
    end
    Adapter->>Adapter: Release self._lock
    deactivate Adapter
    Manager-->>Service: OrderResponseEntity
    Service-->>Client: 201 Created / 200 OK / 422 / 409

    Note over Adapter: === Status Transition Transaction ===
    Client->>Service: POST /orders/{id}/transitions
    Service->>Manager: transition_order(...)
    Manager->>Adapter: atomic_transition_order(...)
    activate Adapter
    Adapter->>Adapter: Acquire self._lock
    Adapter->>Adapter: 1. Validate status transition path
    alt Target is ORDER_CANCELLED
        Adapter->>Adapter: reserved -= units; available += units
    else Target is ORDER_COMPLETED
        Adapter->>Adapter: reserved -= units; sold += units
    end
    Adapter->>Adapter: Update order_status
    Adapter->>Adapter: Release self._lock
    deactivate Adapter
    Manager-->>Service: Updated OrderResponseEntity
    Service-->>Client: 200 OK
```

---

## 8. Test Plan (`tests/test_food_delivery.py`)

Full stack integration tests will verify:
1. **Catalog & Inventory Initialization**:
   - Verify seeded dishes, portion counters, and minor-unit prices.
2. **Active Cart Operations & Lifecycle**:
   - Add items, increment units, decrement units, remove item, clear cart under thread safety.
   - Verify single active cart reflects exact integer sums.
3. **Order Placement - Success (`ORDER_ACCEPTED`)**:
   - Cart with items places order.
   - Status is `ORDER_ACCEPTED`.
   - Inventory portion counters: `total_available_portions` decreased, `total_reserved_portions` increased.
   - **Active cart is verified to be completely emptied**.
   - Invariant checked: `total == available + reserved + sold`.
4. **Order Placement - Portions Exceeded (`ORDER_REJECTED`)**:
   - Cart units exceed available portions.
   - Order created with `ORDER_REJECTED` status.
   - Portions remain untouched.
   - Active cart is **retained** with its contents intact.
5. **Idempotency Guarantee**:
   - Replay with identical key + payload hash: returns original order without re-decrementing inventory or affecting cart.
   - Replay with same key + different payload hash: raises `409 Conflict`.
6. **State Transitions & Terminal States**:
   - `ORDER_ACCEPTED -> ORDER_PREPARING -> ORDER_DELIVERING -> ORDER_COMPLETED`:
     - Valid transition path.
     - On reaching `ORDER_COMPLETED`: portions move from `reserved` to `sold`. Invariant holds.
   - `ORDER_ACCEPTED -> ORDER_CANCELLED`: portions return from `reserved` to `available`.
   - `ORDER_PREPARING -> ORDER_CANCELLED`: portions return from `reserved` to `available`.
   - Disallowed transitions:
     - Cannot cancel from `ORDER_DELIVERING` or `ORDER_COMPLETED`.
     - Cannot transition out of `ORDER_COMPLETED`, `ORDER_CANCELLED`, or `ORDER_REJECTED`.
     - Direct jump from `ORDER_ACCEPTED` to `ORDER_DELIVERING` fails.
7. **Concurrency & Thread Safety**:
   - **Race on Last Portion**: Multiple concurrent threads attempting to place orders for the last remaining portion of a dish: exactly one order is accepted, others rejected; zero overselling.
   - **Concurrent Transition vs Placement**: Thread A placing an order while Thread B cancels an earlier order returning portions: inventory invariant holds strictly without deadlocks or corrupted counters.

