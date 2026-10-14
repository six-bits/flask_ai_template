# Card Authorization and Multi-Clearing Core

## 1. Problem Statement
An in-memory card issuing payment service where users have cards with defined credit limits.
The service handles the full payment lifecycle:
1. **Authorization**: Temporary hold on available limit valid for 60 seconds.
2. **Clearing / Settlement**: Merchant settles and captures money.
   - **Multi-clearing**: Authorizations can be cleared in multiple partial amounts over time.
   - **Over-capture**: Merchants can capture slightly more than the authorized amount (e.g. tips).
   - **Force-posts**: Clearing requests arriving without prior authorization must be accepted even if exceeding card credit limit.
3. **Reversals**: Authorizations can be cancelled early, releasing remaining hold balance.
4. **Card Inquiry & History**: Users can view credit limit, settled balance, held balance, available remaining limit, and full transaction history.
5. **Seed Cards & Merchants**:
   - Initial cards with limits (e.g., `card_seed_1`: $1000, `card_seed_2`: $500, `card_seed_3`: $2000).
   - Seed merchants (e.g., `Amazon`, `Restaurant`, `Target`, `Starbucks`, `Airline Offline`). Transactions must validate against seeded merchants.

## 2. In-Memory Database & Concurrency Model
- **Central Storage (`app/adapter/db.py`)**: Stores cards, authorizations, clearings, reversals, ledger transactions, and idempotency records.
- **Granular Locking & Deadlock Prevention**:
  - Lock at the most granular level (per-card and per-authorization locks).
  - Strict lock acquisition order (e.g., `Card` lock acquired before `Authorization` lock) to prevent deadlocks under concurrent requests.
  - Collection-level synchronization to protect concurrent mutations of collections holding objects.
- **Idempotency Entity & Deterministic Hashing**:
  - `IdempotencyRecordEntity` tracking `(idempotency_key, card_id, request_hash, status_code, response_body)`.
  - Request hash calculated deterministically via SHA-256 over canonical HTTP method, path, and sorted JSON body.
  - Matching hash returns cached response (no-op). Mismatched payload with same key returns conflict.
- **Configurable Hold Expiration (Fast-Expiry Testing)**:
  - Default hold duration is 60.0 seconds.
  - Configurable TTL (e.g. 0.2s) to enable fast, deterministic concurrent expiry testing without sleep lag.
- **Concurrency Invariants**:
  - **Balance Conservation**: $\text{Available Limit} = \text{Credit Limit} - \text{Settled Balance} - \text{Active Held Balance}$ across all cards at all times.
  - **Idempotent Singularity**: Concurrent bursts of duplicate keys must debit balance and record transactions exactly once.
  - **Over-subscription Safety**: $N$ concurrent threads over-subscribing a card must never exceed the credit limit.

## 3. Core Concepts & Math
- **Credit Limit**: Total credit line assigned to a card.
- **Settled Balance**: Sum of all captured/cleared transactions.
- **Held Balance**: Sum of all active, unexpired, and unreversed hold amounts.
- **Available Remaining Limit**:
  $$\text{Available Limit} = \text{Credit Limit} - \text{Settled Balance} - \text{Held Balance}$$
  *(Note: Available limit can be negative if force-posts exceed the credit limit).*
- **Hold Expiration**: Authorizations hold funds for 60 seconds. Holds expire automatically after 60s if not settled or reversed.

## 3. Idempotency Requirements
Payment requests across distributed networks are prone to network retries.
- All mutating endpoints (`authorizations`, `clearings`, `reversals`) MUST support an `Idempotency-Key`.
- **Idempotency Convention**: If a request is received with an existing `Idempotency-Key`:
  - No backend state modification occurs (no-op).
  - The service returns the exact response previously produced for that key.

## 4. Expected Behaviors & Edge Cases
| Scenario | Behavior |
| :--- | :--- |
| Auth with sufficient limit | Approve hold (valid for 60s), reduce available limit. |
| Auth with insufficient limit | Decline with `INSUFFICIENT_FUNDS` (hold not created). |
| Partial clearing | Settle partial amount, reduce hold accordingly. |
| Multi-clearing | Successive clearings capture amounts until hold is exhausted or expired. |
| Over-capture | Settle full amount (> auth amount), release original hold. |
| Force-post | Always approve and increase settled balance, even if pushing card over limit. |
| Reversal | Cancel active remaining hold early (partial or full remaining hold), restoring available limit. Settled funds are never reversed. |
| Auth hold expiry | After 60 seconds, hold expires; held balance returns to 0 without clearing. |
| Retried mutating request | Return stored response; perform no-op on balance or transaction ledger. |
