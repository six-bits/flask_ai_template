"""Flask API service layer handling HTTP requests, schema validation, and error mappings."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.exceptions import (
    AccountNotFoundError,
    IdempotencyConflictError,
    InsufficientFundsError,
    InvalidQuoteError,
    QuoteExpiredError,
    QuoteNotFoundError,
    RateNotFoundError,
    TransferExecutionError,
    UserNotFoundError,
    WalletError,
)
from app.manager.entities import (
    AcceptQuoteRequestEntity,
    CreateQuoteRequestEntity,
    GetRatesRequestEntity,
    GetTransactionHistoryRequestEntity,
    GetUserBalancesRequestEntity,
    GreetingRequestEntity,
    P2PTransferRequestEntity,
)
from app.manager.greeting_manager import greeting_manager
from app.manager.quote_manager import quote_manager
from app.manager.transfer_manager import transfer_manager
from app.manager.user_account_manager import user_account_manager
from app.service.schema import (
    ACCEPT_QUOTE_SCHEMA,
    CREATE_QUOTE_SCHEMA,
    GREETING_SCHEMA,
    P2P_TRANSFER_SCHEMA,
)

app = Flask(__name__)


# --- Error Handlers ---

@app.errorhandler(ValidationError)
def handle_validation_error(err):
    """Format JSON Schema validation error response."""
    return jsonify({"error": "Validation error", "message": err.message}), 400


@app.errorhandler(UserNotFoundError)
@app.errorhandler(QuoteNotFoundError)
@app.errorhandler(RateNotFoundError)
@app.errorhandler(AccountNotFoundError)
def handle_not_found_error(err):
    """Format 404 Not Found error response."""
    return jsonify({"error": "Not Found", "message": str(err)}), 404


@app.errorhandler(IdempotencyConflictError)
def handle_idempotency_conflict(err):
    """Format 409 Conflict error response."""
    return jsonify({"error": "Conflict", "message": str(err)}), 409


@app.errorhandler(QuoteExpiredError)
def handle_quote_expired(err):
    """Format 422 Unprocessable Entity error response for expired quote."""
    return jsonify({"error": "Quote Expired", "message": str(err)}), 422


@app.errorhandler(InsufficientFundsError)
def handle_insufficient_funds(err):
    """Format 422 Unprocessable Entity error response for insufficient funds."""
    return jsonify({"error": "Insufficient Funds", "message": str(err)}), 422


@app.errorhandler(InvalidQuoteError)
def handle_invalid_quote(err):
    """Format 422 Unprocessable Entity error response for invalid quote state."""
    return jsonify({"error": "Invalid Quote", "message": str(err)}), 422


@app.errorhandler(TransferExecutionError)
def handle_transfer_execution_error(err):
    """Format 422 error response when a money movement failed and was compensated."""
    return jsonify({
        "error": "Transfer Failed",
        "message": str(err),
        "status": "REVERSED" if err.reversed else "FAILED",
        "legs_executed": err.legs_executed,
    }), 422


@app.errorhandler(WalletError)
def handle_wallet_error(err):
    """Format 400 Bad Request error response for generic wallet errors."""
    return jsonify({"error": "Bad Request", "message": str(err)}), 400


# --- Health & Existing Greeting Endpoint ---

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


# --- Wallet Endpoints ---

@app.route("/quotes", methods=["POST"])
def create_quote():
    """Request a time-limited 30s FX quote."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=CREATE_QUOTE_SCHEMA)

    req = CreateQuoteRequestEntity(
        user_id=data["user_id"],
        from_currency=data["from_currency"],
        to_currency=data["to_currency"],
        from_amount=data["from_amount"],
    )
    res = quote_manager.create_quote(req)
    return jsonify(res.to_dict()), 201


@app.route("/quotes/accept", methods=["POST"])
@app.route("/quotes/<quote_id>/accept", methods=["POST"])
def accept_quote(quote_id: str = ""):
    """Accept and execute an FX conversion quote."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    if quote_id and "quote_id" not in data:
        data["quote_id"] = quote_id

    validate(instance=data, schema=ACCEPT_QUOTE_SCHEMA)

    idempotency_key = request.headers.get("Idempotency-Key")

    req = AcceptQuoteRequestEntity(
        quote_id=data["quote_id"],
        user_id=data["user_id"],
        idempotency_key=idempotency_key,
    )
    res = quote_manager.accept_quote(req)
    return jsonify(res.to_dict()), 200


@app.route("/transfers", methods=["POST"])
def transfer():
    """Initiate a peer-to-peer (P2P) money transfer across settlement pools."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=P2P_TRANSFER_SCHEMA)

    idempotency_key = request.headers.get("Idempotency-Key")

    req = P2PTransferRequestEntity(
        sender_user_id=data["sender_user_id"],
        recipient_user_id=data["recipient_user_id"],
        currency=data["currency"],
        amount=data["amount"],
        idempotency_key=idempotency_key,
    )
    res = transfer_manager.transfer(req)
    return jsonify(res.to_dict()), 200


@app.route("/users/<user_id>/balances", methods=["GET"])
def get_user_balances(user_id: str):
    """Retrieve all currency balances for a given user in minor units."""
    req = GetUserBalancesRequestEntity(user_id=user_id)
    res = user_account_manager.get_balances(req)
    return jsonify(res.to_dict()), 200


@app.route("/users/<user_id>/transactions", methods=["GET"])
def get_user_transactions(user_id: str):
    """Retrieve transaction history and movement legs for a given user."""
    req = GetTransactionHistoryRequestEntity(user_id=user_id)
    res = user_account_manager.get_transaction_history(req)
    return jsonify(res.to_dict()), 200


@app.route("/rates", methods=["GET"])
def get_rates():
    """Retrieve all available FX exchange rates."""
    req = GetRatesRequestEntity()
    res = quote_manager.get_rates(req)
    return jsonify(res.to_dict()), 200


if __name__ == "__main__":
    app.run(port=5001, debug=True)
