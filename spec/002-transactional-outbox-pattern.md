# Specification 002: Transactional Outbox Pattern via Entity-Attached Domain Events

**Scope**: `Scope: Full Stack` (Service Layer, Manager Layer, Adapter Layer, and Test Suite)

---

## 1. Overview & Scope

### 1.1 The Dual-Write Problem
In decoupled event publishing (such as writing to a separate `WalAdapter` before or after executing a state change), a failure during state mutation produces an unrecoverable inconsistency:
$$\text{Event Published} \longrightarrow \text{DB / In-Memory Mutation Fails} \Longrightarrow \textbf{Phantom Event!}$$
Conversely, mutating state before publishing risks losing the event if the server terminates before logging occurs.

### 1.2 The Solution: Entity-Attached Domain Events & State Machines
Every financial operation is modeled as a **state machine where transitions attach events directly to the specific participating entities**:
1. **Transfers (3 Hops)**:
   - **Hop 1 (Sender $\rightarrow$ Outbound Pool)**: Debit sender, credit outbound pool. Event `TRANSFER_OUTBOUND_COMMITTED` lives in **Sender's record** (`UserRecordEntity`).
   - **Hop 2 (Outbound Pool $\rightarrow$ Inbound Pool)**: Transit hop between system pools. Event `TRANSIT_POOL_CLEARED` lives in **Outbound Pool record** (`PoolRecordEntity`).
   - **Hop 3 (Inbound Pool $\rightarrow$ Recipient)**: Debit inbound pool, credit recipient. Event `TRANSFER_INBOUND_SETTLED` lives in **Recipient's record** (`UserRecordEntity`).
2. **Quotes & Conversions (Matching Hops)**:
   - **Quote Creation**: Event `QUOTE_CREATED` lives in **Quote record** (`QuoteRecordEntity`).
   - **Hop 1 (User $\rightarrow$ Outbound Pool)**: Debit user source currency, credit outbound pool. Event `CONVERSION_OUTBOUND_COMMITTED` lives in **User's record** (`UserRecordEntity`).
   - **Hop 2 (Outbound Pool $\rightarrow$ Inbound Pool & Fee Pool)**: Outbound source swapped, fee allocated to fee pool, net target staged in inbound pool. Event `CONVERSION_FX_CLEARED` lives in **Outbound Pool record** (`PoolRecordEntity`).
   - **Hop 3 (Inbound Pool $\rightarrow$ User Target Currency)**: Debit inbound pool, credit user target currency. Event `CONVERSION_INBOUND_SETTLED` lives in **User's record** (`UserRecordEntity`).
   - **Quote Acceptance**: Status updated to `ACCEPTED`. Event `QUOTE_ACCEPTED` lives in **Quote record** (`QuoteRecordEntity`).
3. **Outbox Scraper Manager**: An `OutboxManager` queries the entities across adapters, gathers their attached events, presents them as a unified chronological audit log, and acknowledges them when polled.

---

## 2. Service Layer (`app/service/`)

### 2.1 HTTP Routes & Endpoints

| Method | Path | Query / Body Params | Status Codes | Description |
| :--- | :--- | :--- | :--- | :--- |
| `GET` | `/outbox/events` | Query: `status` (`PENDING`, `PUBLISHED`, `ALL`), `limit` (default 50) | `200` | Scrapes outbox events across all entities |
| `POST` | `/outbox/events/ack` | JSON: `event_ids` (list of strings) | `200`, `400` | Acknowledges events as `PUBLISHED` |

### 2.2 JSON Schemas (`app/service/schema.py`)

```python
ACK_OUTBOX_EVENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "event_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        }
    },
    "required": ["event_ids"],
    "additionalProperties": False,
}
```

### 2.3 API Request & Response Specifications

#### 1. `GET /outbox/events`
Scrapes all outbox events attached across user wallets, clearing pools, and quotes.

- **Query Parameters**:
  - `status`: `"PENDING"` (default), `"PUBLISHED"`, or `"ALL"`.
  - `limit`: Integer maximum results (default `50`).
- **Success Response (`200 OK`)**:
  ```json
  {
    "events": [
      {
        "event_id": "evt_tx_out_101",
        "entity_type": "USER_WALLET",
        "entity_id": "user_1",
        "event_type": "TRANSFER_OUTBOUND_COMMITTED",
        "payload": {
          "transfer_id": "tx_transfer_123",
          "to_user_id": "user_2",
          "currency": "USD",
          "amount": 5000,
          "sender_remaining_balance": 95000
        },
        "timestamp": "2026-10-02T11:05:00Z",
        "status": "PENDING"
      },
      {
        "event_id": "evt_pool_hop_102",
        "entity_type": "CLEARING_POOL",
        "entity_id": "SYSTEM_OUTBOUND",
        "event_type": "TRANSIT_POOL_CLEARED",
        "payload": {
          "transfer_id": "tx_transfer_123",
          "from_pool": "SYSTEM_OUTBOUND",
          "to_pool": "SYSTEM_INBOUND",
          "currency": "USD",
          "amount": 5000
        },
        "timestamp": "2026-10-02T11:05:00.010Z",
        "status": "PENDING"
      },
      {
        "event_id": "evt_tx_in_103",
        "entity_type": "USER_WALLET",
        "entity_id": "user_2",
        "event_type": "TRANSFER_INBOUND_SETTLED",
        "payload": {
          "transfer_id": "tx_transfer_123",
          "from_user_id": "user_1",
          "currency": "USD",
          "amount": 5000,
          "recipient_updated_balance": 30000
        },
        "timestamp": "2026-10-02T11:05:00.020Z",
        "status": "PENDING"
      }
    ],
    "total": 3
  }
  ```

---

#### 2. `POST /outbox/events/ack`
Acknowledges that an external worker or polling service has delivered events, updating their status on the host entities from `PENDING` to `PUBLISHED`.

- **Request Body**:
  ```json
  {
    "event_ids": ["evt_tx_out_101", "evt_pool_hop_102", "evt_tx_in_103"]
  }
  ```
- **Success Response (`200 OK`)**:
  ```json
  {
    "acknowledged_ids": ["evt_tx_out_101", "evt_pool_hop_102", "evt_tx_in_103"],
    "count": 3
  }
  ```

---

## 3. Service &harr; Manager Contract (`app/manager/entities.py`)

```python
from dataclasses import dataclass, asdict
from typing import Any, Dict, List

@dataclass
class GetOutboxEventsRequestEntity:
    status: str = "PENDING"
    limit: int = 50

@dataclass
class OutboxEventItemEntity:
    event_id: str
    entity_type: str  # USER_WALLET, CLEARING_POOL, QUOTE
    entity_id: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: str
    status: str  # PENDING, PUBLISHED

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class GetOutboxEventsResponseEntity:
    events: List[OutboxEventItemEntity]
    total: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self.events],
            "total": self.total,
        }

@dataclass
class AckOutboxEventsRequestEntity:
    event_ids: List[str]

@dataclass
class AckOutboxEventsResponseEntity:
    acknowledged_ids: List[str]
    count: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

---

## 4. Manager Layer (`app/manager/`)

### 4.1 `OutboxManager` (`app/manager/outbox_manager.py`)
Scrapes and acknowledges events across all entity repositories:
- Injects: `UserWalletAdapter`, `QuoteAdapter`.
- Methods:
  1. `get_events(request: GetOutboxEventsRequestEntity) -> GetOutboxEventsResponseEntity`:
     - Collects `outbox_events` from all user wallets via `UserWalletAdapter.get_all_user_events()`.
     - Collects `outbox_events` from clearing pools via `UserWalletAdapter.get_all_pool_events()`.
     - Collects `outbox_events` from quotes via `QuoteAdapter.get_all_quote_events()`.
     - Merges and sorts events chronologically by `timestamp`.
     - Filters by `status` (if not `"ALL"`).
     - Limits results to `request.limit`.
  2. `ack_events(request: AckOutboxEventsRequestEntity) -> AckOutboxEventsResponseEntity`:
     - Calls `UserWalletAdapter.mark_outbox_events_published(request.event_ids)`.
     - Calls `QuoteAdapter.mark_outbox_events_published(request.event_ids)`.
     - Returns acknowledged IDs.

### 4.2 State Machine Updates to `TransferManager`
In `TransferManager.transfer()`:
1. Stage 1 (Sender $\rightarrow$ Outbound Pool):
   - Invokes `UserWalletAdapter.debit_sender_to_outbound(...)`.
   - Attaches `TRANSFER_OUTBOUND_COMMITTED` to the sender's `UserRecordEntity`.
2. Stage 2 (Outbound Pool $\rightarrow$ Inbound Pool):
   - Invokes `UserWalletAdapter.route_outbound_to_inbound(...)`.
   - Attaches `TRANSIT_POOL_CLEARED` to `PoolRecordEntity("SYSTEM_OUTBOUND")`.
3. Stage 3 (Inbound Pool $\rightarrow$ Recipient):
   - Invokes `UserWalletAdapter.settle_inbound_to_recipient(...)`.
   - Attaches `TRANSFER_INBOUND_SETTLED` to the recipient's `UserRecordEntity`.

### 4.3 State Machine Updates to `QuoteManager`
In `QuoteManager`:
1. `create_quote()`:
   - Attaches `QUOTE_CREATED` to `QuoteRecordEntity`.
2. `accept_quote()`:
   - Stage 1 (User $\rightarrow$ Outbound Pool): Invokes `UserWalletAdapter.debit_user_for_conversion(...)`. Attaches `CONVERSION_OUTBOUND_COMMITTED` to user's `UserRecordEntity`.
   - Stage 2 (Outbound Pool $\rightarrow$ Inbound & Fee Pools): Invokes `UserWalletAdapter.clear_fx_pools(...)`. Attaches `CONVERSION_FX_CLEARED` to `PoolRecordEntity("SYSTEM_OUTBOUND")`.
   - Stage 3 (Inbound Pool $\rightarrow$ User Target Currency): Invokes `UserWalletAdapter.credit_user_from_inbound(...)`. Attaches `CONVERSION_INBOUND_SETTLED` to user's `UserRecordEntity`.
   - Stage 4: Transitions quote status to `ACCEPTED`. Attaches `QUOTE_ACCEPTED` to `QuoteRecordEntity`.

---

## 5. Manager &harr; Adapter Contract (`app/adapter/entities.py`)

### 5.1 Outbox Event Record
```python
@dataclass
class OutboxEventRecordEntity:
    event_id: str
    entity_type: str      # "USER_WALLET", "CLEARING_POOL", "QUOTE"
    entity_id: str        # e.g. "user_1", "SYSTEM_OUTBOUND", "quote_123"
    event_type: str       # "TRANSFER_OUTBOUND_COMMITTED", etc.
    payload: Dict[str, Any]
    timestamp: str
    status: str = "PENDING"  # PENDING, PUBLISHED

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

### 5.2 Entity Models with Attached Outbox Events
```python
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class UserRecordEntity:
    user_id: str
    name: str
    balances: Dict[str, int]
    outbox_events: List[OutboxEventRecordEntity] = field(default_factory=list)

@dataclass
class PoolRecordEntity:
    pool_id: str          # "SYSTEM_OUTBOUND", "SYSTEM_INBOUND", "SYSTEM_FEES"
    balances: Dict[str, int]
    outbox_events: List[OutboxEventRecordEntity] = field(default_factory=list)

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
    status: str
    outbox_events: List[OutboxEventRecordEntity] = field(default_factory=list)
```

---

## 6. Adapter Layer (`app/adapter/`)

### 6.1 `UserWalletAdapter` (`app/adapter/user_wallet_adapter.py`)
- Owns:
  - `self._users: Dict[str, UserRecordEntity]`
  - `self._pools: Dict[str, PoolRecordEntity]` (`"SYSTEM_OUTBOUND"`, `"SYSTEM_INBOUND"`, `"SYSTEM_FEES"`)
- Multi-stage mutation methods attach events directly to the host entity:
  - `debit_sender_to_outbound(...)`: Updates sender + outbound pool, appends `TRANSFER_OUTBOUND_COMMITTED` to `sender.outbox_events`.
  - `route_outbound_to_inbound(...)`: Updates outbound pool + inbound pool, appends `TRANSIT_POOL_CLEARED` to `outbound_pool.outbox_events`.
  - `settle_inbound_to_recipient(...)`: Updates inbound pool + recipient, appends `TRANSFER_INBOUND_SETTLED` to `recipient.outbox_events`.
  - `debit_user_for_conversion(...)`: Appends `CONVERSION_OUTBOUND_COMMITTED` to user's wallet.
  - `clear_fx_pools(...)`: Appends `CONVERSION_FX_CLEARED` to `outbound_pool.outbox_events`.
  - `credit_user_from_inbound(...)`: Appends `CONVERSION_INBOUND_SETTLED` to user's wallet.
- Scraper / Acknowledgment Methods:
  - `get_all_user_events() -> List[OutboxEventRecordEntity]`
  - `get_all_pool_events() -> List[OutboxEventRecordEntity]`
  - `mark_outbox_events_published(event_ids: List[str]) -> List[str]`

### 6.2 `QuoteAdapter` (`app/adapter/quote_adapter.py`)
- Owns: `self._quotes: Dict[str, QuoteRecordEntity]`
- Attaches events directly to quotes:
  - `save_quote(...)`: Appends `QUOTE_CREATED` to `quote.outbox_events`.
  - `update_status(quote_id, "ACCEPTED")`: Appends `QUOTE_ACCEPTED` to `quote.outbox_events`.
- Scraper / Acknowledgment Methods:
  - `get_all_quote_events() -> List[OutboxEventRecordEntity]`
  - `mark_outbox_events_published(event_ids: List[str]) -> List[str]`

---

## 7. Test Plan (`tests/test_outbox.py`)

1. **Transactional Invariant & Event Placement**:
   - Execute transfer:
     - Verify `TRANSFER_OUTBOUND_COMMITTED` exists in Alice's `UserRecordEntity.outbox_events`.
     - Verify `TRANSIT_POOL_CLEARED` exists in `PoolRecordEntity("SYSTEM_OUTBOUND").outbox_events`.
     - Verify `TRANSFER_INBOUND_SETTLED` exists in Bob's `UserRecordEntity.outbox_events`.
2. **Zero Phantom Events on Error**:
   - Transfer with insufficient funds raises error; verify no events are created on any entity or pool.
3. **Conversion Event Placement**:
   - Execute quote creation and acceptance:
     - Verify `QUOTE_CREATED` and `QUOTE_ACCEPTED` on `QuoteRecordEntity`.
     - Verify `CONVERSION_OUTBOUND_COMMITTED` and `CONVERSION_INBOUND_SETTLED` on user's wallet.
     - Verify `CONVERSION_FX_CLEARED` on `PoolRecordEntity("SYSTEM_OUTBOUND")`.
4. **Outbox Scraper API (`GET /outbox/events`)**:
   - Scrape events across all entities; verify they appear in chronological order matching the 3-step state machine hops.
5. **Acknowledgment Workflow (`POST /outbox/events/ack`)**:
   - Acknowledge pending events; verify status flips to `PUBLISHED` on the hosting entities.
