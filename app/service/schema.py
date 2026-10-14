"""JSON Schemas for API request validation."""

# Food Delivery Schemas
ADD_CART_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "dish_id": {"type": "string", "minLength": 1},
        "units": {"type": "integer", "minimum": 1},
    },
    "required": ["dish_id", "units"],
    "additionalProperties": False,
}

SEED_DISH_SCHEMA = {
    "type": "object",
    "properties": {
        "dish_id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "price_per_unit": {"type": "integer", "minimum": 0},
        "total_portions": {"type": "integer", "minimum": 1},
    },
    "required": ["dish_id", "name", "price_per_unit", "total_portions"],
    "additionalProperties": False,
}

PLACE_ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "idempotency_key": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

ORDER_TRANSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "ORDER_PREPARING",
                "ORDER_DELIVERING",
                "ORDER_COMPLETED",
                "ORDER_CANCELLED",
            ],
        },
    },
    "required": ["status"],
    "additionalProperties": False,
}

# Greeting Schema (backward compatibility)
GREETING_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "full_name": {"type": "string", "minLength": 1},
    },
    "anyOf": [
        {"required": ["name"]},
        {"required": ["full_name"]},
    ],
    "additionalProperties": False,
}
