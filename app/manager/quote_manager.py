"""Quote Manager handling FX rate quotes, TTL expiry, and cross-currency conversions."""

import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.adapter.entities import (
    LedgerLegRecordEntity,
    QuoteRecordEntity,
    TransactionRecordEntity,
)
from app.adapter.quote_adapter import QuoteAdapter, quote_adapter
from app.adapter.wallet_adapter import (
    WalletAdapter,
    compute_payload_hash,
    wallet_adapter,
)
from app.exceptions import (
    IdempotencyConflictError,
    IdempotencyPayloadMismatchError,
    InvalidQuoteError,
    QuoteExpiredError,
    QuoteNotFoundError,
    RateNotFoundError,
    TransferExecutionError,
    UserNotFoundError,
)
from app.manager.entities import (
    AcceptQuoteRequestEntity,
    AcceptQuoteResponseEntity,
    CreateQuoteRequestEntity,
    GetRatesRequestEntity,
    QuoteResponseEntity,
    RatesResponseEntity,
)


class QuoteManager:
    """
    Manages FX rate quotes, 30s TTL expiry, and cross-currency FX conversion execution.
    - Uses QuoteAdapter for rates, quote persistence, and status.
    - Uses WalletAdapter for user balance validation and cross-currency money movement legs across pools.
    """

    def __init__(
        self,
        quote_adapter: Optional[QuoteAdapter] = None,
        wallet_adapter: Optional[WalletAdapter] = None,
    ) -> None:
        self.quote_adapter = quote_adapter or quote_adapter_instance
        self.wallet_adapter = wallet_adapter or wallet_adapter_instance

    def get_rates(self, request: GetRatesRequestEntity) -> RatesResponseEntity:
        """Returns all configured exchange rates and current fee percentage."""
        rates = self.quote_adapter.get_all_rates()
        fee_pct = self.quote_adapter.get_fee_percentage()
        return RatesResponseEntity(rates=rates, fee_percentage=fee_pct)

    def create_quote(self, request: CreateQuoteRequestEntity) -> QuoteResponseEntity:
        """
        Calculates converted amount and fees in minor units.
        Sets TTL to now + 30 seconds and persists quote with status PENDING.
        """
        if not self.wallet_adapter.user_exists(request.user_id):
            raise UserNotFoundError(f"User '{request.user_id}' does not exist")

        rate = self.quote_adapter.get_rate(request.from_currency, request.to_currency)
        if rate is None:
            raise RateNotFoundError(
                f"Exchange rate not available for pair {request.from_currency}/{request.to_currency}"
            )

        fee_pct = self.quote_adapter.get_fee_percentage()
        gross_to_amount = int(request.from_amount * rate)
        fee_amount = max(1, int(gross_to_amount * fee_pct))
        net_to_amount = gross_to_amount - fee_amount

        if net_to_amount <= 0:
            raise InvalidQuoteError("Amount is too small after fee deduction")

        quote_id = f"qt_{uuid.uuid4().hex[:10]}"
        now = datetime.utcnow()
        expires_at_dt = now + timedelta(seconds=30)
        expires_at_str = expires_at_dt.isoformat() + "Z"

        record = QuoteRecordEntity(
            quote_id=quote_id,
            user_id=request.user_id,
            from_currency=request.from_currency,
            to_currency=request.to_currency,
            from_amount=request.from_amount,
            exchange_rate=rate,
            gross_to_amount=gross_to_amount,
            fee_percentage=fee_pct,
            fee_amount=fee_amount,
            net_to_amount=net_to_amount,
            expires_at=expires_at_str,
            status="PENDING",
            created_at=now.isoformat() + "Z",
        )
        self.quote_adapter.save_quote(record)

        return QuoteResponseEntity(
            quote_id=quote_id,
            user_id=request.user_id,
            from_currency=request.from_currency,
            to_currency=request.to_currency,
            from_amount=request.from_amount,
            exchange_rate=rate,
            gross_to_amount=gross_to_amount,
            fee_percentage=fee_pct,
            fee_amount=fee_amount,
            net_to_amount=net_to_amount,
            expires_at=expires_at_str,
            validity_seconds=30,
        )

    def accept_quote(self, request: AcceptQuoteRequestEntity) -> AcceptQuoteResponseEntity:
        """
        Accepts and executes an FX conversion:
        1. Check idempotency and payload hash matching via wallet_adapter.
        2. Validate quote exists in quote_adapter, belongs to user, is PENDING, and within 30s TTL.
        3. Register PENDING transaction.
        4. Execute multi-hop pool sequence via wallet_adapter using fine-grained resource locks:
           - Leg 1: User(from_curr) -> Pool: FX Outbound(from_curr) [from_amount]
           - Leg 2: Pool: FX Outbound(from_curr) -> Pool: FX Inbound(to_curr) [gross_to_amount]
           - Leg 3: Pool: FX Inbound(to_curr) -> Pool: Fee(to_curr) [fee_amount]
           - Leg 4: Pool: FX Inbound(to_curr) -> User(to_curr) [net_to_amount]
        5. If any leg fails, perform LIFO compensation on all completed legs and mark tx REVERSED.
        6. Mark quote as ACCEPTED and record transaction as COMPLETED caching response payload.
        """
        # 1. Idempotency & payload hash verification
        incoming_hash = None
        if request.idempotency_key:
            payload_to_hash = {
                "quote_id": request.quote_id,
                "user_id": request.user_id,
            }
            incoming_hash = compute_payload_hash(payload_to_hash)
            existing = self.wallet_adapter.get_transaction_by_idempotency_key(
                request.idempotency_key
            )
            if existing:
                if (
                    existing.request_hash
                    and incoming_hash
                    and existing.request_hash != incoming_hash
                ):
                    raise IdempotencyPayloadMismatchError(
                        "Idempotency-Key reused with different request payload"
                    )
                if existing.status == "PENDING":
                    raise IdempotencyConflictError(
                        "A request with this Idempotency-Key is currently processing"
                    )
                if existing.status == "COMPLETED" and existing.response_payload:
                    return AcceptQuoteResponseEntity(**existing.response_payload)

        # 2. Quote validations
        quote = self.quote_adapter.get_quote(request.quote_id)
        if not quote:
            raise QuoteNotFoundError(f"Quote '{request.quote_id}' does not exist")

        if quote.user_id != request.user_id:
            raise InvalidQuoteError("Quote does not belong to the requesting user")

        if quote.status != "PENDING":
            raise InvalidQuoteError(f"Quote '{request.quote_id}' is already {quote.status}")

        # Check 30s TTL
        clean_expiry = quote.expires_at.rstrip("Z")
        expires_dt = datetime.fromisoformat(clean_expiry)
        if datetime.utcnow() > expires_dt:
            self.quote_adapter.update_quote_status(quote.quote_id, "EXPIRED")
            raise QuoteExpiredError(
                f"Quote '{quote.quote_id}' has expired (validity was 30 seconds)"
            )

        # 3. Register PENDING transaction
        tx_id = f"tx_fx_{uuid.uuid4().hex[:10]}"
        tx_record = self.wallet_adapter.get_or_create_transaction(
            tx_id=tx_id,
            user_id=quote.user_id,
            tx_type="FX_CONVERSION",
            metadata={
                "quote_id": quote.quote_id,
                "from_currency": quote.from_currency,
                "to_currency": quote.to_currency,
                "debited_amount": quote.from_amount,
                "credited_amount": quote.net_to_amount,
                "fee_amount": quote.fee_amount,
                "fee_currency": quote.to_currency,
            },
            idempotency_key=request.idempotency_key,
            request_hash=incoming_hash,
        )

        user_src_acc = f"{quote.user_id}:{quote.from_currency}"
        user_tgt_acc = f"{quote.user_id}:{quote.to_currency}"
        pool_outbound = f"pool:outbound:{quote.from_currency}"
        pool_inbound = f"pool:inbound:{quote.to_currency}"
        pool_fee = f"pool:fee:{quote.to_currency}"

        planned_legs = [
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=1,
                from_account_id=user_src_acc,
                to_account_id=pool_outbound,
                currency=quote.from_currency,
                amount=quote.from_amount,
            ),
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=2,
                from_account_id=pool_outbound,
                to_account_id=pool_inbound,
                currency=quote.to_currency,
                amount=quote.gross_to_amount,
            ),
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=3,
                from_account_id=pool_inbound,
                to_account_id=pool_fee,
                currency=quote.to_currency,
                amount=quote.fee_amount,
            ),
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=4,
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
            # 4. Saga Compensation in LIFO order
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
            self.quote_adapter.update_quote_status(quote.quote_id, "FAILED")
            raise TransferExecutionError(
                f"FX conversion failed: {str(exc)}; reversing operations completed successfully",
                legs_executed=len(completed_legs),
                reversed=True,
            ) from exc

        # 5. Finalize transaction and quote
        self.quote_adapter.update_quote_status(quote.quote_id, "ACCEPTED")

        response = AcceptQuoteResponseEntity(
            transaction_id=tx_id,
            quote_id=quote.quote_id,
            user_id=quote.user_id,
            from_currency=quote.from_currency,
            to_currency=quote.to_currency,
            debited_amount=quote.from_amount,
            credited_amount=quote.net_to_amount,
            fee_amount=quote.fee_amount,
            fee_currency=quote.to_currency,
            status="COMPLETED",
        )

        self.wallet_adapter.complete_transaction(
            tx_id=tx_id,
            response_payload=response.to_dict(),
        )

        return response


# Default singleton instances
quote_adapter_instance = quote_adapter
wallet_adapter_instance = wallet_adapter
quote_manager = QuoteManager(
    quote_adapter=quote_adapter_instance, wallet_adapter=wallet_adapter_instance
)
