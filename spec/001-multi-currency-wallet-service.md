# 001: Multi-Currency Wallet Service Specification

**Scope: Full Stack** (Service &rarr; Manager &rarr; Adapter)

---

## 1. Overview & Architecture Breakdown

### 1.1 Purpose
The **Multi-Currency Wallet Service** provides an in-memory, thread-safe, multi-currency financial ledger. It allows users to hold multi-currency accounts, query their balances and transaction history, obtain guaranteed 30-second foreign exchange (FX) quotes, execute conversions minus transaction fees, and transfer funds between users (P2P).

### 1.2 Core Architectural Principles & In-Memory LLD Design
1. **Layered Architecture**: Strict unidirectional flow:
   $$\text{Service (HTTP \& Schema Validation)} \longrightarrow \text{Manager (Business Logic \& Sagas)} \longrightarrow \text{Adapter (In-Memory Persistence \& Locking)}$$
2. **Domain-Driven Manager Organization**:
   - **`UserAccountManager`**: Manages user balances query and transaction history queries.
   - **`QuoteManager`**: Manages FX quote generation (30s TTL), rate lookups, and quote acceptance/conversion execution across FX pools.
   - **`TransferManager`**: Manages P2P transfers across settlement pools with compensation rollback on failure.
3. **Monetary Amounts as Minor Units (`long` / `int`)**:
   - All amounts (balances, transfer amounts, converted amounts, fees) are strictly represented as integers in **minor units** (e.g., USD/EUR in cents: `$10.50` &rarr; `1050`, JPY in units: `¥500` &rarr; `500`).
   - Floating-point representations for money are prohibited to prevent rounding drift.
4. **Multi-Hop Pool Balance Movements**:
   - **P2P Transfer Flow**:
     $$\text{User A Account} \xrightarrow{\text{Leg 1}} \text{Pool: Outbound} \xrightarrow{\text{Leg 2}} \text{Pool: Inbound} \xrightarrow{\text{Leg 3}} \text{User B Account}$$
   - **FX Conversion Flow**:
     $$\text{User (CCY A)} \xrightarrow{\text{Leg 1}} \text{Pool: FX Outbound (CCY A)} \xrightarrow{\text{Leg 2}} \text{Pool: FX Inbound (CCY B)} \xrightarrow{\text{Leg 3}} \text{User (CCY B)}$$
     *(With fee routed: $\text{Pool: FX Inbound (CCY B)} \xrightarrow{\text{Fee Leg}} \text{Pool: Fee Collection (CCY B)}$ or collected in CCY A)*
5. **Compensating Transactions (Saga / Reversal)**:
   - Balance movements are broken down into discrete ledger legs.
   - If any intermediate leg fails (e.g. recipient account not found, insufficient balance, concurrency collision, simulated failure injection), the manager executes reversing operations in reverse order (LIFO) to restore balances.
6. **Thread-Safe Concurrency & Deadlock Prevention**:
   - In-memory balances are protected using reentrant locks per account.
   - Cross-account transfers acquire locks in a globally deterministic order (e.g. sorted lexicographically by account ID) to prevent circular wait deadlocks.
7. **Idempotency**:
   - Mutating endpoints (`/transfers`, `/quotes/accept`) support an `Idempotency-Key` header.
   - Duplicate requests return cached responses without re-executing balance mutations.

---

## 2. Service Layer & API Specifications (`app/service/`)

All requests returning JSON have `Content-Type: application/json`. All monetary amounts are integers in minor units.

### 2.1 API 1: Create FX Quote
- **Route**: `POST /quotes`
- **Purpose**: Generates an FX conversion quote guaranteed for 30 seconds.

#### Request
- **Headers**: `Content-Type: application/json`
- **Schema** (`CREATE_QUOTE_SCHEMA`):
  ```json
  {
    "type": "object",
    "properties": {
      "user_id": { "type": "string", "minLength": 1 },
      "from_currency": { "type": "string", "minLength": 3, "maxLength": 3 },
      "to_currency": { "type": "string", "minLength": 3, "maxLength": 3 },
      "from_amount": { "type": "integer", "minimum": 1 }
    },
    "required": ["user_id", "from_currency", "to_currency", "from_amount"],
    "additionalProperties": false
  }
  ```
- **Example Request Body**:
  ```json
  {
    "user_id": "usr_alice",
    "from_currency": "USD",
    "to_currency": "EUR",
    "from_amount": 10000
  }
  ```

#### Response
- **Status `201 Created`**:
  ```json
  {
    "quote_id": "qt_9a8f7c6b12",
    "user_id": "usr_alice",
    "from_currency": "USD",
    "to_currency": "EUR",
    "from_amount": 10000,
    "exchange_rate": 0.92,
    "gross_to_amount": 9200,
    "fee_percentage": 0.01,
    "fee_amount": 92,
    "net_to_amount": 9108,
    "expires_at": "2026-10-03T02:30:30.123456Z",
    "validity_seconds": 30
  }
  ```
- **Status `400 Bad Request`**: Validation error (invalid currency, non-integer or $\le 0$ amount, missing fields).
  ```json
  {
    "error": "Validation error",
    "message": "'from_amount' must be an integer >= 1"
  }
  ```
- **Status `404 Not Found`**: Unsupported currency pair.
  ```json
  {
    "error": "Not Found",
    "message": "Exchange rate not available for pair USD/XYZ"
  }
  ```

---

### 2.2 API 2: Accept FX Quote
- **Route**: `POST /quotes/accept` (or `POST /quotes/<quote_id>/accept`)
- **Purpose**: Executes the conversion defined in the quote if within the 30s TTL. Deducts `from_amount` from user's `from_currency` balance and credits `net_to_amount` in `to_currency`.

#### Request
- **Headers**:
  - `Content-Type: application/json`
  - `Idempotency-Key: <string>` *(optional, recommended)*
- **Schema** (`ACCEPT_QUOTE_SCHEMA`):
  ```json
  {
    "type": "object",
    "properties": {
      "quote_id": { "type": "string", "minLength": 1 },
      "user_id": { "type": "string", "minLength": 1 }
    },
    "required": ["quote_id", "user_id"],
    "additionalProperties": false
  }
  ```
- **Example Request Body**:
  ```json
  {
    "quote_id": "qt_9a8f7c6b12",
    "user_id": "usr_alice"
  }
  ```

#### Response
- **Status `200 OK`**:
  ```json
  {
    "transaction_id": "tx_fx_44b910ca",
    "quote_id": "qt_9a8f7c6b12",
    "user_id": "usr_alice",
    "from_currency": "USD",
    "to_currency": "EUR",
    "debited_amount": 10000,
    "credited_amount": 9108,
    "fee_amount": 92,
    "fee_currency": "EUR",
    "status": "COMPLETED"
  }
  ```
- **Status `404 Not Found`**: Quote not found.
  ```json
  {
    "error": "Not Found",
    "message": "Quote 'qt_9a8f7c6b12' does not exist"
  }
  ```
- **Status `422 Unprocessable Entity`**: Quote expired or already accepted, or insufficient balance.
  ```json
  {
    "error": "Quote Expired",
    "message": "Quote qt_9a8f7c6b12 has expired (validity was 30 seconds)"
  }
  ```
  *or*:
  ```json
  {
    "error": "Insufficient Funds",
    "message": "User usr_alice has insufficient USD balance"
  }
  ```
- **Status `409 Conflict`**: Idempotency collision (request currently processing).
  ```json
  {
    "error": "Conflict",
    "message": "A request with this Idempotency-Key is currently processing"
  }
  ```

---

### 2.3 API 3: Peer-to-Peer (P2P) Transfer
- **Route**: `POST /transfers`
- **Purpose**: Moves money between two users in a specified currency via outbound and inbound settlement pools.

#### Request
- **Headers**:
  - `Content-Type: application/json`
  - `Idempotency-Key: <string>` *(optional, recommended)*
- **Schema** (`P2P_TRANSFER_SCHEMA`):
  ```json
  {
    "type": "object",
    "properties": {
      "sender_user_id": { "type": "string", "minLength": 1 },
      "recipient_user_id": { "type": "string", "minLength": 1 },
      "currency": { "type": "string", "minLength": 3, "maxLength": 3 },
      "amount": { "type": "integer", "minimum": 1 }
    },
    "required": ["sender_user_id", "recipient_user_id", "currency", "amount"],
    "additionalProperties": false
  }
  ```
- **Example Request Body**:
  ```json
  {
    "sender_user_id": "usr_alice",
    "recipient_user_id": "usr_bob",
    "currency": "USD",
    "amount": 2500
  }
  ```

#### Response
- **Status `200 OK`**:
  ```json
  {
    "transaction_id": "tx_p2p_887e32aa",
    "sender_user_id": "usr_alice",
    "recipient_user_id": "usr_bob",
    "currency": "USD",
    "amount": 2500,
    "status": "COMPLETED",
    "legs_executed": 3
  }
  ```
- **Status `400 Bad Request`**: Validation error or sender equals recipient.
  ```json
  {
    "error": "Validation error",
    "message": "Sender and recipient cannot be the same user"
  }
  ```
- **Status `404 Not Found`**: Sender or recipient user not found.
  ```json
  {
    "error": "Not Found",
    "message": "Recipient user usr_bob does not exist"
  }
  ```
- **Status `422 Unprocessable Entity`**: Insufficient funds or execution failure rolled back.
  ```json
  {
    "error": "Insufficient Funds",
    "message": "Sender usr_alice has insufficient USD balance"
  }
  ```
  *or if compensation was triggered*:
  ```json
  {
    "error": "Transfer Failed",
    "message": "Transfer failed at leg 3; reversing operations completed successfully",
    "status": "REVERSED"
  }
  ```

---

### 2.4 API 4: Get User Balances
- **Route**: `GET /users/<user_id>/balances`
- **Purpose**: Retrieves all held currency balances for a user (in minor units).

#### Request
- **Headers**: None
- **Query / Path Params**: `user_id` in path

#### Response
- **Status `200 OK`**:
  ```json
  {
    "user_id": "usr_alice",
    "balances": {
      "USD": 97500,
      "EUR": 59108,
      "GBP": 20000
    }
  }
  ```
- **Status `404 Not Found`**:
  ```json
  {
    "error": "Not Found",
    "message": "User usr_unknown does not exist"
  }
  ```

---

### 2.5 API 5: Get User Transaction History
- **Route**: `GET /users/<user_id>/transactions`
- **Purpose**: Returns the ledger transaction history for a user, including status and intermediate pool legs.

#### Request
- **Headers**: None
- **Query / Path Params**: `user_id` in path

#### Response
- **Status `200 OK`**:
  ```json
  {
    "user_id": "usr_alice",
    "transactions": [
      {
        "transaction_id": "tx_fx_44b910ca",
        "type": "FX_CONVERSION",
        "status": "COMPLETED",
        "created_at": "2026-10-03T02:30:15.100Z",
        "details": {
          "quote_id": "qt_9a8f7c6b12",
          "from_currency": "USD",
          "to_currency": "EUR",
          "debited_amount": 10000,
          "credited_amount": 9108,
          "fee_amount": 92
        },
        "legs": [
          {
            "leg_id": "leg_1",
            "step_number": 1,
            "from_account": "usr_alice:USD",
            "to_account": "pool:fx_outbound:USD",
            "currency": "USD",
            "amount": 10000,
            "status": "COMPLETED"
          },
          {
            "leg_id": "leg_2",
            "step_number": 2,
            "from_account": "pool:fx_outbound:USD",
            "to_account": "pool:fx_inbound:EUR",
            "currency": "EUR",
            "amount": 9200,
            "status": "COMPLETED"
          },
          {
            "leg_id": "leg_3",
            "step_number": 3,
            "from_account": "pool:fx_inbound:EUR",
            "to_account": "pool:fee:EUR",
            "currency": "EUR",
            "amount": 92,
            "status": "COMPLETED"
          },
          {
            "leg_id": "leg_4",
            "step_number": 4,
            "from_account": "pool:fx_inbound:EUR",
            "to_account": "usr_alice:EUR",
            "currency": "EUR",
            "amount": 9108,
            "status": "COMPLETED"
          }
        ]
      }
    ]
  }
  ```
- **Status `404 Not Found`**: User does not exist.

---

### 2.6 API 6: Get Exchange Rates
- **Route**: `GET /rates`
- **Purpose**: Returns available exchange rate pairs and current conversion fee rate.

#### Request
- **Headers**: None

#### Response
- **Status `200 OK`**:
  ```json
  {
    "rates": {
      "USD/EUR": 0.92,
      "EUR/USD": 1.087,
      "USD/GBP": 0.78,
      "GBP/USD": 1.282,
      "USD/JPY": 155.0,
      "JPY/USD": 0.00645,
      "EUR/GBP": 0.85,
      "GBP/EUR": 1.176
    },
    "fee_percentage": 0.01
  }
  ```

---

## 3. Service &harr; Manager Contract (`app/manager/entities.py`)

All amounts are typed as `int` (minor units).

```python
# app/manager/entities.py

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# --- Quote Entities ---

@dataclass
class CreateQuoteRequestEntity:
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int  # Minor units (e.g. cents)


@dataclass
class QuoteResponseEntity:
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int
    exchange_rate: float
    gross_to_amount: int
    fee_percentage: float
    fee_amount: int
    net_to_amount: int
    expires_at: str
    validity_seconds: int = 30

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptQuoteRequestEntity:
    quote_id: str
    user_id: str
    idempotency_key: Optional[str] = None


@dataclass
class AcceptQuoteResponseEntity:
    transaction_id: str
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    debited_amount: int
    credited_amount: int
    fee_amount: int
    fee_currency: str
    status: str  # COMPLETED | FAILED | REVERSED
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --- P2P Transfer Entities ---

@dataclass
class P2PTransferRequestEntity:
    sender_user_id: str
    recipient_user_id: str
    currency: str
    amount: int  # Minor units
    idempotency_key: Optional[str] = None


@dataclass
class P2PTransferResponseEntity:
    transaction_id: str
    sender_user_id: str
    recipient_user_id: str
    currency: str
    amount: int
    status: str  # COMPLETED | FAILED | REVERSED
    legs_executed: int
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --- User Balance & History Entities ---

@dataclass
class GetUserBalancesRequestEntity:
    user_id: str


@dataclass
class UserBalancesResponseEntity:
    user_id: str
    balances: Dict[str, int]  # Currency -> minor units

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GetTransactionHistoryRequestEntity:
    user_id: str


@dataclass
class TransactionLegViewEntity:
    leg_id: str
    step_number: int
    from_account: str
    to_account: str
    currency: str
    amount: int
    status: str


@dataclass
class TransactionHistoryItemEntity:
    transaction_id: str
    type: str  # P2P_TRANSFER | FX_CONVERSION
    status: str
    created_at: str
    details: Dict[str, Any]
    legs: List[TransactionLegViewEntity] = field(default_factory=list)


@dataclass
class TransactionHistoryResponseEntity:
    user_id: str
    transactions: List[TransactionHistoryItemEntity]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --- Exchange Rates Entities ---

@dataclass
class GetRatesRequestEntity:
    pass


@dataclass
class RatesResponseEntity:
    rates: Dict[str, float]
    fee_percentage: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

---

## 4. Manager Layer (`app/manager/`)

The Manager layer is structured into **3 domain managers**:
1. `UserAccountManager`: user balances & transaction history
2. `QuoteManager`: quote generation, rate queries, and quote acceptance/conversion
3. `TransferManager`: P2P money transfers across settlement pools

```text
app/manager/
├── entities.py
├── quote_manager.py           # Class: QuoteManager
├── transfer_manager.py        # Class: TransferManager
└── user_account_manager.py    # Class: UserAccountManager
```

---

### 4.1 `UserAccountManager` (`app/manager/user_account_manager.py`)
Responsible for reading and presenting account balance state and transaction histories.

```python
class UserAccountManager:
    """Manages user wallet balance queries and historical ledger reporting."""

    def __init__(self, wallet_adapter: Optional[WalletAdapter] = None) -> None:
        self.wallet_adapter = wallet_adapter or default_wallet_adapter

    def get_balances(self, request: GetUserBalancesRequestEntity) -> UserBalancesResponseEntity:
        """Retrieves all non-zero currency balances for a given user."""
        ...

    def get_transaction_history(self, request: GetTransactionHistoryRequestEntity) -> TransactionHistoryResponseEntity:
        """Retrieves all historical transactions and constituent legs for a given user."""
        ...
```

---

### 4.2 `QuoteManager` (`app/manager/quote_manager.py`)
Responsible for quoting exchange rates (with 30-second TTL) and executing cross-currency conversions through FX pools with compensation rollback.

```python
class QuoteManager:
    """Manages FX rate quotes, 30s TTL expiry, and cross-currency FX conversion execution."""

    def __init__(
        self,
        quote_adapter: Optional[QuoteAdapter] = None,
        wallet_adapter: Optional[WalletAdapter] = None,
    ) -> None:
        self.quote_adapter = quote_adapter or default_quote_adapter
        self.wallet_adapter = wallet_adapter or default_wallet_adapter

    def get_rates(self, request: GetRatesRequestEntity) -> RatesResponseEntity:
        """Returns all configured exchange rates and current fee percentage from QuoteAdapter."""
        ...

    def create_quote(self, request: CreateQuoteRequestEntity) -> QuoteResponseEntity:
        """
        Calculates converted amount and fees in minor units using rates from QuoteAdapter.
        Sets TTL to now + 30 seconds. Persists quote as PENDING in QuoteAdapter.
        """
        ...

    def accept_quote(self, request: AcceptQuoteRequestEntity) -> AcceptQuoteResponseEntity:
        """
        Accepts and executes an FX conversion:
        1. Check idempotency via wallet_adapter.
        2. Validate quote exists, belongs to user, is PENDING, and within 30s TTL via quote_adapter.
        3. Execute multi-hop pool sequence via wallet_adapter.execute_transfer_leg:
           - Leg 1: User(from_curr) -> Pool: FX Outbound(from_curr) [from_amount]
           - Leg 2: Pool: FX Outbound(from_curr) -> Pool: FX Inbound(to_curr) [gross_to_amount]
           - Leg 3: Pool: FX Inbound(to_curr) -> Pool: Fee(to_curr) [fee_amount]
           - Leg 4: Pool: FX Inbound(to_curr) -> User(to_curr) [net_to_amount]
        4. If any leg fails, perform LIFO compensation on all completed legs.
        5. Mark quote as ACCEPTED via quote_adapter and record transaction via wallet_adapter.
        """
        ...
```

---

### 4.3 `TransferManager` (`app/manager/transfer_manager.py`)
Responsible for orchestrating P2P transfers across settlement pools and executing reversing operations on failure.

```python
class TransferManager:
    """Manages P2P transfers via Outbound and Inbound pools with saga compensation."""

    def __init__(self, wallet_adapter: Optional[WalletAdapter] = None) -> None:
        self.wallet_adapter = wallet_adapter or default_wallet_adapter

    def transfer(self, request: P2PTransferRequestEntity) -> P2PTransferResponseEntity:
        """
        Executes a 3-hop P2P transfer:
        1. Check idempotency via wallet_adapter.
        2. Validate sender != recipient and both users exist via wallet_adapter.
        3. Multi-hop execution via wallet_adapter.execute_transfer_leg:
           - Leg 1: Sender(CCY) -> Pool: Outbound(CCY) [amount]
           - Leg 2: Pool: Outbound(CCY) -> Pool: Inbound(CCY) [amount]
           - Leg 3: Pool: Inbound(CCY) -> Recipient(CCY) [amount]
        4. If any leg fails (e.g. insufficient funds, recipient error, simulated fault):
           - Trigger LIFO compensation:
             - If Leg 2 succeeded: Inbound(CCY) -> Outbound(CCY)
             - If Leg 1 succeeded: Outbound(CCY) -> Sender(CCY)
           - Record status REVERSED and return 422.
        5. Mark transaction COMPLETED and cache idempotency result.
        """
        ...
```

---

## 5. Manager &harr; Adapter Contract (`app/adapter/entities.py`)

All amounts are stored in minor units as `int`.

```python
# app/adapter/entities.py

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class AccountRecordEntity:
    account_id: str          # e.g. "usr_alice:USD", "pool:outbound:USD"
    owner_id: str            # e.g. "usr_alice" or "system_pool"
    currency: str            # e.g. "USD"
    balance: int             # Minor units (e.g. 10000 = $100.00)
    is_pool: bool = False
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class QuoteRecordEntity:
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int         # Minor units
    exchange_rate: float
    gross_to_amount: int     # Minor units
    fee_percentage: float
    fee_amount: int          # Minor units
    net_to_amount: int       # Minor units
    expires_at: str          # ISO-8601 timestamp
    status: str              # PENDING | ACCEPTED | EXPIRED
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class LedgerLegRecordEntity:
    leg_id: str
    transaction_id: str
    step_number: int
    from_account_id: str
    to_account_id: str
    currency: str
    amount: int              # Minor units
    is_reversal: bool = False
    status: str = "COMPLETED"  # COMPLETED | FAILED
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class TransactionRecordEntity:
    transaction_id: str
    user_id: str
    transaction_type: str    # P2P_TRANSFER | FX_CONVERSION
    status: str              # COMPLETED | FAILED | REVERSED
    legs: List[LedgerLegRecordEntity] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class IdempotencyRecordEntity:
    idempotency_key: str
    status: str              # PROCESSING | COMPLETED
    response_code: int
    response_data: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
```

---

## 6. Adapter Layer (`app/adapter/`)

### 6.1 Domain-Split Adapters with Shared In-Memory Database Engine
The Adapter layer is organized into two domain-focused adapters backed by a centralized thread-safe in-memory database engine (`InMemoryDatabase` in `app/adapter/database.py`):

1. **`WalletAdapter` (`app/adapter/wallet_adapter.py`)**:
   - Manages user balances (`get_user_balances`, `user_exists`).
   - Executes **all money movement** (both P2P transfers and FX conversion legs across pools).
   - Enforces deadlock-free two-account lock acquisition in sorted lexicographical order.
   - Enforces non-negative balance constraints on user accounts.
   - Manages transaction audit logs (`record_transaction`, `get_user_transactions`).
   - Manages idempotency key reservation and response caching.

2. **`QuoteAdapter` (`app/adapter/quote_adapter.py`)**:
   - Manages FX quote lifecycle and persistence (`save_quote`, `get_quote`, `update_quote_status`).
   - Manages exchange rates table and queries (`get_rate`, `get_all_rates`, `get_fee_percentage`).

```text
┌─────────────────────────┐  ┌─────────────────────────────────┐  ┌─────────────────────────┐
│   UserAccountManager    │  │          QuoteManager           │  │     TransferManager     │
└────────────┬────────────┘  └────────┬───────────────────┬────┘  └────────────┬────────────┘
             │                        │                   │                    │
             │                        │ (quotes & rates)  │ (money movement)   │
             ▼                        ▼                   ▼                    ▼
┌─────────────────────────┐  ┌──────────────────┐  ┌────────────────────────────────────┐
│      WalletAdapter      │  │   QuoteAdapter   │  │           WalletAdapter            │
│ (balances & tx history) │  │  (quotes & rates)│  │ (money movement: P2P & FX pools)   │
└────────────┬────────────┘  └────────┬─────────┘  └───────────────────┬────────────────┘
             │                        │                                │
             └────────────────────────┼────────────────────────────────┘
                                      ▼
             ┌──────────────────────────────────────────────────┐
             │         InMemoryDatabase (app/adapter/database.py)│
             │                                                  │
             │  • accounts: Dict[str, AccountRecordEntity]      │
             │  • quotes: Dict[str, QuoteRecordEntity]          │
             │  • transactions: Dict[str, TransactionRecord]   │
             │  • idempotency: Dict[str, IdempotencyRecord]     │
             │  • rates: Dict[str, float]                       │
             │  • account_locks: Dict[str, threading.RLock]     │
             └──────────────────────────────────────────────────┘
```

---

### 6.2 Adapter Interfaces

#### `WalletAdapter` (`app/adapter/wallet_adapter.py`)
```python
class WalletAdapter:
    """Adapter handling user balances and all money movement (P2P and FX)."""

    def __init__(self, db: Optional[InMemoryDatabase] = None) -> None:
        self.db = db or default_db

    def user_exists(self, user_id: str) -> bool: ...
    def get_user_balances(self, user_id: str) -> Dict[str, int]: ...
    def get_account(self, account_id: str) -> Optional[AccountRecordEntity]: ...
    def get_or_create_account(self, owner_id: str, currency: str, is_pool: bool = False) -> AccountRecordEntity: ...
    def execute_transfer_leg(self, leg: LedgerLegRecordEntity) -> LedgerLegRecordEntity: ...
    def record_transaction(self, tx: TransactionRecordEntity) -> TransactionRecordEntity: ...
    def get_transaction(self, tx_id: str) -> Optional[TransactionRecordEntity]: ...
    def get_user_transactions(self, user_id: str) -> List[TransactionRecordEntity]: ...
    def check_or_reserve_idempotency(self, key: str) -> Optional[IdempotencyRecordEntity]: ...
    def save_idempotency_response(self, key: str, status_code: int, response_data: Dict[str, Any]) -> None: ...
```

#### `QuoteAdapter` (`app/adapter/quote_adapter.py`)
```python
class QuoteAdapter:
    """Adapter handling quote persistence, quote lifecycle, and exchange rates."""

    def __init__(self, db: Optional[InMemoryDatabase] = None) -> None:
        self.db = db or default_db

    def save_quote(self, quote: QuoteRecordEntity) -> QuoteRecordEntity: ...
    def get_quote(self, quote_id: str) -> Optional[QuoteRecordEntity]: ...
    def update_quote_status(self, quote_id: str, status: str) -> None: ...
    def get_rate(self, from_curr: str, to_curr: str) -> Optional[float]: ...
    def get_all_rates(self) -> Dict[str, float]: ...
    def get_fee_percentage(self) -> float: ...
```

---

### 6.3 Pre-Seeded Base State (in Minor Units)
The in-memory repository initializes with base seed state:
- **Users**:
  - `usr_alice`:
    - USD: `100000` ($1,000.00)
    - EUR: `50000` (€500.00)
    - GBP: `20000` (£200.00)
  - `usr_bob`:
    - USD: `50000` ($500.00)
    - EUR: `100000` (€1,000.00)
    - GBP: `10000` (£100.00)
  - `usr_charlie`:
    - USD: `25000` ($250.00)
    - EUR: `25000` (€250.00)
    - JPY: `5000000` (¥50,000)
- **Exchange Rates Table** (standard fee rate: 1.0%):
  - `USD/EUR`: 0.92, `EUR/USD`: 1.087
  - `USD/GBP`: 0.78, `GBP/USD`: 1.282
  - `USD/JPY`: 155.0, `JPY/USD`: 0.00645
  - `EUR/GBP`: 0.85, `GBP/EUR`: 1.176
- **System Settlement Pools** (initialized in repository):
  - `pool:outbound:<CCY>` (USD, EUR, GBP, JPY)
  - `pool:inbound:<CCY>` (USD, EUR, GBP, JPY)
  - `pool:fee:<CCY>` (USD, EUR, GBP, JPY)

---

## 7. Test Plan (`tests/`)

### 7.1 Single-Layer Unit Tests
- **Adapter Layer (`tests/test_adapters.py`)**:
  - Atomic balance transfer between accounts in minor units.
  - Non-negative balance constraint enforcement on user accounts.
  - Concurrency test: Multiple threads transferring simultaneously between accounts without deadlocks or corrupted balances.
- **Manager Layer (`tests/test_managers.py`)**:
  - `UserAccountManager`: Returns correct user balances and formats transaction leg histories.
  - `QuoteManager`:
    - Calculates gross, fee, and net amounts accurately in minor units.
    - Quote expiration test: Quotes older than 30s cannot be accepted.
    - FX conversion pool movement test (User &rarr; FX Outbound &rarr; FX Inbound &rarr; User + Fee).
    - Compensation test: Failure at target credit step triggers LIFO reversals and restores original funds.
  - `TransferManager`:
    - 3-hop transfer execution (User A &rarr; Outbound &rarr; Inbound &rarr; User B).
    - Intermediate failure triggers rollback of completed legs; sender balance restored.
- **Service Layer (`tests/test_api_schemas.py`)**:
  - Schema validation rejects floating point amounts (must be integer minor units).
  - Validation rejects missing `quote_id` on accept quote.
  - Validation rejects negative amounts and unsupported currency strings.

### 7.2 Integration Tests (`tests/test_wallet_integration.py`)
1. **End-to-End P2P Transfer**:
   - Alice sends 2500 USD cents ($25.00) to Bob.
   - Alice balance becomes 97500. Bob balance becomes 52500.
   - Settlement pools net to zero. 3 legs recorded with status `COMPLETED`.
2. **End-to-End FX Quote & Conversion**:
   - Alice requests quote: 10000 USD cents to EUR.
   - Quote expires in 30s. Alice accepts quote within 30s.
   - USD debited: 10000. EUR gross: 9200. Fee: 92 EUR. Net credited to Alice EUR: 9108.
   - Alice balances: USD 87500, EUR 59108. Fee pool: 92 EUR.
3. **Quote TTL Expiry (30 seconds)**:
   - Request quote, artificially advance clock by 31 seconds.
   - Attempt `POST /quotes/accept`. Assert HTTP 422, status `EXPIRED`, no balance deducted.
4. **Saga Failure Compensation**:
   - Trigger P2P transfer with simulated failure on leg 3 (Inbound &rarr; Recipient).
   - Verify compensating legs executed (Inbound &rarr; Outbound, Outbound &rarr; Alice).
   - Alice's USD balance remains unchanged. Transaction marked `REVERSED`.
5. **Idempotency Replay**:
   - Send `POST /transfers` with `Idempotency-Key: idemp-001`.
   - Send exact same request with same key.
   - Assert exact same response returned and Alice's balance is only debited once.
6. **Thread Concurrency Stress Test**:
   - Run 20 concurrent transfer requests across multiple threads to verify thread safety and absence of race conditions.
