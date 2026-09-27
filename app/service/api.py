"""Flask API service layer handling HTTP requests and validation."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.manager.entities import GreetingRequestEntity
from app.manager.greeting_manager import greeting_manager
from app.service.schema import GREETING_SCHEMA

app = Flask(__name__)


@app.errorhandler(ValidationError)
def handle_validation_error(err):
    """Format JSON Schema validation error response."""
    return jsonify({"error": "Validation error", "message": err.message}), 400


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


if __name__ == "__main__":
    app.run(port=5001, debug=True)
