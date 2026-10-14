"""Flask API service layer handling HTTP requests and validation for Food Delivery."""

from flask import Flask, jsonify, request
from jsonschema import ValidationError, validate

from app.adapter.food_delivery_adapter import (
    DishNotFoundError,
    EmptyCartError,
    IdempotencyConflictError,
    InsufficientPortionsError,
    InvalidTransitionError,
    OrderNotFoundError,
)
from app.manager.entities import (
    AddToCartRequestEntity,
    GreetingRequestEntity,
    OrderStatus,
    OrderTransitionRequestEntity,
    PlaceOrderRequestEntity,
)
from app.manager.food_delivery_manager import food_delivery_manager
from app.manager.greeting_manager import greeting_manager
from app.service.schema import (
    ADD_CART_ITEM_SCHEMA,
    GREETING_SCHEMA,
    ORDER_TRANSITION_SCHEMA,
    PLACE_ORDER_SCHEMA,
    SEED_DISH_SCHEMA,
)

app = Flask(__name__)


# --- Error Handlers ---


@app.errorhandler(ValidationError)
def handle_validation_error(err: ValidationError):
    """Format JSON Schema validation error response."""
    return jsonify({"error": "Validation error", "message": err.message}), 400


@app.errorhandler(DishNotFoundError)
def handle_dish_not_found(err: DishNotFoundError):
    """Format dish not found error response."""
    return jsonify({"error": "Not Found", "message": str(err)}), 404


@app.errorhandler(OrderNotFoundError)
def handle_order_not_found(err: OrderNotFoundError):
    """Format order not found error response."""
    return jsonify({"error": "Not Found", "message": str(err)}), 404


@app.errorhandler(EmptyCartError)
def handle_empty_cart(err: EmptyCartError):
    """Format empty cart error response."""
    return jsonify({"error": "Bad Request", "message": str(err)}), 400


@app.errorhandler(IdempotencyConflictError)
def handle_idempotency_conflict(err: IdempotencyConflictError):
    """Format idempotency conflict error response."""
    return jsonify({"error": "Conflict", "message": str(err)}), 409


@app.errorhandler(InvalidTransitionError)
def handle_invalid_transition(err: InvalidTransitionError):
    """Format invalid order status transition error response."""
    return jsonify({"error": "Bad Request", "message": str(err)}), 400


@app.errorhandler(InsufficientPortionsError)
def handle_insufficient_portions(err: InsufficientPortionsError):
    """Format insufficient portions error response when adding items to cart."""
    return jsonify({"error": "Bad Request", "message": str(err)}), 400


# --- Base & Greeting Routes ---


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
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


# --- Dish Routes ---


@app.route("/dishes", methods=["GET"])
def list_dishes():
    """List all dishes with portion statistics."""
    dishes = food_delivery_manager.list_dishes()
    return jsonify([dish.to_dict() for dish in dishes]), 200


@app.route("/dishes", methods=["POST"])
def create_or_seed_dish():
    """Seed or add a dish to the restaurant catalog."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=SEED_DISH_SCHEMA)

    dish = food_delivery_manager.seed_dish(
        dish_id=data["dish_id"],
        name=data["name"],
        price_per_unit=data["price_per_unit"],
        total_portions=data["total_portions"],
    )
    return jsonify(dish.to_dict()), 201


# --- Cart Routes ---


@app.route("/cart", methods=["GET"])
def get_cart():
    """Retrieve the single active shopping cart."""
    cart = food_delivery_manager.get_cart()
    return jsonify(cart.to_dict()), 200


@app.route("/cart/items", methods=["POST"])
def add_to_cart():
    """Add or increment items in the single active cart."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=ADD_CART_ITEM_SCHEMA)

    req_entity = AddToCartRequestEntity(
        dish_id=data["dish_id"],
        units=data["units"],
    )
    cart = food_delivery_manager.add_to_cart(req_entity)
    return jsonify(cart.to_dict()), 200


@app.route("/cart/items/<dish_id>", methods=["DELETE"])
def remove_from_cart(dish_id: str):
    """Remove or decrement items from the single active cart."""
    units_param = request.args.get("units")
    units = None
    if units_param is not None:
        try:
            units = int(units_param)
            if units <= 0:
                return jsonify({"error": "Validation error", "message": "units query param must be >= 1"}), 400
        except ValueError:
            return jsonify({"error": "Validation error", "message": "units query param must be an integer"}), 400

    cart = food_delivery_manager.remove_from_cart(dish_id, units=units)
    return jsonify(cart.to_dict()), 200


@app.route("/cart", methods=["DELETE"])
def clear_cart():
    """Clear all items from the active cart."""
    cart = food_delivery_manager.clear_cart()
    return jsonify(cart.to_dict()), 200


# --- Order Routes ---


@app.route("/orders", methods=["POST"])
def place_order():
    """Place an order from the active cart using an idempotency key."""
    idempotency_key = request.headers.get("Idempotency-Key")

    # If not in header, check JSON body
    data = request.get_json(silent=True)
    if not idempotency_key and data and isinstance(data, dict):
        validate(instance=data, schema=PLACE_ORDER_SCHEMA)
        idempotency_key = data.get("idempotency_key")

    if not idempotency_key or not idempotency_key.strip():
        return (
            jsonify({
                "error": "Bad Request",
                "message": "Missing required 'Idempotency-Key' header or 'idempotency_key' in request body.",
            }),
            400,
        )

    req_entity = PlaceOrderRequestEntity(idempotency_key=idempotency_key.strip())
    order, is_replay = food_delivery_manager.place_order(req_entity)

    if is_replay:
        return jsonify(order.to_dict()), 200

    if order.order_status == OrderStatus.ORDER_ACCEPTED:
        return jsonify(order.to_dict()), 201

    # Rejected order due to insufficient portions
    return jsonify(order.to_dict()), 422


@app.route("/orders", methods=["GET"])
def list_orders():
    """List all placed orders."""
    orders = food_delivery_manager.list_orders()
    return jsonify([order.to_dict() for order in orders]), 200


@app.route("/orders/<order_id>", methods=["GET"])
def get_order(order_id: str):
    """Retrieve details of a specific order."""
    order = food_delivery_manager.get_order(order_id)
    if not order:
        return jsonify({"error": "Not Found", "message": f"Order '{order_id}' not found."}), 404
    return jsonify(order.to_dict()), 200


@app.route("/orders/<order_id>/transitions", methods=["POST"])
def transition_order(order_id: str):
    """Transition an order to the next lifecycle status."""
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be valid JSON"}), 400

    validate(instance=data, schema=ORDER_TRANSITION_SCHEMA)

    target_status = OrderStatus(data["status"])
    req_entity = OrderTransitionRequestEntity(
        order_id=order_id,
        target_status=target_status,
    )
    order = food_delivery_manager.transition_order_status(req_entity)
    return jsonify(order.to_dict()), 200


if __name__ == "__main__":
    app.run(port=5001, debug=True)
