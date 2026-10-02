"""Quote manager coordinating guaranteed quote generation and atomic conversion with locking and idempotency."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
import uuid

from app.adapter.entities import QuoteRecordEntity, TransactionRecordEntity
from app.adapter.exchange_rate_adapter import ExchangeRateAdapter, exchange_rate_adapter
from app.adapter.quote_adapter import QuoteAdapter, quote_adapter
from app.adapter.transaction_adapter import TransactionAdapter, transaction_adapter
from app.adapter.user_wallet_adapter import UserWalletAdapter, user_wallet_adapter
from app.manager.entities import (
    AcceptQuoteRequestEntity,
    AcceptQuoteResponseEntity,
    CreateQuoteRequestEntity,
    QuoteResponseEntity,
)
from app.manager.errors import (
    IdenticalCurrenciesError,
    InsufficientFundsError,
    InvalidAmountError,
    QuoteAlreadyAcceptedError,
    QuoteExpiredError,
    QuoteNotFoundError,
    QuoteOwnershipError,
    UnsupportedCurrencyError,
    UserNotFoundError,
)
from app.manager.idempotency_manager import IdempotencyManager, idempotency_manager
from app.manager.lock_manager import LockManager, lock_manager


class QuoteManager:
    """Manager coordinating foreign exchange quotes and entity-attached atomic conversions."""

    def __init__(
        self,
        rate_adapter: Optional[ExchangeRateAdapter] = None,
        quote_adpt: Optional[QuoteAdapter] = None,
        wallet_adpt: Optional[UserWalletAdapter] = None,
        tx_adpt: Optional[TransactionAdapter] = None,
        lock_mgr: Optional[LockManager] = None,
        idemp_mgr: Optional[IdempotencyManager] = None,
    ) -> None:
        self.rate_adapter = rate_adapter or exchange_rate_adapter
        self.quote_adapter = quote_adpt or quote_adapter
        self.wallet_adapter = wallet_adpt or user_wallet_adapter
        self.tx_adapter = tx_adpt or transaction_adapter
        self.lock_manager = lock_mgr or lock_manager
        self.idempotency_manager = idemp_mgr or idempotency_manager

    def create_quote(self, request: CreateQuoteRequestEntity) -> QuoteResponseEntity:
        """Create a 30-second locked exchange quote with upfront fee calculation."""
        if not self.wallet_adapter.user_exists(request.user_id):
            raise UserNotFoundError(request.user_id)

        if request.from_currency == request.to_currency:
            raise IdenticalCurrenciesError()

        if request.from_amount <= 0:
            raise InvalidAmountError("Conversion amount must be greater than zero")

        rate_str = self.rate_adapter.get_rate(request.from_currency, request.to_currency)
        if rate_str is None:
            raise UnsupportedCurrencyError(f"{request.from_currency}->{request.to_currency}")

        # Compute target and 0.5% fee rounding immediately to integer minor units
        rate_dec = Decimal(rate_str)
        from_amt_dec = Decimal(request.from_amount)
        gross_target = round(from_amt_dec * rate_dec)
        fee_amount = round(gross_target * Decimal("0.005"))
        to_amount = int(gross_target - fee_amount)
        fee_amount_int = int(fee_amount)

        quote_id = f"quote_{uuid.uuid4().hex}"
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        expires_at = (now + timedelta(seconds=30)).isoformat()

        record = QuoteRecordEntity(
            quote_id=quote_id,
            user_id=request.user_id,
            from_currency=request.from_currency,
            to_currency=request.to_currency,
            from_amount=request.from_amount,
            to_amount=to_amount,
            exchange_rate=rate_str,
            fee_amount=fee_amount_int,
            fee_percentage="0.005",
            created_at=created_at,
            expires_at=expires_at,
            status="PENDING",
        )
        saved = self.quote_adapter.save_quote(record)

        return QuoteResponseEntity(
            quote_id=saved.quote_id,
            user_id=saved.user_id,
            from_currency=saved.from_currency,
            to_currency=saved.to_currency,
            from_amount=saved.from_amount,
            to_amount=saved.to_amount,
            exchange_rate=saved.exchange_rate,
            fee_amount=saved.fee_amount,
            fee_percentage=saved.fee_percentage,
            created_at=saved.created_at,
            expires_at=saved.expires_at,
            status=saved.status,
        )

    def accept_quote(self, request: AcceptQuoteRequestEntity) -> AcceptQuoteResponseEntity:
        """Accept quote and execute atomic conversion through entity-attached clearing stages."""
        # 1. Idempotency Check & Reservation
        endpoint = f"/quotes/{request.quote_id}/accept"
        if request.idempotency_key:
            req_hash = self.idempotency_manager.compute_hash(
                endpoint=endpoint,
                user_id=request.user_id,
                payload_json=request.request_payload_json,
            )
            is_replayed, cached_body, _ = self.idempotency_manager.check_or_reserve(
                key=request.idempotency_key,
                user_id=request.user_id,
                endpoint=endpoint,
                request_hash=req_hash,
            )
            if is_replayed and cached_body:
                return AcceptQuoteResponseEntity(
                    quote_id=cached_body["quote_id"],
                    status=cached_body["status"],
                    from_currency=cached_body["from_currency"],
                    to_currency=cached_body["to_currency"],
                    from_amount=cached_body["from_amount"],
                    to_amount=cached_body["to_amount"],
                    fee_amount=cached_body["fee_amount"],
                    executed_at=cached_body["executed_at"],
                    balances=cached_body["balances"],
                    is_replayed=True,
                )

        try:
            quote = self.quote_adapter.get_quote(request.quote_id)
            if quote is None:
                raise QuoteNotFoundError(request.quote_id)

            if quote.user_id != request.user_id:
                raise QuoteOwnershipError()

            # 2. Deadlock-free resource locking on quote and user
            with self.lock_manager.acquire_ordered_locks(quote.quote_id, quote.user_id):
                # Re-verify quote status under lock
                quote = self.quote_adapter.get_quote(request.quote_id)
                assert quote is not None

                if quote.status == "ACCEPTED":
                    raise QuoteAlreadyAcceptedError()

                now = datetime.now(timezone.utc)
                expires_at_dt = datetime.fromisoformat(quote.expires_at)
                if now > expires_at_dt or quote.status == "EXPIRED":
                    self.quote_adapter.update_status(quote.quote_id, "EXPIRED")
                    raise QuoteExpiredError()

                # Check funds availability
                available = self.wallet_adapter.get_balance(quote.user_id, quote.from_currency)
                if available < quote.from_amount:
                    raise InsufficientFundsError(quote.from_currency, available, quote.from_amount)

                executed_at = datetime.now(timezone.utc).isoformat()

                # Multi-stage State Machine with Entity-Attached Domain Events
                # Stage 1: Debit source to outbound transit pool (event attached to user)
                self.wallet_adapter.debit_user_for_conversion(
                    user_id=quote.user_id,
                    currency=quote.from_currency,
                    amount=quote.from_amount,
                    quote_id=quote.quote_id,
                    timestamp=executed_at,
                )

                # Stage 2: Settle FX swap & allocate fee (event attached to outbound clearing pool)
                self.wallet_adapter.clear_fx_pools(
                    from_curr=quote.from_currency,
                    to_curr=quote.to_currency,
                    from_amount=quote.from_amount,
                    to_amount=quote.to_amount,
                    fee_amount=quote.fee_amount,
                    quote_id=quote.quote_id,
                    timestamp=executed_at,
                )

                # Stage 3: Credit target currency to user from inbound transit pool (event attached to user)
                self.wallet_adapter.credit_user_from_inbound(
                    user_id=quote.user_id,
                    currency=quote.to_currency,
                    amount=quote.to_amount,
                    quote_id=quote.quote_id,
                    timestamp=executed_at,
                )

                # Stage 4: Finalize quote status (event attached to quote entity)
                self.quote_adapter.update_status(quote.quote_id, "ACCEPTED")

                # Record in transaction ledger
                tx_id = f"tx_conv_{uuid.uuid4().hex}"
                description = (
                    f"Converted {quote.from_amount} {quote.from_currency} to {quote.to_amount} {quote.to_currency} "
                    f"(Fee: {quote.fee_amount} {quote.to_currency})"
                )
                self.tx_adapter.record(
                    TransactionRecordEntity(
                        transaction_id=tx_id,
                        user_id=quote.user_id,
                        type="CONVERSION",
                        from_currency=quote.from_currency,
                        to_currency=quote.to_currency,
                        from_amount=quote.from_amount,
                        to_amount=quote.to_amount,
                        fee_amount=quote.fee_amount,
                        quote_id=quote.quote_id,
                        timestamp=executed_at,
                        description=description,
                    )
                )

                user = self.wallet_adapter.get_user(quote.user_id)
                current_balances = user.balances if user else {}

                response = AcceptQuoteResponseEntity(
                    quote_id=quote.quote_id,
                    status="ACCEPTED",
                    from_currency=quote.from_currency,
                    to_currency=quote.to_currency,
                    from_amount=quote.from_amount,
                    to_amount=quote.to_amount,
                    fee_amount=quote.fee_amount,
                    executed_at=executed_at,
                    balances=current_balances,
                    is_replayed=False,
                )

                # 3. Mark idempotency key COMPLETED
                if request.idempotency_key:
                    self.idempotency_manager.complete(
                        key=request.idempotency_key,
                        status_code=200,
                        response_body=response.to_dict(),
                    )

                return response

        except Exception:
            if request.idempotency_key:
                self.idempotency_manager.release(request.idempotency_key)
            raise


# Default singleton instance
quote_manager = QuoteManager()
