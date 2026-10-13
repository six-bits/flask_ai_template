"""Domain entities for the greeting application.

These entities define the data contracts between:
- Service layer <-> Manager layer
- Manager layer <-> Adapter layer
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class GreetingRequestEntity:
    """Entity representing an incoming greeting request."""
    name: str
    salutation: str = "Hello"


@dataclass
class GreetingResponseEntity:
    """Entity representing a processed greeting response."""
    message: str
    salutation: str
    name: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to a dictionary for JSON serialization."""
        return asdict(self)


# Card Payment Service Entities (Service <-> Manager Contract)


@dataclass
class AuthorizationRequestEntity:
    card_id: str
    amount: float
    merchant: str
    idempotency_key: str


@dataclass
class AuthorizationResponseEntity:
    card_id: str
    amount: float
    merchant: str
    status: str
    created_at: str
    authorization_id: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None
    available_limit: Optional[float] = None
    is_replayed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ClearingRequestEntity:
    card_id: str
    amount: float
    merchant: str
    idempotency_key: str
    authorization_id: Optional[str] = None


@dataclass
class ClearingResponseEntity:
    card_id: str
    amount: float
    merchant: str
    status: str
    created_at: str
    is_force_post: bool
    clearing_id: Optional[str] = None
    authorization_id: Optional[str] = None
    error: Optional[str] = None
    is_replayed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ReversalRequestEntity:
    card_id: str
    authorization_id: str
    idempotency_key: str
    amount: Optional[float] = None


@dataclass
class ReversalResponseEntity:
    authorization_id: str
    card_id: str
    reversed_amount: float
    status: str
    created_at: str
    remaining_held_amount: Optional[float] = None
    reversal_id: Optional[str] = None
    error: Optional[str] = None
    is_replayed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CardBalanceResponseEntity:
    card_id: str
    credit_limit: float
    settled_balance: float
    held_balance: float
    available_limit: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransactionEntity:
    transaction_id: str
    card_id: str
    type: str
    amount: float
    merchant: str
    status: str
    timestamp: str
    authorization_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class CardTransactionsResponseEntity:
    card_id: str
    transactions: List[TransactionEntity]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "card_id": self.card_id,
            "transactions": [t.to_dict() for t in self.transactions],
        }

