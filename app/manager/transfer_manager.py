"""Transfer Manager handling P2P money transfers across settlement pools with saga compensation."""

import uuid
from typing import List, Optional

from app.adapter.entities import (
    LedgerLegRecordEntity,
    TransactionRecordEntity,
)
from app.adapter.wallet_adapter import WalletAdapter, wallet_adapter
from app.exceptions import (
    IdempotencyConflictError,
    TransferExecutionError,
    UserNotFoundError,
    WalletError,
)
from app.manager.entities import (
    P2PTransferRequestEntity,
    P2PTransferResponseEntity,
)


class TransferManager:
    """Manages P2P transfers via Outbound and Inbound pools with saga compensation."""

    def __init__(self, wallet_adapter: Optional[WalletAdapter] = None) -> None:
        self.wallet_adapter = wallet_adapter or wallet_adapter_instance

    def transfer(self, request: P2PTransferRequestEntity) -> P2PTransferResponseEntity:
        """
        Executes a 3-hop P2P transfer:
        1. Check idempotency via wallet_adapter.
        2. Validate sender != recipient and both users exist via wallet_adapter.
        3. Multi-hop execution via wallet_adapter:
           - Leg 1: Sender(CCY) -> Pool: Outbound(CCY) [amount]
           - Leg 2: Pool: Outbound(CCY) -> Pool: Inbound(CCY) [amount]
           - Leg 3: Pool: Inbound(CCY) -> Recipient(CCY) [amount]
        4. If any leg fails, perform LIFO compensation on all completed legs.
        5. Mark transaction COMPLETED and cache idempotency result.
        """
        # 1. Idempotency check
        if request.idempotency_key:
            existing = self.wallet_adapter.check_or_reserve_idempotency(request.idempotency_key)
            if existing:
                if existing.status == "PROCESSING":
                    raise IdempotencyConflictError(
                        "A request with this Idempotency-Key is currently processing"
                    )
                if existing.status == "COMPLETED":
                    return P2PTransferResponseEntity(**existing.response_data)

        # 2. Validations
        if request.sender_user_id == request.recipient_user_id:
            raise WalletError("Sender and recipient cannot be the same user")

        if not self.wallet_adapter.user_exists(request.sender_user_id):
            raise UserNotFoundError(f"Sender user '{request.sender_user_id}' does not exist")

        if not self.wallet_adapter.user_exists(request.recipient_user_id):
            raise UserNotFoundError(f"Recipient user '{request.recipient_user_id}' does not exist")

        # 3. Multi-hop pool movements
        tx_id = f"tx_p2p_{uuid.uuid4().hex[:10]}"
        sender_acc = f"{request.sender_user_id}:{request.currency}"
        recipient_acc = f"{request.recipient_user_id}:{request.currency}"
        pool_outbound = f"pool:outbound:{request.currency}"
        pool_inbound = f"pool:inbound:{request.currency}"

        tx_record = TransactionRecordEntity(
            transaction_id=tx_id,
            user_id=request.sender_user_id,
            transaction_type="P2P_TRANSFER",
            status="PENDING",
            legs=[],
            metadata={
                "sender_user_id": request.sender_user_id,
                "recipient_user_id": request.recipient_user_id,
                "currency": request.currency,
                "amount": request.amount,
            },
        )
        self.wallet_adapter.record_transaction(tx_record)

        planned_legs = [
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=1,
                from_account_id=sender_acc,
                to_account_id=pool_outbound,
                currency=request.currency,
                amount=request.amount,
            ),
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=2,
                from_account_id=pool_outbound,
                to_account_id=pool_inbound,
                currency=request.currency,
                amount=request.amount,
            ),
            LedgerLegRecordEntity(
                leg_id=f"leg_{uuid.uuid4().hex[:8]}",
                transaction_id=tx_id,
                step_number=3,
                from_account_id=pool_inbound,
                to_account_id=recipient_acc,
                currency=request.currency,
                amount=request.amount,
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

            tx_record.status = "REVERSED"
            raise TransferExecutionError(
                f"Transfer failed: {str(exc)}; reversing operations completed successfully",
                legs_executed=len(completed_legs),
                reversed=True,
            ) from exc

        # 5. Finalize transaction
        tx_record.status = "COMPLETED"

        response = P2PTransferResponseEntity(
            transaction_id=tx_id,
            sender_user_id=request.sender_user_id,
            recipient_user_id=request.recipient_user_id,
            currency=request.currency,
            amount=request.amount,
            status="COMPLETED",
            legs_executed=len(completed_legs),
        )

        if request.idempotency_key:
            self.wallet_adapter.save_idempotency_response(
                request.idempotency_key, status_code=200, response_data=response.to_dict()
            )

        return response


# Default singleton instance
wallet_adapter_instance = wallet_adapter
transfer_manager = TransferManager(wallet_adapter=wallet_adapter_instance)
