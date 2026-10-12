# 002: Multi-Currency Wallet Full Stack Specification

## 1. Overview & Scope

**Declared Scope: Full Stack (Service &rarr; Manager &rarr; Adapter &rarr; In-Memory DB &amp; Utils)**

This specification details the complete implementation of the Multi-Currency Wallet system, incorporating:
1. **Multi-Step Money Movement Model**: Every financial transaction is executed as a series of recorded atomic steps between accounts (user accounts and system clearing/pool accounts).
2. **Compensating Rollback Mechanism**: If any step in a multi-step sequence fails midway, all prior completed steps in that transaction are reversed via compensating transfers.
3. **Fine-Grained Account-Level Locking**: Concurrency control locks *only* the specific accounts participating in the transaction, ordered canonically to prevent deadlocks.
4. **Idempotency Validation & Response Caching**: Guarantees exactly-once semantics for quote acceptance and P2P transfers using `idempotency_key`.
5. **In-Memory Storage Architecture**: Centralized in-memory storage and seed data in `app/adapter/db.py`, with cross-cutting utilities in `app/utils/`.

---

## 2. In-Memory Data Model (`app/adapter/db.py`)

All application data resides in a thread-safe in-memory database singleton in `app/adapter/db.py`.

### 2.1 Core Entities & Schema

```text
┌─────────────────┐       ┌────────────────────────┐       ┌───────────────────────┐
│   UserRecord    │       │     AccountRecord      │       │  ExchangeRateRecord   │
├─────────────────┤       ├────────────────────────┤       ├───────────────────────┤
│ id              │1     *│ account_id (PK)        │       │ from_currency (PK)    │
│ name            │───────│ owner_type (USER/SYS)  │       │ to_currency (PK)      │
│ email           │       │ owner_id               │       │ rate                  │
└─────────────────┘       │ currency               │       └───────────────────────┘
                          │ balance (Decimal)      │
                          │ allow_negative (bool)  │
                          └───────────┬────────────┘
                                      │ 1
                                      │
                                      ▼ *
                          ┌────────────────────────┐       ┌───────────────────────┐
                          │   MovementStepRecord   │       │   TransactionRecord   │
                          ├────────────────────────┤       ├───────────────────────┤
                          │ step_id (PK)           │*     1│ id (PK)               │
                          │ transaction_id (FK)    │───────│ type (TRANSFER/CONV)  │
                          │ step_index             │       │ initiator_user_id     │
                          │ from_account_id        │       │ idempotency_key       │
                          │ to_account_id          │       │ status                │
                          │ currency               │       │ metadata              │
                          │ amount (Decimal)       │       │ timestamp             │
                          │ status                 │       └───────────────────────┘
                          │ timestamp              │
                          └────────────────────────┘
```

#### 1. `AccountRecord`
Every holder of value (whether a user or an internal system pool) is represented uniformly as an `AccountRecord`:
- `account_id` (str): Unique identifier format:
  - User accounts: `user:{user_id}:{currency}` (e.g. `user:usr_alice:USD`)
  - System Outbound Pool: `system:outbound_pool:{currency}`
  - System Inbound Pool: `system:inbound_pool:{currency}`
  - System FX Pool: `system:fx_pool:{currency}`
  - System Fee Pool: `system:fee_pool:{currency}`
- `owner_type` (str): `"USER"` or `"SYSTEM"`
- `owner_id` (str): `user_id` or `"system"`
- `currency` (str): 3-letter currency code (e.g. `USD`, `EUR`, `GBP`, `JPY`)
- `balance` (Decimal): Current monetary balance
- `allow_negative` (bool): `False` for `USER` accounts (strictly no overdraft); `True` for `SYSTEM` clearing pools.

#### 2. `MovementStepRecord`
Individual leg of a multi-step transaction:
- `step_id` (str): Unique UUID
- `transaction_id` (str): Parent transaction UUID
- `step_index` (int): 1-based sequential position within the transaction
- `from_account_id` (str): Debited account ID
- `to_account_id` (str): Credited account ID
- `currency` (str): Currency of transfer
- `amount` (Decimal): Positive quantity transferred
- `status` (str): `"COMPLETED"` | `"REVERSED"` | `"FAILED"`
- `timestamp` (datetime): Timestamp of execution

#### 3. `TransactionRecord`
High-level transaction header:
- `id` (str): Unique transaction UUID
- `type` (str): `"TRANSFER"` | `"CONVERSION"`
- `initiator_user_id` (str): User initiating the transaction
- `idempotency_key` (Optional[str]): Key provided by client
- `status` (str): `"COMPLETED"` | `"REVERSED"` | `"FAILED"`
- `metadata` (Dict[str, Any]): Audit context (amounts, rates, fee, counterparty, note)
- `steps` (List[MovementStepRecord]): Ordered list of movement steps executed
- `timestamp` (datetime): Creation timestamp

#### 4. `QuoteRecord`
Temporary conversion rate quote:
- `id` (str): Unique quote ID (e.g. `qte_...`)
- `user_id` (str): User who requested the quote
- `from_currency` (str): Source currency
- `to_currency` (str): Target currency
- `from_amount` (Decimal): Gross source amount to convert
- `to_amount` (Decimal): Net target amount received (after fee)
- `exchange_rate` (Decimal): Applied base exchange rate
- `fee_rate` (Decimal): Fee spread percentage (e.g. `0.005` = 0.5%)
- `fee_amount` (Decimal): Fee deducted in target currency
- `created_at` (datetime): Quote generation time
- `expires_at` (datetime): `created_at + 30 seconds`
- `status` (str): `"PENDING"` | `"ACCEPTED"` | `"EXPIRED"`

#### 5. `IdempotencyRecord`
- `idempotency_key` (str): Unique client key
- `operation` (str): `"ACCEPT_QUOTE"` | `"TRANSFER"`
- `request_hash` (str): SHA-256 hash of canonical request parameters
- `response_payload` (Dict[str, Any]): Cached serializable response body
- `status_code` (int): Cached HTTP status code (e.g. 200, 201)
- `created_at` (datetime): Timestamp of first completion

---

### 2.2 Initial Seed Data in `app/adapter/db.py`

#### Users
- `usr_alice`: "Alice Smith" (`alice@example.com`)
- `usr_bob`: "Bob Jones" (`bob@example.com`)
- `usr_charlie`: "Charlie Brown" (`charlie@example.com`)

#### User Balances
- `usr_alice`:
  - `user:usr_alice:USD`: `1000.00`
  - `user:usr_alice:EUR`: `500.00`
- `usr_bob`:
  - `user:usr_bob:EUR`: `750.00`
  - `user:usr_bob:GBP`: `250.00`
- `usr_charlie`:
  - `user:usr_charlie:JPY`: `100000.00`
  - `user:usr_charlie:USD`: `300.00`

#### System Clearing Accounts (Initialized with `balance = 0.00`, `allow_negative = True`)
- Outbound Pools: `system:outbound_pool:USD`, `EUR`, `GBP`, `JPY`
- Inbound Pools: `system:inbound_pool:USD`, `EUR`, `GBP`, `JPY`
- FX Pools: `system:fx_pool:USD`, `EUR`, `GBP`, `JPY`
- Fee Pools: `system:fee_pool:USD`, `EUR`, `GBP`, `JPY`

#### Exchange Rates Table
- `USD &harr; EUR`: `0.92` (USD &rarr; EUR), `1.087` (EUR &rarr; USD)
- `USD &harr; GBP`: `0.79` (USD &rarr; GBP), `1.266` (GBP &rarr; USD)
- `USD &harr; JPY`: `155.00` (USD &rarr; JPY), `0.00645` (JPY &rarr; USD)
- `EUR &harr; GBP`: `0.86` (EUR &rarr; GBP), `1.163` (GBP &rarr; EUR)
- `EUR &harr; JPY`: `168.00` (EUR &rarr; JPY), `0.00595` (JPY &rarr; EUR)
- `GBP &harr; JPY`: `195.00` (GBP &rarr; JPY), `0.00513` (JPY &rarr; GBP)

---

## 3. Multi-Step Money Movement & Rollback Logic

### 3.1 Money Movement Step Sequences

#### 1. Peer-to-Peer Transfer Flow ($X$ amount of currency from User A to User B)
```text
┌────────────────────────┐  Step 1: Amount X  ┌──────────────────────────────┐
│  user:usr_alice:{curr} │ ─────────────────> │ system:outbound_pool:{curr}  │
└────────────────────────┘                    └──────────────┬───────────────┘
                                                             │ Step 2: Amount X
                                                             ▼
┌────────────────────────┐  Step 3: Amount X  ┌──────────────────────────────┐
│   user:usr_bob:{curr}  │ <───────────────── │  system:inbound_pool:{curr}  │
└────────────────────────┘                    └──────────────────────────────┘
```
1. **Step 1**: Debit `user:{sender_id}:{curr}` $X$, Credit `system:outbound_pool:{curr}` $X$.
2. **Step 2**: Debit `system:outbound_pool:{curr}` $X$, Credit `system:inbound_pool:{curr}` $X$.
3. **Step 3**: Debit `system:inbound_pool:{curr}` $X$, Credit `user:{recipient_id}:{curr}` $X$.

#### 2. Quote Conversion Flow (Convert $X$ `USD` to $Y$ `EUR`, fee $F$ `EUR`, payout $P = Y - F$ `EUR`)
```text
┌────────────────────────┐  Step 1: Amount X USD  ┌────────────────────────┐
│  user:usr_alice:USD    │ ─────────────────────> │   system:fx_pool:USD   │
└────────────────────────┘                        └────────────────────────┘

┌────────────────────────┐  Step 2: Fee F EUR     ┌────────────────────────┐
│   system:fx_pool:EUR   │ ─────────────────────> │   system:fee_pool:EUR  │
└───────────┬────────────┘                        └────────────────────────┘
            │ Step 3: Payout P EUR
            ▼
┌────────────────────────┐
│   user:usr_alice:EUR   │
└────────────────────────┘
```
1. **Step 1**: Debit `user:{user_id}:{from_currency}` $X$, Credit `system:fx_pool:{from_currency}` $X$.
2. **Step 2**: Debit `system:fx_pool:{to_currency}` $F$, Credit `system:fee_pool:{to_currency}` $F$.
3. **Step 3**: Debit `system:fx_pool:{to_currency}` $P$, Credit `user:{user_id}:{to_currency}` $P$.

---

### 3.2 Midway Failure & Compensating Rollback Algorithm

During transaction execution, each step is executed and marked `COMPLETED`. If an unexpected exception occurs (e.g. balance check fails, simulated injected failure, or invariant breach):
1. Execution halts immediately.
2. A rollback routine traverses all steps executed so far for this transaction in **reverse order** ($S_k, S_{k-1}, \dots, S_1$).
3. For each completed step $S_i$:
   - Debit $S_i.\text{to\_account\_id}$ by $S_i.\text{amount}$.
   - Credit $S_i.\text{from\_account\_id}$ by $S_i.\text{amount}$.
   - Update $S_i.\text{status} = \text{"REVERSED"}$.
4. Update parent transaction status to `"FAILED"` or `"REVERSED"`.
5. Re-raise or return domain error without leaving dangling partial balances.

---

## 4. Fine-Grained Locking & Concurrency Control (`app/utils/locking.py`)

### 4.1 Locking Principles
- **Fine-Grained Isolation**: We never lock the entire database or entire wallet system. A transaction only locks the specific set of `account_id`s involved in its money movement steps.
- **Canonical Ordering (Deadlock-Free Guarantee)**:
  - When a transaction touches multiple accounts $\mathcal{A} = \{a_1, a_2, \dots, a_n\}$, the list is sorted lexicographically:
    $$\text{sorted\_accounts} = \text{sorted}(\text{list}(\text{set}(\mathcal{A})))$$
  - Locks are acquired in strict ascending order and released in reverse order.
  - Since all threads acquire locks in the exact same global total order, **deadlocks are mathematically impossible**.

### 4.2 Lock Manager Design
Implemented in `app/utils/locking.py`:
```python
class AccountLockManager:
    """Thread-safe fine-grained account lock manager."""
    def __init__(self):
        self._locks: Dict[str, threading.RLock] = {}
        self._registry_lock = threading.Lock()

    def get_lock(self, account_id: str) -> threading.RLock:
        with self._registry_lock:
            if account_id not in self._locks:
                self._locks[account_id] = threading.RLock()
            return self._locks[account_id]

    @contextmanager
    def acquire_account_locks(self, account_ids: Iterable[str]):
        """Acquire locks on specified account IDs in deterministic sorted order."""
        unique_sorted_ids = sorted(list(set(account_ids)))
        acquired_locks = []
        try:
            for acc_id in unique_sorted_ids:
                lock = self.get_lock(acc_id)
                lock.acquire()
                acquired_locks.append(lock)
            yield
        finally:
            for lock in reversed(acquired_locks):
                lock.release()
```

---

## 5. Idempotency Validation Design

### 5.1 Request Fingerprint & Cache Validation
When `Idempotency-Key` is passed on `POST /api/v1/quotes/<quote_id>/accept` or `POST /api/v1/transfers`:
1. Calculate canonical payload hash: $\text{hash} = \text{SHA256}(\text{canonical\_json}(\text{request\_body}))$.
2. Check `db.idempotency_store`:
   - If key exists:
     - Compare cached `request_hash` with incoming `hash`.
     - If matching: return cached `response_payload` with cached `status_code` immediately (zero balance mutation).
     - If mismatch: raise `IdempotencyConflictError` &rarr; returns `409 Conflict`.
3. If key does not exist:
   - Execute transaction under account locks.
   - Store `IdempotencyRecord` in DB upon success.
   - Return new response.

---

## 6. Layered Architecture & Contracts

### 6.1 Service Layer (`app/service/api.py`, `app/service/schema.py`)
- Unwraps HTTP requests, runs JSON Schema validation.
- Extracts `Idempotency-Key` header or payload property.
- Maps domain exceptions to HTTP status codes:
  - `ValidationError` &rarr; `400 Bad Request`
  - `ResourceNotFoundError` &rarr; `404 Not Found`
  - `IdempotencyConflictError` &rarr; `409 Conflict`
  - `InsufficientFundsError`, `QuoteExpiredError`, `QuoteAlreadyExecutedError` &rarr; `422 Unprocessable Entity`

### 6.2 Service &harr; Manager Contract (`app/manager/entities.py`)
Dataclasses exchanged between Service and Manager:
- `WalletBalanceResponseEntity`: `user_id: str`, `balances: Dict[str, float]`
- `QuoteRequestEntity`: `user_id: str`, `from_currency: str`, `to_currency: str`, `amount: float`
- `QuoteResponseEntity`: `quote_id: str`, `user_id: str`, `from_currency: str`, `to_currency: str`, `from_amount: float`, `to_amount: float`, `exchange_rate: float`, `fee_amount: float`, `fee_rate: float`, `created_at: str`, `expires_at: str`, `status: str`
- `AcceptQuoteRequestEntity`: `quote_id: str`, `user_id: Optional[str]`, `idempotency_key: Optional[str]`
- `AcceptQuoteResponseEntity`: `transaction_id: str`, `quote_id: str`, `user_id: str`, `from_currency: str`, `from_amount: float`, `to_currency: str`, `to_amount: float`, `fee_amount: float`, `status: str`, `timestamp: str`, `steps: List[Dict[str, Any]]`
- `TransferRequestEntity`: `sender_id: str`, `recipient_id: str`, `currency: str`, `amount: float`, `note: str`, `idempotency_key: Optional[str]`
- `TransferResponseEntity`: `transfer_id: str`, `sender_id: str`, `recipient_id: str`, `currency: str`, `amount: float`, `note: str`, `status: str`, `timestamp: str`, `steps: List[Dict[str, Any]]`
- `TransactionHistoryResponseEntity`: `user_id: str`, `transactions: List[Dict[str, Any]]`, `total: int`

### 6.3 Manager Layer (`app/manager/wallet_manager.py`)
Class `WalletManager`:
- Coordinates quote calculations, expiration (30 seconds), and fee deductions.
- Orchestrates multi-step transfers and conversions via the Adapter.
- Handles idempotency checks and exceptions.

### 6.4 Manager &harr; Adapter Contract (`app/adapter/entities.py`)
Dataclasses exchanged between Manager and Adapter:
- `AccountRecordEntity`: `account_id: str`, `owner_type: str`, `owner_id: str`, `currency: str`, `balance: Decimal`, `allow_negative: bool`
- `QuoteRecordEntity`: `id: str`, `user_id: str`, `from_currency: str`, `to_currency: str`, `from_amount: Decimal`, `to_amount: Decimal`, `rate: Decimal`, `fee_rate: Decimal`, `fee_amount: Decimal`, `created_at: datetime`, `expires_at: datetime`, `status: str`
- `MovementStepRecordEntity`: `step_id: str`, `transaction_id: str`, `step_index: int`, `from_account_id: str`, `to_account_id: str`, `currency: str`, `amount: Decimal`, `status: str`, `timestamp: datetime`
- `TransactionRecordEntity`: `id: str`, `type: str`, `initiator_user_id: str`, `idempotency_key: Optional[str]`, `status: str`, `metadata: Dict[str, Any]`, `steps: List[MovementStepRecordEntity]`, `timestamp: datetime`
- `IdempotencyRecordEntity`: `idempotency_key: str`, `operation: str`, `request_hash: str`, `response_payload: Dict[str, Any]`, `status_code: int`, `created_at: datetime`

### 6.5 Adapter Layer (`app/adapter/wallet_adapter.py`, `app/adapter/db.py`)
Class `WalletAdapter`:
- Executes atomic multi-step money movements under fine-grained locks.
- Performs step reversals on failure.
- Manages CRUD on users, balances, quotes, and transactions in `InMemoryDB`.

---

## 7. Test Plan (`tests/`)

Comprehensive test suite verifying the full stack:

1. **User Balances & Rates**:
   - `GET /api/v1/users` returns seed users (Alice, Bob, Charlie).
   - `GET /api/v1/users/usr_alice/balances` returns exact initial balances.
   - `GET /api/v1/rates` returns supported currency pairs and exchange rates.
2. **Quote Lifecycle**:
   - `POST /api/v1/quotes` creates a valid quote with 30s expiry.
   - `POST /api/v1/quotes/<quote_id>/accept` executes multi-step conversion, debits USD, credits EUR, deducts fee, records all 3 movement steps.
   - Attempting to accept expired quote (> 30s) returns `422 Unprocessable Entity`.
   - Attempting to accept already accepted quote returns `422 Unprocessable Entity`.
3. **P2P Transfers**:
   - `POST /api/v1/transfers` transfers EUR from Alice to Bob, updates balances, records 3 movement steps.
   - Transfer with insufficient balance returns `422 Unprocessable Entity` without balance changes.
4. **Multi-Step Rollback on Midway Failure**:
   - Simulate/trigger failure midway during a transaction.
   - Assert all prior steps are reversed and user/pool balances remain exactly identical to initial state.
5. **Idempotency**:
   - Repeating transfer or quote accept with same `Idempotency-Key` returns original cached result without repeated deductions.
   - Repeating with modified payload returns `409 Conflict`.
6. **Concurrent Isolation & Fine-Grained Locking**:
   - Concurrent independent transfers (e.g. Alice &rarr; Bob EUR while Charlie converts JPY) execute concurrently.
   - Concurrent transfers targeting the same account serialize properly without race conditions.
