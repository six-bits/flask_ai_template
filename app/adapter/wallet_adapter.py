"""Wallet adapter providing atomic in-memory persistence and multi-step transactions."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.adapter.db import (
    AccountRecord,
    IdempotencyRecord,
    MovementStepRecord,
    QuoteRecord,
    TransactionRecord,
    db,
)
from app.adapter.entities import (
    AccountRecordEntity,
    ExchangeRateRecordEntity,
    IdempotencyRecordEntity,
    MovementStepRecordEntity,
    QuoteRecordEntity,
    TransactionRecordEntity,
    UserRecordEntity,
)
from app.utils.exceptions import (
    InsufficientFundsError,
    StepExecutionError,
)
from app.utils.locking import lock_manager


class WalletAdapter:
    """Adapter for wallet persistence, locking, and multi-step movement execution."""

    def __init__(self, database=None):
        self.db = database or db

    def get_users(self) -> List[UserRecordEntity]:
        """List all users."""
        with self.db.lock:
            return [
                UserRecordEntity(id=u.id, name=u.name, email=u.email)
                for u in self.db.users.values()
            ]

    def get_user(self, user_id: str) -> Optional[UserRecordEntity]:
        """Fetch a single user by ID."""
        with self.db.lock:
            u = self.db.users.get(user_id)
            if not u:
                return None
            return UserRecordEntity(id=u.id, name=u.name, email=u.email)

    def get_user_balances(self, user_id: str) -> Dict[str, Decimal]:
        """Get all currency balances for a user."""
        with self.db.lock:
            prefix = f"user:{user_id}:"
            balances: Dict[str, Decimal] = {}
            for acc_id, acc in self.db.accounts.items():
                if acc_id.startswith(prefix):
                    balances[acc.currency] = acc.balance
            return balances

    def get_account(self, account_id: str) -> Optional[AccountRecordEntity]:
        """Fetch an account by its unique account_id."""
        with self.db.lock:
            acc = self.db.accounts.get(account_id)
            if not acc:
                return None
            return AccountRecordEntity(
                account_id=acc.account_id,
                owner_type=acc.owner_type,
                owner_id=acc.owner_id,
                currency=acc.currency,
                balance=acc.balance,
                allow_negative=acc.allow_negative,
            )

    def get_rates(self) -> List[ExchangeRateRecordEntity]:
        """List all exchange rates."""
        with self.db.lock:
            return [
                ExchangeRateRecordEntity(
                    from_currency=r.from_currency,
                    to_currency=r.to_currency,
                    rate=r.rate,
                )
                for r in self.db.rates.values()
            ]

    def get_rate(self, from_currency: str, to_currency: str) -> Optional[Decimal]:
        """Get exchange rate for a currency pair."""
        with self.db.lock:
            r = self.db.rates.get((from_currency.upper(), to_currency.upper()))
            return r.rate if r else None

    def save_quote(self, quote: QuoteRecordEntity) -> None:
        """Store or update a quote."""
        with self.db.lock:
            self.db.quotes[quote.id] = QuoteRecord(
                id=quote.id,
                user_id=quote.user_id,
                from_currency=quote.from_currency,
                to_currency=quote.to_currency,
                from_amount=quote.from_amount,
                to_amount=quote.to_amount,
                exchange_rate=quote.exchange_rate,
                fee_rate=quote.fee_rate,
                fee_amount=quote.fee_amount,
                created_at=quote.created_at,
                expires_at=quote.expires_at,
                status=quote.status,
            )

    def get_quote(self, quote_id: str) -> Optional[QuoteRecordEntity]:
        """Retrieve a quote by ID."""
        with self.db.lock:
            q = self.db.quotes.get(quote_id)
            if not q:
                return None
            return QuoteRecordEntity(
                id=q.id,
                user_id=q.user_id,
                from_currency=q.from_currency,
                to_currency=q.to_currency,
                from_amount=q.from_amount,
                to_amount=q.to_amount,
                exchange_rate=q.exchange_rate,
                fee_rate=q.fee_rate,
                fee_amount=q.fee_amount,
                created_at=q.created_at,
                expires_at=q.expires_at,
                status=q.status,
            )

    def update_quote_status(self, quote_id: str, status: str) -> None:
        """Update the status of a quote."""
        with self.db.lock:
            if quote_id in self.db.quotes:
                self.db.quotes[quote_id].status = status

    def execute_multi_step_transaction(
        self,
        transaction_id: str,
        transaction_type: str,
        initiator_user_id: str,
        steps: List[Tuple[str, str, str, Decimal]],
        metadata: Dict[str, Any],
        idempotency_key: Optional[str] = None,
        simulate_failure_at_step: Optional[int] = None,
    ) -> TransactionRecordEntity:
        """Execute multiple atomic money movement steps under fine-grained account locks.
        
        If any step fails, all previously completed steps are reversed in reverse order.
        """
        # Determine unique account IDs to lock
        account_ids = set()
        for from_acc_id, to_acc_id, _, _ in steps:
            account_ids.add(from_acc_id)
            account_ids.add(to_acc_id)

        # Acquire fine-grained locks in deterministic canonical order
        with lock_manager.acquire_account_locks(account_ids):
            executed_step_records: List[MovementStepRecord] = []
            try:
                for idx, (from_acc_id, to_acc_id, curr, amt) in enumerate(steps, start=1):
                    if simulate_failure_at_step == idx:
                        raise StepExecutionError(f"Simulated failure at step {idx}")

                    with self.db.lock:
                        from_acc = self.db.accounts.get(from_acc_id)
                        to_acc = self.db.accounts.get(to_acc_id)

                        if not from_acc:
                            raise InsufficientFundsError(f"Account {from_acc_id} does not exist")
                        if not to_acc:
                            raise InsufficientFundsError(f"Account {to_acc_id} does not exist")

                        # Validate balance
                        if not from_acc.allow_negative and from_acc.balance < amt:
                            raise InsufficientFundsError(
                                f"Insufficient funds in account {from_acc_id} "
                                f"(balance: {from_acc.balance}, required: {amt})"
                            )

                        # Apply atomic balances
                        from_acc.balance -= amt
                        to_acc.balance += amt

                        step_record = MovementStepRecord(
                            step_id=f"step_{uuid.uuid4().hex[:12]}",
                            transaction_id=transaction_id,
                            step_index=idx,
                            from_account_id=from_acc_id,
                            to_account_id=to_acc_id,
                            currency=curr,
                            amount=amt,
                            status="COMPLETED",
                            timestamp=datetime.utcnow(),
                        )
                        executed_step_records.append(step_record)
                        self.db.movement_steps[step_record.step_id] = step_record

                # Transaction succeeded: record transaction
                with self.db.lock:
                    txn_record = TransactionRecord(
                        id=transaction_id,
                        type=transaction_type,
                        initiator_user_id=initiator_user_id,
                        status="COMPLETED",
                        metadata=metadata,
                        steps=executed_step_records,
                        idempotency_key=idempotency_key,
                        timestamp=datetime.utcnow(),
                    )
                    self.db.transactions[transaction_id] = txn_record

                return self._to_transaction_entity(txn_record)

            except Exception as exc:
                # Compensating rollback: reverse executed steps in reverse order
                with self.db.lock:
                    for step in reversed(executed_step_records):
                        from_acc = self.db.accounts.get(step.from_account_id)
                        to_acc = self.db.accounts.get(step.to_account_id)
                        if to_acc and from_acc:
                            to_acc.balance -= step.amount
                            from_acc.balance += step.amount
                        step.status = "REVERSED"

                    # Record transaction as FAILED / REVERSED
                    txn_record = TransactionRecord(
                        id=transaction_id,
                        type=transaction_type,
                        initiator_user_id=initiator_user_id,
                        status="REVERSED",
                        metadata=metadata,
                        steps=executed_step_records,
                        idempotency_key=idempotency_key,
                        timestamp=datetime.utcnow(),
                    )
                    self.db.transactions[transaction_id] = txn_record

                raise exc

    def get_idempotency_record(self, idempotency_key: str) -> Optional[IdempotencyRecordEntity]:
        """Fetch idempotency record by key."""
        with self.db.lock:
            rec = self.db.idempotency_store.get(idempotency_key)
            if not rec:
                return None
            return IdempotencyRecordEntity(
                idempotency_key=rec.idempotency_key,
                operation=rec.operation,
                request_hash=rec.request_hash,
                response_payload=rec.response_payload,
                status_code=rec.status_code,
                created_at=rec.created_at,
            )

    def save_idempotency_record(self, record: IdempotencyRecordEntity) -> None:
        """Save idempotency record."""
        with self.db.lock:
            self.db.idempotency_store[record.idempotency_key] = IdempotencyRecord(
                idempotency_key=record.idempotency_key,
                operation=record.operation,
                request_hash=record.request_hash,
                response_payload=record.response_payload,
                status_code=record.status_code,
                created_at=record.created_at,
            )

    def get_user_transactions(self, user_id: str) -> List[TransactionRecordEntity]:
        """Retrieve transactions where user is initiator or counterparty."""
        with self.db.lock:
            user_txns = []
            for t in self.db.transactions.values():
                if t.initiator_user_id == user_id or t.metadata.get("recipient_id") == user_id:
                    user_txns.append(self._to_transaction_entity(t))
            # Sort newest first
            user_txns.sort(key=lambda x: x.timestamp or datetime.min, reverse=True)
            return user_txns

    def _to_transaction_entity(self, t: TransactionRecord) -> TransactionRecordEntity:
        return TransactionRecordEntity(
            id=t.id,
            type=t.type,
            initiator_user_id=t.initiator_user_id,
            status=t.status,
            metadata=t.metadata,
            steps=[
                MovementStepRecordEntity(
                    step_id=s.step_id,
                    transaction_id=s.transaction_id,
                    step_index=s.step_index,
                    from_account_id=s.from_account_id,
                    to_account_id=s.to_account_id,
                    currency=s.currency,
                    amount=s.amount,
                    status=s.status,
                    timestamp=s.timestamp,
                )
                for s in t.steps
            ],
            idempotency_key=t.idempotency_key,
            timestamp=t.timestamp,
        )


# Global singleton adapter instance
wallet_adapter = WalletAdapter()
