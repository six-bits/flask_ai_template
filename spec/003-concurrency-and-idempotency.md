# Specification 003: Concurrency Control and Idempotency for Transfers and Quotes

**Scope**: `Scope: Full Stack` (Service Layer, Manager Layer, Adapter Layer, and Test Suite)

---

## 1. Overview & Scope

Financial transactions require strict guarantees against two distinct distributed systems hazards:
1. **Concurrency Hazards (Race Conditions & Deadlocks)**:
   - When multiple threads attempt to mutate the same account simultaneously (e.g. concurrent transfers from Alice to Bob and Charlie), interleaving can cause **overdrafts below zero** or state loss.
   - When concurrent transactions acquire locks across multiple accounts in arbitrary order (e.g. Alice $\rightarrow$ Bob concurrently with Bob $\rightarrow$ Alice), classic **circular deadlocks** occur.
2. **Idempotency Hazards (Network Retries & Duplicate Submissions)**:
   - When network failures disconnect a client before receiving an HTTP response, retrying the operation must **not** execute a second transfer or quote conversion.
   - Clients supply a unique `Idempotency-Key` HTTP header. Replaying the exact same request must return the cached original response without side effects.
   - Replaying with the same key but different parameters must be rejected as an idempotency payload conflict.
   - Concurrent in-flight requests with the identical key must be rejected with `409 Conflict`.

---

## 2. Architecture & Design Principles

### 2.1 Concurrency Architecture: Deadlock-Free Lexicographical Mutex Locking
- **Resource Lock Striping (`LockManager`)**:
  - Each financial aggregate (`user_id`, `quote_id`) has a dedicated re-entrant mutex (`threading.RLock`).
- **Global Strict Lock Ordering (Deadlock Prevention)**:
  - Whenever an operation involves multiple resources (e.g. P2P transfer between `user_A` and `user_B`), locks **MUST** be acquired in lexicographical order:
    $$\text{Order} = \text{sorted}([A, B])$$
  - Acquiring in monotonic order mathematically eliminates circular wait cycles ($A \to B$ vs $B \to A$), guaranteeing deadlock freedom.
- **Critical Section Scope**:
  - The critical section encapsulates both the balance availability check and the state machine mutation pipeline. No other thread can read or modify the accounts while the lock is held, completely preventing double-spending and overdrafts.

### 2.2 Idempotency Architecture: Three-State State Machine
Idempotency records transition through a strict lifecycle:
```text
[POST Request + Idempotency-Key] 
       │
       ▼
  IN_PROGRESS (Atomic Reservation)
       ├─ Concurrent Key In-Flight ──> 409 Conflict
       ├─ Success ───────────────────> COMPLETED (Caches Response + 200 OK)
       └─ Domain Failure ────────────> FAILED / RELEASED (Allows Safe Retry)
```

1. **State 1: `IN_PROGRESS`**:
   - When a request with `Idempotency-Key` arrives, the system attempts an atomic reservation.
   - If the key already exists and is `IN_PROGRESS`: return `409 Conflict` (`CONCURRENT_REQUEST_IN_PROGRESS`).
2. **State 2: `COMPLETED`**:
   - On successful transaction, the record is updated with `status="COMPLETED"`, original HTTP `status_code`, and serializable `response_body`.
   - On subsequent retries:
     - If `SHA256(request_body)` matches: replay cached response with HTTP header `Idempotent-Replayed: true`.
     - If `SHA256(request_body)` differs: reject with `422 Unprocessable Entity` or `400 Bad Request` (`IDEMPOTENCY_KEY_PAYLOAD_MISMATCH`).
3. **State 3: `FAILED`**:
   - If an unexpected server failure occurs during execution, the reservation is released or marked `FAILED` so that subsequent attempts may retry safely.

---

## 3. Service Layer (`app/service/`)

### 3.1 HTTP Headers & Status Codes

| Endpoint | Method | Header | Status Codes | Description |
| :--- | :--- | :--- | :--- | :--- |
| `/transfers` | `POST` | `Idempotency-Key: <string>` (optional) | `200`, `400`, `404`, `409`, `422` | Transfer money with concurrency lock & idempotency |
| `/quotes/<quote_id>/accept` | `POST` | `Idempotency-Key: <string>` (optional) | `200`, `400`, `404`, `409`, `422` | Accept quote with concurrency lock & idempotency |

- **Response Header**:
  - `Idempotent-Replayed: true` (returned on idempotent replay).

### 3.2 Error Codes & HTTP Mappings

| Error Code | HTTP Status | Meaning |
| :--- | :--- | :--- |
| `CONCURRENT_REQUEST_IN_PROGRESS` | `409 Conflict` | Another request with the same idempotency key is currently executing. |
| `IDEMPOTENCY_KEY_PAYLOAD_MISMATCH` | `422 Unprocessable Entity` | The idempotency key was previously used with a different request payload. |
| `INSUFFICIENT_FUNDS` | `400 Bad Request` | Concurrently serialized debit failed because balance was exhausted. |
| `QUOTE_ALREADY_ACCEPTED` | `400 Bad Request` | Quote was already accepted (without idempotency key). |

---

## 4. Service &harr; Manager Contract (`app/manager/entities.py`)

### 4.1 Request & Response Entity Updates

```python
@dataclass
class TransferRequestEntity:
    from_user_id: str
    to_user_id: str
    currency: str
    amount: int
    idempotency_key: Optional[str] = None
    request_payload_json: str = ""

@dataclass
class AcceptQuoteRequestEntity:
    quote_id: str
    user_id: str
    idempotency_key: Optional[str] = None
    request_payload_json: str = ""

@dataclass
class IdempotencyResultEntity:
    is_replayed: bool
    status_code: int
    response_body: Dict[str, Any]
```

---

## 5. Manager Layer (`app/manager/`)

### 5.1 `LockManager` (`app/manager/lock_manager.py`)
Fine-grained concurrency coordinator:
- `get_lock(resource_id: str) -> threading.RLock`: Returns or creates a re-entrant lock for a given resource.
- `acquire_ordered_locks(*resource_ids: str)`: Context manager that sorts resource IDs lexicographically and acquires them in sequential nested order to eliminate circular deadlocks.

### 5.2 `IdempotencyManager` (`app/manager/idempotency_manager.py`)
Coordinates request deduplication:
- `compute_hash(endpoint: str, user_id: str, payload_json: str) -> str`: Produces a deterministic SHA256 signature.
- `reserve_key(key: str, user_id: str, endpoint: str, request_hash: str) -> Tuple[bool, Optional[IdempotencyRecordEntity]]`:
  - Returns `(True, None)` if reserved successfully.
  - Returns `(False, existing_record)` if key already exists.
- `complete_key(key: str, status_code: int, response_body: Dict[str, Any]) -> None`: Updates status to `COMPLETED` and caches response.
- `release_key(key: str) -> None`: Deletes or resets `IN_PROGRESS` key if domain execution fails.

### 5.3 Updates to `TransferManager` (`app/manager/transfer_manager.py`)
1. **Idempotency Check**:
   - If `idempotency_key` is provided, compute hash and call `IdempotencyManager.reserve_key()`.
   - If existing record is `COMPLETED`: check hash match; if match, return cached response; if mismatch, raise `IdempotencyPayloadMismatchError`.
   - If existing record is `IN_PROGRESS`: raise `ConcurrentRequestConflictError`.
2. **Deadlock-Free Resource Locking**:
   - `with lock_manager.acquire_ordered_locks(request.from_user_id, request.to_user_id):`
     - Perform balance check.
     - Execute 3-hop state machine (`debit_sender_to_outbound`, `route_outbound_to_inbound`, `settle_inbound_to_recipient`).
     - Record transaction ledger entries.
3. **Idempotency Completion**:
   - If `idempotency_key` provided, mark record `COMPLETED` and cache `TransferResponseEntity`.
   - On domain error, release reservation so client may fix parameters or retry.

### 5.4 Updates to `QuoteManager` (`app/manager/quote_manager.py`)
1. **Idempotency Check**:
   - Same idempotency reservation logic for `accept_quote()`.
2. **Resource Locking**:
   - `with lock_manager.acquire_ordered_locks(quote.quote_id, quote.user_id):`
     - Verify status is not `ACCEPTED`.
     - Verify funds availability.
     - Execute conversion state machine (`debit_user_for_conversion`, `clear_fx_pools`, `credit_user_from_inbound`).
     - Update quote status to `ACCEPTED`.
3. **Idempotency Completion**:
   - Mark record `COMPLETED` and cache `AcceptQuoteResponseEntity`.

---

## 6. Manager &harr; Adapter Contract (`app/adapter/entities.py`)

### 6.1 `IdempotencyRecordEntity`
```python
@dataclass
class IdempotencyRecordEntity:
    """Storage entity representing an idempotency key and cached response."""
    key: str
    user_id: str
    endpoint: str
    request_hash: str
    status: str  # "IN_PROGRESS", "COMPLETED", "FAILED"
    status_code: int = 200
    response_body: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

---

## 7. Adapter Layer (`app/adapter/`)

### 7.1 `IdempotencyAdapter` (`app/adapter/idempotency_adapter.py`)
- In-memory thread-safe store for `IdempotencyRecordEntity`.
- Methods:
  - `reserve(key: str, user_id: str, endpoint: str, request_hash: str) -> Tuple[bool, Optional[IdempotencyRecordEntity]]`
  - `get(key: str) -> Optional[IdempotencyRecordEntity]`
  - `save(record: IdempotencyRecordEntity) -> IdempotencyRecordEntity`
  - `delete(key: str) -> None`
  - `reset() -> None`

---

## 8. Test Plan

### 8.1 Concurrency Tests (`tests/test_concurrency.py`)
1. **Parallel Transfer Stress Test**:
   - User Alice has 1000 USD (100,000 cents).
   - Launch 20 concurrent threads each transferring 100 USD (10,000 cents) to Bob.
   - Exactly 10 transfers must succeed (200 OK); exactly 10 transfers must fail with `400 INSUFFICIENT_FUNDS`.
   - Alice's final balance must be exactly 0 cents. Bob's balance must be incremented by exactly 100,000 cents.
   - No negative balances; no lost updates; zero pool drift.
2. **Bidirectional Transfer Deadlock Test**:
   - Launch 10 threads running Alice $\rightarrow$ Bob and 10 threads running Bob $\rightarrow$ Alice concurrently.
   - All threads must complete within timeout (zero deadlocks).
3. **Concurrent Quote Acceptance Test**:
   - Create quote for 100 USD $\rightarrow$ EUR.
   - Launch 5 concurrent threads attempting to accept the exact same quote.
   - Exactly 1 thread must succeed (200 OK); other 4 threads must fail with `400 QUOTE_ALREADY_ACCEPTED`.
   - Source currency is debited exactly once.

### 8.2 Idempotency Tests (`tests/test_idempotency.py`)
1. **Idempotent Transfer Replay**:
   - Send `POST /transfers` with `Idempotency-Key: key_1`.
   - Resend exact same request with `Idempotency-Key: key_1`.
   - Both return 200 OK with identical transfer ID and balance.
   - Second response includes header `Idempotent-Replayed: true`.
   - Alice is debited only once; transaction ledger has only 1 transfer.
2. **Idempotency Payload Mismatch**:
   - Send `POST /transfers` with `Idempotency-Key: key_2` for 50 USD.
   - Resend with `Idempotency-Key: key_2` for 60 USD.
   - Second request rejected with `422 Unprocessable Entity` or `400 Bad Request` (`IDEMPOTENCY_KEY_PAYLOAD_MISMATCH`).
3. **Concurrent In-Flight Duplicate**:
   - Simulate concurrent arrival of two requests with the same `Idempotency-Key`.
   - One thread executes; the other is rejected with `409 Conflict` (`CONCURRENT_REQUEST_IN_PROGRESS`).
4. **Idempotent Quote Acceptance**:
   - Accept quote with `Idempotency-Key: key_quote_1`.
   - Replay with same key: returns identical 200 OK response with `Idempotent-Replayed: true`.
   - Conversion occurs only once.
