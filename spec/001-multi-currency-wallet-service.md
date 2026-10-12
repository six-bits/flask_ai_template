# 001: Multi-Currency Wallet Service Specification

## 1. Overview & Scope

**Declared Scope: Service Layer Only (Route Stubs & Schema Validation)**  
*Deferred to Subsequent Phases: Manager business logic and Adapter in-memory persistence.*

> [!NOTE]
> **Variation in Subsequent Specifications**:
> The Manager layer and Adapter layer structures, entity contracts, and persistence models specified in this document are initial blueprints for the overall system. The concrete implementation details, contracts, and partitioning of both the Manager layer and Adapter layer might vary in following specifications.

### 1.1 Problem Summary & Breakdown
We are building a multi-currency digital wallet service where:
- Each user holds non-negative balances across multiple currencies.
- Users can request currency conversion quotes valid for 30 seconds.
- Upon timely acceptance (within 30 seconds), conversions execute at the quoted rate minus a fee.
- Users can transfer funds to other users peer-to-peer (P2P) in any currency they hold.
- Users can view their balances across all currencies and their chronological transaction history.
- The system is initialized with seed users, balances, and an exchange rate table.

### 1.2 Architectural Breakdown
```text
┌────────────────────────────────────────────────────────┐
│                     Service Layer                      │  HTTP Routes, Query Params, JSON Schema Validation
│                  app/service/api.py                    │  (Phase 1: Stubbed routes raising NotImplementedError / 501)
│                 app/service/schema.py                  │
└───────────────────────────┬────────────────────────────┘
                            │  Contract: Entities in app/manager/entities.py
                            ▼
┌────────────────────────────────────────────────────────┐
│                     Manager Layer                      │  WalletManager:
│            app/manager/wallet_manager.py               │  - Quote generation & 30s TTL expiry checks
│                                                        │  - Fee deduction calculation
│                                                        │  - Balance sufficiency & transfer orchestration
└───────────────────────────┬────────────────────────────┘
                            │  Contract: Entities in app/adapter/entities.py
                            ▼
┌────────────────────────────────────────────────────────┐
│                     Adapter Layer                      │  WalletAdapter:
│            app/adapter/wallet_adapter.py               │  - In-memory atomic balance stores
│                                                        │  - Quote cache & transaction history ledger
│                                                        │  - Initial seed data (users, balances, rates)
└────────────────────────────────────────────────────────┘
```

---

## 2. Service Layer (`app/service/`) — IN SCOPE

### 2.1 HTTP Route Endpoints

| Method | Path | Description | Request Body / Params | Status Codes |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/health` | Service health check | None | `200 OK` |
| `POST` | `/hello` | Template greeting endpoint | `GREETING_SCHEMA` | `200 OK`, `400 Bad Request` |
| `GET` | `/api/v1/rates` | View exchange rate table | Query: optional `from_currency`, `to_currency` | `501 Not Implemented` (for now) |
| `GET` | `/api/v1/users` | List seed users | None | `501 Not Implemented` (for now) |
| `GET` | `/api/v1/users/<user_id>/balances` | Get all currency balances for a user | Path: `user_id` (str) | `501 Not Implemented` (for now) |
| `POST` | `/api/v1/quotes` | Request 30s conversion quote | Body: `QUOTE_REQUEST_SCHEMA` | `501 Not Implemented` (for now), `400 Bad Request` |
| `POST` | `/api/v1/quotes/<quote_id>/accept` | Accept and execute quote | Path: `quote_id` (str), Header: `Idempotency-Key` (optional), Body: `QUOTE_ACCEPT_SCHEMA` | `501 Not Implemented` (for now), `400 Bad Request` |
| `POST` | `/api/v1/transfers` | Transfer money to another user | Header: `Idempotency-Key` (optional), Body: `TRANSFER_REQUEST_SCHEMA` | `501 Not Implemented` (for now), `400 Bad Request` |
| `GET` | `/api/v1/users/<user_id>/transactions` | View user's transaction history | Path: `user_id` (str), Query: `limit`, `offset` | `501 Not Implemented` (for now) |

### 2.2 Error Handling Specification
- `ValidationError`: Caught by `@app.errorhandler(ValidationError)` and formatted as:
  ```json
  {
    "error": "Validation error",
    "message": "<schema failure detail>"
  }
  ```
  Status: `400 Bad Request`.
- `NotImplementedError`: Caught by `@app.errorhandler(NotImplementedError)` and formatted as:
  ```json
  {
    "error": "Not implemented",
    "message": "<endpoint name> is not implemented yet"
  }
  ```
  Status: `501 Not Implemented`.

### 2.3 JSON Schema Definitions (`app/service/schema.py`)

#### 1. Quote Request Schema (`QUOTE_REQUEST_SCHEMA`)
```python
QUOTE_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
        "from_currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "to_currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "amount": {"type": "number", "exclusiveMinimum": 0},
    },
    "required": ["user_id", "from_currency", "to_currency", "amount"],
    "additionalProperties": False,
}
```

#### 2. Quote Acceptance Schema (`QUOTE_ACCEPT_SCHEMA`)
```python
QUOTE_ACCEPT_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    "additionalProperties": False,
}
```

#### 3. Transfer Request Schema (`TRANSFER_REQUEST_SCHEMA`)
```python
TRANSFER_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "sender_id": {"type": "string", "minLength": 1},
        "recipient_id": {"type": "string", "minLength": 1},
        "currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "amount": {"type": "number", "exclusiveMinimum": 0},
        "note": {"type": "string", "maxLength": 255},
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    "required": ["sender_id", "recipient_id", "currency", "amount"],
    "additionalProperties": False,
}
```

---

## 3. Service &harr; Manager Contract (`app/manager/entities.py`) — SPECIFIED (DEFERRED IMPLEMENTATION)

Dataclasses defining contracts between the Service and Manager layers:

```python
@dataclass
class WalletBalanceResponseEntity:
    user_id: str
    balances: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuoteRequestEntity:
    user_id: str
    from_currency: str
    to_currency: str
    amount: float


@dataclass
class QuoteResponseEntity:
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: float
    to_amount: float
    exchange_rate: float
    fee_amount: float
    fee_rate: float
    created_at: str
    expires_at: str
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptQuoteRequestEntity:
    quote_id: str
    user_id: Optional[str] = None
    idempotency_key: Optional[str] = None


@dataclass
class AcceptQuoteResponseEntity:
    transaction_id: str
    quote_id: str
    user_id: str
    from_currency: str
    from_amount: float
    to_currency: str
    to_amount: float
    fee_amount: float
    status: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransferRequestEntity:
    sender_id: str
    recipient_id: str
    currency: str
    amount: float
    note: str = ""
    idempotency_key: Optional[str] = None


@dataclass
class TransferResponseEntity:
    transfer_id: str
    sender_id: str
    recipient_id: str
    currency: str
    amount: float
    note: str
    status: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransactionHistoryResponseEntity:
    user_id: str
    transactions: List[Dict[str, Any]]
    total: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

---

## 4. Manager Layer (`app/manager/`) — SPECIFIED (DEFERRED IMPLEMENTATION)

Grouped into a single manager: `WalletManager` in `app/manager/wallet_manager.py`.

### Responsibilities:
1. **Quote Lifecycle Management**:
   - Computes conversion using rate matrix: `base_converted = from_amount * exchange_rate`.
   - Computes fee (e.g. standard spread fee `fee_rate = 0.005` or 0.5%): `fee_amount = base_converted * fee_rate`.
   - Calculates net payout: `to_amount = base_converted - fee_amount`.
   - Assigns 30-second TTL: `expires_at = now + 30 seconds`.
   - Quote status tracking: `PENDING` &rarr; `ACCEPTED` or `EXPIRED`.
2. **Quote Acceptance**:
   - Enforces `now <= expires_at`.
   - Enforces atomic balance verification: sender has balance >= `from_amount`.
   - Debits `from_currency`, credits `to_currency`.
   - Records completed transaction.
3. **P2P Transfer Logic**:
   - Enforces `sender_id != recipient_id`.
   - Enforces sender has balance >= `amount`.
   - Atomically debits sender and credits recipient.
   - Records transfer transactions for both parties.
4. **Idempotency Coordination**:
   - Inspects `idempotency_key` on quote acceptances and transfers.
   - If an operation with this key was already successfully completed, retrieves the existing result and returns it without repeating side-effects (debiting/crediting).
5. **Balances & History**:
   - Aggregates user balances and lists chronological transactions.

---

## 5. Manager &harr; Adapter Contract (`app/adapter/entities.py`) — SPECIFIED (DEFERRED IMPLEMENTATION)

Dataclasses defining persistence records between Manager and Adapter layers:

```python
@dataclass
class UserRecordEntity:
    id: str
    name: str
    email: str


@dataclass
class BalanceRecordEntity:
    user_id: str
    currency: str
    amount: Decimal


@dataclass
class ExchangeRateRecordEntity:
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass
class QuoteRecordEntity:
    id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: Decimal
    to_amount: Decimal
    exchange_rate: Decimal
    fee_rate: Decimal
    fee_amount: Decimal
    created_at: datetime
    expires_at: datetime
    status: str  # "PENDING", "ACCEPTED", "EXPIRED"


@dataclass
class TransactionRecordEntity:
    id: str
    user_id: str
    type: str  # "CONVERSION", "TRANSFER_SENT", "TRANSFER_RECEIVED"
    from_currency: Optional[str]
    from_amount: Optional[Decimal]
    to_currency: Optional[str]
    to_amount: Optional[Decimal]
    fee_amount: Decimal
    counterparty_id: Optional[str]
    note: Optional[str]
    timestamp: datetime
    status: str
    idempotency_key: Optional[str] = None
```

---

## 6. Adapter Layer (`app/adapter/`) — SPECIFIED (DEFERRED IMPLEMENTATION)

Grouped into a single adapter: `WalletAdapter` in `app/adapter/wallet_adapter.py`.

### Storage Structures:
- `users`: User storage indexed by `user_id`.
- `balances`: Balance storage mapping `(user_id, currency) -> Decimal`.
- `rates`: Exchange rate storage mapping `(from_currency, to_currency) -> Decimal`.
- `quotes`: Quote cache mapping `quote_id -> QuoteRecordEntity`.
- `transactions`: Chronological ledger of transactions.
- `idempotency_store`: Cache mapping `idempotency_key -> TransactionRecordEntity` to guarantee idempotent execution.

### Initial Seed Data:
- **Users**:
  - `usr_alice`: "Alice Smith"
  - `usr_bob`: "Bob Jones"
  - `usr_charlie`: "Charlie Brown"
- **Balances**:
  - `usr_alice`: `USD: 1000.00`, `EUR: 500.00`
  - `usr_bob`: `EUR: 750.00`, `GBP: 250.00`
  - `usr_charlie`: `JPY: 100000.00`, `USD: 300.00`
- **Exchange Rates Matrix**:
  - `USD -> EUR`: `0.92`, `EUR -> USD`: `1.087`
  - `USD -> GBP`: `0.79`, `GBP -> USD`: `1.266`
  - `USD -> JPY`: `155.00`, `JPY -> USD`: `0.00645`
  - `EUR -> GBP`: `0.86`, `GBP -> EUR`: `1.163`
  - `EUR -> JPY`: `168.00`, `JPY -> EUR`: `0.00595`
  - `GBP -> JPY`: `195.00`, `JPY -> GBP`: `0.00513`

---

## 7. Test Plan (`tests/`)

For the current scope (**Service Layer Only — Route Stubs & Schema Validation**):
1. **Existing Regression Tests**:
   - Verify `/health` continues to return 200 OK.
   - Verify `/hello` continues to validate payloads and return 200 OK.
2. **Schema Validation Tests**:
   - `POST /api/v1/quotes` rejects invalid bodies (missing `user_id`, non-positive `amount`, bad currency code) with `400 Bad Request`.
   - `POST /api/v1/quotes/<quote_id>/accept` rejects invalid body attributes with `400 Bad Request`.
   - `POST /api/v1/quotes/<quote_id>/accept` accepts valid optional `idempotency_key` (via body or `Idempotency-Key` header).
   - `POST /api/v1/transfers` rejects invalid bodies (missing `recipient_id`, negative `amount`, extra properties) with `400 Bad Request`.
   - `POST /api/v1/transfers` accepts valid optional `idempotency_key` (via body or `Idempotency-Key` header).
3. **NotImplemented / Stub Route Tests**:
   - `GET /api/v1/rates` returns `501 Not Implemented`.
   - `GET /api/v1/users` returns `501 Not Implemented`.
   - `GET /api/v1/users/usr_alice/balances` returns `501 Not Implemented`.
   - `POST /api/v1/quotes` with valid schema raises `NotImplementedError` / returns `501 Not Implemented`.
   - `POST /api/v1/quotes/qte_1/accept` with valid schema returns `501 Not Implemented`.
   - `POST /api/v1/transfers` with valid schema returns `501 Not Implemented`.
   - `GET /api/v1/users/usr_alice/transactions` returns `501 Not Implemented`.
4. **Postman Collection**:
   - `postman_collection.json` configured with all wallet endpoints, collection variables (`baseUrl`, `userId`, `recipientId`, `quoteId`), and test scripts for automated development verification.

