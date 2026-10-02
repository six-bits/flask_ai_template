# Specification 004: Distributed Database Sharding, Shard-Local Transit Pools, and Asynchronous Sagas

**Scope**: `Scope: Architectural Design & Production System Specification`

---

## 1. Overview & Problem Context

In a single-node database architecture, peer-to-peer transfers and currency conversions can execute atomically in a single local ACID transaction. However, as the platform scales to tens of millions of users, account data must be horizontally partitioned across multiple database shards (typically partitioned by `user_id`).

### 1.1 The Distributed Sharding Dilemma
When Alice (`user_1` on **Shard 1**) transfers funds to Bob (`user_2` on **Shard 2**), a single local database transaction is physically impossible.

Engineering teams face two choices:
1. **Distributed Two-Phase Commit (2PC / XA Transactions)**:
   - Holds blocking network locks across Shard 1 and Shard 2 simultaneously.
   - **Why 2PC Fails at Scale**: Network partitions or slow locks on Shard 2 freeze Shard 1. Transaction latency spikes from $2\text{ ms}$ to $200+\text{ ms}$, throughput collapses, and system availability degrades (violating CAP theorem under partitions).
2. **Shard-Local Transit Pools with Asynchronous Sagas**:
   - Each shard maintains its own local clearing pools (`SHARD_X_OUTBOUND_POOL`, `SHARD_X_INBOUND_POOL`).
   - The transaction decomposes into **two independent, local ACID transactions** linked asynchronously via a durable, transactional event bus.

---

## 2. High-Level System Architecture

```text
                           Client / Mobile App
                                   │
                                   │ 1. POST /transfers (Idempotency-Key: K1)
                                   ▼
                      ┌───────────────────────────┐
                      │   API Gateway / Router    │ (Resolves Shard via hash(from_user_id))
                      └─────────────┬─────────────┘
                                    │
               ┌────────────────────┴────────────────────┐
               │ 2. Routes to Shard 1 (Alice's Node)     │
               ▼                                         ▼
    ┌───────────────────────┐                 ┌───────────────────────┐
    │    SHARD 1 WORKER     │                 │    SHARD 2 WORKER     │
    │  ┌─────────────────┐  │                 │  ┌─────────────────┐  │
    │  │   DB SHARD 1    │  │                 │  │   DB SHARD 2    │  │
    │  │ • Alice Balance │  │                 │  │ • Bob Balance   │  │
    │  │ • Outbound Pool │  │                 │  │ • Inbound Pool  │  │
    │  │ • Outbox Table  │  │                 │  │ • Idempotency   │  │
    │  └────────┬────────┘  │                 │  └────────▲────────┘  │
    └───────────┼───────────┘                 └───────────┼───────────┘
                │                                         │
                │ 3. CDC / Poller (Debezium)              │ 5. Consumer processes event
                ▼                                         │    & executes local credit
    ┌─────────────────────────────────────────────────────┴───────────┐
    │             DISTRIBUTED MESSAGE BUS (Kafka / Pulsar)            │
    │     Topic: cross-shard-transfers (Partitioned by target_shard)  │
    └─────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ 6. Emits TransferCompleted event
                                    │
                      ┌─────────────┴─────────────┐
                      │   Notification Service    │ ──> Push Notification / WebSocket
                      │   (Pushes to Bob & Alice) │
                      └───────────────────────────┘
```

---

## 3. The Asynchronous Paradigm Shift

In a distributed environment, keeping an HTTP thread open while waiting for cross-shard network hops causes thread starvation and cascading failures. The API shifts from synchronous RPC to **asynchronous acceptance with deterministic state tracking**:

### 3.1 HTTP Ingress Contract
* **Request**:
  ```http
  POST /transfers
  Idempotency-Key: 7b8f9e01-2a4c-4e89
  Content-Type: application/json

  {
    "from_user_id": "alice",
    "to_user_id": "bob",
    "amount": 10000,
    "currency": "USD"
  }
  ```

* **Immediate Response (`202 Accepted`)**:
  ```json
  {
    "transfer_id": "tx_20261003_8f9e",
    "status": "PENDING",
    "from_user_id": "alice",
    "to_user_id": "bob",
    "currency": "USD",
    "amount": 10000,
    "from_user_balance": 90000,
    "message": "Transfer initiated. Funds locked in transit."
  }
  ```

### 3.2 Transfer State Machine Lifecycle
```text
[INITIATED]
     │
     ▼
[DEBITED_ON_SHARD_1]  ──(Event Stream)──► [IN_TRANSIT]
                                               │
                       ┌───────────────────────┴───────────────────────┐
                       ▼                                               ▼
            [SETTLED_ON_SHARD_2]                            [REJECTED_ON_SHARD_2]
                       │                                               │
                       ▼                                               ▼
             (Notify Recipient & Sender)                      (Compensation Saga:
                                                              Refund to Shard 1)
```

---

## 4. End-to-End Orchestration Flow

### Phase 1: Local Ingress on Source Shard (Shard 1)
1. **Routing**: API Gateway hashes `from_user_id` and dispatches the request to Shard 1.
2. **Local ACID Transaction ($< 2\text{ ms}$)**:
   - Verify Alice's balance in `USD` $\ge 10,000$ cents.
   - Debit Alice: $-\$100.00$.
   - Credit `SHARD_1_OUTBOUND_POOL`: $+\$100.00$.
   - Insert Outbox Event:
     ```json
     {
       "event_id": "evt_out_8f9e",
       "event_type": "CROSS_SHARD_TRANSFER_DISPATCHED",
       "aggregate_id": "tx_20261003_8f9e",
       "payload": {
         "transfer_id": "tx_20261003_8f9e",
         "from_user_id": "alice",
         "to_user_id": "bob",
         "source_shard": "shard_1",
         "target_shard": "shard_2",
         "amount": 10000,
         "currency": "USD",
         "timestamp": "2026-10-03T00:00:00Z"
       },
       "status": "PENDING"
     }
     ```
   - Store idempotency record with status `IN_PROGRESS` / `PENDING`.
   - **COMMIT**.
3. **Guaranteed Invariant**: Alice's balance is debited immediately. She cannot double-spend, even if downstream networks stall.

### Phase 2: Reliable Cross-Shard Event Streaming
1. A Change Data Capture (CDC) connector (e.g. Debezium) or outbox scraper tails Shard 1's outbox table.
2. Publishes the event to Kafka topic `cross-shard-transfers`, partitioned by `target_shard` (`shard_2`) to ensure ordered delivery per shard.

### Phase 3: Idempotent Settlement on Target Shard (Shard 2)
1. Shard 2's worker consumes `CROSS_SHARD_TRANSFER_DISPATCHED`.
2. **Local ACID Transaction ($< 2\text{ ms}$)**:
   - Check local idempotency table:
     ```sql
     INSERT INTO processed_events (event_id, transfer_id) VALUES ('evt_out_8f9e', 'tx_20261003_8f9e');
     ```
     *(If primary key collision occurs, skip processing — duplicate delivery avoided).*
   - Debit `SHARD_2_INBOUND_POOL`: $-\$100.00$.
   - Credit Bob's balance: $+\$100.00$.
   - Insert Outbox Event: `TRANSFER_SETTLED_ON_SHARD_2`.
   - **COMMIT**.
3. Shard 2 publishes completion event:
   - **Notification Service** pushes an alert to Bob (WebSocket/Push).
   - **Shard 1 Listener** updates its local transfer record to `SETTLED`.

---

## 5. Failure Handling: The Compensating Saga

What happens if Bob's account on Shard 2 was suspended, closed, or currency-restricted?

```text
Shard 2 Consumer (Cannot Credit Bob)
       │
       ▼ Emits: CROSS_SHARD_TRANSFER_REJECTED (reason: ACCOUNT_SUSPENDED)
[Kafka Stream]
       │
       ▼ Delivered to Shard 1
Shard 1 Consumer (Executes Local Compensation)
       │
       ├── Debit SHARD_1_OUTBOUND_POOL (-$100)
       ├── Credit Alice's balance (+$100)
       └── Update Idempotency Record -> FAILED_REFUNDED
```

1. **No Distributed Rollbacks**: Shard 1 does not need to undo committed state; it issues an **explicit compensating credit**.
2. **Audit Integrity**: The transaction history shows:
   - `TRANSFER_SENT` ($-\$100.00$)
   - `TRANSFER_REFUND` ($+\$100.00$, reference: `tx_20261003_8f9e`, reason: `RECIPIENT_ACCOUNT_SUSPENDED`).

---

## 6. Mathematical Reconciliation: Bilateral Net Settlement

### 6.1 The Shard Drift Question
During cross-shard transfers:
- Shard 1's Outbound Pool has a balance of $+\$100.00$.
- Shard 2's Inbound Pool has a balance of $-\$100.00$.
- **System Conservation Invariant**:
  $$\sum \Delta \text{Pools} = \text{Pool}_{\text{Shard 1}} + \text{Pool}_{\text{Shard 2}} = (+100) + (-100) = 0$$

### 6.2 The Nostro / Vostro Parallel
This architecture mirrors international correspondent banking (SWIFT):
* Bank A (JPMorgan) debits the sender, credits an account representing Bank B (Nostro), and sends a SWIFT message.
* Bank B (Barclays) debits its matching clearing account (Vostro) and credits the recipient.

### 6.3 Automated Rebalancing Sweeper
Over thousands of daily transfers between Shards:
1. Shard 1 $\to$ Shard 2: \$5,000,000.
2. Shard 2 $\to$ Shard 1: \$4,800,000.
3. **Net Position**: Shard 1 owes Shard 2 net \$200,000.
4. On a scheduled cron (e.g. hourly), an **Inter-Shard Clearing Sweeper** executes a single net rebalancing entry between the central treasury reserves, zeroing out shard pool drift without touching individual user accounts.

---

## 7. Coordination Strategies: Orchestration vs. Choreography

| Dimension | Event Choreography (Direct Shard-to-Shard) | Saga Orchestrator (Workflow Engine) |
| :--- | :--- | :--- |
| **Coordination** | Shards react directly to domain events emitted by peers. | Central coordinator (e.g. Temporal, AWS Step Functions) explicitly commands each shard step. |
| **Failure Handling** | Each shard has listeners for peer rejection events. | Central state machine invokes compensating activities. |
| **Throughput & Latency** | **Maximum throughput**, sub-second latency, zero central bottleneck. | Slight latency overhead from state machine persistence. |
| **Observability** | Requires distributed tracing (OpenTelemetry correlation IDs). | Central UI displays exact state of every in-flight saga. |
| **Recommended Fit** | **Simple 2-Shard P2P Transfers** | **Multi-step flows** (e.g. P2P + FX Conversion + AML Check + Tax Withholding) |

---

## 8. Concurrency & Edge-Case Defenses

### 8.1 Zombie Process / Network Partition Defense (OCC Fencing)
If a worker executing Shard 1's in-process flow suffers a 60-second GC pause or VM freeze, the reconciliation sweeper may declare the SLA expired and trigger a reversal.
* **The Defense**: All transfer rows maintain an incrementing `version` column.
* When the sweeper executes a reversal:
  ```sql
  UPDATE transfers SET status = 'REVERSED', version = version + 1 
  WHERE transfer_id = 'tx_123' AND version = 1;
  ```
* When the zombie thread wakes up and tries to settle, its write matches 0 rows due to version mismatch and safely terminates.

### 8.2 Payload Canonicalization
Before computing idempotency key hashes, payloads are normalized:
```python
canonical_payload = json.dumps(
    json.loads(raw_body),
    sort_keys=True,
    separators=(",", ":")
)
```
This guarantees that harmless client variations in JSON key ordering or whitespace never trigger false `422 IDEMPOTENCY_KEY_PAYLOAD_MISMATCH` errors.

---

## 9. Summary for Staff LLD Interviews

When discussing this architecture in a Staff interview, lead with this summary:

1. **Localize Contention**: Never hold distributed locks. Convert cross-database operations into sequential local ACID transactions using shard-local transit clearing pools.
2. **Asynchronous Contracts**: Return `202 Accepted` immediately upon source-shard debit to eliminate client wait times and prevent double-spending.
3. **Compensate, Never Erase**: Handle downstream rejections via backward compensating events that issue explicit refund journal entries.
4. **Zero-Sum Bilateral Netting**: Reconcile inter-shard clearing pools periodically using batch net settlement, preserving double-entry ledger balance across all shards.
