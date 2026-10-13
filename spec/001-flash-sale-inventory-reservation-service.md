# Specification 001: Flash Sale Inventory Reservation Service

**Scope: Service Layer Only** (HTTP routes, JSON schema validation & route handlers raising `NotImplementedError` / returning HTTP 501)

---

## 1. Overview & Scope

### 1.1 Purpose
The Flash Sale Inventory Reservation Service provides a high-contention inventory reservation lease engine for limited drops (e.g., concert tickets, limited edition goods). It allows users to hold items for a strict 30-second lease window during checkout, commits orders upon payment confirmation, immediately releases stock back to the available pool upon expiration or cancellation, and strictly enforces anti-hoarding limits per user without ever overselling.

### 1.2 Declared Scope
- **In Scope (Current Phase)**:
  - **Service Layer (`app/service/api.py`)**: Define all HTTP endpoints, route signatures, path parameters, request body extraction, JSON Schema validation, and error handlers. Every business route handler will validate its input payload and raise `NotImplementedError` (returning HTTP 501 Not Implemented).
  - **Schema Validation (`app/service/schema.py`)**: Define JSON schemas for all request payloads (`CREATE_RESERVATION_SCHEMA`, `CONFIRM_RESERVATION_SCHEMA`, `CANCEL_RESERVATION_SCHEMA`).
  - **Service &harr; Manager Data Contracts (`app/manager/entities.py`)**: Define frozen dataclass entities establishing the contract between the Service Layer and the downstream Manager Layer.
- **Deferred / Out of Scope (Future Phases)**:
  - **Manager Layer (`app/manager/inventory_manager.py`)**: Business logic, lease lifecycle state machine, anti-hoarding rules, and domain exception definitions.
  - **Manager &harr; Adapter Contract (`app/adapter/entities.py`)**: Storage entities.
  - **Adapter Layer (`app/adapter/inventory_adapter.py`, `db.py`)**: In-memory database, per-item locking, and lazy TTL expiration.
  - **Tests (`tests/`)**: Deferred until subsequent implementation phase per prompt instruction.

---

## 2. Service Layer (`app/service/`)

### 2.1 HTTP Routes & Endpoint Specifications

| HTTP Method | Route Path | Purpose | Request Body / Schema | Success Status | Error Responses | Handler Status (This Phase) |
|---|---|---|---|---|---|---|
| `GET` | `/health` | Liveness health check | None | `200 OK` | - | Implemented (`{"status": "ok"}`) |
| `GET` | `/items` | List stock breakdown for all catalog items | None | `200 OK` | `501 Not Implemented` | Raises `NotImplementedError` |
| `GET` | `/items/<item_id>` | Get stock breakdown for a specific item | None | `200 OK` | `404 Not Found`<br>`501 Not Implemented` | Raises `NotImplementedError` |
| `POST` | `/reservations` | Acquire a 30s reservation lease | `CREATE_RESERVATION_SCHEMA` | `201 Created` | `400 Bad Request`<br>`404 Not Found`<br>`409 Conflict`<br>`501 Not Implemented` | Validates Schema &rarr; Raises `NotImplementedError` |
| `POST` | `/reservations/<reservation_id>/confirm` | Confirm checkout within lease window | `CONFIRM_RESERVATION_SCHEMA` | `200 OK` | `400 Bad Request`<br>`404 Not Found`<br>`409 Conflict`<br>`410 Gone`<br>`501 Not Implemented` | Validates Schema &rarr; Raises `NotImplementedError` |
| `POST` | `/reservations/<reservation_id>/cancel` | Explicitly cancel an active reservation lease | `CANCEL_RESERVATION_SCHEMA` | `200 OK` | `400 Bad Request`<br>`404 Not Found`<br>`409 Conflict`<br>`501 Not Implemented` | Validates Schema &rarr; Raises `NotImplementedError` |

### 2.2 Error Handling & HTTP Status Semantics
- **400 Bad Request**: JSON Schema validation failure, missing request body, invalid field types, or non-positive quantity. Handled globally via `@app.errorhandler(ValidationError)`.
- **404 Not Found**: Specified `item_id` or `reservation_id` does not exist (to be raised by Manager in future phase).
- **409 Conflict**: Insufficient available stock, user purchase limit (`max_per_user`) exceeded, or invalid lease state transition (to be raised by Manager in future phase).
- **410 Gone**: 30-second reservation lease has expired (to be raised by Manager in future phase).
- **501 Not Implemented**: Raised by route handlers during this phase via `@app.errorhandler(NotImplementedError)`.

```python
@app.errorhandler(ValidationError)
def handle_validation_error(err):
    return jsonify({"error": "Validation error", "message": err.message}), 400

@app.errorhandler(NotImplementedError)
def handle_not_implemented(err):
    return jsonify({"error": "Not Implemented", "message": str(err)}), 501
```

### 2.3 JSON Schema Definitions (`app/service/schema.py`)

```python
"""JSON Schemas for Flash Sale Reservation API validation."""

CREATE_RESERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "item_id": {
            "type": "string",
            "minLength": 1,
        },
        "user_id": {
            "type": "string",
            "minLength": 1,
        },
        "quantity": {
            "type": "integer",
            "minimum": 1,
        },
    },
    "required": ["item_id", "user_id", "quantity"],
    "additionalProperties": False,
}

CONFIRM_RESERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {
            "type": "string",
            "minLength": 1,
        },
    },
    "required": ["user_id"],
    "additionalProperties": False,
}

CANCEL_RESERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {
            "type": "string",
            "minLength": 1,
        },
    },
    "required": ["user_id"],
    "additionalProperties": False,
}
```

---

## 3. Service &harr; Manager Contract (`app/manager/entities.py`)

These dataclass entities define the strongly typed interface between the Service layer and the Manager layer.

```python
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class CreateReservationRequestEntity:
    """Request payload to create an inventory reservation lease."""
    item_id: str
    user_id: str
    quantity: int


@dataclass(frozen=True)
class ConfirmReservationRequestEntity:
    """Request payload to confirm an active reservation lease."""
    reservation_id: str
    user_id: str


@dataclass(frozen=True)
class CancelReservationRequestEntity:
    """Request payload to explicitly cancel an active reservation lease."""
    reservation_id: str
    user_id: str


@dataclass(frozen=True)
class ReservationResponseEntity:
    """Response representation of a reservation lease."""
    reservation_id: str
    item_id: str
    user_id: str
    quantity: int
    status: str  # "PENDING" | "CONFIRMED" | "CANCELLED" | "EXPIRED"
    created_at: float
    expires_at: float
    confirmed_at: Optional[float] = None
    time_remaining_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ItemStockResponseEntity:
    """Response representation of an item's live stock breakdown."""
    item_id: str
    name: str
    total_stock: int
    available_stock: int
    held_stock: int
    confirmed_stock: int
    max_per_user: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ListItemStockResponseEntity:
    """Response representation of multiple items' stock breakdowns."""
    items: List[ItemStockResponseEntity]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

---

## 4. Manager Layer (`app/manager/`) &mdash; Deferred

*Status: Out of scope for this phase.*

When implemented in future phases, the Manager layer will:
1. Provide a consolidated `InventoryManager` class.
2. Coordinate reservation lifecycle state transitions: `PENDING` &rarr; `CONFIRMED`, `PENDING` &rarr; `CANCELLED`, `PENDING` &rarr; `EXPIRED`.
3. Enforce the invariant:
   $$\text{Available Stock} = \text{Total Stock} - (\text{Confirmed Stock} + \text{Active Held Stock})$$
4. Enforce anti-hoarding per user:
   $$\text{User Total Quota} = \text{User Confirmed Stock} + \text{User Active Held Stock}$$
   Reject requests where $\text{User Total Quota} + \text{Requested Quantity} > \text{Item}.\text{max\_per\_user}$.
5. Map domain exceptions (`ItemNotFoundError`, `ReservationNotFoundError`, `InsufficientStockError`, `PurchaseLimitExceededError`, `ReservationExpiredError`, `ReservationStateConflictError`, `UnauthorizedReservationAccessError`) to HTTP status codes.

---

## 5. Manager &harr; Adapter Contract (`app/adapter/entities.py`) &mdash; Deferred

*Status: Out of scope for this phase.*

Future storage entities:
- `ItemRecordEntity`: In-memory persistence representation of an inventory item.
- `ReservationRecordEntity`: In-memory persistence representation of a reservation lease.

---

## 6. Adapter Layer (`app/adapter/`) &mdash; Deferred

*Status: Out of scope for this phase.*

When implemented in future phases, the Adapter layer will:
1. Provide a consolidated `InventoryAdapter` class.
2. Provide a thread-safe in-memory database (`app/adapter/db.py`) utilizing granular per-item locking (`threading.RLock` keyed by `item_id`).
3. Implement lazy lease expiration: automatically evaluating and marking expired holds when an item is accessed under lock.

---

## 7. Test Plan (`tests/`) &mdash; Deferred

*Status: Deferred for this phase per instruction.*

Future testing will validate:
1. HTTP route schema validation (400 responses for malformed JSON, negative quantities, missing fields).
2. End-to-end lease creation, confirmation, cancellation, and expiration flows.
3. Concurrent hold acquisition with zero overselling guarantees.
