# Specification 001: Multi-Currency Wallet Core Engine

**Scope**: `Scope: Full Stack` (Service Layer, Manager Layer, Adapter Layer, and E2E Tests)

---

## 1. Overview & Scope

### 1.1 Purpose
Build the foundational in-memory Multi-Currency Wallet platform supporting:
1. Multi-currency balance inspection per user.
2. Guaranteed 30-second foreign exchange quote generation with upfront fee transparency.
3. Timed quote acceptance, wallet debit/credit conversion, and audit logging.
4. Peer-to-peer (P2P) transfers in any supported currency with balance validation.
5. Full chronological transaction ledger tracking conversions and transfers.

### 1.2 Financial Precision & Units
> [!IMPORTANT]
> **Minor Units & Long/Integer Constraint**:
> All monetary values (balances, transfer amounts, quote amounts, and fees) are represented **strictly in currency minor units** (e.g. cents, pence) as **integers (`int`)**.
> 
> Examples:
> - `$100.00 USD` = `10000` (minor units)
> - `€50.00 EUR` = `5000` (minor units)
> - `£0.46 GBP fee` = `46` (minor units)
>
> Exchange rates are represented as decimal strings (e.g. `"0.9200"`), and calculations round immediately to the nearest integer minor unit.

### 1.3 Seed Data
The application starts with pre-configured in-memory seed data in minor units:
- **Currencies**: `USD`, `EUR`, `GBP`
- **Users & Balances** (Values in minor units as integers):
  - `user_1` (Alice): `{"USD": 100000, "EUR": 50000, "GBP": 10000}` ($1,000.00, €500.00, £100.00)
  - `user_2` (Bob): `{"USD": 25000, "EUR": 0, "GBP": 30000}` ($250.00, €0.00, £300.00)
  - `user_3` (Charlie): `{"USD": 5000, "EUR": 120000, "GBP": 5000}` ($50.00, €1,200.00, £50.00)
- **Exchange Rates** (Bidirectional matrix):
  - `USD -> EUR`: `0.9200` | `EUR -> USD`: `1.0870`
  - `USD -> GBP`: `0.7900` | `GBP -> USD`: `1.2660`
  - `EUR -> GBP`: `0.8600` | `GBP -> EUR`: `1.1630`
  - Same-currency rate: `1.0000`
- **Fee Configuration**:
  - `0.5%` (`0.005`) fee applied to gross target amount:
    $$\text{gross\_target} = \text{round}(\text{from\_amount} \times \text{rate})$$
    $$\text{fee\_amount} = \text{round}(\text{gross\_target} \times 0.005)$$
    $$\text{to\_amount} = \text{gross\_target} - \text{fee\_amount}$$

### 1.4 Write-Ahead Logging (WAL) & Double-Entry Transit Pools
> [!IMPORTANT]
> **WAL & Transit Accounting Invariant**:
> No in-memory user balance is ever mutated without first appending an immutable event to the Write-Ahead Log (`WalAdapter`). Furthermore, money in transit is never unbacked; it moves through dedicated internal system clearing accounts:
> - `SYSTEM_OUTBOUND_TRANSIT`: Escrows funds debited from a sender while routing.
> - `SYSTEM_INBOUND_TRANSIT`: Holds funds staged for settlement into the recipient's balance.
> - `SYSTEM_FEE_COLLECTOR`: Collects FX conversion fees.
>
> At every millisecond, the double-entry balance conservation equation holds:
> $$\sum \text{User Balances} + \sum \text{Transit Pools} + \sum \text{Fee Collector} = \text{Constant Total}$$

#### P2P Transfer Event Sequence:
1. `TRANSFER_INITIATED`: Log intent, validate sender balance.
2. `TRANSFER_SENDER_DEBITED`: Debit sender account $\rightarrow$ Credit `SYSTEM_OUTBOUND_TRANSIT`.
3. `TRANSFER_TRANSIT_ROUTED`: Debit `SYSTEM_OUTBOUND_TRANSIT` $\rightarrow$ Credit `SYSTEM_INBOUND_TRANSIT`.
4. `TRANSFER_RECIPIENT_CREDITED`: Debit `SYSTEM_INBOUND_TRANSIT` $\rightarrow$ Credit recipient account.
5. `TRANSFER_COMPLETED`: Finalize and record `TRANSFER_SENT` & `TRANSFER_RECEIVED` in audit ledger.

#### Quote Conversion Event Sequence:
1. `CONVERSION_INITIATED`: Log intent, validate quote status, expiry, and balance.
2. `CONVERSION_SOURCE_DEBITED`: Debit source currency from user $\rightarrow$ Credit `SYSTEM_OUTBOUND_TRANSIT`.
3. `CONVERSION_FX_SETTLED`: Swap source currency from `SYSTEM_OUTBOUND_TRANSIT`, allocate fee to `SYSTEM_FEE_COLLECTOR`, and credit net target currency to `SYSTEM_INBOUND_TRANSIT`.
4. `CONVERSION_TARGET_CREDITED`: Debit target currency from `SYSTEM_INBOUND_TRANSIT` $\rightarrow$ Credit user's target currency balance.
5. `CONVERSION_COMPLETED`: Mark quote `ACCEPTED` and record `CONVERSION` in audit ledger.

---

## 2. Service Layer (`app/service/`)

### 2.1 HTTP Routes & Endpoints

| Method | Path | Query / Body Params | Status Codes | Description |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/users/<user_id>/balances` | Path: `user_id` | `200`, `404` | Returns all minor-unit balances for user |
| `POST` | `/quotes` | JSON: `user_id`, `from_currency`, `to_currency`, `from_amount` | `201`, `400`, `404` | Creates 30s locked quote |
| `POST` | `/quotes/<quote_id>/accept` | Path: `quote_id`, JSON: `user_id` | `200`, `400`, `404` | Accepts quote, executes conversion |
| `POST` | `/transfers` | JSON: `from_user_id`, `to_user_id`, `currency`, `amount` | `200`, `400`, `404` | Executes P2P money transfer |
| `GET` | `/users/<user_id>/transactions` | Path: `user_id` | `200`, `404` | Returns transaction audit ledger |

### 2.2 JSON Schemas (`app/service/schema.py`)

```python
CREATE_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
        "from_currency": {"type": "string", "enum": ["USD", "EUR", "GBP"]},
        "to_currency": {"type": "string", "enum": ["USD", "EUR", "GBP"]},
        "from_amount": {
            "type": "integer",
            "minimum": 1
        }
    },
    "required": ["user_id", "from_currency", "to_currency", "from_amount"],
    "additionalProperties": False,
}

ACCEPT_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1}
    },
    "required": ["user_id"],
    "additionalProperties": False,
}

TRANSFER_SCHEMA = {
    "type": "object",
    "properties": {
        "from_user_id": {"type": "string", "minLength": 1},
        "to_user_id": {"type": "string", "minLength": 1},
        "currency": {"type": "string", "enum": ["USD", "EUR", "GBP"]},
        "amount": {
            "type": "integer",
            "minimum": 1
        }
    },
    "required": ["from_user_id", "to_user_id", "currency", "amount"],
    "additionalProperties": False,
}
```

### 2.3 Complete API Request & Response Specifications

#### 1. `GET /users/<user_id>/balances`
Retrieves real-time minor-unit balances for all currencies held by the user.

- **Request**:
  - Path Parameter: `user_id` (string, e.g. `user_1`)
- **Success Response (`200 OK`)**:
  ```json
  {
    "user_id": "user_1",
    "balances": {
      "USD": 100000,
      "EUR": 50000,
      "GBP": 10000
    }
  }
  ```
  *Fields:*
  - `user_id` (string): Unique identifier of the user.
  - `balances` (object): Map of ISO currency codes to integer balances in minor units (e.g. cents).
- **Error Responses**:
  - `404 Not Found` (User does not exist):
    ```json
    {
      "error": "USER_NOT_FOUND",
      "message": "User with ID 'unknown_user' does not exist"
    }
    ```

---

#### 2. `POST /quotes`
Requests a guaranteed exchange rate quote valid for 30 seconds, specifying conversion amounts and fee in minor units.

- **Request**:
  - Headers: `Content-Type: application/json`
  - Body:
    ```json
    {
      "user_id": "user_1",
      "from_currency": "USD",
      "to_currency": "EUR",
      "from_amount": 10000
    }
    ```
  *Fields:*
  - `user_id` (string, required): ID of requesting user.
  - `from_currency` (string, required): Source currency code (`USD`, `EUR`, `GBP`).
  - `to_currency` (string, required): Target currency code (`USD`, `EUR`, `GBP`). Must differ from `from_currency`.
  - `from_amount` (integer, required): Integer amount in minor units (> 0).
- **Success Response (`201 Created`)**:
  ```json
  {
    "quote_id": "quote_f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
    "user_id": "user_1",
    "from_currency": "USD",
    "to_currency": "EUR",
    "from_amount": 10000,
    "to_amount": 9154,
    "exchange_rate": "0.9200",
    "fee_amount": 46,
    "fee_percentage": "0.005",
    "created_at": "2026-10-02T11:00:00Z",
    "expires_at": "2026-10-02T11:00:30Z",
    "status": "PENDING"
  }
  ```
  *Fields:*
  - `quote_id` (string): Unique identifier for this guaranteed quote.
  - `user_id` (string): User identifier.
  - `from_currency` / `to_currency` (string): Currencies exchanged.
  - `from_amount` (integer): Input minor units in source currency (10000 = $100.00).
  - `to_amount` (integer): Net target minor units user will receive (`gross_target - fee_amount` = 9154 = €91.54).
  - `exchange_rate` (string): Applied rate (`"0.9200"`).
  - `fee_amount` (integer): Fee in target minor units (46 = €0.46).
  - `fee_percentage` (string): Fee rate applied (`"0.005"`).
  - `created_at` (string ISO8601): Quote creation timestamp.
  - `expires_at` (string ISO8601): Expiration time exactly 30 seconds after `created_at`.
  - `status` (string): Current quote state (`"PENDING"`).
- **Error Responses**:
  - `400 Bad Request` (Invalid input / Schema validation error):
    ```json
    {
      "error": "VALIDATION_ERROR",
      "message": "'from_amount' must be an integer >= 1"
    }
    ```
  - `400 Bad Request` (Identical currencies):
    ```json
    {
      "error": "IDENTICAL_CURRENCIES",
      "message": "Source and target currencies must be different"
    }
    ```
  - `400 Bad Request` (Invalid amount):
    ```json
    {
      "error": "INVALID_AMOUNT",
      "message": "Conversion amount must be an integer greater than zero"
    }
    ```
  - `404 Not Found` (User does not exist):
    ```json
    {
      "error": "USER_NOT_FOUND",
      "message": "User with ID 'unknown_user' does not exist"
    }
    ```

---

#### 3. `POST /quotes/<quote_id>/accept`
Accepts a pending quote within the 30-second window, debiting source currency and crediting target currency minus fee.

- **Request**:
  - Path Parameter: `quote_id` (string, e.g. `quote_f81d4fae-7dec-11d0-a765-00a0c91e6bf6`)
  - Body:
    ```json
    {
      "user_id": "user_1"
    }
    ```
- **Success Response (`200 OK`)**:
  ```json
  {
    "quote_id": "quote_f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
    "status": "ACCEPTED",
    "from_currency": "USD",
    "to_currency": "EUR",
    "from_amount": 10000,
    "to_amount": 9154,
    "fee_amount": 46,
    "executed_at": "2026-10-02T11:00:15Z",
    "balances": {
      "USD": 90000,
      "EUR": 59154,
      "GBP": 10000
    }
  }
  ```
  *Fields:*
  - `quote_id` (string): ID of accepted quote.
  - `status` (string): Updated quote state (`"ACCEPTED"`).
  - `from_currency` / `to_currency` (string): Currency pair.
  - `from_amount` / `to_amount` / `fee_amount` (integer): Financial amounts in minor units.
  - `executed_at` (string ISO8601): Execution timestamp.
  - `balances` (object): User's updated balance state in minor units across all currencies.
- **Error Responses**:
  - `400 Bad Request` (Quote expired):
    ```json
    {
      "error": "QUOTE_EXPIRED",
      "message": "Quote has expired (validity period was 30 seconds)"
    }
    ```
  - `400 Bad Request` (Quote already accepted):
    ```json
    {
      "error": "QUOTE_ALREADY_ACCEPTED",
      "message": "Quote has already been accepted"
    }
    ```
  - `400 Bad Request` (Quote ownership mismatch):
    ```json
    {
      "error": "QUOTE_OWNERSHIP_MISMATCH",
      "message": "User does not own this quote"
    }
    ```
  - `400 Bad Request` (Insufficient source balance):
    ```json
    {
      "error": "INSUFFICIENT_FUNDS",
      "message": "Insufficient USD balance: available 5000, required 10000"
    }
    ```
  - `404 Not Found` (Quote does not exist):
    ```json
    {
      "error": "QUOTE_NOT_FOUND",
      "message": "Quote with ID 'quote_xyz' not found"
    }
    ```

---

#### 4. `POST /transfers`
Executes a peer-to-peer balance transfer in a single currency between two users.

- **Request**:
  - Headers: `Content-Type: application/json`
  - Body:
    ```json
    {
      "from_user_id": "user_1",
      "to_user_id": "user_2",
      "currency": "USD",
      "amount": 5000
    }
    ```
  *Fields:*
  - `from_user_id` (string, required): Sender user ID.
  - `to_user_id` (string, required): Recipient user ID (must differ from `from_user_id`).
  - `currency` (string, required): Transfer currency (`USD`, `EUR`, `GBP`).
  - `amount` (integer, required): Minor unit amount to transfer (> 0).
- **Success Response (`200 OK`)**:
  ```json
  {
    "transfer_id": "tx_transfer_e3b0c442-98fc-1c14-9afb-4c8996fb9242",
    "from_user_id": "user_1",
    "to_user_id": "user_2",
    "currency": "USD",
    "amount": 5000,
    "timestamp": "2026-10-02T11:05:00Z",
    "from_user_balance": 95000
  }
  ```
  *Fields:*
  - `transfer_id` (string): Unique transaction identifier for the transfer.
  - `from_user_id` (string): Sender ID.
  - `to_user_id` (string): Recipient ID.
  - `currency` (string): Currency transferred.
  - `amount` (integer): Transferred minor units (5000 = $50.00).
  - `timestamp` (string ISO8601): Execution timestamp.
  - `from_user_balance` (integer): Remaining sender minor unit balance in the transferred currency.
- **Error Responses**:
  - `400 Bad Request` (Self transfer):
    ```json
    {
      "error": "SELF_TRANSFER_NOT_ALLOWED",
      "message": "Cannot transfer money to yourself"
    }
    ```
  - `400 Bad Request` (Insufficient funds):
    ```json
    {
      "error": "INSUFFICIENT_FUNDS",
      "message": "Insufficient USD balance: available 2500, required 5000"
    }
    ```
  - `400 Bad Request` (Invalid amount):
    ```json
    {
      "error": "INVALID_AMOUNT",
      "message": "Transfer amount must be an integer greater than zero"
    }
    ```
  - `404 Not Found` (Sender or Recipient does not exist):
    ```json
    {
      "error": "USER_NOT_FOUND",
      "message": "Recipient user 'user_99' not found"
    }
    ```

---

#### 5. `GET /users/<user_id>/transactions`
Retrieves chronological audit ledger history for a user (newest first).

- **Request**:
  - Path Parameter: `user_id` (string, e.g. `user_1`)
- **Success Response (`200 OK`)**:
  ```json
  {
    "user_id": "user_1",
    "transactions": [
      {
        "transaction_id": "tx_2222",
        "type": "TRANSFER_SENT",
        "currency": "USD",
        "amount": 5000,
        "fee_amount": 0,
        "related_user_id": "user_2",
        "from_currency": null,
        "to_currency": null,
        "from_amount": null,
        "to_amount": null,
        "quote_id": null,
        "timestamp": "2026-10-02T11:05:00Z",
        "description": "Transferred 5000 USD to user_2"
      },
      {
        "transaction_id": "tx_1111",
        "type": "CONVERSION",
        "currency": null,
        "amount": null,
        "fee_amount": 46,
        "related_user_id": null,
        "from_currency": "USD",
        "to_currency": "EUR",
        "from_amount": 10000,
        "to_amount": 9154,
        "quote_id": "quote_f81d4fae-7dec-11d0-a765-00a0c91e6bf6",
        "timestamp": "2026-10-02T11:00:15Z",
        "description": "Converted 10000 USD to 9154 EUR (Fee: 46 EUR)"
      }
    ]
  }
  ```
  *Fields:*
  - `user_id` (string): User ID whose history is requested.
  - `transactions` (array of objects): Chronological list of ledger events.
    - `transaction_id` (string): Unique transaction ID.
    - `type` (string): `"CONVERSION"`, `"TRANSFER_SENT"`, or `"TRANSFER_RECEIVED"`.
    - For Transfers: `currency`, `amount` (integer), `related_user_id` (counterparty).
    - For Conversions: `from_currency`, `to_currency`, `from_amount` (int), `to_amount` (int), `fee_amount` (int), `quote_id`.
    - `timestamp` (string ISO8601): Event timestamp.
    - `description` (string): Human-readable summary.
- **Error Responses**:
  - `404 Not Found` (User does not exist):
    ```json
    {
      "error": "USER_NOT_FOUND",
      "message": "User with ID 'unknown_user' does not exist"
    }
    ```

---

## 3. Service &harr; Manager Contract (`app/manager/entities.py`)

Dataclasses exchanged between the HTTP Service layer and Manager business logic:

```python
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

@dataclass
class GetBalancesRequestEntity:
    user_id: str

@dataclass
class GetBalancesResponseEntity:
    user_id: str
    balances: Dict[str, int]

    def to_dict(self):
        return asdict(self)

@dataclass
class CreateQuoteRequestEntity:
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int

@dataclass
class QuoteResponseEntity:
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int
    to_amount: int
    exchange_rate: str
    fee_amount: int
    fee_percentage: str
    created_at: str
    expires_at: str
    status: str

    def to_dict(self):
        return asdict(self)

@dataclass
class AcceptQuoteRequestEntity:
    quote_id: str
    user_id: str

@dataclass
class AcceptQuoteResponseEntity:
    quote_id: str
    status: str
    from_currency: str
    to_currency: str
    from_amount: int
    to_amount: int
    fee_amount: int
    executed_at: str
    balances: Dict[str, int]

    def to_dict(self):
        return asdict(self)

@dataclass
class TransferRequestEntity:
    from_user_id: str
    to_user_id: str
    currency: str
    amount: int

@dataclass
class TransferResponseEntity:
    transfer_id: str
    from_user_id: str
    to_user_id: str
    currency: str
    amount: int
    timestamp: str
    from_user_balance: int

    def to_dict(self):
        return asdict(self)

@dataclass
class TransactionItemEntity:
    transaction_id: str
    user_id: str
    type: str
    currency: Optional[str]
    from_currency: Optional[str]
    to_currency: Optional[str]
    from_amount: Optional[int]
    to_amount: Optional[int]
    amount: Optional[int]
    fee_amount: Optional[int]
    related_user_id: Optional[str]
    quote_id: Optional[str]
    timestamp: str
    description: str

@dataclass
class GetTransactionsRequestEntity:
    user_id: str

@dataclass
class GetTransactionsResponseEntity:
    user_id: str
    transactions: List[TransactionItemEntity]

    def to_dict(self):
        return asdict(self)
```

---

## 4. Manager Layer (`app/manager/`)

The business logic is organized into three domain managers coordinating state changes through Write-Ahead Log (WAL) events and resource-centric adapters:

1. **`AccountManager`** (`app/manager/account_manager.py`)
   - Injects: `UserWalletAdapter`, `TransactionAdapter`
   - Coordinates account reads, balance inquiries, and transaction ledger retrieval.
   - Methods:
     - `get_balances(request: GetBalancesRequestEntity) -> GetBalancesResponseEntity`: Validates user exists and returns current minor-unit balances.
     - `get_transactions(request: GetTransactionsRequestEntity) -> GetTransactionsResponseEntity`: Validates user exists and returns chronological ledger history (newest first).

2. **`QuoteManager`** (`app/manager/quote_manager.py`)
   - Injects: `ExchangeRateAdapter`, `QuoteAdapter`, `UserWalletAdapter`, `WalAdapter`, `TransactionAdapter`
   - Coordinates foreign exchange quotes and WAL-driven atomic conversion execution.
   - Methods:
     - `create_quote(request: CreateQuoteRequestEntity) -> QuoteResponseEntity`: Validates user and currency pair, calculates target amount and 0.5% fee in minor units, sets 30-second expiry window, and saves quote with `PENDING` status.
     - `accept_quote(request: AcceptQuoteRequestEntity) -> AcceptQuoteResponseEntity`: Orchestrates the multi-stage conversion pipeline:
       1. Publish WAL `CONVERSION_INITIATED`: Validates quote existence, ownership, `PENDING` state, `now <= expires_at`, and user source balance.
       2. Publish WAL `CONVERSION_SOURCE_DEBITED`: Calls `UserWalletAdapter.debit_to_outbound()` to escrow source currency.
       3. Publish WAL `CONVERSION_FX_SETTLED`: Calls `UserWalletAdapter.settle_fx_conversion()` to swap currencies and route fee to `SYSTEM_FEE_COLLECTOR`.
       4. Publish WAL `CONVERSION_TARGET_CREDITED`: Credits target currency to user's balance.
       5. Publish WAL `CONVERSION_COMPLETED`: Updates quote to `ACCEPTED` and logs `CONVERSION` in `TransactionAdapter`.

3. **`TransferManager`** (`app/manager/transfer_manager.py`)
   - Injects: `UserWalletAdapter`, `WalAdapter`, `TransactionAdapter`
   - Coordinates peer-to-peer money transfers via the multi-stage WAL clearing pipeline:
   - Methods:
     - `transfer(request: TransferRequestEntity) -> TransferResponseEntity`:
       1. Publish WAL `TRANSFER_INITIATED`: Validates sender != receiver, amount > 0, sender and receiver exist, sender balance $\ge$ amount.
       2. Publish WAL `TRANSFER_SENDER_DEBITED`: Calls `UserWalletAdapter.debit_to_outbound()` (debits sender, credits `SYSTEM_OUTBOUND_TRANSIT`).
       3. Publish WAL `TRANSFER_TRANSIT_ROUTED`: Calls `UserWalletAdapter.outbound_to_inbound()` (debits `SYSTEM_OUTBOUND_TRANSIT`, credits `SYSTEM_INBOUND_TRANSIT`).
       4. Publish WAL `TRANSFER_RECIPIENT_CREDITED`: Calls `UserWalletAdapter.inbound_to_recipient()` (debits `SYSTEM_INBOUND_TRANSIT`, credits recipient).
       5. Publish WAL `TRANSFER_COMPLETED`: Records `TRANSFER_SENT` for sender and `TRANSFER_RECEIVED` for recipient in `TransactionAdapter`.

---

## 5. Manager &harr; Adapter Contract (`app/adapter/entities.py`)

Dataclasses defining storage models and data exchange between Manager and Adapter:

```python
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

@dataclass
class UserRecordEntity:
    user_id: str
    name: str
    balances: Dict[str, int]

@dataclass
class ExchangeRateRecordEntity:
    from_currency: str
    to_currency: str
    rate: str

@dataclass
class QuoteRecordEntity:
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int
    to_amount: int
    exchange_rate: str
    fee_amount: int
    fee_percentage: str
    created_at: str
    expires_at: str
    status: str  # PENDING, ACCEPTED, EXPIRED

@dataclass
class TransactionRecordEntity:
    transaction_id: str
    user_id: str
    type: str  # CONVERSION, TRANSFER_SENT, TRANSFER_RECEIVED
    currency: Optional[str]
    from_currency: Optional[str]
    to_currency: Optional[str]
    from_amount: Optional[int]
    to_amount: Optional[int]
    amount: Optional[int]
    fee_amount: Optional[int]
    related_user_id: Optional[str]
    quote_id: Optional[str]
    timestamp: str
    description: str

    def to_dict(self):
        return asdict(self)

@dataclass
class WALEntryEntity:
    wal_id: int
    correlation_id: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: str

    def to_dict(self):
        return asdict(self)
```

---

## 6. Adapter Layer (`app/adapter/`)

The persistence layer is structured around resource-centric adapters with exclusive data structure ownership:

- **1. `UserWalletAdapter` (`app/adapter/user_wallet_adapter.py`)**:
  - Owns:
    - `self._users: Dict[str, UserRecordEntity]`
    - `self._outbound_transit: Dict[str, int]` (System outbound clearing pool)
    - `self._inbound_transit: Dict[str, int]` (System inbound clearing pool)
    - `self._fee_collector: Dict[str, int]` (System collected fees)
  - Methods:
    - `get_user(user_id: str) -> Optional[UserRecordEntity]`
    - `user_exists(user_id: str) -> bool`
    - `debit_to_outbound(user_id: str, currency: str, amount: int) -> int`
    - `outbound_to_inbound(currency: str, amount: int) -> None`
    - `inbound_to_recipient(user_id: str, currency: str, amount: int) -> int`
    - `settle_fx_conversion(user_id: str, from_curr: str, to_curr: str, from_amount: int, to_amount: int, fee_amount: int) -> Dict[str, int]`
    - `get_transit_pool_balances() -> Dict[str, Dict[str, int]]` (for audit verification)

- **2. `QuoteAdapter` (`app/adapter/quote_adapter.py`)**:
  - Owns: `self._quotes: Dict[str, QuoteRecordEntity]`
  - Methods:
    - `save_quote(quote: QuoteRecordEntity) -> QuoteRecordEntity`
    - `get_quote(quote_id: str) -> Optional[QuoteRecordEntity]`
    - `update_status(quote_id: str, status: str) -> Optional[QuoteRecordEntity]`

- **3. `TransactionAdapter` (`app/adapter/transaction_adapter.py`)**:
  - Owns: `self._ledger: List[TransactionRecordEntity]`
  - Methods:
    - `record(transaction: TransactionRecordEntity) -> TransactionRecordEntity`
    - `get_by_user(user_id: str) -> List[TransactionRecordEntity]`

- **4. `ExchangeRateAdapter` (`app/adapter/exchange_rate_adapter.py`)**:
  - Owns: `self._rates: Dict[Tuple[str, str], str]`
  - Methods:
    - `get_rate(from_curr: str, to_curr: str) -> Optional[str]`

- **5. `WalAdapter` (`app/adapter/wal_adapter.py`)**:
  - Owns: `self._log: List[WALEntryEntity]`
  - Methods:
    - `append(correlation_id: str, event_type: str, payload: Dict[str, Any]) -> WALEntryEntity`
    - `get_by_correlation_id(correlation_id: str) -> List[WALEntryEntity]`
    - `get_all_events() -> List[WALEntryEntity]`

---

## 7. Test Plan (`tests/`)

E2E and unit test coverage in `tests/test_wallet_api.py`:
1. **Balances**:
   - Query existing user balances (`user_1` returns `{"USD": 100000, "EUR": 50000, "GBP": 10000}`).
   - Query non-existent user returns 404.
2. **Quote Generation**:
   - Request quote for valid currencies (`from_amount`: `10000` USD -> EUR). Returns 201 with `to_amount`: `9154`, `fee_amount`: `46`, and 30s expiration.
   - Non-integer or <= 0 amount returns 400.
   - Unsupported currency returns 400.
3. **Quote Acceptance & Conversion**:
   - Accept within 30s -> deducts `10000` from source balance, adds `9154` to target balance, records transaction with `fee_amount: 46`.
   - Accept expired quote (> 30s) -> rejected with 400 Expired.
   - Accept with insufficient balance -> rejected with 400 Insufficient Funds.
   - Double accept attempt -> rejected with 400 (already accepted).
4. **P2P Transfer**:
   - Transfer `5000` USD from `user_1` to `user_2` -> deducts 5000 from sender, credits 5000 to receiver, records sent/received transactions.
   - Transfer with insufficient balance -> 400.
   - Transfer to self -> 400.
   - Transfer to unknown user -> 404.
5. **Transaction Ledger**:
   - Verify all conversion and transfer transactions reflect integer amounts in `GET /users/<user_id>/transactions`.
6. **Write-Ahead Log (WAL) & Transit Pools Verification**:
   - Verify full 5-stage WAL events emitted on transfer (`TRANSFER_INITIATED`, `TRANSFER_SENDER_DEBITED`, `TRANSFER_TRANSIT_ROUTED`, `TRANSFER_RECIPIENT_CREDITED`, `TRANSFER_COMPLETED`).
   - Verify full 5-stage WAL events emitted on quote conversion (`CONVERSION_INITIATED`, `CONVERSION_SOURCE_DEBITED`, `CONVERSION_FX_SETTLED`, `CONVERSION_TARGET_CREDITED`, `CONVERSION_COMPLETED`).
   - Verify zero-drift: All transit clearing pools (`SYSTEM_OUTBOUND_TRANSIT`, `SYSTEM_INBOUND_TRANSIT`) return to `0` after completed transfers and conversions.

