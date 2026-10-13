# Problem Statement: High-Demand Flash Sale Inventory Reservation Engine

## 1. Problem Overview
We are building an in-memory inventory reservation service for high-demand flash sales (e.g., concert ticket drops, limited edition item releases). In these scenarios, large numbers of concurrent users race for a finite amount of inventory.

A traditional immediate checkout model causes race conditions, cart lockouts, and poor user experience under heavy contention. To provide fairness and consistency, the system implements a two-phase reservation lease pattern:
1. **Hold Phase**: When a user begins checkout, they acquire a time-bounded reservation lease holding the requested quantity of items for strictly 30 seconds.
2. **Commit Phase**: If the user confirms checkout within 30 seconds, the hold transitions to a confirmed order, permanently deducting inventory.
3. **Release Phase**: If the lease expires (after 30 seconds without confirmation) or the user cancels the hold, the reserved items immediately return to the available stock pool for other buyers.

## 2. Core Functional Requirements
1. **Inventory Initialization & Seeding**:
   - Items are initialized with an `item_id`, `name`, starting `total_stock`, and a `max_per_user` purchase limit.
2. **Reservation Lease (30-Second TTL Hold)**:
   - A buyer requests a reservation lease for a specified quantity $Q$ of an item.
   - The hold is valid for 30 seconds from creation.
   - While held, those items cannot be claimed, reserved, or purchased by other buyers.
3. **Checkout Confirmation**:
   - If the user confirms checkout within 30 seconds, the reservation transitions to `CONFIRMED`.
   - Confirmed items are permanently deducted from available inventory.
4. **Lease Expiration & Automatic Release**:
   - If 30 seconds elapse without confirmation, the reservation transitions to `EXPIRED`.
   - Expired items immediately return to available stock for other users.
5. **Reservation Cancellation**:
   - A user can explicitly cancel an active reservation during the 30-second window.
   - Cancelled items immediately return to available stock.
6. **Anti-Hoarding & Purchase Limits**:
   - Each item enforces a strict `max_per_user` limit.
   - The limit accounts for both active (unexpired) reservations and confirmed purchases by the user.
   - Requests exceeding this limit must be rejected.
7. **Live Stock Availability**:
   - Users and admins can query real-time stock levels for items: total stock, available stock, currently held/reserved stock, and confirmed sold stock.

## 3. Concurrency & Performance Constraints
1. **Zero Overselling Guarantee**: Stock must never drop below zero under any concurrency level or race conditions.
2. **Granular Concurrency**: Contention on Item A must never block operations on Item B (per-item concurrency controls).
3. **Deterministic Lease Expiration**: The state of leases must be accurately reconciled upon access (lazy expiration) so that available stock is always fresh and correct without race hazards.

## 4. Expected API Behavior
- `GET /health`: Basic health check.
- `GET /items`: List all items with live stock metrics (`total_stock`, `available_stock`, `held_stock`, `confirmed_stock`).
- `GET /items/<item_id>`: Fetch live stock metrics for a specific item.
- `POST /reservations`: Create a 30-second reservation lease (`item_id`, `user_id`, `quantity`).
- `POST /reservations/<reservation_id>/confirm`: Confirm checkout for an active reservation within the 30s lease window.
- `POST /reservations/<reservation_id>/cancel`: Explicitly cancel an active reservation before lease expiry.
