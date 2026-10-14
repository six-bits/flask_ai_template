# Specification: End-to-End Concurrency & Invariant Verification Suite

**Scope**: Full Stack (Test Suite, Fast Expiration Configuration & Concurrency Verification)  
**Status**: Pending Review  
**Layer Focus**: Multi-threaded live server HTTP testing, balance invariant mathematical verification, concurrent idempotent duplicate storm handling, and fast hold expiration.

---

## 1. Overview & Scope

Testing concurrent financial systems requires verifying that:
1. Under heavy multi-threaded contention, no race conditions, deadlocks, or collection corruptions occur.
2. The core accounting invariant holds true across every card at all times:
   $$\text{Available Limit} = \text{Credit Limit} - \text{Settled Balance} - \text{Active Held Balance}$$
3. Simultaneous duplicate requests sharing an `Idempotency-Key` debit the card **exactly once** (idempotent singularity).
4. Authorizations expire cleanly under concurrent load without leaving orphaned holds or corrupted balances.

To make tests blazingly fast without waiting 60 seconds, this specification also introduces a **Configurable Fast Expiration Mechanism**.

---

## 2. Fast Expiration Mechanism

### 2.1 Configuration
In `app/manager/payment_manager.py`:
- Add a configurable hold TTL property:
  ```python
  class PaymentManager:
      def __init__(self, adapter: Optional[PaymentAdapter] = None, hold_ttl_seconds: float = 60.0):
          self.adapter = adapter or payment_adapter
          self.hold_ttl_seconds = float(os.environ.get("HOLD_TTL_SECONDS", hold_ttl_seconds))
  ```
- **Default in Production**: 60.0 seconds.
- **In Fast Concurrency Tests**: Set `payment_manager.hold_ttl_seconds = 0.2` (200 milliseconds).
- **Benefit**: Expiration-related concurrency races can be tested deterministically in $\sim$250 milliseconds instead of 60 seconds.

---

## 3. Core System Invariants

After any concurrent barrage settles, the test suite must assert the following invariants against the live HTTP API:

### Invariant 1: Balance Conservation
For every card $c \in \text{SEED\_CARDS}$:
$$\text{available\_limit}_c = \text{credit\_limit}_c - \text{settled\_balance}_c - \text{held\_balance}_c$$
*(When force-posts push a card over limit, $\text{held\_balance}_c = 0$, so $\text{available\_limit}_c = \text{credit\_limit}_c - \text{settled\_balance}_c < 0$).*

### Invariant 2: Idempotent Singularity (No Double Debits)
If $N$ concurrent HTTP requests are sent across $K$ distinct `Idempotency-Key`s:
- Exactly $K$ requests execute original business logic.
- Exactly $N - K$ requests receive `Idempotent-Replay: true` (backend no-op).
- The total amount deducted from the card's available limit is **strictly equal** to the sum of the $K$ unique requests, **never** $N$.

### Invariant 3: Over-Subscription Boundary
If $M$ concurrent threads each attempt to authorize amount $A$ against a card with limit $C$ (where $M \times A > C$):
- Exactly $\lfloor C / A \rfloor$ requests return `201 Created`.
- Exactly $M - \lfloor C / A \rfloor$ requests return `422 Unprocessable Entity` (`INSUFFICIENT_FUNDS`).
- Final $\text{held\_balance} = \lfloor C / A \rfloor \times A$.
- Final $\text{available\_limit} = C - (\lfloor C / A \rfloor \times A) \ge 0$.
- **Zero over-authorization** is mathematically permitted.

---

## 4. Concurrency Test Scenarios (`tests/test_concurrency.py`)

All tests will run against the live Werkzeug HTTP server over genuine TCP/HTTP sockets.

### Scenario A: High-Contention Idempotent Duplicate Storm
* **Setup**:
  - Card: `card_seed_1` (Limit: \$1,000.00).
  - 40 concurrent worker threads fire simultaneously.
  - The 40 threads share **only 4 unique `Idempotency-Key`s** (10 threads per key), each requesting \$50.00 authorization.
* **Verification**:
  - Total requests processed: 40.
  - Status code: `201 Created` for all 40 responses.
  - Exactly 4 responses do NOT have `Idempotent-Replay`.
  - Exactly 36 responses have `Idempotent-Replay: true`.
  - Card balance: `held_balance == 200.00`, `available_limit == 800.00` (NOT \$2,000!).
  - Ledger contains **exactly 4 transactions**.

### Scenario B: Concurrent Over-Subscription Depletion Race
* **Setup**:
  - Card: `card_seed_2` (Limit: \$500.00).
  - 50 concurrent worker threads simultaneously attempt to authorize \$50.00 each with unique idempotency keys (Total demand: \$2,500.00).
* **Verification**:
  - Exactly 10 requests succeed (`201 Created`).
  - Exactly 40 requests fail (`422 Declined`, `INSUFFICIENT_FUNDS`).
  - `held_balance == 500.00`, `available_limit == 0.00`.
  - Invariant 1 verified.

### Scenario C: Fast Hold Expiration Race Condition
* **Setup**:
  - Fast TTL enabled: `hold_ttl_seconds = 0.2` (200ms).
  - Card: `card_seed_1` (Limit: \$1,000.00).
  - 10 threads authorize \$50 each (\$500 held).
  - Concurrently, 4 threads immediately clear \$50 each against 4 of the auths within 50ms.
  - Remaining 6 holds are left untouched.
  - Test sleeps 250ms to trigger hold expiration.
* **Verification**:
  - Cleared authorizations remain settled: `settled_balance == 200.00`.
  - The 6 untouched authorizations automatically expire: `held_balance == 0.00`.
  - Available limit is restored: `available_limit == 800.00`.
  - Subsequent late clearing or reversal attempts against the 6 expired auths return `422 Unprocessable Entity` or settle as expired without hold release.

### Scenario D: Mixed Multi-Card Concurrency Chaos
* **Setup**:
  - 120 concurrent requests across all 3 seed cards (`card_seed_1`, `card_seed_2`, `card_seed_3`).
  - Distributed request mix:
    - 40 Authorizations (some exceeding limit).
    - 30 Clearings (normal, partial, over-capture).
    - 20 Force-Posts (exceeding limit on some cards).
    - 20 Reversals.
    - 10 Retried duplicate requests interspersed randomly.
* **Verification**:
  - Zero deadlocks (all 120 requests complete within 5 seconds).
  - Zero unhandled 500 errors.
  - For every card: Invariant 1 ($\text{Available} = \text{Limit} - \text{Settled} - \text{Held}$) holds to the cent.
  - In-memory database collections remain intact and uncorrupted.

---

## 5. Implementation Requirements for This Spec

1. **Manager**: Add `hold_ttl_seconds` property to `PaymentManager` (default 60.0s, configurable via parameter or `HOLD_TTL_SECONDS` env var).
2. **Test Suite**: Create [`tests/test_concurrency.py`](file:///Users/hammad/Projects/flask_ai_template/tests/test_concurrency.py) executing Scenarios A, B, C, and D against the live server.
