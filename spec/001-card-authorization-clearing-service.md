# Specification: Card Authorization and Multi-Clearing Service

**Scope**: Service Layer Only (`app/service/`)  
**Status**: Pending Review  
**Layer Focus**: HTTP Endpoints, Request/Response Schemas, Idempotency Conventions, Service &harr; Manager Data Contracts.

---

## 1. Overview & Scope

This specification defines the HTTP API service layer for an in-memory card issuing payment service.
- **In Scope**:
  - Flask HTTP routing and handler implementation in `app/service/api.py`.
  - JSON Schema validation definitions in `app/service/schema.py`.
  - Idempotency key extraction and validation (header verification).
  - Service &harr; Manager contract dataclasses in `app/manager/entities.py`.
  - **Not Implemented Error Behavior**: Because manager/adapter layers are deferred to Spec 002 & 003, all newly defined routes will perform request validation (headers & schema) and then throw `NotImplementedError` (returning HTTP `501 Not Implemented`).
- **Deferred Layers**:
  - Manager Layer (`app/manager/`): *Deferred to Spec 002*.
  - Manager &harr; Adapter Contract (`app/adapter/entities.py`): *Deferred to Spec 002 / Spec 003*.
  - Adapter Layer (`app/adapter/`): *Deferred to Spec 003*.
  - Test Suite (`tests/`): *Deferred to subsequent specs*.

---

## 2. Phase 1 Stub Behavior (501 Not Implemented)

For this initial service-layer-only specification:
1. **Validation Precedes Stubbing**:
   - Request headers (`Idempotency-Key` on mutating endpoints) are checked first. If missing, return `400 Bad Request`.
   - JSON Schema validation (`AUTHORIZATION_SCHEMA`, `CLEARING_SCHEMA`, `REVERSAL_SCHEMA`) runs next. If invalid, return `400 Bad Request`.
2. **Throw Not Implemented**:
   - After validation passes, handlers raise `NotImplementedError("Manager layer deferred to Spec 002")`.
   - A Flask errorhandler intercepts `NotImplementedError` and responds with HTTP `501 Not Implemented`:
     ```json
     {
       "error": "Not Implemented",
       "message": "Manager layer deferred to Spec 002"
     }
     ```
3. **Target Responses (Post-Manager Wiring)**:
   - The status codes documented below (`201`, `200`, `422`, `404`, replay cache) represent the final target contracts once the Manager layer is wired in Spec 002.

---

## 3. Idempotency Convention

Payment mutations must guard against network retries:
1. **Header**: Mutating endpoints (`POST /authorizations`, `POST /clearings`, `POST /authorizations/<id>/reversals`) require the header:
   ```http
   Idempotency-Key: <unique-client-key>
   ```
2. **Behavior**:
   - **First Arrival**: Request executes normally; response status code and payload are recorded against `(card_id, idempotency_key)`.
   - **Retry Arrival**: The service returns the exact previous HTTP status and response payload with header `Idempotent-Replay: true`. The backend executes a **no-op** (no balance changes, no new hold or ledger entries created).
3. **Missing Key**: If `Idempotency-Key` is missing or empty on a mutating route, return `400 Bad Request`.

---

## 4. Service Layer Endpoints (`app/service/api.py`)

### 4.1 `POST /authorizations`
Place a temporary hold (valid for 60 seconds) on a card's available limit.

- **Headers**: `Idempotency-Key: <str>` (Required)
- **Request Body**:
  ```json
  {
    "card_id": "card_seed_1",
    "amount": 100.00,
    "merchant": "Amazon"
  }
  ```
- **Responses**:
  - `201 Created`: Hold placed successfully.
    ```json
    {
      "authorization_id": "auth_101",
      "card_id": "card_seed_1",
      "amount": 100.00,
      "merchant": "Amazon",
      "status": "APPROVED",
      "expires_at": "2026-10-13T20:31:00Z",
      "created_at": "2026-10-13T20:30:00Z"
    }
    ```
  - `422 Unprocessable Entity`: Declined (e.g. `INSUFFICIENT_FUNDS`).
    ```json
    {
      "error": "INSUFFICIENT_FUNDS",
      "message": "Hold amount exceeds available limit",
      "card_id": "card_seed_1",
      "amount": 100.00,
      "available_limit": 50.00,
      "status": "DECLINED"
    }
    ```
  - `400 Bad Request`: Validation failure or missing `Idempotency-Key`.
  - `404 Not Found`: Card does not exist.

---

### 4.2 `POST /clearings`
Capture and settle funds. Supports regular clearings against an authorization, partial multi-clearings, over-captures (e.g., restaurant tip), and force-posts (no authorization).

- **Headers**: `Idempotency-Key: <str>` (Required)
- **Request Body**:
  ```json
  {
    "card_id": "card_seed_1",
    "amount": 40.00,
    "merchant": "Amazon",
    "authorization_id": "auth_101"
  }
  ```
  *(Note: `authorization_id` is optional. If omitted or null, the request is processed as a **force-post**).*
- **Responses**:
  - `201 Created`: Settle recorded successfully.
    ```json
    {
      "clearing_id": "clr_201",
      "card_id": "card_seed_1",
      "amount": 40.00,
      "merchant": "Amazon",
      "authorization_id": "auth_101",
      "is_force_post": false,
      "status": "SETTLED",
      "created_at": "2026-10-13T20:30:15Z"
    }
    ```
  - `400 Bad Request`: Validation failure or missing `Idempotency-Key`.
  - `404 Not Found`: Card or referenced `authorization_id` not found.

---

### 4.3 `POST /authorizations/<authorization_id>/reversals`
Cancel an active authorization hold early, restoring available limit.
- **Rule**: Reversals **only apply to the active remaining held amount** of an authorization. They never touch settled funds.
- **Partial Reversals**:
  - If `amount` is specified: reverses that partial amount (must be $\le$ remaining held amount).
  - If `amount` is omitted: reverses the full remaining held amount for the authorization.
- **Headers**: `Idempotency-Key: <str>` (Required)
- **Request Body**:
  ```json
  {
    "card_id": "card_seed_1",
    "amount": 60.00
  }
  ```
- **Responses**:
  - `200 OK`: Reversal processed.
    ```json
    {
      "reversal_id": "rev_301",
      "authorization_id": "auth_101",
      "card_id": "card_seed_1",
      "reversed_amount": 60.00,
      "remaining_held_amount": 0.00,
      "status": "REVERSED",
      "created_at": "2026-10-13T20:30:30Z"
    }
    ```
  - `400 Bad Request`: Validation failure or missing `Idempotency-Key`.
  - `404 Not Found`: Authorization or card not found.
  - `422 Unprocessable Entity`: Hold already expired, already fully cleared/reversed, or requested amount exceeds remaining held balance.

---

### 4.4 `GET /cards/<card_id>/balance`
Retrieve current credit limit and balance breakdown. Safe & read-only (no idempotency key required).

- **Responses**:
  - `200 OK`:
    ```json
    {
      "card_id": "card_seed_1",
      "credit_limit": 1000.00,
      "settled_balance": 40.00,
      "held_balance": 60.00,
      "available_limit": 900.00
    }
    ```
  - `404 Not Found`: Card not found.

---

### 4.5 `GET /cards/<card_id>/transactions`
Retrieve the card transaction and activity ledger. Safe & read-only.

- **Responses**:
  - `200 OK`:
    ```json
    {
      "card_id": "card_seed_1",
      "transactions": [
        {
          "transaction_id": "auth_101",
          "card_id": "card_seed_1",
          "type": "AUTHORIZATION",
          "amount": 100.00,
          "merchant": "Amazon",
          "status": "APPROVED",
          "timestamp": "2026-10-13T20:30:00Z"
        },
        {
          "transaction_id": "clr_201",
          "card_id": "card_seed_1",
          "type": "CLEARING",
          "amount": 40.00,
          "merchant": "Amazon",
          "status": "SETTLED",
          "authorization_id": "auth_101",
          "timestamp": "2026-10-13T20:30:15Z"
        }
      ]
    }
    ```
  - `404 Not Found`: Card not found.

---

## 5. JSON Validation Schemas (`app/service/schema.py`)

```python
AUTHORIZATION_SCHEMA = {
    "type": "object",
    "properties": {
        "card_id": {"type": "string", "minLength": 1},
        "amount": {"type": "number", "exclusiveMinimum": 0},
        "merchant": {"type": "string", "minLength": 1},
    },
    "required": ["card_id", "amount", "merchant"],
    "additionalProperties": False,
}

CLEARING_SCHEMA = {
    "type": "object",
    "properties": {
        "card_id": {"type": "string", "minLength": 1},
        "amount": {"type": "number", "exclusiveMinimum": 0},
        "merchant": {"type": "string", "minLength": 1},
        "authorization_id": {"type": "string", "minLength": 1},
    },
    "required": ["card_id", "amount", "merchant"],
    "additionalProperties": False,
}

REVERSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "card_id": {"type": "string", "minLength": 1},
        "amount": {"type": "number", "exclusiveMinimum": 0},
    },
    "required": ["card_id"],
    "additionalProperties": False,
}
```

---

## 6. Service &harr; Manager Contract (`app/manager/entities.py`)

```python
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class AuthorizationRequestEntity:
    card_id: str
    amount: float
    merchant: str
    idempotency_key: str


@dataclass
class AuthorizationResponseEntity:
    card_id: str
    amount: float
    merchant: str
    status: str
    created_at: str
    authorization_id: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None
    available_limit: Optional[float] = None
    is_replayed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ClearingRequestEntity:
    card_id: str
    amount: float
    merchant: str
    idempotency_key: str
    authorization_id: Optional[str] = None


@dataclass
class ClearingResponseEntity:
    card_id: str
    amount: float
    merchant: str
    status: str
    created_at: str
    is_force_post: bool
    clearing_id: Optional[str] = None
    authorization_id: Optional[str] = None
    error: Optional[str] = None
    is_replayed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ReversalRequestEntity:
    card_id: str
    authorization_id: str
    idempotency_key: str
    amount: Optional[float] = None


@dataclass
class ReversalResponseEntity:
    authorization_id: str
    card_id: str
    reversed_amount: float
    status: str
    created_at: str
    remaining_held_amount: Optional[float] = None
    reversal_id: Optional[str] = None
    error: Optional[str] = None
    is_replayed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CardBalanceResponseEntity:
    card_id: str
    credit_limit: float
    settled_balance: float
    held_balance: float
    available_limit: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransactionEntity:
    transaction_id: str
    card_id: str
    type: str
    amount: float
    merchant: str
    status: str
    timestamp: str
    authorization_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CardTransactionsResponseEntity:
    card_id: str
    transactions: List[TransactionEntity]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "card_id": self.card_id,
            "transactions": [t.to_dict() for t in self.transactions],
        }
```

---

## 7. Deferred Layers & Components

- **Manager Layer (`app/manager/`)**: *Deferred to Spec 002*. Will handle limit validation, 60s hold expiration logic, partial clears, over-capture handling, force-posts, and idempotency cache lookup.
- **Manager &harr; Adapter Contract (`app/adapter/entities.py`)**: *Deferred to Spec 002 / Spec 003*.
- **Adapter Layer (`app/adapter/`)**: *Deferred to Spec 003*. In-memory stores for cards, holds, clearings, ledger, and idempotency records.
- **Tests (`tests/`)**: *Deferred to subsequent specs*.
