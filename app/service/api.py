"""Flask API service layer handling HTTP requests and validation."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

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


@app.errorhandler(NotImplementedError)
def handle_not_implemented(err: NotImplementedError):
    """Format 501 response when endpoint handler is not yet implemented."""
    return jsonify({"error": "Not Implemented", "message": str(err)}), 501


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/health", methods=["GET"])
def health():
    """Liveness health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/items", methods=["GET"])
def list_items():
    """List all catalog items with live stock metrics."""
    raise NotImplementedError("GET /items is not yet implemented")


@app.route("/items/<item_id>", methods=["GET"])
def get_item(item_id: str):
    """Get live stock metrics for a single item."""
    raise NotImplementedError(f"GET /items/{item_id} is not yet implemented")


@app.route("/reservations", methods=["POST"])
def create_reservation():
    """Request a temporary 30-second reservation lease."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=CREATE_RESERVATION_SCHEMA)

    raise NotImplementedError("POST /reservations is not yet implemented")


@app.route("/reservations/<reservation_id>/confirm", methods=["POST"])
def confirm_reservation(reservation_id: str):
    """Confirm checkout for an active reservation lease."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=CONFIRM_RESERVATION_SCHEMA)

    raise NotImplementedError(
        f"POST /reservations/{reservation_id}/confirm is not yet implemented"
    )


@app.route("/reservations/<reservation_id>/cancel", methods=["POST"])
def cancel_reservation(reservation_id: str):
    """Cancel an active reservation lease and release hold immediately."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=CANCEL_RESERVATION_SCHEMA)

    raise NotImplementedError(
        f"POST /reservations/{reservation_id}/cancel is not yet implemented"
    )


if __name__ == "__main__":
    app.run(port=5001, debug=True)
