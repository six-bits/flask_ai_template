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
5. **Seed Cards**: Initial cards and credit limits available on startup.

## 2. Core Concepts & Math
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
