"""JSON Schemas for API request validation."""

# Schema for creating a 30-second inventory reservation lease
CREATE_RESERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "item_id": {
            "type": "string",
            "minLength": 1,
        },
        "user_id": {
            "type": "string",
            "minLength": 1,
        },
        "quantity": {
            "type": "integer",
            "minimum": 1,
        },
    },
    "required": ["item_id", "user_id", "quantity"],
    "additionalProperties": False,
}

# Schema for confirming a reservation checkout
CONFIRM_RESERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {
            "type": "string",
            "minLength": 1,
        },
    },
    "required": ["user_id"],
    "additionalProperties": False,
}

# Schema for explicitly cancelling a reservation lease
CANCEL_RESERVATION_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {
            "type": "string",
            "minLength": 1,
        },
    },
    "required": ["user_id"],
    "additionalProperties": False,
}
