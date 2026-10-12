"""Flask API service layer handling HTTP requests and validation."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.manager.entities import (
    AcceptQuoteRequestEntity,
    GreetingRequestEntity,
    QuoteRequestEntity,
    TransferRequestEntity,
)
from app.manager.greeting_manager import greeting_manager
from app.manager.wallet_manager import wallet_manager
from app.service.schema import (
    GREETING_SCHEMA,
    QUOTE_ACCEPT_SCHEMA,
    QUOTE_REQUEST_SCHEMA,
    TRANSFER_REQUEST_SCHEMA,
)
from app.utils.exceptions import (
    IdempotencyConflictError,
    InsufficientFundsError,
    InvalidAmountError,
    QuoteAlreadyExecutedError,
    QuoteExpiredError,
    ResourceNotFoundError,
    StepExecutionError,
    TransferToSelfError,
)

app = Flask(__name__)


@app.errorhandler(ValidationError)
def handle_validation_error(err):
    """Format JSON Schema validation error response."""
    return jsonify({"error": "Validation error", "message": err.message}), 400


@app.errorhandler(InvalidAmountError)
@app.errorhandler(TransferToSelfError)
def handle_bad_request_domain_error(err):
    """Format invalid argument/amount domain errors as 400."""
    return jsonify({"error": "Bad request", "message": str(err)}), 400


@app.errorhandler(ResourceNotFoundError)
def handle_not_found_error(err):
    """Format ResourceNotFoundError as 404."""
    return jsonify({"error": "Not found", "message": str(err)}), 404


@app.errorhandler(IdempotencyConflictError)
def handle_idempotency_conflict_error(err):
    """Format IdempotencyConflictError as 409."""
    return jsonify({"error": "Idempotency conflict", "message": str(err)}), 409


@app.errorhandler(InsufficientFundsError)
@app.errorhandler(QuoteExpiredError)
@app.errorhandler(QuoteAlreadyExecutedError)
def handle_unprocessable_entity_error(err):
    """Format business constraint breaches as 422."""
    return jsonify({"error": "Unprocessable entity", "message": str(err)}), 422


@app.errorhandler(StepExecutionError)
def handle_step_execution_error(err):
    """Format step execution failure as 500."""
    return jsonify({"error": "Internal server error", "message": str(err)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/hello", methods=["POST"])
def greet():
    """Greet the user: Service -> Manager -> Adapter."""
    salutation = request.args.get("salutation", "Hello").strip()

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=GREETING_SCHEMA)

    full_name = data.get("full_name") or data.get("name")

    request_entity = GreetingRequestEntity(name=full_name, salutation=salutation)
    response_entity = greeting_manager.greet(request_entity)

    return jsonify(response_entity.to_dict()), 200


# ---------------------------------------------------------
# Multi-Currency Wallet API Routes
# ---------------------------------------------------------


@app.route("/api/v1/rates", methods=["GET"])
def get_rates():
    """Retrieve exchange rates table."""
    rates = wallet_manager.get_rates()
    return jsonify({"rates": rates}), 200


@app.route("/api/v1/users", methods=["GET"])
def get_users():
    """List seed users."""
    users = wallet_manager.get_users()
    return jsonify({"users": users}), 200


@app.route("/api/v1/users/<user_id>/balances", methods=["GET"])
def get_user_balances(user_id: str):
    """Retrieve multi-currency balances for a specific user."""
    response_entity = wallet_manager.get_balances(user_id)
    return jsonify(response_entity.to_dict()), 200


@app.route("/api/v1/quotes", methods=["POST"])
def create_quote():
    """Request a 30-second conversion quote."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=QUOTE_REQUEST_SCHEMA)

    request_entity = QuoteRequestEntity(
        user_id=data["user_id"],
        from_currency=data["from_currency"],
        to_currency=data["to_currency"],
        amount=float(data["amount"]),
    )
    response_entity = wallet_manager.create_quote(request_entity)
    return jsonify(response_entity.to_dict()), 201


@app.route("/api/v1/quotes/<quote_id>/accept", methods=["POST"])
def accept_quote(quote_id: str):
    """Accept and execute a quote using an optional idempotency key."""
    idempotency_key = request.headers.get("Idempotency-Key")
    data = request.get_json(silent=True)
    user_id = None
    if data is not None:
        validate(instance=data, schema=QUOTE_ACCEPT_SCHEMA)
        idempotency_key = idempotency_key or data.get("idempotency_key")
        user_id = data.get("user_id")

    request_entity = AcceptQuoteRequestEntity(
        quote_id=quote_id,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    response_entity = wallet_manager.accept_quote(request_entity)
    return jsonify(response_entity.to_dict()), 200


@app.route("/api/v1/transfers", methods=["POST"])
def transfer_money():
    """Send money peer-to-peer to another user using an optional idempotency key."""
    idempotency_key = request.headers.get("Idempotency-Key")
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=TRANSFER_REQUEST_SCHEMA)
    idempotency_key = idempotency_key or data.get("idempotency_key")

    request_entity = TransferRequestEntity(
        sender_id=data["sender_id"],
        recipient_id=data["recipient_id"],
        currency=data["currency"],
        amount=float(data["amount"]),
        note=data.get("note", ""),
        idempotency_key=idempotency_key,
    )
    response_entity = wallet_manager.transfer_money(request_entity)
    return jsonify(response_entity.to_dict()), 201


@app.route("/api/v1/users/<user_id>/transactions", methods=["GET"])
def get_user_transactions(user_id: str):
    """Retrieve chronological transaction history for a user."""
    response_entity = wallet_manager.get_transactions(user_id)
    return jsonify(response_entity.to_dict()), 200


if __name__ == "__main__":
    app.run(port=5001, debug=True)


