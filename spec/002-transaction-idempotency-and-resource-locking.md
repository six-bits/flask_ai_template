# 002: Transaction-Bound Idempotency & Resource-Level Locking Specification

**Scope: Full Stack** (Adapter &rarr; Manager &rarr; Service)

---

## 1. Overview & Scope

### 1.1 Purpose
This specification updates the **Multi-Currency Wallet Service** to resolve two key architectural concerns:
1. **Transaction-Bound Idempotency**:
   - Eliminate the separate, detached `IdempotencyRecordEntity` and standalone `idempotency` collection.
   - Bind `idempotency_key` and `response_payload` directly to the [`TransactionRecordEntity`](file:///Users/hammad/Projects/flask_ai_template/app/adapter/entities.py#L73-L84).
   - The transaction entity itself acts as the single source of truth for both audit logging and request deduplication.
2. **Resource-Level Locking (Elimination of Global Locks)**:
   - Eliminate coarse global locks (`global_lock`) across `InMemoryDatabase`, `WalletAdapter`, and `QuoteAdapter`.
   - Restrict locking **strictly to money movement operations** and **only to the involved resources** (the specific accounts participating in the debit and credit legs).
   - Read queries (`get_user_balances`, `get_rates`, `get_quote`, `get_user_transactions`) and non-movement writes operate lock-free.
   - Each account entity owns its own reentrant lock (`AccountRecordEntity.lock`), acquired in deterministic lexicographical order during leg execution.

---

## 2. Service Layer (`app/service/`)

### 2.1 HTTP Endpoints
HTTP route signatures, request schemas, and responses remain identical and backwards-compatible with [spec/001-multi-currency-wallet-service.md](file:///Users/hammad/Projects/flask_ai_template/spec/001-multi-currency-wallet-service.md):
- `POST /quotes`
- `POST /quotes/accept` (accepts `quote_id`, `user_id`, and optional `Idempotency-Key` header)
- `POST /transfers` (accepts sender, recipient, currency, minor amount, and optional `Idempotency-Key` header)
- `GET /users/<user_id>/balances` (Lock-free balance query)
- `GET /users/<user_id>/transactions` (Lock-free transaction history query)
- `GET /rates` (Lock-free exchange rates query)

---

## 3. Service &harr; Manager Contract (`app/manager/entities.py`)

No changes required to the Service &harr; Manager contract. Entities already carry `idempotency_key: Optional[str] = None` on mutating requests:
- [`P2PTransferRequestEntity`](file:///Users/hammad/Projects/flask_ai_template/app/manager/entities.py#L107-L114)
- [`AcceptQuoteRequestEntity`](file:///Users/hammad/Projects/flask_ai_template/app/manager/entities.py#L70-L75)

---

## 4. Manager &harr; Adapter Contract (`app/adapter/entities.py`)

### 4.1 Update: `AccountRecordEntity` (Owns Resource Lock)
Each account holds its own reentrant lock (`threading.RLock`), eliminating the need for any global lock dictionary:

```python
# app/adapter/entities.py

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class AccountRecordEntity:
    """Storage entity for a currency account (user or settlement pool)."""
    account_id: str          # e.g. "usr_alice:USD", "pool:outbound:USD"
    owner_id: str            # e.g. "usr_alice" or "system_pool"
    currency: str            # e.g. "USD"
    balance: int             # Minor units (e.g. 100000 = $1,000.00)
    is_pool: bool = False
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("lock", None)
        return d
```

---

### 4.2 Update: `TransactionRecordEntity` (Unifies Idempotency with Audit)
The standalone `IdempotencyRecordEntity` is **removed**. Idempotency key, deterministic request payload hash, and cached response are stored directly on the transaction:

```python
@dataclass
class TransactionRecordEntity:
    """
    Storage entity for a high-level transaction grouping multiple legs.
    Serves as both the audit ledger and the idempotency record.
    """
    transaction_id: str
    user_id: str
    transaction_type: str                  # P2P_TRANSFER | FX_CONVERSION
    status: str                            # PENDING | COMPLETED | FAILED | REVERSED
    idempotency_key: Optional[str] = None  # Bound idempotency key
    request_hash: Optional[str] = None     # SHA-256 hash of canonical request payload
    response_payload: Optional[Dict[str, Any]] = None  # Cached response for idempotency replay
    legs: List[LedgerLegRecordEntity] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

---

### 4.3 Deterministic Payload Hashing
To prevent idempotency key collisions across different payloads, the service computes a SHA-256 hash of the canonical (sorted keys, compact separators) JSON payload:

```python
import hashlib
import json

def compute_payload_hash(payload: Dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 hash of the request payload."""
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
```

---

## 5. Manager Layer (`app/manager/`)

Managers orchestrate transaction-bound idempotency, validate payload hash matching, and delegate money movement to `WalletAdapter`:

### 5.1 `TransferManager` Workflow
1. **Idempotency Lease & Hash Verification**:
   - If `request.idempotency_key` is provided:
     - Compute `incoming_hash = compute_payload_hash(request.to_dict())`.
     - Calls `wallet_adapter.get_or_create_idempotent_transaction(key=request.idempotency_key, request_hash=incoming_hash, ...)`.
     - If an existing transaction with this key exists:
       - **Payload Mismatch Check**:
         `if existing_tx.request_hash != incoming_hash:`
         &rarr; Raise `IdempotencyPayloadMismatchError("Idempotency-Key reused with different request payload")` (maps to **HTTP 400 Bad Request**).
       - **In-Flight Check**:
         `if existing_tx.status == "PENDING":`
         &rarr; Raise `IdempotencyConflictError("A request with this Idempotency-Key is currently processing")` (maps to **HTTP 409 Conflict**).
       - **Completed Replay**:
         `if existing_tx.status == "COMPLETED":`
         &rarr; Return `P2PTransferResponseEntity(**existing_tx.response_payload)`.
2. **Execute Legs (Money Movement)**:
   - Forward legs:
     $$\text{Sender} \longrightarrow \text{Pool: Outbound} \longrightarrow \text{Pool: Inbound} \longrightarrow \text{Recipient}$$
   - Executed through `wallet_adapter.execute_transfer_leg()`, which only locks the two accounts involved in each step.
3. **Complete or Compensate**:
   - On success: updates `tx.status = "COMPLETED"`, sets `tx.response_payload = response.to_dict()`.
   - On failure: triggers LIFO compensations, updates `tx.status = "REVERSED"`, and raises `TransferExecutionError`.

### 5.2 `QuoteManager` Workflow
1. **Create Quote**: Lock-free query to `QuoteAdapter` for rates, lock-free quote persistence.
2. **Accept Quote (Idempotency Lease, Hash Verification & Movement)**:
   - If `request.idempotency_key` is provided:
     - Compute `incoming_hash = compute_payload_hash({"quote_id": request.quote_id, "user_id": request.user_id})`.
     - Inspects or leases `TransactionRecordEntity` via `wallet_adapter`.
     - Rejects with `400 Bad Request` if key was previously used with a different quote ID or user.
     - Rejects with `409 Conflict` if currently `PENDING`.
     - Replays cached response if `COMPLETED`.
   - Validates TTL ($\le 30\text{s}$) and quote status via `QuoteAdapter` without locks.
   - Executes 4 cross-currency movement legs via `wallet_adapter.execute_transfer_leg()` (locking only participating accounts per leg).
   - On success: updates `tx.status = "COMPLETED"`, caches `response_payload`.
   - On failure: compensates completed legs in LIFO order and updates `tx.status = "REVERSED"`.

---

## 6. Adapter Layer (`app/adapter/`)

### 6.1 `InMemoryDatabase` (`app/adapter/database.py`)
- **No Global Locks**: `self.global_lock = None` (removed).
- **No Account Locks Registry**: Removed `self.account_locks`. Locks live directly inside `AccountRecordEntity.lock`.
- **No Idempotency Table**: Removed `self.idempotency`. Added index `transactions_by_idempotency: Dict[str, TransactionRecordEntity]`.

```python
class InMemoryDatabase:
    def __init__(self, seed: bool = True) -> None:
        self.accounts: Dict[str, AccountRecordEntity] = {}
        self.quotes: Dict[str, QuoteRecordEntity] = {}
        self.transactions: Dict[str, TransactionRecordEntity] = {}
        self.transactions_by_idempotency: Dict[str, TransactionRecordEntity] = {}
        self.rates: Dict[str, float] = {}
        self.fee_percentage: float = 0.01

        if seed:
            self.seed_base_state()
```

---

### 6.2 `WalletAdapter` (`app/adapter/wallet_adapter.py`)
Locks **ONLY** involved accounts during money movement:

```python
class WalletAdapter:
    def __init__(self, db: Optional[InMemoryDatabase] = None) -> None:
        self.db = db or default_db

    # --- Lock-Free Queries ---
    def user_exists(self, user_id: str) -> bool:
        return any(acc.owner_id == user_id for acc in self.db.accounts.values())

    def get_user_balances(self, user_id: str) -> Dict[str, int]:
        return {acc.currency: acc.balance for acc in self.db.accounts.values() if acc.owner_id == user_id}

    # --- Money Movement: Locks ONLY Involved Resources ---
    def execute_transfer_leg(self, leg: LedgerLegRecordEntity) -> LedgerLegRecordEntity:
        from_acc = self._resolve_account(leg.from_account_id, leg.currency)
        to_acc = self._resolve_account(leg.to_account_id, leg.currency)

        # Deterministic lock ordering on the two involved accounts
        first, second = (from_acc, to_acc) if from_acc.account_id < to_acc.account_id else (to_acc, from_acc)

        with first.lock:
            with second.lock:
                if not from_acc.is_pool and from_acc.balance < leg.amount:
                    raise InsufficientFundsError(f"Account {from_acc.account_id} has insufficient balance")

                from_acc.balance -= leg.amount
                to_acc.balance += leg.amount
                leg.status = "COMPLETED"

                if leg.transaction_id in self.db.transactions:
                    self.db.transactions[leg.transaction_id].legs.append(leg)

                return leg

    # --- Transaction-Bound Idempotency ---
    def get_or_create_transaction(
        self,
        tx_id: str,
        user_id: str,
        tx_type: str,
        metadata: Dict[str, Any],
        idempotency_key: Optional[str] = None,
        request_hash: Optional[str] = None,
    ) -> TransactionRecordEntity:
        if idempotency_key:
            if idempotency_key in self.db.transactions_by_idempotency:
                existing = self.db.transactions_by_idempotency[idempotency_key]
                if existing.request_hash and request_hash and existing.request_hash != request_hash:
                    raise IdempotencyPayloadMismatchError(
                        "Idempotency-Key reused with different request payload"
                    )
                return existing

        tx = TransactionRecordEntity(
            transaction_id=tx_id,
            user_id=user_id,
            transaction_type=tx_type,
            status="PENDING",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            metadata=metadata,
        )
        self.db.transactions[tx_id] = tx
        if idempotency_key:
            self.db.transactions_by_idempotency[idempotency_key] = tx
        return tx

    def complete_transaction(self, tx_id: str, response_payload: Dict[str, Any]) -> None:
        if tx_id in self.db.transactions:
            tx = self.db.transactions[tx_id]
            tx.status = "COMPLETED"
            tx.response_payload = response_payload

    def fail_or_reverse_transaction(self, tx_id: str, status: str = "REVERSED") -> None:
        if tx_id in self.db.transactions:
            self.db.transactions[tx_id].status = status
```

---

### 6.3 `QuoteAdapter` (`app/adapter/quote_adapter.py`)
- Completely lock-free operations:
  - `save_quote()`, `get_quote()`, `update_quote_status()`
  - `get_rate()`, `get_all_rates()`, `get_fee_percentage()`

---

## 7. Test Plan (`tests/`)

### 7.1 Adapter Layer Tests (`tests/test_adapters.py`)
- **Resource Lock Verification**:
  - Verify `account.lock` is acquired during `execute_transfer_leg`.
  - Verify that two independent transfers on disjoint accounts (e.g. Alice $\rightarrow$ Bob and Charlie $\rightarrow$ Pool) can execute simultaneously without blocking each other.
- **Transaction Idempotency Verification**:
  - Verify `TransactionRecordEntity` contains `idempotency_key`, `request_hash`, and `response_payload`.
  - Verify `IdempotencyRecordEntity` is eliminated from the codebase.
- **Lock-Free Read Verification**:
  - Verify `get_user_balances` and `get_rates` execute without acquiring locks.

### 7.2 Manager & Service Integration Tests (`tests/test_managers.py`, `tests/test_wallet_api.py`)
- **P2P Transfer with Idempotency**:
  - First request creates `TransactionRecordEntity` with `idempotency_key` and completes.
  - Second identical request returns cached `response_payload` directly from the transaction.
- **Payload Mismatch Rejection (400 Bad Request)**:
  - Send request with `Idempotency-Key: key-123` and amount `2000`.
  - Re-send request with same `Idempotency-Key: key-123` but amount `5000` (or different recipient).
  - Verify service rejects request with **HTTP 400 Bad Request** (`"Idempotency-Key reused with different request payload"`).
  - Verify no money is moved for the mismatched request.
- **Concurrent In-Flight Collision (409 Conflict)**:
  - Simultaneous request with identical idempotency key while status is `PENDING` raises 409 Conflict.
- **Multi-Threaded Concurrency Test**:
  - 20+ concurrent threads executing transfers on accounts verify no race conditions, no negative balances, and no deadlocks.

