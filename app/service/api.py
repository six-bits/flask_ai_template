"""Chat Service HTTP API layer (Stub Implementation)."""

from datetime import datetime, timezone
from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.service.schema import (
    JOIN_ROOM_SCHEMA,
    LEAVE_ROOM_SCHEMA,
    SEND_MESSAGE_SCHEMA,
)

app = Flask(__name__)


@app.errorhandler(ValidationError)
def handle_validation_error(err):
    """Format JSON Schema validation error response."""
    return jsonify({"error": "Validation error", "message": err.message}), 400


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/rooms/<room_id>/join", methods=["POST"])
def join_room(room_id: str):
    """Join a chat room (Stub)."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=JOIN_ROOM_SCHEMA)

    return jsonify({
        "room_id": room_id,
        "user_id": data["user_id"],
        "status": "joined",
    }), 200


@app.route("/rooms/<room_id>/messages", methods=["POST"])
def send_message(room_id: str):
    """Send a message to a chat room (Stub)."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=SEND_MESSAGE_SCHEMA)

    timestamp = datetime.now(timezone.utc).isoformat()

    return jsonify({
        "id": 1,
        "room_id": room_id,
        "user_id": data["user_id"],
        "content": data["content"],
        "timestamp": timestamp,
    }), 201


@app.route("/rooms/<room_id>/messages", methods=["GET"])
def get_messages(room_id: str):
    """Retrieve messages from a chat room (Stub)."""
    user_id = request.args.get("user_id")
    if not user_id or not user_id.strip():
        return jsonify({
            "error": "Bad Request",
            "message": "Query parameter 'user_id' is required",
        }), 400

    timestamp = datetime.now(timezone.utc).isoformat()

    return jsonify([
        {
            "id": 1,
            "room_id": room_id,
            "user_id": user_id.strip(),
            "content": "Hello team, welcome to the channel!",
            "timestamp": timestamp,
        }
    ]), 200


@app.route("/rooms/<room_id>/leave", methods=["POST"])
def leave_room(room_id: str):
    """Leave a chat room (Stub)."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=LEAVE_ROOM_SCHEMA)

    return jsonify({
        "room_id": room_id,
        "user_id": data["user_id"],
        "status": "left",
    }), 200


if __name__ == "__main__":
    app.run(port=5001, debug=True)
