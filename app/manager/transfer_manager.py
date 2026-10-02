"""Transfer manager coordinating peer-to-peer transfers with concurrency locking and idempotency."""

from datetime import datetime, timezone
from typing import Optional
import uuid

from app.adapter.entities import TransactionRecordEntity
from app.adapter.transaction_adapter import TransactionAdapter, transaction_adapter
from app.adapter.user_wallet_adapter import UserWalletAdapter, user_wallet_adapter
from app.manager.entities import TransferRequestEntity, TransferResponseEntity
from app.manager.errors import (
    InsufficientFundsError,
    InvalidAmountError,
    SelfTransferError,
    UserNotFoundError,
)
from app.manager.idempotency_manager import IdempotencyManager, idempotency_manager
from app.manager.lock_manager import LockManager, lock_manager


class TransferManager:
    """Manager coordinating P2P money transfers through transit clearing stages."""

    def __init__(
        self,
        wallet_adpt: Optional[UserWalletAdapter] = None,
        tx_adpt: Optional[TransactionAdapter] = None,
        lock_mgr: Optional[LockManager] = None,
        idemp_mgr: Optional[IdempotencyManager] = None,
    ) -> None:
        self.wallet_adapter = wallet_adpt or user_wallet_adapter
        self.tx_adapter = tx_adpt or transaction_adapter
        self.lock_manager = lock_mgr or lock_manager
        self.idempotency_manager = idemp_mgr or idempotency_manager

    def transfer(self, request: TransferRequestEntity) -> TransferResponseEntity:
        """Execute a peer-to-peer transfer via sequential entity-attached transit stages."""
        # 1. Idempotency Check & Reservation
        if request.idempotency_key:
            req_hash = self.idempotency_manager.compute_hash(
                endpoint="/transfers",
                user_id=request.from_user_id,
                payload_json=request.request_payload_json,
            )
            is_replayed, cached_body, _ = self.idempotency_manager.check_or_reserve(
                key=request.idempotency_key,
                user_id=request.from_user_id,
                endpoint="/transfers",
                request_hash=req_hash,
            )
            if is_replayed and cached_body:
                return TransferResponseEntity(
                    transfer_id=cached_body["transfer_id"],
                    from_user_id=cached_body["from_user_id"],
                    to_user_id=cached_body["to_user_id"],
                    currency=cached_body["currency"],
                    amount=cached_body["amount"],
                    timestamp=cached_body["timestamp"],
                    from_user_balance=cached_body["from_user_balance"],
                    is_replayed=True,
                )

        try:
            if request.from_user_id == request.to_user_id:
                raise SelfTransferError()

            if request.amount <= 0:
                raise InvalidAmountError("Transfer amount must be greater than zero")

            # 2. Deadlock-free lexicographical resource locking
            with self.lock_manager.acquire_ordered_locks(request.from_user_id, request.to_user_id):
                if not self.wallet_adapter.user_exists(request.from_user_id):
                    raise UserNotFoundError(request.from_user_id)

                if not self.wallet_adapter.user_exists(request.to_user_id):
                    raise UserNotFoundError(request.to_user_id)

                available = self.wallet_adapter.get_balance(request.from_user_id, request.currency)
                if available < request.amount:
                    raise InsufficientFundsError(request.currency, available, request.amount)

                transfer_id = f"tx_transfer_{uuid.uuid4().hex}"
                timestamp = datetime.now(timezone.utc).isoformat()

                # Multi-stage State Machine with Entity-Attached Domain Events
                # Stage 1: Debit sender to outbound transit pool (event attached to sender)
                sender_remaining_balance = self.wallet_adapter.debit_sender_to_outbound(
                    sender_id=request.from_user_id,
                    currency=request.currency,
                    amount=request.amount,
                    transfer_id=transfer_id,
                    timestamp=timestamp,
                )

                # Stage 2: Transit Hop (event attached to outbound clearing pool)
                self.wallet_adapter.route_outbound_to_inbound(
                    currency=request.currency,
                    amount=request.amount,
                    transfer_id=transfer_id,
                    timestamp=timestamp,
                )

                # Stage 3: Inbound Settlement to recipient (event attached to recipient)
                self.wallet_adapter.settle_inbound_to_recipient(
                    recipient_id=request.to_user_id,
                    currency=request.currency,
                    amount=request.amount,
                    transfer_id=transfer_id,
                    timestamp=timestamp,
                )

                # Sender transaction ledger entry
                self.tx_adapter.record(
                    TransactionRecordEntity(
                        transaction_id=f"tx_sent_{uuid.uuid4().hex[:12]}",
                        user_id=request.from_user_id,
                        type="TRANSFER_SENT",
                        currency=request.currency,
                        amount=request.amount,
                        fee_amount=0,
                        related_user_id=request.to_user_id,
                        timestamp=timestamp,
                        description=f"Transferred {request.amount} {request.currency} to {request.to_user_id}",
                    )
                )

                # Recipient transaction ledger entry
                self.tx_adapter.record(
                    TransactionRecordEntity(
                        transaction_id=f"tx_recv_{uuid.uuid4().hex[:12]}",
                        user_id=request.to_user_id,
                        type="TRANSFER_RECEIVED",
                        currency=request.currency,
                        amount=request.amount,
                        fee_amount=0,
                        related_user_id=request.from_user_id,
                        timestamp=timestamp,
                        description=f"Received {request.amount} {request.currency} from {request.from_user_id}",
                    )
                )

                response = TransferResponseEntity(
                    transfer_id=transfer_id,
                    from_user_id=request.from_user_id,
                    to_user_id=request.to_user_id,
                    currency=request.currency,
                    amount=request.amount,
                    timestamp=timestamp,
                    from_user_balance=sender_remaining_balance,
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
transfer_manager = TransferManager()
