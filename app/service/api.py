"""Flask API service layer handling HTTP requests and validation for Flash Sale Inventory Reservations."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.manager.entities import (
    CancelReservationRequestEntity,
    ConfirmReservationRequestEntity,
    CreateReservationRequestEntity,
)
from app.manager.exceptions import (
    InsufficientStockError,
    ItemNotFoundError,
    PurchaseLimitExceededError,
    ReservationExpiredError,
    ReservationNotFoundError,
    ReservationStateConflictError,
    UnauthorizedReservationAccessError,
    UserNotFoundError,
)
from app.manager.inventory_manager import inventory_manager
from app.service.schema import (
    CANCEL_RESERVATION_SCHEMA,
    CONFIRM_RESERVATION_SCHEMA,
    CREATE_RESERVATION_SCHEMA,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------


@app.errorhandler(ValidationError)
def handle_validation_error(err: ValidationError):
    """Format JSON Schema validation error response."""
    return jsonify({"error": "Validation error", "message": err.message}), 400


@app.errorhandler(UserNotFoundError)
def handle_user_not_found(err: UserNotFoundError):
    """Format 404 response when user does not exist."""
    return jsonify({"error": "User not found", "message": err.message}), 404


@app.errorhandler(ItemNotFoundError)
def handle_item_not_found(err: ItemNotFoundError):
    """Format 404 response when item does not exist."""
    return jsonify({"error": "Item not found", "message": err.message}), 404


@app.errorhandler(ReservationNotFoundError)
def handle_reservation_not_found(err: ReservationNotFoundError):
    """Format 404 response when reservation does not exist."""
    return jsonify({"error": "Reservation not found", "message": err.message}), 404


@app.errorhandler(InsufficientStockError)
def handle_insufficient_stock(err: InsufficientStockError):
    """Format 409 conflict when stock is insufficient."""
    return jsonify({"error": "Insufficient stock", "message": err.message}), 409


@app.errorhandler(PurchaseLimitExceededError)
def handle_purchase_limit_exceeded(err: PurchaseLimitExceededError):
    """Format 409 conflict when user purchase limit is exceeded."""
    return jsonify({"error": "Purchase limit exceeded", "message": err.message}), 409


@app.errorhandler(ReservationStateConflictError)
def handle_state_conflict(err: ReservationStateConflictError):
    """Format 409 conflict when reservation is in invalid state."""
    return jsonify({"error": "Reservation state conflict", "message": err.message}), 409


@app.errorhandler(ReservationExpiredError)
def handle_reservation_expired(err: ReservationExpiredError):
    """Format 410 gone when reservation lease has expired."""
    return jsonify({"error": "Reservation expired", "message": err.message}), 410


@app.errorhandler(UnauthorizedReservationAccessError)
def handle_unauthorized_access(err: UnauthorizedReservationAccessError):
    """Format 403 forbidden when user is unauthorized to modify reservation."""
    return jsonify({"error": "Unauthorized access", "message": err.message}), 403


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/health", methods=["GET"])
def health():
    """Liveness health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/users", methods=["GET"])
def list_users():
    """List all registered users."""
    users = inventory_manager.list_users()
    return jsonify([user.to_dict() for user in users]), 200


@app.route("/users/<user_id>", methods=["GET"])
def get_user(user_id: str):
    """Get registered user by user_id."""
    user = inventory_manager.get_user(user_id)
    return jsonify(user.to_dict()), 200


@app.route("/items", methods=["GET"])
def list_items():
    """List all catalog items with live stock metrics after JIT reclamation."""
    stocks = inventory_manager.list_items_stock()
    return jsonify([stock.to_dict() for stock in stocks]), 200


@app.route("/items/<item_id>", methods=["GET"])
def get_item(item_id: str):
    """Get live stock metrics for a single item after JIT reclamation."""
    stock = inventory_manager.get_item_stock(item_id)
    return jsonify(stock.to_dict()), 200


@app.route("/reservations", methods=["POST"])
def create_reservation():
    """Request a temporary 30-second reservation lease."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=CREATE_RESERVATION_SCHEMA)

    request_entity = CreateReservationRequestEntity(
        item_id=data["item_id"],
        user_id=data["user_id"],
        quantity=data["quantity"],
    )
    response_entity = inventory_manager.create_reservation(request_entity)
    return jsonify(response_entity.to_dict()), 201


@app.route("/reservations/<reservation_id>/confirm", methods=["POST"])
def confirm_reservation(reservation_id: str):
    """Confirm checkout for an active reservation lease."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=CONFIRM_RESERVATION_SCHEMA)

    request_entity = ConfirmReservationRequestEntity(
        reservation_id=reservation_id,
        user_id=data["user_id"],
    )
    response_entity = inventory_manager.confirm_reservation(request_entity)
    return jsonify(response_entity.to_dict()), 200


@app.route("/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id: str):
    """Cancel an active reservation lease and release hold immediately."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=CANCEL_RESERVATION_SCHEMA)

    request_entity = CancelReservationRequestEntity(
        reservation_id=reservation_id,
        user_id=data["user_id"],
    )
    response_entity = inventory_manager.cancel_reservation(request_entity)
    return jsonify(response_entity.to_dict()), 200


if __name__ == "__main__":
    app.run(port=5001, debug=True)
