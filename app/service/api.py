"""Flask API service layer handling HTTP routes, JSON schema validation, and error mapping."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.manager.account_manager import account_manager
from app.manager.entities import (
    AcceptQuoteRequestEntity,
    AckOutboxEventsRequestEntity,
    CreateQuoteRequestEntity,
    GetBalancesRequestEntity,
    GetOutboxEventsRequestEntity,
    GetTransactionsRequestEntity,
    GreetingRequestEntity,
    TransferRequestEntity,
)
from app.manager.errors import (
    ConcurrentRequestConflictError,
    IdenticalCurrenciesError,
    IdempotencyPayloadMismatchError,
    InsufficientFundsError,
    InvalidAmountError,
    QuoteAlreadyAcceptedError,
    QuoteExpiredError,
    QuoteNotFoundError,
    QuoteOwnershipError,
    SelfTransferError,
    UnsupportedCurrencyError,
    UserNotFoundError,
    WalletError,
)
from app.manager.greeting_manager import greeting_manager
from app.manager.outbox_manager import outbox_manager
from app.manager.quote_manager import quote_manager
from app.manager.transfer_manager import transfer_manager
from app.service.schema import (
    ACCEPT_QUOTE_SCHEMA,
    ACK_OUTBOX_EVENTS_SCHEMA,
    CREATE_QUOTE_SCHEMA,
    GREETING_SCHEMA,
    TRANSFER_SCHEMA,
)

app = Flask(__name__)


# -------------------------------------------------------------------------
# Error Handlers
# -------------------------------------------------------------------------

@app.errorhandler(ValidationError)
def handle_validation_error(err):
    """Format JSON Schema validation error response."""
    # Preserve backwards compatibility for template greeting endpoint
    if request.path.startswith("/hello"):
        return jsonify({"error": "Validation error", "message": err.message}), 400
    return jsonify({"error": "VALIDATION_ERROR", "message": err.message}), 400


@app.errorhandler(UserNotFoundError)
def handle_user_not_found(err: UserNotFoundError):
    return jsonify({"error": err.error_code, "message": err.message}), 404


@app.errorhandler(ConcurrentRequestConflictError)
def handle_concurrent_conflict(err: ConcurrentRequestConflictError):
    return jsonify({"error": err.error_code, "message": err.message}), 409


@app.errorhandler(IdempotencyPayloadMismatchError)
def handle_idempotency_mismatch(err: IdempotencyPayloadMismatchError):
    return jsonify({"error": err.error_code, "message": err.message}), 422


@app.errorhandler(QuoteNotFoundError)
def handle_quote_not_found(err: QuoteNotFoundError):
    return jsonify({"error": err.error_code, "message": err.message}), 404


@app.errorhandler(QuoteExpiredError)
@app.errorhandler(QuoteAlreadyAcceptedError)
@app.errorhandler(QuoteOwnershipError)
@app.errorhandler(InsufficientFundsError)
@app.errorhandler(SelfTransferError)
@app.errorhandler(IdenticalCurrenciesError)
@app.errorhandler(InvalidAmountError)
@app.errorhandler(UnsupportedCurrencyError)
@app.errorhandler(WalletError)
def handle_domain_error(err: WalletError):
    return jsonify({"error": err.error_code, "message": err.message}), 400


# -------------------------------------------------------------------------
# Routes
# -------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/hello", methods=["POST"])
def greet():
    """Template demo greeting endpoint (Service -> Manager -> Adapter)."""
    salutation = request.args.get("salutation", "Hello").strip()

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=GREETING_SCHEMA)

    full_name = data.get("full_name") or data.get("name")
    request_entity = GreetingRequestEntity(name=full_name, salutation=salutation)
    response_entity = greeting_manager.greet(request_entity)

    return jsonify(response_entity.to_dict()), 200


@app.route("/users/<user_id>/balances", methods=["GET"])
def get_user_balances(user_id: str):
    """Retrieve all real-time minor-unit balances for a user."""
    request_entity = GetBalancesRequestEntity(user_id=user_id)
    response_entity = account_manager.get_balances(request_entity)
    return jsonify(response_entity.to_dict()), 200


@app.route("/quotes", methods=["POST"])
def create_quote():
    """Request a 30-second locked exchange quote with upfront fee calculation."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "VALIDATION_ERROR", "message": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=CREATE_QUOTE_SCHEMA)

    request_entity = CreateQuoteRequestEntity(
        user_id=data["user_id"],
        from_currency=data["from_currency"],
        to_currency=data["to_currency"],
        from_amount=data["from_amount"],
    )
    response_entity = quote_manager.create_quote(request_entity)
    return jsonify(response_entity.to_dict()), 201


@app.route("/quotes/<quote_id>/accept", methods=["POST"])
def accept_quote(quote_id: str):
    """Accept an active quote within 30 seconds and execute atomic currency conversion."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "VALIDATION_ERROR", "message": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=ACCEPT_QUOTE_SCHEMA)

    idempotency_key = request.headers.get("Idempotency-Key")
    raw_payload = request.get_data(as_text=True)

    request_entity = AcceptQuoteRequestEntity(
        quote_id=quote_id,
        user_id=data["user_id"],
        idempotency_key=idempotency_key,
        request_payload_json=raw_payload,
    )
    response_entity = quote_manager.accept_quote(request_entity)
    headers = {}
    if response_entity.is_replayed:
        headers["Idempotent-Replayed"] = "true"
    return jsonify(response_entity.to_dict()), 200, headers


@app.route("/transfers", methods=["POST"])
def transfer_money():
    """Execute peer-to-peer balance transfer between two users with concurrency locking and idempotency."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "VALIDATION_ERROR", "message": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=TRANSFER_SCHEMA)

    idempotency_key = request.headers.get("Idempotency-Key")
    raw_payload = request.get_data(as_text=True)

    request_entity = TransferRequestEntity(
        from_user_id=data["from_user_id"],
        to_user_id=data["to_user_id"],
        currency=data["currency"],
        amount=data["amount"],
        idempotency_key=idempotency_key,
        request_payload_json=raw_payload,
    )
    response_entity = transfer_manager.transfer(request_entity)
    headers = {}
    if response_entity.is_replayed:
        headers["Idempotent-Replayed"] = "true"
    return jsonify(response_entity.to_dict()), 200, headers


@app.route("/users/<user_id>/transactions", methods=["GET"])
def get_user_transactions(user_id: str):
    """Retrieve chronological audit ledger for a user."""
    request_entity = GetTransactionsRequestEntity(user_id=user_id)
    response_entity = account_manager.get_transactions(request_entity)
    return jsonify(response_entity.to_dict()), 200


@app.route("/outbox/events", methods=["GET"])
def get_outbox_events():
    """Scrapes outbox events attached across all user entities, clearing pools, and quotes."""
    status = request.args.get("status", "PENDING").upper()
    limit_str = request.args.get("limit", "50")
    try:
        limit = int(limit_str)
    except ValueError:
        limit = 50

    request_entity = GetOutboxEventsRequestEntity(status=status, limit=limit)
    response_entity = outbox_manager.get_events(request_entity)
    return jsonify(response_entity.to_dict()), 200


@app.route("/outbox/events/ack", methods=["POST"])
def ack_outbox_events():
    """Acknowledge delivered events, updating their status on host entities from PENDING to PUBLISHED."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "VALIDATION_ERROR", "message": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=ACK_OUTBOX_EVENTS_SCHEMA)

    request_entity = AckOutboxEventsRequestEntity(event_ids=data["event_ids"])
    response_entity = outbox_manager.ack_events(request_entity)
    return jsonify(response_entity.to_dict()), 200


if __name__ == "__main__":
    app.run(port=5001, debug=True)

