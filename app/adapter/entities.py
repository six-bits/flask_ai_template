"""Adapter entities defining the data contract between Manager and Adapter layers."""

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class GreetingRecordEntity:
    """Storage/persistence entity for greeting records in the adapter."""
    name: str
    salutation: str
    message: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert adapter entity to dictionary."""
        return asdict(self)


from datetime import datetime
from decimal import Decimal
from typing import List


@dataclass
class UserRecordEntity:
    id: str
    name: str
    email: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AccountRecordEntity:
    account_id: str
    owner_type: str
    owner_id: str
    currency: str
    balance: Decimal
    allow_negative: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "currency": self.currency,
            "balance": float(self.balance),
            "allow_negative": self.allow_negative,
        }


@dataclass
class ExchangeRateRecordEntity:
    from_currency: str
    to_currency: str
    rate: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "rate": float(self.rate),
        }


@dataclass
class QuoteRecordEntity:
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
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "quote_id": self.id,
            "user_id": self.user_id,
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "from_amount": float(self.from_amount),
            "to_amount": float(self.to_amount),
            "exchange_rate": float(self.exchange_rate),
            "fee_rate": float(self.fee_rate),
            "fee_amount": float(self.fee_amount),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "status": self.status,
        }


@dataclass
class MovementStepRecordEntity:
    step_id: str
    transaction_id: str
    step_index: int
    from_account_id: str
    to_account_id: str
    currency: str
    amount: Decimal
    status: str
    timestamp: datetime
    is_compensating: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "transaction_id": self.transaction_id,
            "step_index": self.step_index,
            "from_account_id": self.from_account_id,
            "to_account_id": self.to_account_id,
            "currency": self.currency,
            "amount": float(self.amount),
            "status": self.status,
            "is_compensating": self.is_compensating,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class TransactionRecordEntity:
    id: str
    type: str
    initiator_user_id: str
    status: str
    metadata: Dict[str, Any]
    steps: List[MovementStepRecordEntity]
    idempotency_key: Optional[str] = None
    timestamp: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "initiator_user_id": self.initiator_user_id,
            "status": self.status,
            "metadata": self.metadata,
            "steps": [s.to_dict() for s in self.steps],
            "idempotency_key": self.idempotency_key,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


@dataclass
class IdempotencyRecordEntity:
    idempotency_key: str
    operation: str
    request_hash: str
    response_payload: Dict[str, Any]
    status_code: int
    created_at: datetime

