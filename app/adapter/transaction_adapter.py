"""Adapter managing the immutable transaction audit ledger."""

from typing import List
from app.adapter.entities import TransactionRecordEntity


class TransactionAdapter:
    """In-memory append-only audit ledger recording all financial movements."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Clear ledger records."""
        self._ledger: List[TransactionRecordEntity] = []

    def record(self, transaction: TransactionRecordEntity) -> TransactionRecordEntity:
        """Append a completed transaction to the immutable ledger."""
        self._ledger.append(transaction)
        return transaction

    def get_by_user(self, user_id: str) -> List[TransactionRecordEntity]:
        """Retrieve chronological transactions for a user, newest first."""
        matching = [tx for tx in self._ledger if tx.user_id == user_id]
        # Return newest first
        return list(reversed(matching))


# Default singleton instance
transaction_adapter = TransactionAdapter()
