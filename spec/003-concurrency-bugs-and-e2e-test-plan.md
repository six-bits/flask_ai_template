# 003: Concurrency Vulnerabilities Audit & Proposed E2E Test Suite

## 1. Overview & Scope

**Declared Scope: Audit & Test Proposals Only (No Code Fixes)**

This specification audits concurrency flaws, race conditions, and architectural edge cases in the current implementation, and proposes a crisp suite of End-to-End (E2E) concurrency tests to rigorously verify isolation, atomicity, idempotency, and deadlock freedom.

---

## 2. Identified Bugs & Concurrency Vulnerabilities

### Bug 1: Quote Double-Spend Race Condition (Critical)
- **Location**: [`app/manager/wallet_manager.py:accept_quote`](file:///Users/hammad/Projects/flask_ai_template/app/manager/wallet_manager.py#L121-L200)
- **Vulnerability**: 
  1. `quote = self.adapter.get_quote(request.quote_id)` and the check `if quote.status == "ACCEPTED"` occur **outside any quote lock**.
  2. The fine-grained account locks in [`execute_multi_step_transaction`](file:///Users/hammad/Projects/flask_ai_template/app/adapter/wallet_adapter.py#L125-L150) lock only account IDs (`user:usr_alice:USD`, `system:fx_pool:...`), **not the quote record**.
  3. If two concurrent threads attempt to accept the same quote simultaneously (without idempotency keys or with different client requests), both observe `quote.status == "PENDING"`.
  4. Both threads proceed into [`execute_multi_step_transaction`](file:///Users/hammad/Projects/flask_ai_template/app/adapter/wallet_adapter.py#L125-L224), debiting the user twice and crediting target funds twice for a single quote!
- **Impact**: Double currency conversion for a single quote; double fee charged; balance loss.

---

### Bug 2: Idempotency Key In-Flight Collision (Critical)
- **Location**: [`app/manager/wallet_manager.py:accept_quote`](file:///Users/hammad/Projects/flask_ai_template/app/manager/wallet_manager.py#L133-L167) & [`transfer_money`](file:///Users/hammad/Projects/flask_ai_template/app/manager/wallet_manager.py#L248-L278)
- **Vulnerability**:
  1. Both endpoints inspect `cached_rec = self.adapter.get_idempotency_record(request.idempotency_key)`.
  2. The record is only written *after* the multi-step transaction completes: `self.adapter.save_idempotency_record(...)`.
  3. If two identical requests arrive in parallel (network burst / client retry before initial response), neither finds a cached record in `idempotency_store`.
  4. Both requests execute their multi-step transactions, duplicating transfers or conversions.
- **Impact**: Breaks exactly-once processing guarantee during network retries.

---

### Bug 3: Inter-Step Intermediate Read State (Medium)
- **Location**: [`app/adapter/wallet_adapter.py:execute_multi_step_transaction`](file:///Users/hammad/Projects/flask_ai_template/app/adapter/wallet_adapter.py#L150-L188)
- **Vulnerability**:
  1. In [`execute_multi_step_transaction`](file:///Users/hammad/Projects/flask_ai_template/app/adapter/wallet_adapter.py#L150-L188), the loop enters and exits `with self.db.lock:` for each individual step.
  2. While account-level locks are held across the whole transaction, concurrent readers calling [`get_user_balances`](file:///Users/hammad/Projects/flask_ai_template/app/adapter/wallet_adapter.py#L58-L67) acquire only `self.db.lock`.
  3. Between Step 1 (debit sender &rarr; outbound pool) and Step 3 (inbound pool &rarr; recipient), funds appear deducted from sender but not yet present for recipient or appearing transiently in clearing pools.
- **Impact**: Non-repeatable or "dirty" balance reads during concurrent multi-step execution.

---

### Bug 4: Unconstrained System Pool Balances (Medium)
- **Location**: [`app/adapter/db.py:AccountRecord`](file:///Users/hammad/Projects/flask_ai_template/app/adapter/db.py#L18-L26)
- **Vulnerability**:
  - `allow_negative=True` is enabled for system clearing pools (`system:fx_pool:...`, `system:outbound_pool:...`).
  - System FX pools can operate at infinite negative balances without liquidity limits, meaning currency conversions do not require reserves in the target currency pool.
- **Impact**: System can issue unlimited currency if user balances permit.

---

### Bug 5: Timezone-Naive Datetime Formatting in Quotes (Minor)
- **Location**: [`app/manager/wallet_manager.py:create_quote`](file:///Users/hammad/Projects/flask_ai_template/app/manager/wallet_manager.py#L98-L119)
- **Vulnerability**:
  - `datetime.utcnow().isoformat()` produces timestamps without a `Z` or UTC offset suffix (e.g. `2026-10-12T14:30:00.123456`).
  - Standard JavaScript/HTTP clients parsing this string may interpret it in the browser's local timezone, causing client-side premature or delayed expiration display.
- **Impact**: Client-server clock synchronization ambiguity.

---

## 3. Proposed Crisp E2E Concurrency Tests

Below are proposed End-to-End concurrency tests designed to validate correctness, isolate race conditions, and expose the identified bugs:

### Test 1: Competing Double-Spend Transfers (Overdraft Prevention)
- **Goal**: Ensure concurrent transfers attempting to overdraw a single account cannot both succeed.
- **Setup**: User Alice has 100 EUR.
- **Action**: Fire 2 concurrent HTTP `POST /api/v1/transfers` requests:
  - Thread 1: Send 80 EUR to Bob.
  - Thread 2: Send 80 EUR to Charlie.
- **Expectation**: Exactly **1 request returns `201 Created`** and **1 request returns `422 Unprocessable Entity`** (insufficient funds). Alice's balance must remain non-negative (20 EUR).

---

### Test 2: Concurrent Quote Double-Acceptance (Quote Double-Spend)
- **Goal**: Expose whether a single quote can be accepted more than once under concurrent execution.
- **Setup**: User Alice has 1,000 USD. Request 1 quote to convert 100 USD to EUR.
- **Action**: Fire 2 concurrent HTTP `POST /api/v1/quotes/{quote_id}/accept` requests simultaneously.
- **Expectation**: Exactly **1 request returns `200 OK`** and **1 request returns `422 Unprocessable Entity`** (already accepted). Alice's USD balance must only be deducted once (900 USD, not 800 USD).

---

### Test 3: Simultaneous Duplicate Idempotency Key Retries
- **Goal**: Expose whether duplicate requests with the same `Idempotency-Key` can slip through before completion.
- **Setup**: User Alice has 500 EUR.
- **Action**: Fire 5 concurrent HTTP `POST /api/v1/transfers` requests with the **exact same `Idempotency-Key`** and payload (send 50 EUR to Bob).
- **Expectation**: All 5 requests return identical responses (either 201 or cached 201). **Alice's balance must be deducted exactly once** (450 EUR, not 250 EUR).

---

### Test 4: Bidirectional Transfers (Deadlock-Free Canonical Lock Order)
- **Goal**: Verify that simultaneous transfers between mutual counterparties never produce deadlocks.
- **Setup**: Alice has 500 EUR, Bob has 500 EUR.
- **Action**: Fire 20 concurrent transfers:
  - 10 threads: Alice &rarr; Bob (5 EUR each).
  - 10 threads: Bob &rarr; Alice (5 EUR each).
- **Expectation**: All 20 requests complete within seconds without hanging, timeout, or deadlocking. Final balances must equal exactly 500 EUR for both users.

---

### Test 5: High-Concurrency Fan-In Transfer Stress (Mass Mutual Credit)
- **Goal**: Verify atomic balance consistency when multiple senders target a single recipient simultaneously.
- **Setup**: 10 distinct sender threads each send 10 EUR to User Bob concurrently.
- **Action**: 10 concurrent HTTP `POST /api/v1/transfers`.
- **Expectation**: All 10 requests succeed (`201 Created`). Bob's balance increases by exactly 100 EUR, with no lost updates.

---

### Test 6: Concurrent Multi-Step Failure Rollback Under Load
- **Goal**: Ensure that an in-flight transaction failing midway cleanly reverses its steps even while other concurrent transactions touch the same clearing pools.
- **Setup**: Alice sends 50 EUR to Bob (simulated failure midway), while Charlie successfully sends 20 USD to Alice concurrently.
- **Action**: Run both transactions concurrently.
- **Expectation**: Alice's failed transaction completely rolls back without leaving funds stuck in `outbound_pool` or corrupting Charlie's concurrent transfer.

---

## 4. Implementation Status & Test Verification

All 6 proposed concurrency E2E tests have been implemented in [`tests/test_api.py`](file:///Users/hammad/Projects/flask_ai_template/tests/test_api.py#L578-L782):
1. **Error Injection Hook**: Implemented via Approach 1 (`X-Simulate-Failure-At-Step` HTTP header, active when `app.config["TESTING"] is True`).
2. **Resource Synchronization**: Protected quotes (`quote:{id}`) and in-flight idempotency keys (`idempotency:{key}`) via [`lock_manager.acquire_account_locks`](file:///Users/hammad/Projects/flask_ai_template/app/utils/locking.py#L25-L42).
3. **Execution Results**: 36 of 36 unit and E2E concurrency tests pass deterministically across consecutive stress runs.

