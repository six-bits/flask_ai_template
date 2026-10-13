"""Domain exceptions for Flash Sale Inventory Reservation business logic."""


class InventoryDomainError(Exception):
    """Base class for domain exceptions."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class UserNotFoundError(InventoryDomainError):
    """Raised when an operation targets a non-existent user."""


class ItemNotFoundError(InventoryDomainError):
    """Raised when an item ID does not exist in the catalog."""


class ReservationNotFoundError(InventoryDomainError):
    """Raised when a reservation ID does not exist."""


class InsufficientStockError(InventoryDomainError):
    """Raised when available stock is insufficient to fulfill the requested reservation."""


class PurchaseLimitExceededError(InventoryDomainError):
    """Raised when a reservation would exceed the user's allowed purchase quota."""


class ReservationExpiredError(InventoryDomainError):
    """Raised when attempting to confirm or operate on an expired reservation lease."""


class ReservationStateConflictError(InventoryDomainError):
    """Raised when a reservation is in an incompatible state for the requested operation."""


class UnauthorizedReservationAccessError(InventoryDomainError):
    """Raised when a user attempts to operate on another user's reservation."""
