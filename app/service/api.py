"""Chat Service HTTP API layer."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.manager import chat_manager, messages_manager
from app.manager.entities import (
    GetMessagesRequestEntity,
    JoinRoomRequestEntity,
    LeaveRoomRequestEntity,
    SendMessageRequestEntity,
)
from app.manager.exceptions import (
    ChatManagerError,
    RoomNotFoundError,
    UserNotFoundError,
    UserNotMemberError,
)
from app.service.schema import (
    JOIN_ROOM_SCHEMA,
    LEAVE_ROOM_SCHEMA,
    SEND_MESSAGE_SCHEMA,
)

app = Flask(__name__)


# ==============================================================================
# Error Handlers
# ==============================================================================

@app.errorhandler(ValidationError)
def handle_validation_error(err):
    """Format JSON Schema validation error response."""
    return jsonify({"error": "Validation error", "message": err.message}), 400


@app.errorhandler(UserNotFoundError)
def handle_user_not_found(err: UserNotFoundError):
    """Handle user not found error."""
    return jsonify({"error": "Not Found", "message": str(err)}), 404


@app.errorhandler(UserNotMemberError)
def handle_user_not_member(err: UserNotMemberError):
    """Handle permission error when user has not joined the room."""
    return jsonify({"error": "Forbidden", "message": str(err)}), 403


@app.errorhandler(RoomNotFoundError)
def handle_room_not_found(err: RoomNotFoundError):
    """Handle room not found error."""
    return jsonify({"error": "Not Found", "message": str(err)}), 404



@app.errorhandler(ChatManagerError)
def handle_chat_manager_error(err: ChatManagerError):
    """Handle general chat manager domain errors."""
    return jsonify({"error": "Bad Request", "message": str(err)}), 400


@app.errorhandler(500)
@app.errorhandler(Exception)
def handle_generic_exception(err: Exception):
    """Handle unexpected server errors, returning clean 500 JSON."""
    app.logger.exception(err)
    return jsonify({
        "error": "Internal Server Error",
        "message": "An unexpected error occurred while processing the request",
    }), 500


# ==============================================================================
# Routes
# ==============================================================================

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/rooms/<room_id>/join", methods=["POST"])
def join_room(room_id: str):
    """Join a chat room."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=JOIN_ROOM_SCHEMA)

    request_entity = JoinRoomRequestEntity(
        room_id=room_id,
        user_id=data["user_id"],
    )
    response_entity = chat_manager.join(request_entity)

    return jsonify(response_entity.to_dict()), 200


@app.route("/rooms/<room_id>/messages", methods=["POST"])
def send_message(room_id: str):
    """Send a message to a chat room."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=SEND_MESSAGE_SCHEMA)

    request_entity = SendMessageRequestEntity(
        room_id=room_id,
        user_id=data["user_id"],
        content=data["content"],
    )
    response_entity = messages_manager.send_message(request_entity)

    return jsonify(response_entity.to_dict()), 201


@app.route("/rooms/<room_id>/messages", methods=["GET"])
def get_messages(room_id: str):
    """Retrieve messages from a chat room."""
    user_id = request.args.get("user_id")
    if not user_id or not user_id.strip():
        return jsonify({
            "error": "Bad Request",
            "message": "Query parameter 'user_id' is required",
        }), 400

    request_entity = GetMessagesRequestEntity(
        room_id=room_id,
        user_id=user_id.strip(),
    )
    messages = messages_manager.get_messages(request_entity)

    return jsonify([m.to_dict() for m in messages]), 200


@app.route("/rooms/<room_id>/leave", methods=["POST"])
def leave_room(room_id: str):
    """Leave a chat room."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=LEAVE_ROOM_SCHEMA)

    request_entity = LeaveRoomRequestEntity(
        room_id=room_id,
        user_id=data["user_id"],
    )
    response_entity = chat_manager.leave(request_entity)

    return jsonify(response_entity.to_dict()), 200


if __name__ == "__main__":
    app.run(port=5001, debug=True)
