# 003: Quote Locking, Currency-Conserved FX Hops, and Decimal Rounding Specification

**Scope: Full Stack** (Adapter &rarr; Manager &rarr; Service)

---

## 1. Overview & Scope

### 1.1 Purpose
This specification enhances the **Multi-Currency Wallet Service** by resolving three critical architectural and financial calculation flaws identified in the Staff Engineer code review:

1. **Flaw 1: Quote Concurrency & Locking**:
   - Prevent the double-execution race condition where concurrent requests race to accept the same quote.
   - Add a reentrant lock (`threading.RLock`) to `QuoteRecordEntity`.
   - Implement an atomic lease state transition (`PENDING` &rarr; `PROCESSING`) inside `QuoteAdapter` / `QuoteManager` under the quote lock before any balance legs execute.
   - Any concurrent acceptance request immediately encounters status `PROCESSING` or `ACCEPTED` and is rejected with `InvalidQuoteError` (HTTP 422 Unprocessable Entity or 409 Conflict).

2. **Flaw 2: Currency-Conserved Multi-Hop FX Ledger (Additional Hops)**:
   - Eliminate the dimensional accounting error where a USD account (`pool:outbound:USD`) is debited in EUR minor units.
   - Strictly enforce **currency conservation**: every account in the system is strictly single-currency, and every ledger leg transfers funds *only* between accounts of the identical currency.
   - Bridge cross-currency conversions using dedicated currency-specific clearing accounts (`pool:fx:<CURRENCY>`).
   - FX conversion is structured into **5 distinct single-currency legs**:
     - **Source Currency Book (`from_currency`, e.g. USD)**:
       - Leg 1: User (`usr_alice:USD`) &rarr; Outbound Pool (`pool:outbound:USD`) [`amount: from_amount`]
       - Leg 2: Outbound Pool (`pool:outbound:USD`) &rarr; FX Clearing (`pool:fx:USD`) [`amount: from_amount`]
     - **Target Currency Book (`to_currency`, e.g. EUR)**:
       - Leg 3: FX Clearing (`pool:fx:EUR`) &rarr; Inbound Pool (`pool:inbound:EUR`) [`amount: gross_to_amount`]
       - Leg 4: Inbound Pool (`pool:inbound:EUR`) &rarr; Fee Pool (`pool:fee:EUR`) [`amount: fee_amount`]
       - Leg 5: Inbound Pool (`pool:inbound:EUR`) &rarr; User (`usr_alice:EUR`) [`amount: net_to_amount`]
   - Intermediate settlement pools (`outbound` and `inbound`) net out to zero for each conversion. The institution's FX position increases in `from_currency` and decreases in `to_currency`.
   - On mid-flight failure, reverse legs run in LIFO order to restore both books.

3. **Flaw 3: Decimal Precision & Banker's Rounding**:
   - Eliminate binary floating-point precision truncation bugs (e.g. `int(1.15 * 100)` evaluating to `114` instead of `115`).
   - Use Python's `decimal.Decimal` with explicit banker's rounding (`ROUND_HALF_EVEN`) for all rate conversions and fee computations.
   - Guarantee exact integer minor-unit conversion math across all currency pairs.

---

## 2. Service Layer (`app/service/`)

### 2.1 HTTP Routes & Schema
No breaking changes to HTTP route signatures. Request validation in [app/service/schema.py](file:///Users/hammad/Projects/flask_ai_template/app/service/schema.py) continues to enforce integer minor units:
- `POST /quotes`
- `POST /quotes/accept` (and `POST /quotes/<quote_id>/accept`)
- `POST /transfers`
- `GET /users/<user_id>/balances`
- `GET /users/<user_id>/transactions`
- `GET /rates`

### 2.2 Error Mappings in `app/service/api.py`
- `InvalidQuoteError` continues to map to **HTTP 422 Unprocessable Entity** (or 409 when already processing/accepted).
- `QuoteExpiredError` maps to **HTTP 422 Unprocessable Entity**.
- `InsufficientFundsError` maps to **HTTP 422 Unprocessable Entity**.
- `IdempotencyConflictError` maps to **HTTP 409 Conflict**.
- `IdempotencyPayloadMismatchError` maps to **HTTP 400 Bad Request**.

---

## 3. Service &harr; Manager Contract (`app/manager/entities.py`)

Data contracts remain clean, typed, and backwards-compatible:
- [`CreateQuoteRequestEntity`](file:///Users/hammad/Projects/flask_ai_template/app/manager/entities.py#L36-L42): `from_amount: int`
- [`QuoteResponseEntity`](file:///Users/hammad/Projects/flask_ai_template/app/manager/entities.py#L44-L62): `gross_to_amount: int`, `fee_amount: int`, `net_to_amount: int`, `exchange_rate: float`
- [`AcceptQuoteRequestEntity`](file:///Users/hammad/Projects/flask_ai_template/app/manager/entities.py#L64-L70): `quote_id: str`, `user_id: str`, `idempotency_key: Optional[str]`
- [`AcceptQuoteResponseEntity`](file:///Users/hammad/Projects/flask_ai_template/app/manager/entities.py#L72-L89): `debited_amount: int`, `credited_amount: int`, `fee_amount: int`, `status: str`

---

## 4. Manager &harr; Adapter Contract (`app/adapter/entities.py`)

### 4.1 Update `QuoteRecordEntity` to Own Its Own Resource Lock
Add a reentrant lock to `QuoteRecordEntity` to prevent race conditions during quote acceptance:

```python
# app/adapter/entities.py

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class QuoteRecordEntity:
    """Storage entity for an FX rate quote, owning its own lock for thread-safe state transitions."""
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int         # Minor units
    exchange_rate: float
    gross_to_amount: int     # Minor units (calculated via Decimal)
    fee_percentage: float
    fee_amount: int          # Minor units (calculated via Decimal)
    net_to_amount: int       # Minor units (gross_to_amount - fee_amount)
    expires_at: str          # ISO-8601 timestamp string
    status: str = "PENDING"  # PENDING | PROCESSING | ACCEPTED | EXPIRED | FAILED
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("lock", None)
        return d
```

---

## 5. Adapter Layer (`app/adapter/`)

### 5.1 `InMemoryDatabase` (`app/adapter/database.py`)
Add pre-seeded settlement pools for `pool:fx:<CURRENCY>` alongside existing `outbound`, `inbound`, and `fee` pools:

```python
# Preloaded system settlement pools (USD, EUR, GBP, JPY)
supported_currencies = ["USD", "EUR", "GBP", "JPY"]
pool_prefixes = ["pool:outbound", "pool:inbound", "pool:fee", "pool:fx"]
for prefix in pool_prefixes:
    for curr in supported_currencies:
        acc_id = f"{prefix}:{curr}"
        self.accounts[acc_id] = AccountRecordEntity(
            account_id=acc_id,
            owner_id="system_pool",
            currency=curr,
            balance=0,
            is_pool=True,
        )
```

### 5.2 `QuoteAdapter` (`app/adapter/quote_adapter.py`)
Add an atomic claim method that inspects status, checks TTL, and transitions status to `PROCESSING` under the quote's reentrant lock:

```python
class QuoteAdapter:
    ...
    def claim_quote_for_execution(self, quote_id: str, user_id: str) -> QuoteRecordEntity:
        """
        Thread-safely validates and claims a quote for execution.
        Acquires quote.lock, verifies existence, ownership, TTL, and status == 'PENDING',
        then transitions status to 'PROCESSING'.
        """
        quote = self.get_quote(quote_id)
        if not quote:
            raise QuoteNotFoundError(f"Quote '{quote_id}' does not exist")

        with quote.lock:
            if quote.user_id != user_id:
                raise InvalidQuoteError("Quote does not belong to the requesting user")

            if quote.status != "PENDING":
                raise InvalidQuoteError(f"Quote '{quote_id}' is already {quote.status}")

            clean_expiry = quote.expires_at.rstrip("Z")
            expires_dt = datetime.fromisoformat(clean_expiry)
            if datetime.utcnow() > expires_dt:
                quote.status = "EXPIRED"
                raise QuoteExpiredError(f"Quote '{quote.quote_id}' has expired (validity was 30 seconds)")

            # Atomically claim quote
            quote.status = "PROCESSING"
            return quote
```

---

## 6. Manager Layer (`app/manager/`)

### 6.1 `QuoteManager.create_quote` (Decimal Calculations)
Eliminate float truncation using `Decimal` and `ROUND_HALF_EVEN`:

```python
from decimal import Decimal, ROUND_HALF_EVEN

class QuoteManager:
    ...
    def create_quote(self, request: CreateQuoteRequestEntity) -> QuoteResponseEntity:
        if not self.wallet_adapter.user_exists(request.user_id):
            raise UserNotFoundError(f"User '{request.user_id}' does not exist")

        rate = self.quote_adapter.get_rate(request.from_currency, request.to_currency)
        if rate is None:
            raise RateNotFoundError(
                f"Exchange rate not available for pair {request.from_currency}/{request.to_currency}"
            )

        fee_pct = self.quote_adapter.get_fee_percentage()

        # Decimal precision calculations
        from_amount_dec = Decimal(request.from_amount)
        rate_dec = Decimal(str(rate))
        fee_pct_dec = Decimal(str(fee_pct))

        gross_dec = (from_amount_dec * rate_dec).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
        gross_to_amount = int(gross_dec)

        fee_dec = (gross_dec * fee_pct_dec).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
        fee_amount = max(1, int(fee_dec))

        net_to_amount = gross_to_amount - fee_amount
        if net_to_amount <= 0:
            raise InvalidQuoteError("Amount is too small after fee deduction")

        ...
```

### 6.2 `QuoteManager.accept_quote` (Quote Locking + 5-Leg Currency-Conserved Hops)
Orchestrates quote leasing and 5 currency-conserved balance movement legs:

```python
    def accept_quote(self, request: AcceptQuoteRequestEntity) -> AcceptQuoteResponseEntity:
        # 1. Idempotency replay check
        if request.idempotency_key:
            ...

        # 2. Atomically claim quote under lock (PENDING -> PROCESSING)
        quote = self.quote_adapter.claim_quote_for_execution(request.quote_id, request.user_id)

        # 3. Register PENDING transaction
        tx_id = f"tx_fx_{uuid.uuid4().hex[:10]}"
        ...

        # 4. Multi-hop 5-leg currency-conserved execution
        # Source book accounts (all in from_currency)
        user_src_acc = f"{quote.user_id}:{quote.from_currency}"
        pool_outbound = f"pool:outbound:{quote.from_currency}"
        pool_fx_src = f"pool:fx:{quote.from_currency}"

        # Target book accounts (all in to_currency)
        pool_fx_tgt = f"pool:fx:{quote.to_currency}"
        pool_inbound = f"pool:inbound:{quote.to_currency}"
        pool_fee = f"pool:fee:{quote.to_currency}"
        user_tgt_acc = f"{quote.user_id}:{quote.to_currency}"

        planned_legs = [
            # Leg 1: User(from_curr) -> Pool: Outbound(from_curr)
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=1,
                from_account_id=user_src_acc,
                to_account_id=pool_outbound,
                currency=quote.from_currency,
                amount=quote.from_amount,
            ),
            # Leg 2: Pool: Outbound(from_curr) -> Pool: FX(from_curr)
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=2,
                from_account_id=pool_outbound,
                to_account_id=pool_fx_src,
                currency=quote.from_currency,
                amount=quote.from_amount,
            ),
            # Leg 3: Pool: FX(to_curr) -> Pool: Inbound(to_curr)
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=3,
                from_account_id=pool_fx_tgt,
                to_account_id=pool_inbound,
                currency=quote.to_currency,
                amount=quote.gross_to_amount,
            ),
            # Leg 4: Pool: Inbound(to_curr) -> Pool: Fee(to_curr)
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=4,
                from_account_id=pool_inbound,
                to_account_id=pool_fee,
                currency=quote.to_currency,
                amount=quote.fee_amount,
            ),
            # Leg 5: Pool: Inbound(to_curr) -> User(to_curr)
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=5,
                from_account_id=pool_inbound,
                to_account_id=user_tgt_acc,
                currency=quote.to_currency,
                amount=quote.net_to_amount,
            ),
        ]

        completed_legs: List[LedgerLegRecordEntity] = []
        try:
            for leg in planned_legs:
                executed = self.wallet_adapter.execute_transfer_leg(leg)
                completed_legs.append(executed)
        except Exception as exc:
            # 5. Saga Compensation in LIFO order
            with quote.lock:
                quote.status = "FAILED"
            step_num = len(completed_legs) + 1
            for comp_target in reversed(completed_legs):
                step_num += 1
                rev_leg = LedgerLegRecordEntity(
                    leg_id=f"rev_{uuid.uuid4().hex[:8]}",
                    transaction_id=tx_id,
                    step_number=step_num,
                    from_account_id=comp_target.to_account_id,
                    to_account_id=comp_target.from_account_id,
                    currency=comp_target.currency,
                    amount=comp_target.amount,
                    is_reversal=True,
                )
                self.wallet_adapter.execute_transfer_leg(rev_leg)

            self.wallet_adapter.fail_or_reverse_transaction(tx_id, status="REVERSED")
            raise TransferExecutionError(
                f"FX conversion failed: {str(exc)}; reversing operations completed successfully",
                legs_executed=len(completed_legs),
                reversed=True,
            ) from exc

        # 6. Finalize quote and transaction
        with quote.lock:
            quote.status = "ACCEPTED"

        ...
```

---

## 7. Test Plan (`tests/`)

### 7.1 Quote Concurrency Test (`tests/test_managers.py`, `tests/test_wallet_api.py`)
- **Race Condition Verification**:
  - Spawn 10 concurrent threads simultaneously calling `accept_quote()` with the exact same `quote_id` (without idempotency keys or with unique keys).
  - Verify that **exactly 1 thread succeeds** (`status == "COMPLETED"`).
  - Verify that **all 9 other threads fail** with `InvalidQuoteError` ("already PROCESSING" or "already ACCEPTED").
  - Verify that user balance is debited and credited **only once**.

### 7.2 Currency Conservation Test (`tests/test_managers.py`)
- **Ledger Verification**:
  - Perform FX conversion of 10,000 USD to EUR.
  - Verify that 5 distinct legs were created.
  - Legs 1 & 2 have `currency == "USD"`, moving between `usr_alice:USD`, `pool:outbound:USD`, and `pool:fx:USD`.
  - Legs 3, 4, 5 have `currency == "EUR"`, moving between `pool:fx:EUR`, `pool:inbound:EUR`, `pool:fee:EUR`, and `usr_alice:EUR`.
  - Verify `pool:outbound:USD` balance after conversion is `0` USD.
  - Verify `pool:inbound:EUR` balance after conversion is `0` EUR.
  - Verify no USD account ever holds or experiences transactions in EUR.

### 7.3 Decimal Banker's Rounding Test (`tests/test_managers.py`)
- **Precision Verification**:
  - Test an amount and rate that causes float precision loss (e.g. `100 * 1.15`).
  - Verify calculated gross amount is `115` (not `114`).
  - Test banker's rounding on half-way numbers (e.g. `.5` rounds to nearest even integer).

### 7.4 Existing Test Suite Regression
- Ensure all existing 52 tests in `tests/test_adapters.py`, `tests/test_managers.py`, and `tests/test_wallet_api.py` continue to pass cleanly.
