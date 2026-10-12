"""Domain exceptions for the wallet application."""


class WalletException(Exception):
    """Base exception for all wallet domain errors."""
    pass


class ResourceNotFoundError(WalletException):
    """Raised when a requested resource (user, quote, account) is not found."""
    pass


class InsufficientFundsError(WalletException):
    """Raised when an account lacks sufficient balance for an operation."""
    pass


class QuoteExpiredError(WalletException):
    """Raised when an attempt is made to accept an expired quote (> 30s)."""
    pass


class QuoteAlreadyExecutedError(WalletException):
    """Raised when an attempt is made to accept a quote that was already executed."""
    pass


class IdempotencyConflictError(WalletException):
    """Raised when an idempotency key is reused with a different request payload."""
    pass


class TransferToSelfError(WalletException):
    """Raised when sender attempts to transfer funds to themselves."""
    pass


class InvalidAmountError(WalletException):
    """Raised when an amount is non-positive or invalid."""
    pass


class StepExecutionError(WalletException):
    """Raised when a money movement step fails during transaction execution."""
    pass
