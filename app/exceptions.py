"""Custom domain exceptions for the wallet application."""


class WalletError(Exception):
    """Base exception for all wallet errors."""
    pass


class UserNotFoundError(WalletError):
    """Raised when a user is not found in the wallet."""
    pass


class AccountNotFoundError(WalletError):
    """Raised when an account is not found."""
    pass


class InsufficientFundsError(WalletError):
    """Raised when an account has insufficient balance for an operation."""
    pass


class QuoteNotFoundError(WalletError):
    """Raised when a requested quote ID is not found."""
    pass


class QuoteExpiredError(WalletError):
    """Raised when an accepted quote has exceeded its 30-second TTL."""
    pass


class InvalidQuoteError(WalletError):
    """Raised when quote status or ownership is invalid for acceptance."""
    pass


class RateNotFoundError(WalletError):
    """Raised when an exchange rate pair is not configured."""
    pass


class IdempotencyConflictError(WalletError):
    """Raised when an idempotency key is currently processing."""
    pass


class TransferExecutionError(WalletError):
    """Raised when a balance movement fails mid-flight and triggers compensation."""
    def __init__(self, message: str, legs_executed: int = 0, reversed: bool = True) -> None:
        super().__init__(message)
        self.legs_executed = legs_executed
        self.reversed = reversed
