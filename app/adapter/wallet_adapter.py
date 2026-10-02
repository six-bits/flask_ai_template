"""Wallet Adapter handling user balances and all money movement (P2P and FX) using resource locks."""

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.adapter.database import InMemoryDatabase, default_db
from app.adapter.entities import (
    AccountRecordEntity,
    LedgerLegRecordEntity,
    TransactionRecordEntity,
)
from app.exceptions import (
    AccountNotFoundError,
    IdempotencyConflictError,
    IdempotencyPayloadMismatchError,
    InsufficientFundsError,
)


def compute_payload_hash(payload: Dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 hash of the canonical request payload."""
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class WalletAdapter:
    """
    Adapter responsible for user balance queries and money movement execution
    (both P2P transfers and FX conversion legs across pools).
    Enforces resource-level locking strictly on involved accounts during money movements.
    """

    def __init__(self, db: Optional[InMemoryDatabase] = None) -> None:
        self.db = db or default_db

    def user_exists(self, user_id: str) -> bool:
        """Check if any account belongs to the given user ID (lock-free)."""
        return any(acc.owner_id == user_id for acc in self.db.accounts.values())

    def get_user_balances(self, user_id: str) -> Dict[str, int]:
        """Return non-negative currency balances for a user (lock-free)."""
        balances: Dict[str, int] = {}
        for acc in self.db.accounts.values():
            if acc.owner_id == user_id:
                balances[acc.currency] = acc.balance
        return balances

    def get_account(self, account_id: str) -> Optional[AccountRecordEntity]:
        """Retrieve an account by its unique account_id (lock-free)."""
        return self.db.accounts.get(account_id)

    def get_or_create_account(
        self, owner_id: str, currency: str, is_pool: bool = False
    ) -> AccountRecordEntity:
        """Get an existing account or create a new one with zero balance."""
        account_id = f"{owner_id}:{currency}"
        if account_id not in self.db.accounts:
            self.db.accounts.setdefault(
                account_id,
                AccountRecordEntity(
                    account_id=account_id,
                    owner_id=owner_id,
                    currency=currency,
                    balance=0,
                    is_pool=is_pool,
                ),
            )
        return self.db.accounts[account_id]

    def execute_transfer_leg(self, leg: LedgerLegRecordEntity) -> LedgerLegRecordEntity:
        """
        Atomically executes a single debit/credit leg between two accounts.
        Enforces sorted two-account lock acquisition on involved resources to eliminate deadlocks.
        No global lock is acquired.
        """
        from_acc = self.db.accounts.get(leg.from_account_id)
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

        to_acc = self.db.accounts.get(leg.to_account_id)
        if not to_acc:
            owner = leg.to_account_id.split(":")[0]
            is_pool = leg.to_account_id.startswith("pool:")
            to_acc = self.get_or_create_account(
                owner_id=owner, currency=leg.currency, is_pool=is_pool
            )

        # Deterministic lock ordering on the two involved accounts
        first, second = (
            (from_acc, to_acc)
            if from_acc.account_id < to_acc.account_id
            else (to_acc, from_acc)
        )

        with first.lock:
            with second.lock:
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
        self.db.transactions[tx.transaction_id] = tx
        if tx.idempotency_key:
            self.db.transactions_by_idempotency[tx.idempotency_key] = tx
        return tx

    def get_transaction(self, tx_id: str) -> Optional[TransactionRecordEntity]:
        """Retrieve a transaction by transaction_id (lock-free)."""
        return self.db.transactions.get(tx_id)

    def get_transaction_by_idempotency_key(
        self, idempotency_key: str
    ) -> Optional[TransactionRecordEntity]:
        """Retrieve a transaction by idempotency_key (lock-free)."""
        return self.db.transactions_by_idempotency.get(idempotency_key)

    def get_user_transactions(self, user_id: str) -> List[TransactionRecordEntity]:
        """Retrieve all transactions involving a user, sorted descending by created_at (lock-free)."""
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

    def get_or_create_transaction(
        self,
        tx_id: str,
        user_id: str,
        tx_type: str,
        metadata: Dict[str, Any],
        idempotency_key: Optional[str] = None,
        request_hash: Optional[str] = None,
    ) -> TransactionRecordEntity:
        """
        Get existing transaction by idempotency key or create a new PENDING transaction.
        Rejects payload hash mismatches with IdempotencyPayloadMismatchError.
        Rejects in-flight requests with IdempotencyConflictError.
        """
        if idempotency_key:
            if idempotency_key in self.db.transactions_by_idempotency:
                existing = self.db.transactions_by_idempotency[idempotency_key]
                if existing.request_hash and request_hash and existing.request_hash != request_hash:
                    raise IdempotencyPayloadMismatchError(
                        "Idempotency-Key reused with different request payload"
                    )
                if existing.status == "PENDING":
                    raise IdempotencyConflictError(
                        "A request with this Idempotency-Key is currently processing"
                    )
                return existing

        tx = TransactionRecordEntity(
            transaction_id=tx_id,
            user_id=user_id,
            transaction_type=tx_type,
            status="PENDING",
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            metadata=metadata,
        )
        self.db.transactions[tx_id] = tx
        if idempotency_key:
            self.db.transactions_by_idempotency[idempotency_key] = tx
        return tx

    def complete_transaction(
        self, tx_id: str, response_payload: Dict[str, Any]
    ) -> None:
        """Mark transaction as COMPLETED and cache response payload."""
        if tx_id in self.db.transactions:
            tx = self.db.transactions[tx_id]
            tx.status = "COMPLETED"
            tx.response_payload = response_payload

    def fail_or_reverse_transaction(
        self, tx_id: str, status: str = "REVERSED"
    ) -> None:
        """Mark transaction as REVERSED or FAILED."""
        if tx_id in self.db.transactions:
            self.db.transactions[tx_id].status = status


# Default singleton instance
wallet_adapter = WalletAdapter()
