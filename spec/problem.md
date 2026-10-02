# Problem Statement: In-Memory Multi-Currency Wallet Service

## 1. Context & Overview
Design and implement an in-memory multi-currency wallet service for an LLD (Low-Level Design) interview context. 

The service manages user balances across multiple currencies, enables FX conversions with time-limited guaranteed rate quotes, provides peer-to-peer (P2P) money transfers, and tracks transaction histories and account balances.

The service must be initialized with a base state (pre-seeded users, balances, and exchange rates).

---

## 2. Core Requirements

### 2.1 Minor Units (Long/Integer Representation)
- All monetary amounts (balances, transfer amounts, converted amounts, fees) MUST be represented in **minor units** as integers/longs (e.g., cents: `$10.50` &rarr; `1050`, `¥500` &rarr; `500`).
- No floating-point types for monetary amounts to eliminate precision loss.

### 2.2 Multi-Currency User Accounts
- Users can hold balances in multiple currencies simultaneously (e.g., USD, EUR, GBP, JPY).
- Users can query their balances for all held currencies.
- Users can inspect their complete transaction history with legs and status.

### 2.3 Time-Limited FX Quotes & Conversion
- **Quote Generation**: A user can request an FX quote to convert an amount (`from_amount` in minor units) from `from_currency` to `to_currency`.
- **TTL**: Each quote has a strict validity window of **30 seconds**.
- **Quote Execution**: User accepts the quote by providing `quote_id` in the request body schema. If accepted within the 30-second window, the conversion is executed at the quoted rate minus a specified small transaction fee. If expired, the quote cannot be accepted.

### 2.4 Peer-to-Peer (P2P) Transfers
- Users can send funds to other users within the system in minor units.

### 2.5 Multi-Hop Pool Movement
- Money cannot simply jump directly from User A to User B in an unrecorded mutation.
- **P2P Movement**: Must move through settlement pools:
  $$\text{User A} \longrightarrow \text{Outbound Pool} \longrightarrow \text{Inbound Pool} \longrightarrow \text{User B}$$
- **FX Movement**: Must move through cross-currency pools:
  $$\text{User A (CCY A)} \longrightarrow \text{FX Outbound Pool (CCY A)} \longrightarrow \text{FX Inbound Pool (CCY B)} \longrightarrow \text{User A (CCY B)}$$
  (along with fee transfer to a dedicated fee pool).

### 2.6 Failure Compensation (Reversing Operations)
- If any step in the multi-hop balance movement fails mid-flight (e.g., recipient invalid, transfer constraint violated, or injected simulated failure), the system must execute compensating reversing operations in reverse order (LIFO) to return the system and user balances to their original consistent state.

### 2.7 Concurrency & Idempotency
- **Concurrency**: Operations must be thread-safe. Concurrent operations on the same user or pool must not result in race conditions, negative balances, or deadlocks.
- **Idempotency**: Mutating requests (transfers, quote executions) must accept an idempotency key to prevent double-spending or duplicate executions.

### 2.8 Seed Base State
- Preloaded accounts (e.g., Alice, Bob, Charlie) with starting balances in minor units.
- Preloaded FX exchange rates table.
- System pool accounts for outbound, inbound, FX reserve, and fee collection.

---

## 3. Architecture & Manager Organization
- **In-Memory Storage (Single Source of Truth)**: Centralized `InMemoryWalletRepository` (the adapter layer) that encapsulates all in-memory entities (`accounts`, `quotes`, `transactions`, `idempotency`, `rates`) and fine-grained account locks.
- **Layered Architecture**: Strict `Service` $\rightarrow$ `Manager` $\rightarrow$ `Adapter` pattern.
- **Domain Manager Organization**:
  1. **User Account Manager**: Handles user balance retrieval and transaction history queries.
  2. **Quote Manager**: Handles quote generation, rate lookups, and quote acceptance/execution.
  3. **Transfer Manager**: Handles P2P transfer orchestration across settlement pools and saga compensations.
- **Data Contracts**: Explicit dataclasses for Service $\leftrightarrow$ Manager and Manager $\leftrightarrow$ Adapter boundaries.
