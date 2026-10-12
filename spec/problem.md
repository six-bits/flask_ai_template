# Problem Statement: Multi-Currency Wallet Service

## 1. Overview
Build a multi-currency wallet application backend. Each user holds balances across multiple currencies. Users can query their balances, request exchange quotes valid for 30 seconds, accept valid quotes to execute currency conversions minus a small fee, transfer funds to other users in a specified currency, and view their transaction history.

## 2. Core Requirements

1. **User Accounts & Multi-Currency Balances**:
   - Each user can hold balances in multiple supported currencies (e.g., `USD`, `EUR`, `GBP`, `JPY`, `CAD`).
   - Balances must never drop below zero (no overdraft allowed).
   - System starts with pre-seeded users and initial balances.

2. **Exchange Rates & Currency Quotes**:
   - The system maintains an exchange rate table for currency pairs.
   - Users can request a quote to convert an amount from `from_currency` to `to_currency`.
   - Each quote is valid for exactly **30 seconds** from creation.
   - Quote includes calculated target amount, applied exchange rate, fee rate, and fee amount.

3. **Quote Acceptance & Currency Conversion**:
   - If the user accepts the quote within the 30-second validity window:
     - Validate that the user has sufficient balance in `from_currency`.
     - Deduct `from_amount` from `from_currency`.
     - Credit `to_amount` (net after fee) to `to_currency`.
     - Mark the quote as accepted/executed.
   - If accepted after 30 seconds:
     - Reject the conversion with an expiration error (`422 Unprocessable Entity` or `400 Bad Request`).
   - Quotes cannot be accepted more than once.
   - **Idempotency**: An idempotency key (via `Idempotency-Key` header or `idempotency_key` payload property) must be supported. Repeated requests with the identical idempotency key return the original conversion result without repeating balance mutations.

4. **Peer-to-Peer Transfers**:
   - Users can send money to other users in any supported currency.
   - Validate that:
     - Sender and recipient are distinct valid users.
     - Sender has sufficient balance in the target currency.
     - Transfer amount is positive.
   - Balance updates must be atomic across sender and recipient.
   - **Idempotency**: Transfers require/support an idempotency key (via `Idempotency-Key` header or `idempotency_key` payload property) to prevent double transfers upon network retries.

5. **Balance Inspection & Transaction History**:
   - Users can query their current balances across all currencies.
   - Users can view chronological transaction history (conversions, transfers sent, transfers received).

6. **Seed Data**:
   - Pre-populated set of users with initial multi-currency balances.
   - Pre-populated table of exchange rates.

## 3. Advanced Ledger & Execution Requirements

1. **Multi-Step Money Movement Model**:
   - Every transaction is modeled and executed as a sequence of discrete, recorded money movement steps between accounts:
     - **Transfer Flow**:
       1. `Person A ({currency})` &rarr; `Outbound Pool ({currency})`
       2. `Outbound Pool ({currency})` &rarr; `Inbound Pool ({currency})`
       3. `Inbound Pool ({currency})` &rarr; `Person B ({currency})`
     - **Quote Conversion Flow**:
       1. `Person A ({from_currency})` &rarr; `FX Pool ({from_currency})`
       2. `FX Pool ({to_currency})` &rarr; `Fee Pool ({to_currency})`
       3. `FX Pool ({to_currency})` &rarr; `Person A ({to_currency})`
   - Every movement step must be individually recorded in an audit ledger with `step_id`, `transaction_id`, `step_index`, `from_account`, `to_account`, `currency`, `amount`, and `status`.

2. **Midway Failure & Step Rollback**:
   - If any step fails during transaction execution (e.g. balance check, unexpected failure), all previously completed steps in that transaction must be reversed immediately in reverse order via compensating entries.
   - The transaction status is marked as `FAILED` or `REVERSED`.

3. **Fine-Grained Account-Level Locking**:
   - Concurrency control must not lock the whole system or entire database.
   - **Only the accounts involved in the specific money movement steps must be locked** for the duration of the transaction.
   - To prevent deadlocks, accounts must always be locked in a strictly sorted, deterministic canonical order.

4. **Robust Idempotency Validation**:
   - Idempotency keys (`idempotency_key` via header or body) must be tracked.
   - Replaying a request with the same idempotency key and matching parameters must return the original cached response without re-executing balance debits or credits.
   - Conflicting requests (same key, different payload) must be rejected with an appropriate error (e.g. 409 Conflict / 400 Bad Request).

5. **In-Memory Storage & Cross-Cutting Architecture**:
   - In-memory state and seed data live in `app/adapter/db.py` used by the adapter layer.
   - Cross-cutting functionality across layers (such as locking mechanisms, currency math, and helpers) must reside in `app/utils/`.

## 4. Constraints & Design Principles
- **Monetary Precision**: Handle amounts without floating-point rounding issues using `Decimal`.
- **Layered Architecture**: Strict `Service -> Manager -> Adapter` pattern:
  - Service Layer: HTTP routes, parameters, JSON Schema validation.
  - Service <-> Manager Contract: Domain dataclasses in `app/manager/entities.py`.
  - Manager Layer: Business logic (quote expiry, fees, balance validations, multi-step orchestration) in `app/manager/wallet_manager.py`.
  - Manager <-> Adapter Contract: Persistence dataclasses in `app/adapter/entities.py`.
  - Adapter Layer: In-memory datastore management in `app/adapter/wallet_adapter.py` referencing `app/adapter/db.py`.
- **Validation**: Strict JSON Schema Draft 2020-12 validation for all mutation endpoints.


