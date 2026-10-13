"""Flask API service layer handling HTTP requests and validation."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.manager.entities import (
    AuthorizationRequestEntity,
    ClearingRequestEntity,
    GreetingRequestEntity,
    ReversalRequestEntity,
)
from app.manager.greeting_manager import greeting_manager
from app.service.schema import (
    AUTHORIZATION_SCHEMA,
    CLEARING_SCHEMA,
    GREETING_SCHEMA,
    REVERSAL_SCHEMA,
)

app = Flask(__name__)


@app.errorhandler(ValidationError)
def handle_validation_error(err):
    """Format JSON Schema validation error response."""
    return jsonify({"error": "Validation error", "message": err.message}), 400


@app.errorhandler(NotImplementedError)
def handle_not_implemented(err):
    """Format NotImplementedError response as HTTP 501."""
    message = str(err) or "Manager layer deferred to Spec 002"
    return jsonify({"error": "Not Implemented", "message": message}), 501


def _require_idempotency_key():
    """Extract and validate Idempotency-Key header."""
    key = request.headers.get("Idempotency-Key", "").strip()
    if not key:
        return None
    return key


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


@app.route("/authorizations", methods=["POST"])
def create_authorization():
    """Create a temporary hold against card limit."""
    idempotency_key = _require_idempotency_key()
    if not idempotency_key:
        return jsonify({"error": "Validation error", "message": "Missing or empty Idempotency-Key header"}), 400

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=AUTHORIZATION_SCHEMA)

    _request_entity = AuthorizationRequestEntity(
        card_id=data["card_id"],
        amount=float(data["amount"]),
        merchant=data["merchant"],
        idempotency_key=idempotency_key,
    )
    raise NotImplementedError("Manager layer deferred to Spec 002")


@app.route("/clearings", methods=["POST"])
def create_clearing():
    """Capture and settle funds (supports multi-clearing, over-capture, force-post)."""
    idempotency_key = _require_idempotency_key()
    if not idempotency_key:
        return jsonify({"error": "Validation error", "message": "Missing or empty Idempotency-Key header"}), 400

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=CLEARING_SCHEMA)

    _request_entity = ClearingRequestEntity(
        card_id=data["card_id"],
        amount=float(data["amount"]),
        merchant=data["merchant"],
        authorization_id=data.get("authorization_id"),
        idempotency_key=idempotency_key,
    )
    raise NotImplementedError("Manager layer deferred to Spec 002")


@app.route("/authorizations/<authorization_id>/reversals", methods=["POST"])
def reverse_authorization(authorization_id: str):
    """Cancel active remaining hold early."""
    idempotency_key = _require_idempotency_key()
    if not idempotency_key:
        return jsonify({"error": "Validation error", "message": "Missing or empty Idempotency-Key header"}), 400

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=REVERSAL_SCHEMA)

    _request_entity = ReversalRequestEntity(
        card_id=data["card_id"],
        authorization_id=authorization_id,
        amount=float(data["amount"]) if data.get("amount") is not None else None,
        idempotency_key=idempotency_key,
    )
    raise NotImplementedError("Manager layer deferred to Spec 002")


@app.route("/cards/<card_id>/balance", methods=["GET"])
def get_card_balance(card_id: str):
    """Retrieve card balances and available credit limit."""
    raise NotImplementedError("Manager layer deferred to Spec 002")


@app.route("/cards/<card_id>/transactions", methods=["GET"])
def get_card_transactions(card_id: str):
    """Retrieve card transaction history ledger."""
    raise NotImplementedError("Manager layer deferred to Spec 002")


if __name__ == "__main__":
    app.run(port=5001, debug=True)

