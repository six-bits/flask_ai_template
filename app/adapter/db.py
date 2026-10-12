"""In-memory database and seed data storage used by the adapter layer."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
import threading
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class UserRecord:
    id: str
    name: str
    email: str
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AccountRecord:
    account_id: str
    owner_type: str  # "USER" or "SYSTEM"
    owner_id: str    # user_id or "system"
    currency: str
    balance: Decimal
    allow_negative: bool = False


@dataclass
class ExchangeRateRecord:
    from_currency: str
    to_currency: str
    rate: Decimal


@dataclass
class QuoteRecord:
    id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: Decimal
    to_amount: Decimal
    exchange_rate: Decimal
    fee_rate: Decimal
    fee_amount: Decimal
    created_at: datetime
    expires_at: datetime
    status: str  # "PENDING", "ACCEPTED", "EXPIRED"


@dataclass
class MovementStepRecord:
    step_id: str
    transaction_id: str
    step_index: int
    from_account_id: str
    to_account_id: str
    currency: str
    amount: Decimal
    status: str  # "COMPLETED", "REVERSED", "FAILED"
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TransactionRecord:
    id: str
    type: str  # "TRANSFER" or "CONVERSION"
    initiator_user_id: str
    status: str  # "COMPLETED", "FAILED", "REVERSED"
    metadata: Dict[str, Any]
    steps: List[MovementStepRecord] = field(default_factory=list)
    idempotency_key: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class IdempotencyRecord:
    idempotency_key: str
    operation: str
    request_hash: str
    response_payload: Dict[str, Any]
    status_code: int
    created_at: datetime = field(default_factory=datetime.utcnow)


class InMemoryDB:
    """Thread-safe in-memory database store with initial seed data."""

    def __init__(self):
        self.lock = threading.RLock()
        self.users: Dict[str, UserRecord] = {}
        self.accounts: Dict[str, AccountRecord] = {}
        self.rates: Dict[Tuple[str, str], ExchangeRateRecord] = {}
        self.quotes: Dict[str, QuoteRecord] = {}
        self.transactions: Dict[str, TransactionRecord] = {}
        self.movement_steps: Dict[str, MovementStepRecord] = {}
        self.idempotency_store: Dict[str, IdempotencyRecord] = {}
        self.reset()

    def reset(self):
        """Reset the in-memory database to default seed state."""
        with self.lock:
            self.users.clear()
            self.accounts.clear()
            self.rates.clear()
            self.quotes.clear()
            self.transactions.clear()
            self.movement_steps.clear()
            self.idempotency_store.clear()

            # Seed Users
            users = [
                UserRecord(id="usr_alice", name="Alice Smith", email="alice@example.com"),
                UserRecord(id="usr_bob", name="Bob Jones", email="bob@example.com"),
                UserRecord(id="usr_charlie", name="Charlie Brown", email="charlie@example.com"),
            ]
            for u in users:
                self.users[u.id] = u

            # Supported currencies
            currencies = ["USD", "EUR", "GBP", "JPY"]

            # Seed User Accounts
            user_balances = [
                ("usr_alice", "USD", Decimal("1000.00")),
                ("usr_alice", "EUR", Decimal("500.00")),
                ("usr_bob", "EUR", Decimal("750.00")),
                ("usr_bob", "GBP", Decimal("250.00")),
                ("usr_charlie", "JPY", Decimal("100000.00")),
                ("usr_charlie", "USD", Decimal("300.00")),
            ]
            for user_id, curr, bal in user_balances:
                acc_id = f"user:{user_id}:{curr}"
                self.accounts[acc_id] = AccountRecord(
                    account_id=acc_id,
                    owner_type="USER",
                    owner_id=user_id,
                    currency=curr,
                    balance=bal,
                    allow_negative=False,
                )

            # Ensure all users have account entries for all supported currencies (default to 0.00)
            for u in users:
                for curr in currencies:
                    acc_id = f"user:{u.id}:{curr}"
                    if acc_id not in self.accounts:
                        self.accounts[acc_id] = AccountRecord(
                            account_id=acc_id,
                            owner_type="USER",
                            owner_id=u.id,
                            currency=curr,
                            balance=Decimal("0.00"),
                            allow_negative=False,
                        )

            # Seed System Clearing Pool Accounts (allow_negative=True)
            pool_types = ["outbound_pool", "inbound_pool", "fx_pool", "fee_pool"]
            for p_type in pool_types:
                for curr in currencies:
                    acc_id = f"system:{p_type}:{curr}"
                    self.accounts[acc_id] = AccountRecord(
                        account_id=acc_id,
                        owner_type="SYSTEM",
                        owner_id="system",
                        currency=curr,
                        balance=Decimal("0.00"),
                        allow_negative=True,
                    )

            # Seed Exchange Rates
            rate_pairs = [
                ("USD", "EUR", Decimal("0.92")),
                ("EUR", "USD", Decimal("1.087")),
                ("USD", "GBP", Decimal("0.79")),
                ("GBP", "USD", Decimal("1.266")),
                ("USD", "JPY", Decimal("155.00")),
                ("JPY", "USD", Decimal("0.00645")),
                ("EUR", "GBP", Decimal("0.86")),
                ("GBP", "EUR", Decimal("1.163")),
                ("EUR", "JPY", Decimal("168.00")),
                ("JPY", "EUR", Decimal("0.00595")),
                ("GBP", "JPY", Decimal("195.00")),
                ("JPY", "GBP", Decimal("0.00513")),
            ]
            for fc, tc, rate in rate_pairs:
                self.rates[(fc, tc)] = ExchangeRateRecord(from_currency=fc, to_currency=tc, rate=rate)


# Global singleton instance
db = InMemoryDB()
