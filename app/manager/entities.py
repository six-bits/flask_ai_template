"""Domain entities for the wallet and greeting applications.

These entities define the data contracts between:
- Service layer <-> Manager layer
"""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# --- Existing Greeting Entities ---

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


# --- Quote Entities (Amounts in Minor Units as int) ---

@dataclass
class CreateQuoteRequestEntity:
    """Request to create an FX quote."""
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int  # Minor units


@dataclass
class QuoteResponseEntity:
    """Response containing calculated rate, fees, and 30s TTL expiry."""
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    from_amount: int
    exchange_rate: float
    gross_to_amount: int
    fee_percentage: float
    fee_amount: int
    net_to_amount: int
    expires_at: str
    validity_seconds: int = 30

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AcceptQuoteRequestEntity:
    """Request to accept an FX quote and trigger conversion."""
    quote_id: str
    user_id: str
    idempotency_key: Optional[str] = None


@dataclass
class AcceptQuoteResponseEntity:
    """Response returned upon successful or compensated FX conversion."""
    transaction_id: str
    quote_id: str
    user_id: str
    from_currency: str
    to_currency: str
    debited_amount: int
    credited_amount: int
    fee_amount: int
    fee_currency: str
    status: str  # COMPLETED | FAILED | REVERSED
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --- P2P Transfer Entities ---

@dataclass
class P2PTransferRequestEntity:
    """Request to transfer funds between two users in minor units."""
    sender_user_id: str
    recipient_user_id: str
    currency: str
    amount: int  # Minor units
    idempotency_key: Optional[str] = None


@dataclass
class P2PTransferResponseEntity:
    """Response returned upon P2P transfer completion."""
    transaction_id: str
    sender_user_id: str
    recipient_user_id: str
    currency: str
    amount: int
    status: str  # COMPLETED | FAILED | REVERSED
    legs_executed: int
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --- User Balance & History Entities ---

@dataclass
class GetUserBalancesRequestEntity:
    """Request to fetch all balances for a user."""
    user_id: str


@dataclass
class UserBalancesResponseEntity:
    """Response containing user's currency balances in minor units."""
    user_id: str
    balances: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GetTransactionHistoryRequestEntity:
    """Request to retrieve transaction history for a user."""
    user_id: str


@dataclass
class TransactionLegViewEntity:
    """View of an individual movement leg within a transaction."""
    leg_id: str
    step_number: int
    from_account: str
    to_account: str
    currency: str
    amount: int
    is_reversal: bool
    status: str


@dataclass
class TransactionHistoryItemEntity:
    """View of a complete transaction in user history."""
    transaction_id: str
    type: str  # P2P_TRANSFER | FX_CONVERSION
    status: str
    created_at: str
    details: Dict[str, Any]
    legs: List[TransactionLegViewEntity] = field(default_factory=list)


@dataclass
class TransactionHistoryResponseEntity:
    """Response containing list of transactions."""
    user_id: str
    transactions: List[TransactionHistoryItemEntity]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# --- Exchange Rates Entities ---

@dataclass
class GetRatesRequestEntity:
    """Request to fetch all exchange rates."""
    pass


@dataclass
class RatesResponseEntity:
    """Response containing available exchange rate pairs and fee rate."""
    rates: Dict[str, float]
    fee_percentage: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
