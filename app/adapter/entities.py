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


@dataclass
class CardRecordEntity:
    card_id: str
    credit_limit: float
    settled_balance: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuthorizationRecordEntity:
    authorization_id: str
    card_id: str
    merchant: str
    original_amount: float
    remaining_held_amount: float
    status: str
    created_at: float
    expires_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClearingRecordEntity:
    clearing_id: str
    card_id: str
    amount: float
    merchant: str
    is_force_post: bool
    created_at: float
    authorization_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReversalRecordEntity:
    reversal_id: str
    authorization_id: str
    card_id: str
    amount: float
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerTransactionRecordEntity:
    transaction_id: str
    card_id: str
    type: str
    amount: float
    merchant: str
    status: str
    timestamp: float
    authorization_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IdempotencyRecordEntity:
    idempotency_key: str
    card_id: str
    request_hash: str
    status_code: int
    response_body: Dict[str, Any]
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

