"""Flask API service layer handling HTTP requests and validation for container orchestration."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.manager.entities import (
    GreetingRequestEntity,
    ScheduleContainerRequestEntity,
)
from app.manager.greeting_manager import greeting_manager
from app.manager.orchestrator_manager import orchestrator_manager
from app.service.schema import GREETING_SCHEMA, SCHEDULE_CONTAINER_SCHEMA
from app.utils.exceptions import (
    ContainerAlreadyExistsError,
    ContainerAlreadyStoppedError,
    ContainerNotFoundError,
    InsufficientCapacityError,
)

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------


@app.errorhandler(ValidationError)
def handle_validation_error(err: ValidationError):
    """Format JSON Schema validation error response."""
    return jsonify({"error": "Validation error", "message": err.message}), 400


@app.errorhandler(ContainerAlreadyExistsError)
def handle_already_exists_error(err: ContainerAlreadyExistsError):
    """Format duplicate container conflict error response."""
    return jsonify({"error": "Conflict", "message": str(err)}), 409


@app.errorhandler(InsufficientCapacityError)
def handle_insufficient_capacity_error(err: InsufficientCapacityError):
    """Format insufficient fleet capacity error response."""
    return jsonify({"error": "Insufficient capacity", "message": str(err)}), 422


@app.errorhandler(ContainerNotFoundError)
def handle_not_found_error(err: ContainerNotFoundError):
    """Format container not found error response."""
    return jsonify({"error": "Not found", "message": str(err)}), 404


@app.errorhandler(ContainerAlreadyStoppedError)
def handle_already_stopped_error(err: ContainerAlreadyStoppedError):
    """Format container already stopped error response."""
    return jsonify({"error": "Bad request", "message": str(err)}), 400


# ---------------------------------------------------------------------------
# Core Service Endpoints
# ---------------------------------------------------------------------------


@app.route("/health", methods=["GET"])
def health():
    """Liveness health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/containers", methods=["POST"])
def schedule_container():
    """Schedule and deploy a container across the machine fleet."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=SCHEDULE_CONTAINER_SCHEMA)

    request_entity = ScheduleContainerRequestEntity(
        name=data["name"],
        cpu=data["cpu"],
        memory_mb=data["memory_mb"],
        criteria=data["criteria"],
    )

    response_entity = orchestrator_manager.schedule_container(request_entity)
    return jsonify(response_entity.to_dict()), 201


@app.route("/containers/<name>/stop", methods=["POST"])
def stop_container(name: str):
    """Stop a running container and reclaim fleet capacity."""
    response_entity = orchestrator_manager.stop_container(name)
    return jsonify(response_entity.to_dict()), 200


@app.route("/containers/<name>", methods=["GET"])
def get_container(name: str):
    """Retrieve details and host machine of a specific container."""
    response_entity = orchestrator_manager.get_container(name)
    return jsonify(response_entity.to_dict()), 200


@app.route("/fleet", methods=["GET"])
def get_fleet():
    """Retrieve live metrics and hosted containers for all fleet machines."""
    response_entity = orchestrator_manager.get_fleet()
    return jsonify(response_entity.to_dict()), 200


# ---------------------------------------------------------------------------
# Template Backward-Compatibility Endpoint
# ---------------------------------------------------------------------------


@app.route("/hello", methods=["POST"])
def greet():
    """Template greeting demonstration route."""
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
