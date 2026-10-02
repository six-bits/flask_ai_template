# Multi-Currency Wallet Problem Statement

## 1. Raw Problem Statement

We are building a multi-currency wallet application for an interview round.
Each user holds balances in multiple currencies. A user can request a quote to convert money from one currency to another, with the quote remaining valid for 30 seconds. If accepted within this window, the conversion is executed at the quoted rate minus a small fee. Users can also transfer money to one another in any supported currency, and view their current balances as well as chronological transaction history. Initial seed data includes a set of users, starting balances, and an exchange rates matrix.

The system will be built using Python/Flask following a strict layered architecture (`Service` -> `Manager` -> `Adapter`) with in-memory persistence data structures.

## 2. Phased Roadmap

- **Phase 1 (Current)**:
  - Architecture & Core API Design
  - Domain Entity Contracts (Service <-> Manager and Manager <-> Adapter)
  - Orchestration & Layer Implementation (One Function Per Class pattern)
  - In-memory seed data setup (users, balances, exchange rates)
  - End-to-End (E2E) integration & unit test suite
- **Phase 2 (Upcoming)**:
  - Idempotency support across mutation endpoints (`/transfers`, `/quotes/{id}/accept`)
- **Phase 3 (Upcoming)**:
  - Thread safety and concurrency controls (account balance locking, race condition prevention on quote acceptance and peer-to-peer transfers)

## 3. Goals & Key Capabilities

1. **User Balances**:
   - Query user balances across all held currencies (`USD`, `EUR`, `GBP`, `JPY`, etc.).
2. **Quote Generation**:
   - Request guaranteed conversion quotes with explicit expiration (`now + 30 seconds`), fee computation, and rate locking.
3. **Quote Acceptance**:
   - Convert currency if the quote is valid and active (< 30s elapsed), ensuring sender has sufficient balance in the source currency.
4. **Peer-to-Peer Transfer**:
   - Transfer funds from User A to User B in a specified currency, validating sender funds and recipient existence.
5. **Transaction Ledger & History**:
   - Maintain an immutable audit log of transfers (sent and received) and conversions (source deducted, target credited, fee logged).
6. **Pre-seeded State**:
   - Seeded users (`user_1: Alice`, `user_2: Bob`, `user_3: Charlie`).
   - Initial wallet balances in multiple currencies.
   - Seeded exchange rates table for currency pairs.

## 4. Constraints & Architectural Rules

- **Strict Layer Separation**:
  - `Service Layer` (`app/service/`): HTTP routing, query/path parameter handling, JSON Schema validation. No direct adapter access.
  - `Manager Layer` (`app/manager/`): Business logic, quote validity checks, balance availability checks, entity transformation. One function per class.
  - `Adapter Layer` (`app/adapter/`): In-memory persistence, ledger management, exchange rate lookups. One function per class.
- **Contract Boundary Isolation**:
  - Service communicates with Manager only via `app/manager/entities.py`.
  - Manager communicates with Adapter only via `app/adapter/entities.py`.
- **Financial Precision (Minor Units & Integers)**:
  - All monetary values (balances, transfer amounts, quote amounts, and fees) MUST be represented in currency minor units (e.g. cents, pence) as integers/longs (`int`). No floating-point or decimal-string monetary representations are exposed or stored.
- **Write-Ahead Logging (WAL) & Clearing Transit Pools**:
  - All mutating financial operations (P2P transfers and quote conversions) MUST follow a strict Write-Ahead Log (WAL) pattern: an immutable event is published to the WAL *prior* to executing each state mutation.
  - Funds in transit flow through internal system clearing accounts (`SYSTEM_OUTBOUND_TRANSIT`, `SYSTEM_INBOUND_TRANSIT`, `SYSTEM_FEE_COLLECTOR`) to guarantee double-entry balance conservation ($\sum \Delta \text{Balances} = 0$) at every step.
- **Time Validity**:
  - Quotes expire strictly after 30 seconds.

## 5. Dual-Write Flaw & Transactional Outbox Pattern

### The Problem with Standalone WAL Event Logging
In the initial naive implementation, events are published directly to a separate log (`WalAdapter`) before mutating the in-memory entity state (`UserWalletAdapter`). If the subsequent in-memory or database update fails (e.g. unexpected exception, network blip, validation failure), the event has already been recorded/published—creating a **phantom event** for a financial mutation that never committed.

### The Solution: Transactional Outbox via Entity-Attached Domain Events
1. **Events Attached to Entities**: Domain events (`OutboxEventRecordEntity`) are attached directly to the aggregate/entity itself (e.g., `UserRecordEntity`, `QuoteRecordEntity`).
2. **Atomic Persistence**: When the entity is updated/saved in the repository/adapter, the state change and its associated outbox events are committed **together in the exact same atomic transaction**. If the write fails, both the state mutation and the event are rolled back.
3. **Outbox Event Scraper**: A dedicated Manager (`OutboxManager`) scrapes unpublished outbox events across all entities, aggregates them into a chronological event log, and supports acknowledging/marking them as published.
4. **Polling Foundation**: This manager provides the query and acknowledgment foundation for an external background polling service that delivers events downstream reliably.

## 6. Concurrency & Idempotency Requirements

### The Concurrency Problem (Race Conditions & Overdrafts)
- Concurrent requests mutating the same user balance (e.g. concurrent transfers or quote acceptances) can interleave check-and-debit operations, causing **double spending**, balance overdrafts below zero, or state corruption.
- Bidirectional transfers between two users simultaneously (Alice $\rightarrow$ Bob and Bob $\rightarrow$ Alice) risk **circular deadlocks** if resource locks are acquired in arbitrary order.
- Shared transit clearing pools require synchronized state transitions to prevent race conditions during money movement.

### The Idempotency Problem (Network Retries & Duplicate Submissions)
- In unreliable network conditions, client retries or duplicate POST submissions can cause double transfers or duplicate currency conversions.
- The system must support an `Idempotency-Key` header on all mutating financial endpoints (`POST /transfers`, `POST /quotes/<quote_id>/accept`).
- Retrying with the same key and identical payload must replay the cached original response without re-executing state mutations or appending duplicate ledger/outbox events.
- Retrying with the same key but different payload must be rejected with an idempotency mismatch error (`400 Bad Request` or `422 Unprocessable Entity`).
- Concurrent requests arriving with the same key while the first is in-flight must be rejected with `409 Conflict`.



