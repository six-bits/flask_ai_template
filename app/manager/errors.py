"""Domain error exceptions for the multi-currency wallet application."""


class WalletError(Exception):
    """Base wallet domain exception."""
    error_code = "WALLET_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UserNotFoundError(WalletError):
    error_code = "USER_NOT_FOUND"

    def __init__(self, user_id: str) -> None:
        super().__init__(f"User with ID '{user_id}' does not exist")
        self.user_id = user_id


class QuoteNotFoundError(WalletError):
    error_code = "QUOTE_NOT_FOUND"

    def __init__(self, quote_id: str) -> None:
        super().__init__(f"Quote with ID '{quote_id}' not found")
        self.quote_id = quote_id


class QuoteExpiredError(WalletError):
    error_code = "QUOTE_EXPIRED"

    def __init__(self) -> None:
        super().__init__("Quote has expired (validity period was 30 seconds)")


class QuoteAlreadyAcceptedError(WalletError):
    error_code = "QUOTE_ALREADY_ACCEPTED"

    def __init__(self) -> None:
        super().__init__("Quote has already been accepted")


class QuoteOwnershipError(WalletError):
    error_code = "QUOTE_OWNERSHIP_MISMATCH"

    def __init__(self) -> None:
        super().__init__("User does not own this quote")


class InsufficientFundsError(WalletError):
    error_code = "INSUFFICIENT_FUNDS"

    def __init__(self, currency: str, available: int, required: int) -> None:
        super().__init__(
            f"Insufficient {currency} balance: available {available}, required {required}"
        )
        self.currency = currency
        self.available = available
        self.required = required


class SelfTransferError(WalletError):
    error_code = "SELF_TRANSFER_NOT_ALLOWED"

    def __init__(self) -> None:
        super().__init__("Cannot transfer money to yourself")


class IdenticalCurrenciesError(WalletError):
    error_code = "IDENTICAL_CURRENCIES"

    def __init__(self) -> None:
        super().__init__("Source and target currencies must be different")


class InvalidAmountError(WalletError):
    error_code = "INVALID_AMOUNT"

    def __init__(self, message: str = "Amount must be greater than zero") -> None:
        super().__init__(message)


class UnsupportedCurrencyError(WalletError):
    error_code = "UNSUPPORTED_CURRENCY"

    def __init__(self, currency: str) -> None:
        super().__init__(f"Currency '{currency}' is not supported")
        self.currency = currency


class ConcurrentRequestConflictError(WalletError):
    error_code = "CONCURRENT_REQUEST_IN_PROGRESS"

    def __init__(self, key: str = "") -> None:
        msg = (
            f"A request with idempotency key '{key}' is already in progress"
            if key
            else "Concurrent request in progress"
        )
        super().__init__(msg)
        self.key = key


class IdempotencyPayloadMismatchError(WalletError):
    error_code = "IDEMPOTENCY_KEY_PAYLOAD_MISMATCH"

    def __init__(self, key: str = "") -> None:
        msg = (
            f"Idempotency key '{key}' was already used with a different request payload"
            if key
            else "Idempotency key payload mismatch"
        )
        super().__init__(msg)
        self.key = key

