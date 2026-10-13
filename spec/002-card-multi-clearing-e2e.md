# Specification: Card Authorization and Multi-Clearing Full-Stack Implementation

**Scope**: Full Stack (Service &rarr; Manager &rarr; Adapter &rarr; In-Memory DB &rarr; Live E2E Tests)  
**Status**: Pending Review  
**Layer Focus**: Complete end-to-end execution with granular locking, deterministic idempotency, in-memory database with seed cards/merchants, and live server testing.

---

## 1. Overview & Architecture

This specification covers the full end-to-end implementation of the card issuing payment service.
- **Layers In Scope**:
  - **Service Layer (`app/service/api.py`)**: Connects HTTP routes to Manager, translates domain responses/exceptions into HTTP status codes and headers (`Idempotent-Replay: true`).
  - **Service &harr; Manager Contract (`app/manager/entities.py`)**: Dataclasses for request/response payloads.
  - **Manager Layer (`app/manager/payment_manager.py`)**: Domain business logic, 60-second hold expiry calculations, available limit validation, multi-clearing, over-captures, force-posts, deterministic request hashing.
  - **Manager &harr; Adapter Contract (`app/adapter/entities.py`)**: Dataclasses for database records.
  - **Adapter Layer (`app/adapter/payment_adapter.py`)**: Adapter querying and mutating in-memory store.
  - **In-Memory Database (`app/adapter/db.py`)**: Stores cards, authorizations, clearings, reversals, ledger transactions, and idempotency records, with seeded cards and merchants.
  - **Test Suite (`tests/test_e2e.py`)**: Live server integration tests executing genuine HTTP requests against the running Flask application.

---

## 2. In-Memory Database & Seed Data (`app/adapter/db.py`)

### 2.1 Seed Entities
```python
SEED_CARDS = {
    "card_seed_1": 1000.00,
    "card_seed_2": 500.00,
    "card_seed_3": 2000.00,
}

SEED_MERCHANTS = {
    "Amazon",
    "Restaurant",
    "Target",
    "Starbucks",
    "Airline Offline",
}
```

### 2.2 Storage Collections
- `cards`: Map of `card_id -> CardRecordEntity`
- `merchants`: Set of valid merchant strings
- `authorizations`: Map of `auth_id -> AuthorizationRecordEntity`
- `clearings`: Map of `clearing_id -> ClearingRecordEntity`
- `reversals`: Map of `reversal_id -> ReversalRecordEntity`
- `transactions`: Map of `card_id -> List[LedgerTransactionRecordEntity]`
- `idempotency`: Map of `idempotency_key -> IdempotencyRecordEntity`

---

## 3. Granular Locking & Concurrency Model

### 3.1 Lock Architecture
To achieve high concurrency without bottlenecks or race conditions:
1. **Object-Level Locks**:
   - Each `CardRecordEntity` has its own `threading.RLock()` (`card.lock`).
   - Each `AuthorizationRecordEntity` has its own `threading.RLock()` (`auth.lock`).
2. **Collection-Level Locks**:
   - `_auths_lock`: Synchronizes additions to the global `authorizations` dictionary.
   - `_clearings_lock`: Synchronizes additions to the global `clearings` dictionary.
   - `_reversals_lock`: Synchronizes additions to the global `reversals` dictionary.
   - `_idempotency_lock`: Synchronizes atomic check-and-insert operations on the `idempotency` dictionary.

### 3.2 Canonical Lock Ordering (Deadlock Prevention)
When an operation requires multiple locks (e.g., settling an authorization against a card), locks must **strictly** be acquired in this global hierarchy:
$$\text{Card Lock} \longrightarrow \text{Authorization Lock}$$

1. **Rule**: A thread must ALWAYS acquire `card.lock` before acquiring `auth.lock`.
2. **Reverse Access Prevention**: No thread is ever permitted to hold an `auth.lock` and then request a `card.lock`.
3. **Lookup Resolution**: If an operation only has `authorization_id`:
   - It reads `auth.card_id` under a momentary read (or registry lookup).
   - It acquires `card.lock` first.
   - It then acquires `auth.lock` second.
4. **Collection Mutation Safety**:
   - Appending to `card.transactions` is protected by `card.lock`.
   - Mutating `card.settled_balance` or checking available balance is protected by `card.lock`.
   - Updating `auth.remaining_held_amount` or `auth.status` is protected by both `card.lock` and `auth.lock`.

---

## 4. Deterministic Idempotency Specification

### 4.1 Idempotency Record Entity
```python
@dataclass
class IdempotencyRecordEntity:
    idempotency_key: str
    card_id: str
    request_hash: str
    status_code: int
    response_body: Dict[str, Any]
    created_at: str
```

### 4.2 Deterministic Request Hashing
- Hash formula:
  $$\text{Hash} = \text{SHA-256}\Big(\text{METHOD} + \text{":""} + \text{ENDPOINT} + \text{":""} + \text{canonical\_json}(\text{payload})\Big)$$
- `canonical_json` sorts all dictionary keys and formats numbers deterministically.
- **Collision / Conflict Handling**:
  - If `idempotency_key` exists and `stored_hash == current_hash`: return stored response with HTTP header `Idempotent-Replay: true` (backend **no-op**).
  - If `idempotency_key` exists and `stored_hash != current_hash`: return HTTP `409 Conflict` (`"Idempotency key reused with different request payload"`).

---

## 5. Domain Rules & Multi-Clearing Math

1. **60-Second Hold Expiration**:
   - `expires_at = created_at + 60.0s`.
   - On evaluation, if `now >= expires_at` and `status == "APPROVED"`: mark `EXPIRED` and `remaining_held_amount = 0`.
   - Active held balance for a card: $\sum_{\text{active unexpired auths}} \text{remaining\_held\_amount}$.
2. **Available Remaining Limit**:
   $$\text{Available Limit} = \text{Credit Limit} - \text{Settled Balance} - \text{Active Held Balance}$$
3. **Multi-Clearing (Partial Clearing)**:
   - Clearing `amount` is subtracted from `auth.remaining_held_amount`.
   - `card.settled_balance` increases by `amount`.
   - If `auth.remaining_held_amount == 0`: `auth.status = "CLEARED"`.
4. **Over-Capture (e.g. Tips)**:
   - Clearing `amount > auth.remaining_held_amount`.
   - Entire remaining held amount is released (`remaining_held_amount = 0`, `status = "CLEARED"`).
   - `card.settled_balance` increases by full clearing `amount`.
5. **Force-Post**:
   - Arrives without `authorization_id`.
   - Always approved and increases `card.settled_balance` by `amount`.
   - Allowed to push `available_limit` negative.
6. **Reversal**:
   - Reverses up to `auth.remaining_held_amount`.
   - Decreases remaining held amount, releasing available limit immediately.
   - Fails with `422 Unprocessable Entity` if authorization is already expired or fully cleared.
7. **Seed Validation**:
   - `card_id` must exist in `SEED_CARDS`; else `404 Not Found`.
   - `merchant` must exist in `SEED_MERCHANTS`; else `400 Bad Request`.

---

## 6. Manager & Adapter Contracts

### 6.1 `app/adapter/entities.py`
- `CardRecordEntity(card_id: str, credit_limit: float, settled_balance: float)`
- `AuthorizationRecordEntity(authorization_id: str, card_id: str, merchant: str, original_amount: float, remaining_held_amount: float, status: str, created_at: float, expires_at: float)`
- `ClearingRecordEntity(clearing_id: str, card_id: str, authorization_id: Optional[str], amount: float, merchant: str, is_force_post: bool, created_at: float)`
- `ReversalRecordEntity(reversal_id: str, authorization_id: str, card_id: str, amount: float, created_at: float)`
- `LedgerTransactionRecordEntity(transaction_id: str, card_id: str, type: str, amount: float, merchant: str, status: str, timestamp: float, authorization_id: Optional[str])`
- `IdempotencyRecordEntity(idempotency_key: str, card_id: str, request_hash: str, status_code: int, response_body: Dict[str, Any], created_at: float)`

### 6.2 `app/manager/entities.py`
Existing dataclasses from Spec 001 wired to the Manager methods:
- `create_authorization(entity, request_hash)`
- `create_clearing(entity, request_hash)`
- `reverse_authorization(entity, request_hash)`
- `get_card_balance(card_id)`
- `get_card_transactions(card_id)`

---

## 7. Test Plan (`tests/test_e2e.py`)

End-to-end tests starting the real Flask server in a background thread and issuing HTTP requests via `requests` or `urllib`:
1. **Health Check**: Server is responsive.
2. **Valid Authorization**: Hold placed for 60s, held balance increases, available limit decreases.
3. **Insufficient Limit**: Authorization declined when `amount > available_limit`.
4. **Seed Validations**: Unknown merchant returns 400; unknown card returns 404.
5. **Idempotency Replay**: Identical request replayed returns stored response, `Idempotent-Replay: true`, and performs no-op.
6. **Idempotency Conflict**: Same key with different payload returns 409 Conflict.
7. **Multi-Clearing**: Successive partial clearings reduce hold and increase settled balance.
8. **Over-Capture**: Clearing exceeding authorized amount captures full amount and releases hold.
9. **Force-Post**: Accepted without authorization and drives available limit negative.
10. **Reversal**: Partial and full hold reversals restore available limit; reversing settled/expired auth returns 422.
11. **Hold Expiry**: Holds older than 60s automatically expire, releasing held funds.
12. **Granular Concurrency Stress Test**: Multiple concurrent threads issue simultaneous authorizations and clearings against same and different cards to verify no deadlocks, race conditions, or collection corruption occur.
