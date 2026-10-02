"""Manager package."""

from app.manager.entities import (
    AcceptQuoteRequestEntity,
    AcceptQuoteResponseEntity,
    CreateQuoteRequestEntity,
    GetRatesRequestEntity,
    GetTransactionHistoryRequestEntity,
    GetUserBalancesRequestEntity,
    GreetingRequestEntity,
    GreetingResponseEntity,
    P2PTransferRequestEntity,
    P2PTransferResponseEntity,
    QuoteResponseEntity,
    RatesResponseEntity,
    TransactionHistoryItemEntity,
    TransactionHistoryResponseEntity,
    TransactionLegViewEntity,
    UserBalancesResponseEntity,
)
from app.manager.greeting_manager import GreetingManager, greeting_manager
from app.manager.quote_manager import QuoteManager, quote_manager
from app.manager.transfer_manager import TransferManager, transfer_manager
from app.manager.user_account_manager import (
    UserAccountManager,
    user_account_manager,
)

__all__ = [
    "GreetingRequestEntity",
    "GreetingResponseEntity",
    "GreetingManager",
    "greeting_manager",
    "CreateQuoteRequestEntity",
    "QuoteResponseEntity",
    "AcceptQuoteRequestEntity",
    "AcceptQuoteResponseEntity",
    "P2PTransferRequestEntity",
    "P2PTransferResponseEntity",
    "GetUserBalancesRequestEntity",
    "UserBalancesResponseEntity",
    "GetTransactionHistoryRequestEntity",
    "TransactionHistoryResponseEntity",
    "TransactionHistoryItemEntity",
    "TransactionLegViewEntity",
    "GetRatesRequestEntity",
    "RatesResponseEntity",
    "UserAccountManager",
    "user_account_manager",
    "QuoteManager",
    "quote_manager",
    "TransferManager",
    "transfer_manager",
]
