# Specification 004: Compensating Step Events for Rollback

`Scope: Adapter Layer & Ledger Model`

## 1. Overview & Problem Analysis

### Current Implementation Gap
In the current rollback implementation inside `WalletAdapter.execute_multi_step_transaction`:
When an in-flight transaction encounters an unexpected exception or simulated failure at step $N$:
1. The rollback loops over previously executed steps in reverse: `for step in reversed(executed_step_records):`
2. It reverses the account balances: `to_acc.balance -= step.amount; from_acc.balance += step.amount`
3. It **in-place mutates** the original step's status: `step.status = "REVERSED"`.

### The Problem
In financial ledgers, audit compliance, and the Saga / Compensating Transaction pattern:
- **Historical events are immutable**: If Step 1 completed, that event occurred in reality and cannot be erased or overwritten in-place.
- **Rollback must be an explicit event**: Instead of mutating the forward step, the engine must emit and persist a **new compensating step event** moving money in the exact opposite direction (`from = previous to`, `to = previous from`).
- **Reverse chronological order**: Compensating events must execute and be recorded in **strict reverse order** of the completed forward steps ($S_k, S_{k-1}, \dots, S_1$).

---

## 2. Compensating Movement Step Design

### Example: P2P Transfer Failure at Step 2
Suppose Alice initiates a 50 EUR transfer to Bob:
- **Step 1 (Forward, Completed)**:
  - `step_id`: `step_abc`
  - `step_index`: 1
  - `from_account_id`: `user:usr_alice:EUR`
  - `to_account_id`: `system:outbound_pool:EUR`
  - `amount`: 50.00
  - `status`: `"COMPLETED"`
- **Step 2 (Forward, Failed)**:
  - Simulated failure or invariant breach occurs before or during Step 2.
  - An optional failure record or halt is logged.
- **Compensating Step 1 (Reverse of Step 1, New Event)**:
  - `step_id`: `step_comp_xyz`
  - `step_index`: 2 (or sequential index in the transaction timeline)
  - `from_account_id`: `system:outbound_pool:EUR` (reversed)
  - `to_account_id`: `user:usr_alice:EUR` (reversed)
  - `amount`: 50.00
  - `status`: `"COMPENSATING"`
  - `timestamp`: current timestamp

### Example: Quote Acceptance Failure at Step 3
Suppose Alice accepts a quote to convert 100 USD to 92 EUR with a fee:
- **Step 1 (Forward)**: Alice USD &rarr; FX Pool USD (100 USD) [`COMPLETED`]
- **Step 2 (Forward)**: FX Pool EUR &rarr; Fee Pool EUR (0.46 EUR) [`COMPLETED`]
- **Step 3 (Forward)**: Fails at Step 3 (FX Pool EUR &rarr; Alice EUR).
- **Compensating Step 1 (Reverse of Step 2)**:
  - `from`: `system:fee_pool:EUR` &rarr; `to`: `system:fx_pool:EUR` (0.46 EUR) [`COMPENSATING`]
- **Compensating Step 2 (Reverse of Step 1)**:
  - `from`: `system:fx_pool:USD` &rarr; `to`: `user:usr_alice:USD` (100 USD) [`COMPENSATING`]

---

## 3. Layer Specifications

### 3.1 Service Layer (`app/service/`)
- *Scope Status*: In Scope (no breaking changes).
- Returns `500 Internal Server Error` on step failure as before.
- When querying transaction history (`GET /api/v1/users/<user_id>/transactions`), any failed/reversed transactions will show the full sequence of forward steps followed by compensating step events.

### 3.2 Service &harr; Manager Contract (`app/manager/entities.py`)
- *Scope Status*: In Scope (preserves compatibility).
- `MovementStepEntity`:
  - `step_id: str`
  - `step_index: int`
  - `from_account_id: str`
  - `to_account_id: str`
  - `currency: str`
  - `amount: float`
  - `status: str` (`"COMPLETED"`, `"COMPENSATING"`, `"FAILED"`)
  - `is_compensating: bool = False`

### 3.3 Manager Layer (`app/manager/`)
- *Scope Status*: In Scope.
- Coordinates business logic; passes through step events into response entities.

### 3.4 Manager &harr; Adapter Contract (`app/adapter/entities.py`)
- *Scope Status*: In Scope.
- `MovementStepRecordEntity`:
  - `step_id: str`
  - `transaction_id: str`
  - `step_index: int`
  - `from_account_id: str`
  - `to_account_id: str`
  - `currency: str`
  - `amount: Decimal`
  - `status: str` (`"COMPLETED"`, `"COMPENSATING"`, `"FAILED"`)
  - `is_compensating: bool = False`
  - `timestamp: datetime`

### 3.5 Adapter Layer (`app/adapter/wallet_adapter.py` & `db.py`)
- *Scope Status*: In Scope (primary implementation change).
- In `execute_multi_step_transaction`:
  ```python
  except Exception as exc:
      with self.db.lock:
          compensating_step_records: List[MovementStepRecord] = []
          curr_idx = len(executed_step_records) + 1

          for forward_step in reversed(executed_step_records):
              comp_from = forward_step.to_account_id
              comp_to = forward_step.from_account_id
              amt = forward_step.amount
              curr = forward_step.currency

              from_acc = self.db.accounts.get(comp_from)
              to_acc = self.db.accounts.get(comp_to)
              if from_acc and to_acc:
                  from_acc.balance -= amt
                  to_acc.balance += amt

              comp_step = MovementStepRecord(
                  step_id=f"step_comp_{uuid.uuid4().hex[:12]}",
                  transaction_id=transaction_id,
                  step_index=curr_idx,
                  from_account_id=comp_from,
                  to_account_id=comp_to,
                  currency=curr,
                  amount=amt,
                  status="COMPENSATING",
                  is_compensating=True,
                  timestamp=datetime.utcnow(),
              )
              compensating_step_records.append(comp_step)
              self.db.movement_steps[comp_step.step_id] = comp_step
              curr_idx += 1

          all_steps = executed_step_records + compensating_step_records
          txn_record = TransactionRecord(
              id=transaction_id,
              type=transaction_type,
              initiator_user_id=initiator_user_id,
              status="REVERSED",
              metadata=metadata,
              steps=all_steps,
              idempotency_key=idempotency_key,
              timestamp=datetime.utcnow(),
          )
          self.db.transactions[transaction_id] = txn_record

      raise exc
  ```

---

## 4. Test Plan (`tests/`)

1. **Compensating Step Event Creation Test**:
   - Trigger a transfer with `simulate_failure_at_step=2`.
   - Verify `StepExecutionError` is raised.
   - Inspect `db.transactions[txn_id].steps`:
     - Contains 2 steps: Forward Step 1 (`status="COMPLETED"`), followed by Compensating Step (`status="COMPENSATING"`, `from=system:outbound_pool:EUR`, `to=user:usr_alice:EUR`).
   - Verify both steps exist in `db.movement_steps`.

2. **Multi-Step Reverse Order Verification**:
   - Trigger quote acceptance with `simulate_failure_at_step=3` (where Steps 1 and 2 completed).
   - Verify compensating steps were emitted in reverse order:
     - Compensating Step 1 reverses forward Step 2 (Fee pool &rarr; FX pool).
     - Compensating Step 2 reverses forward Step 1 (FX pool &rarr; Alice USD).
   - Total steps in transaction: 4 (2 forward + 2 compensating in reverse order).

3. **Balance Invariant & Regression**:
   - Verify all 36 existing unit and concurrent tests continue to pass without regression.
