"""Domain entities for the greeting application.

These entities define the data contracts between:
- Service layer <-> Manager layer
- Manager layer <-> Adapter layer
"""

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


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


from typing import List


@dataclass
class WalletBalanceResponseEntity:
    user_id: str
    balances: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuoteRequestEntity:
    user_id: str
    from_currency: str
    to_currency: str
    amount: float


@dataclass
class QuoteResponseEntity:
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: float
    to_amount: float
    exchange_rate: float
    fee_amount: float
    fee_rate: float
    created_at: str
    expires_at: str
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptQuoteRequestEntity:
    quote_id: str
    user_id: Optional[str] = None
    idempotency_key: Optional[str] = None


@dataclass
class AcceptQuoteResponseEntity:
    transaction_id: str
    quote_id: str
    user_id: str
    from_currency: str
    from_amount: float
    to_currency: str
    to_amount: float
    fee_amount: float
    status: str
    timestamp: str
    steps: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransferRequestEntity:
    sender_id: str
    recipient_id: str
    currency: str
    amount: float
    note: str = ""
    idempotency_key: Optional[str] = None


@dataclass
class TransferResponseEntity:
    transfer_id: str
    sender_id: str
    recipient_id: str
    currency: str
    amount: float
    note: str
    status: str
    timestamp: str
    steps: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TransactionHistoryResponseEntity:
    user_id: str
    transactions: List[Dict[str, Any]]
    total: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

