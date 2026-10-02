"""User Account Manager handling user balance queries and transaction history."""

from typing import List, Optional

from app.adapter.wallet_adapter import WalletAdapter, wallet_adapter
from app.exceptions import UserNotFoundError
from app.manager.entities import (
    GetTransactionHistoryRequestEntity,
    GetUserBalancesRequestEntity,
    TransactionHistoryItemEntity,
    TransactionHistoryResponseEntity,
    TransactionLegViewEntity,
    UserBalancesResponseEntity,
)


class UserAccountManager:
    """Manages user wallet balance queries and historical ledger reporting."""

    def __init__(self, wallet_adapter: Optional[WalletAdapter] = None) -> None:
        self.wallet_adapter = wallet_adapter or wallet_adapter_instance

    def get_balances(self, request: GetUserBalancesRequestEntity) -> UserBalancesResponseEntity:
        """Retrieves all non-zero currency balances for a given user."""
        if not self.wallet_adapter.user_exists(request.user_id):
            raise UserNotFoundError(f"User '{request.user_id}' does not exist")

        balances = self.wallet_adapter.get_user_balances(request.user_id)
        return UserBalancesResponseEntity(user_id=request.user_id, balances=balances)

    def get_transaction_history(
        self, request: GetTransactionHistoryRequestEntity
    ) -> TransactionHistoryResponseEntity:
        """Retrieves all historical transactions and constituent legs for a given user."""
        if not self.wallet_adapter.user_exists(request.user_id):
            raise UserNotFoundError(f"User '{request.user_id}' does not exist")

        records = self.wallet_adapter.get_user_transactions(request.user_id)
        items: List[TransactionHistoryItemEntity] = []

        for r in records:
            leg_views = [
                TransactionLegViewEntity(
                    leg_id=leg.leg_id,
                    step_number=leg.step_number,
                    from_account=leg.from_account_id,
                    to_account=leg.to_account_id,
                    currency=leg.currency,
                    amount=leg.amount,
                    is_reversal=leg.is_reversal,
                    status=leg.status,
                )
                for leg in r.legs
            ]
            items.append(
                TransactionHistoryItemEntity(
                    transaction_id=r.transaction_id,
                    type=r.transaction_type,
                    status=r.status,
                    created_at=r.created_at,
                    details=r.metadata,
                    legs=leg_views,
                )
            )

        return TransactionHistoryResponseEntity(user_id=request.user_id, transactions=items)


# Default singleton instance
wallet_adapter_instance = wallet_adapter
user_account_manager = UserAccountManager(wallet_adapter=wallet_adapter_instance)
