"""Wallet Adapter handling user balances and all money movement (P2P and FX)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.adapter.database import InMemoryDatabase, default_db
from app.adapter.entities import (
    AccountRecordEntity,
    IdempotencyRecordEntity,
    LedgerLegRecordEntity,
    TransactionRecordEntity,
)
from app.exceptions import AccountNotFoundError, InsufficientFundsError


class WalletAdapter:
    """
    Adapter responsible for user balance queries and money movement execution
    (both P2P transfers and FX conversion legs across pools).
    """

    def __init__(self, db: Optional[InMemoryDatabase] = None) -> None:
        self.db = db or default_db

    def user_exists(self, user_id: str) -> bool:
        """Check if any account belongs to the given user ID."""
        with self.db.global_lock:
            return any(acc.owner_id == user_id for acc in self.db.accounts.values())

    def get_user_balances(self, user_id: str) -> Dict[str, int]:
        """Return non-negative currency balances for a user."""
        with self.db.global_lock:
            balances: Dict[str, int] = {}
            for acc in self.db.accounts.values():
                if acc.owner_id == user_id:
                    balances[acc.currency] = acc.balance
            return balances

    def get_account(self, account_id: str) -> Optional[AccountRecordEntity]:
        """Retrieve an account by its unique account_id."""
        with self.db.global_lock:
            return self.db.accounts.get(account_id)

    def get_or_create_account(
        self, owner_id: str, currency: str, is_pool: bool = False
    ) -> AccountRecordEntity:
        """Get an existing account or create a new one with zero balance."""
        account_id = f"{owner_id}:{currency}"
        with self.db.global_lock:
            if account_id not in self.db.accounts:
                self.db.accounts[account_id] = AccountRecordEntity(
                    account_id=account_id,
                    owner_id=owner_id,
                    currency=currency,
                    balance=0,
                    is_pool=is_pool,
                )
            return self.db.accounts[account_id]

    def execute_transfer_leg(self, leg: LedgerLegRecordEntity) -> LedgerLegRecordEntity:
        """
        Atomically executes a single debit/credit leg between two accounts.
        Enforces sorted two-account lock acquisition to eliminate deadlocks.
        Used for both P2P transfers and FX conversion movements across pools.
        """
        acc_first, acc_second = sorted([leg.from_account_id, leg.to_account_id])
        lock1 = self.db.get_lock(acc_first)
        lock2 = self.db.get_lock(acc_second)

        with lock1:
            with lock2:
                from_acc = self.db.accounts.get(leg.from_account_id)
                to_acc = self.db.accounts.get(leg.to_account_id)

                if not from_acc:
                    if leg.from_account_id.startswith("pool:"):
                        from_acc = self.get_or_create_account(
                            owner_id=leg.from_account_id.split(":")[1],
                            currency=leg.currency,
                            is_pool=True,
                        )
                    else:
                        raise AccountNotFoundError(
                            f"Source account {leg.from_account_id} not found"
                        )

                if not to_acc:
                    owner = leg.to_account_id.split(":")[0]
                    is_pool = leg.to_account_id.startswith("pool:")
                    to_acc = self.get_or_create_account(
                        owner_id=owner, currency=leg.currency, is_pool=is_pool
                    )

                # Check non-negative constraint on user accounts
                if not from_acc.is_pool and from_acc.balance < leg.amount:
                    raise InsufficientFundsError(
                        f"Account {leg.from_account_id} has insufficient balance ({from_acc.balance} < {leg.amount})"
                    )

                # Mutate balances atomically
                from_acc.balance -= leg.amount
                from_acc.updated_at = datetime.utcnow().isoformat()
                to_acc.balance += leg.amount
                to_acc.updated_at = datetime.utcnow().isoformat()

                leg.status = "COMPLETED"

                # Link leg to transaction if transaction record exists
                if leg.transaction_id in self.db.transactions:
                    self.db.transactions[leg.transaction_id].legs.append(leg)

                return leg

    def record_transaction(self, tx: TransactionRecordEntity) -> TransactionRecordEntity:
        """Persist or update a transaction record."""
        with self.db.global_lock:
            self.db.transactions[tx.transaction_id] = tx
            return tx

    def get_transaction(self, tx_id: str) -> Optional[TransactionRecordEntity]:
        """Retrieve a transaction by transaction_id."""
        with self.db.global_lock:
            return self.db.transactions.get(tx_id)

    def get_user_transactions(self, user_id: str) -> List[TransactionRecordEntity]:
        """Retrieve all transactions involving a user, sorted descending by created_at."""
        with self.db.global_lock:
            tx_list: List[TransactionRecordEntity] = []
            for tx in self.db.transactions.values():
                if tx.user_id == user_id:
                    tx_list.append(tx)
                elif (
                    tx.metadata.get("recipient_user_id") == user_id
                    or tx.metadata.get("sender_user_id") == user_id
                ):
                    tx_list.append(tx)
            tx_list.sort(key=lambda t: t.created_at, reverse=True)
            return tx_list

    def check_or_reserve_idempotency(self, key: str) -> Optional[IdempotencyRecordEntity]:
        """
        Check if an idempotency key exists.
        If it does, return the existing record.
        If not, atomically reserve it with status 'PROCESSING' and return None.
        """
        with self.db.global_lock:
            if key in self.db.idempotency:
                return self.db.idempotency[key]
            self.db.idempotency[key] = IdempotencyRecordEntity(
                idempotency_key=key,
                status="PROCESSING",
            )
            return None

    def save_idempotency_response(
        self, key: str, status_code: int, response_data: Dict[str, Any]
    ) -> None:
        """Mark idempotency record as COMPLETED with the cached response."""
        with self.db.global_lock:
            if key in self.db.idempotency:
                rec = self.db.idempotency[key]
                rec.status = "COMPLETED"
                rec.response_code = status_code
                rec.response_data = response_data


# Default singleton instance
wallet_adapter = WalletAdapter()
