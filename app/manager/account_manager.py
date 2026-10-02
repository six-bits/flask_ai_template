"""Account manager handling balance inquiries and transaction ledger queries."""

from typing import Optional

from app.adapter.transaction_adapter import TransactionAdapter, transaction_adapter
from app.adapter.user_wallet_adapter import UserWalletAdapter, user_wallet_adapter
from app.manager.entities import (
    GetBalancesRequestEntity,
    GetBalancesResponseEntity,
    GetTransactionsRequestEntity,
    GetTransactionsResponseEntity,
    TransactionItemEntity,
)
from app.manager.errors import UserNotFoundError


class AccountManager:
    """Manager coordinating balance retrieval and ledger inspection."""

    def __init__(
        self,
        wallet_adapter: Optional[UserWalletAdapter] = None,
        tx_adapter: Optional[TransactionAdapter] = None,
    ) -> None:
        self.wallet_adapter = wallet_adapter or user_wallet_adapter
        self.tx_adapter = tx_adapter or transaction_adapter

    def get_balances(self, request: GetBalancesRequestEntity) -> GetBalancesResponseEntity:
        """Retrieve all balances for a user in minor units."""
        user = self.wallet_adapter.get_user(request.user_id)
        if user is None:
            raise UserNotFoundError(request.user_id)

        return GetBalancesResponseEntity(
            user_id=user.user_id,
            balances=user.balances,
        )

    def get_transactions(
        self, request: GetTransactionsRequestEntity
    ) -> GetTransactionsResponseEntity:
        """Retrieve chronological audit ledger for a user (newest first)."""
        if not self.wallet_adapter.user_exists(request.user_id):
            raise UserNotFoundError(request.user_id)

        records = self.tx_adapter.get_by_user(request.user_id)
        items = [
            TransactionItemEntity(
                transaction_id=rec.transaction_id,
                user_id=rec.user_id,
                type=rec.type,
                currency=rec.currency,
                from_currency=rec.from_currency,
                to_currency=rec.to_currency,
                from_amount=rec.from_amount,
                to_amount=rec.to_amount,
                amount=rec.amount,
                fee_amount=rec.fee_amount,
                related_user_id=rec.related_user_id,
                quote_id=rec.quote_id,
                timestamp=rec.timestamp,
                description=rec.description,
            )
            for rec in records
        ]

        return GetTransactionsResponseEntity(
            user_id=request.user_id,
            transactions=items,
        )


# Default singleton instance
account_manager = AccountManager()
