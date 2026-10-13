"""Wallet manager coordinating business logic, quote lifecycle, and multi-step transactions."""

from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from typing import Any, Dict, List, Optional
import uuid

from app.adapter.entities import (
    IdempotencyRecordEntity,
    QuoteRecordEntity,
)
from app.adapter.wallet_adapter import WalletAdapter, wallet_adapter
from app.manager.entities import (
    AcceptQuoteRequestEntity,
    AcceptQuoteResponseEntity,
    QuoteRequestEntity,
    QuoteResponseEntity,
    TransactionHistoryResponseEntity,
    TransferRequestEntity,
    TransferResponseEntity,
    WalletBalanceResponseEntity,
)
from app.utils.exceptions import (
    IdempotencyConflictError,
    InvalidAmountError,
    QuoteAlreadyExecutedError,
    QuoteExpiredError,
    ResourceNotFoundError,
    TransferToSelfError,
)
from app.utils.locking import lock_manager
from app.utils.money import round_currency, to_decimal


class WalletManager:
    """Business logic coordinator for wallet operations."""

    def __init__(self, adapter: Optional[WalletAdapter] = None):
        self.adapter = adapter or wallet_adapter

    def get_users(self) -> List[Dict[str, Any]]:
        """List all users."""
        return [u.to_dict() for u in self.adapter.get_users()]

    def get_rates(self) -> List[Dict[str, Any]]:
        """List all exchange rates."""
        return [r.to_dict() for r in self.adapter.get_rates()]

    def get_balances(self, user_id: str) -> WalletBalanceResponseEntity:
        """Fetch multi-currency balances for a specific user."""
        user = self.adapter.get_user(user_id)
        if not user:
            raise ResourceNotFoundError(f"User {user_id} not found")

        balances = self.adapter.get_user_balances(user_id)
        return WalletBalanceResponseEntity(
            user_id=user_id,
            balances={curr: float(bal) for curr, bal in balances.items()},
        )

    def create_quote(self, request: QuoteRequestEntity) -> QuoteResponseEntity:
        """Create a 30-second conversion quote with 0.5% fee."""
        user = self.adapter.get_user(request.user_id)
        if not user:
            raise ResourceNotFoundError(f"User {request.user_id} not found")

        if request.from_currency.upper() == request.to_currency.upper():
            raise InvalidAmountError("Cannot convert between identical currencies")

        if request.amount <= 0:
            raise InvalidAmountError("Conversion amount must be greater than zero")

        rate = self.adapter.get_rate(request.from_currency, request.to_currency)
        if rate is None:
            raise ResourceNotFoundError(
                f"Exchange rate not found for {request.from_currency} -> {request.to_currency}"
            )

        from_amt = to_decimal(request.amount)
        base_converted = from_amt * rate
        fee_rate = Decimal("0.005")  # 0.5% FX fee
        fee_amt = round_currency(base_converted * fee_rate, request.to_currency)
        to_amt = round_currency(base_converted - fee_amt, request.to_currency)

        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=30)
        quote_id = f"qte_{uuid.uuid4().hex[:12]}"

        quote_entity = QuoteRecordEntity(
            id=quote_id,
            user_id=request.user_id,
            from_currency=request.from_currency.upper(),
            to_currency=request.to_currency.upper(),
            from_amount=from_amt,
            to_amount=to_amt,
            exchange_rate=rate,
            fee_rate=fee_rate,
            fee_amount=fee_amt,
            created_at=now,
            expires_at=expires_at,
            status="PENDING",
        )
        self.adapter.save_quote(quote_entity)

        return QuoteResponseEntity(
            quote_id=quote_id,
            user_id=request.user_id,
            from_currency=request.from_currency.upper(),
            to_currency=request.to_currency.upper(),
            from_amount=float(from_amt),
            to_amount=float(to_amt),
            exchange_rate=float(rate),
            fee_amount=float(fee_amt),
            fee_rate=float(fee_rate),
            created_at=now.isoformat(),
            expires_at=expires_at.isoformat(),
            status="PENDING",
        )

    def accept_quote(
        self, request: AcceptQuoteRequestEntity, simulate_failure_at_step: Optional[int] = None
    ) -> AcceptQuoteResponseEntity:
        """Accept quote and execute 3-step currency conversion."""
        locks_needed = [f"quote:{request.quote_id}"]
        if request.idempotency_key:
            locks_needed.append(f"idempotency:{request.idempotency_key}")

        with lock_manager.acquire_account_locks(locks_needed):
            quote = self.adapter.get_quote(request.quote_id)
            if not quote:
                raise ResourceNotFoundError(f"Quote {request.quote_id} not found")

            if request.user_id and quote.user_id != request.user_id:
                raise ResourceNotFoundError("Quote does not belong to the specified user")

            # Idempotency check (evaluated before status/expiry check to allow replay)
            if request.idempotency_key:
                payload_data = {
                    "op": "accept_quote",
                    "quote_id": request.quote_id,
                    "user_id": quote.user_id,
                }
                req_hash = hashlib.sha256(json.dumps(payload_data, sort_keys=True).encode()).hexdigest()
                cached_rec = self.adapter.get_idempotency_record(request.idempotency_key)
                if cached_rec:
                    if cached_rec.request_hash == req_hash:
                        cached_dict = cached_rec.response_payload
                        return AcceptQuoteResponseEntity(
                            transaction_id=cached_dict["transaction_id"],
                            quote_id=cached_dict["quote_id"],
                            user_id=cached_dict["user_id"],
                            from_currency=cached_dict["from_currency"],
                            from_amount=cached_dict["from_amount"],
                            to_currency=cached_dict["to_currency"],
                            to_amount=cached_dict["to_amount"],
                            fee_amount=cached_dict["fee_amount"],
                            status=cached_dict["status"],
                            timestamp=cached_dict["timestamp"],
                            steps=cached_dict.get("steps", []),
                        )
                    else:
                        raise IdempotencyConflictError(
                            "Idempotency key already used with different parameters"
                        )

            if quote.status == "ACCEPTED":
                raise QuoteAlreadyExecutedError("Quote has already been accepted and executed")

            # Expiration check
            if datetime.utcnow() > quote.expires_at:
                self.adapter.update_quote_status(quote.id, "EXPIRED")
                raise QuoteExpiredError("Quote has expired (validity window is 30 seconds)")

            txn_id = f"txn_conv_{uuid.uuid4().hex[:12]}"

            # 3-step Money Movement Model:
            # Step 1: User A {from_currency} -> FX Pool {from_currency} (from_amount)
            # Step 2: FX Pool {to_currency} -> Fee Pool {to_currency} (fee_amount)
            # Step 3: FX Pool {to_currency} -> User A {to_currency} (to_amount)
            user_from_acc = f"user:{quote.user_id}:{quote.from_currency}"
            fx_from_pool = f"system:fx_pool:{quote.from_currency}"
            fx_to_pool = f"system:fx_pool:{quote.to_currency}"
            fee_to_pool = f"system:fee_pool:{quote.to_currency}"
            user_to_acc = f"user:{quote.user_id}:{quote.to_currency}"

            steps = [
                (user_from_acc, fx_from_pool, quote.from_currency, quote.from_amount),
                (fx_to_pool, fee_to_pool, quote.to_currency, quote.fee_amount),
                (fx_to_pool, user_to_acc, quote.to_currency, quote.to_amount),
            ]

            metadata = {
                "quote_id": quote.id,
                "from_currency": quote.from_currency,
                "to_currency": quote.to_currency,
                "from_amount": float(quote.from_amount),
                "to_amount": float(quote.to_amount),
                "fee_amount": float(quote.fee_amount),
                "exchange_rate": float(quote.exchange_rate),
            }

            txn_record = self.adapter.execute_multi_step_transaction(
                transaction_id=txn_id,
                transaction_type="CONVERSION",
                initiator_user_id=quote.user_id,
                steps=steps,
                metadata=metadata,
                idempotency_key=request.idempotency_key,
                simulate_failure_at_step=simulate_failure_at_step,
            )

            self.adapter.update_quote_status(quote.id, "ACCEPTED")

            response = AcceptQuoteResponseEntity(
                transaction_id=txn_id,
                quote_id=quote.id,
                user_id=quote.user_id,
                from_currency=quote.from_currency,
                from_amount=float(quote.from_amount),
                to_currency=quote.to_currency,
                to_amount=float(quote.to_amount),
                fee_amount=float(quote.fee_amount),
                status="COMPLETED",
                timestamp=txn_record.timestamp.isoformat() if txn_record.timestamp else datetime.utcnow().isoformat(),
                steps=[s.to_dict() for s in txn_record.steps],
            )

            if request.idempotency_key:
                self.adapter.save_idempotency_record(
                    IdempotencyRecordEntity(
                        idempotency_key=request.idempotency_key,
                        operation="ACCEPT_QUOTE",
                        request_hash=req_hash,
                        response_payload=response.to_dict(),
                        status_code=200,
                        created_at=datetime.utcnow(),
                    )
                )

            return response

    def transfer_money(
        self, request: TransferRequestEntity, simulate_failure_at_step: Optional[int] = None
    ) -> TransferResponseEntity:
        """Transfer money peer-to-peer using 3-step pool movement."""
        if request.sender_id == request.recipient_id:
            raise TransferToSelfError("Sender and recipient cannot be the same user")

        if request.amount <= 0:
            raise InvalidAmountError("Transfer amount must be greater than zero")

        sender = self.adapter.get_user(request.sender_id)
        if not sender:
            raise ResourceNotFoundError(f"Sender {request.sender_id} not found")

        recipient = self.adapter.get_user(request.recipient_id)
        if not recipient:
            raise ResourceNotFoundError(f"Recipient {request.recipient_id} not found")

        curr = request.currency.upper()
        amount_dec = round_currency(request.amount, curr)

        locks_needed = []
        if request.idempotency_key:
            locks_needed.append(f"idempotency:{request.idempotency_key}")

        with lock_manager.acquire_account_locks(locks_needed):
            # Idempotency check
            if request.idempotency_key:
                payload_data = {
                    "op": "transfer",
                    "sender_id": request.sender_id,
                    "recipient_id": request.recipient_id,
                    "currency": curr,
                    "amount": float(amount_dec),
                }
                req_hash = hashlib.sha256(json.dumps(payload_data, sort_keys=True).encode()).hexdigest()
                cached_rec = self.adapter.get_idempotency_record(request.idempotency_key)
                if cached_rec:
                    if cached_rec.request_hash == req_hash:
                        cached_dict = cached_rec.response_payload
                        return TransferResponseEntity(
                            transfer_id=cached_dict["transfer_id"],
                            sender_id=cached_dict["sender_id"],
                            recipient_id=cached_dict["recipient_id"],
                            currency=cached_dict["currency"],
                            amount=cached_dict["amount"],
                            note=cached_dict["note"],
                            status=cached_dict["status"],
                            timestamp=cached_dict["timestamp"],
                            steps=cached_dict.get("steps", []),
                        )
                    else:
                        raise IdempotencyConflictError(
                            "Idempotency key already used with different parameters"
                        )

            txn_id = f"trf_{uuid.uuid4().hex[:12]}"

            # 3-step Money Movement Model:
            # Step 1: Sender {curr} -> Outbound Pool {curr} (amount)
            # Step 2: Outbound Pool {curr} -> Inbound Pool {curr} (amount)
            # Step 3: Inbound Pool {curr} -> Recipient {curr} (amount)
            sender_acc = f"user:{request.sender_id}:{curr}"
            outbound_pool = f"system:outbound_pool:{curr}"
            inbound_pool = f"system:inbound_pool:{curr}"
            recipient_acc = f"user:{request.recipient_id}:{curr}"

            steps = [
                (sender_acc, outbound_pool, curr, amount_dec),
                (outbound_pool, inbound_pool, curr, amount_dec),
                (inbound_pool, recipient_acc, curr, amount_dec),
            ]

            metadata = {
                "recipient_id": request.recipient_id,
                "currency": curr,
                "amount": float(amount_dec),
                "note": request.note,
            }

            txn_record = self.adapter.execute_multi_step_transaction(
                transaction_id=txn_id,
                transaction_type="TRANSFER",
                initiator_user_id=request.sender_id,
                steps=steps,
                metadata=metadata,
                idempotency_key=request.idempotency_key,
                simulate_failure_at_step=simulate_failure_at_step,
            )

            response = TransferResponseEntity(
                transfer_id=txn_id,
                sender_id=request.sender_id,
                recipient_id=request.recipient_id,
                currency=curr,
                amount=float(amount_dec),
                note=request.note,
                status="COMPLETED",
                timestamp=txn_record.timestamp.isoformat() if txn_record.timestamp else datetime.utcnow().isoformat(),
                steps=[s.to_dict() for s in txn_record.steps],
            )

            if request.idempotency_key:
                self.adapter.save_idempotency_record(
                    IdempotencyRecordEntity(
                        idempotency_key=request.idempotency_key,
                        operation="TRANSFER",
                        request_hash=req_hash,
                        response_payload=response.to_dict(),
                        status_code=200,
                        created_at=datetime.utcnow(),
                    )
                )

            return response


    def get_transactions(self, user_id: str) -> TransactionHistoryResponseEntity:
        """Retrieve user transaction history."""
        user = self.adapter.get_user(user_id)
        if not user:
            raise ResourceNotFoundError(f"User {user_id} not found")

        txns = self.adapter.get_user_transactions(user_id)
        return TransactionHistoryResponseEntity(
            user_id=user_id,
            transactions=[t.to_dict() for t in txns],
            total=len(txns),
        )


# Global singleton manager instance
wallet_manager = WalletManager()
