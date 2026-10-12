"""JSON Schemas for API request validation."""

# JSON Schema: validates that the body contains the user's name as a non-empty string
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

QUOTE_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
        "from_currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "to_currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "amount": {"type": "number", "exclusiveMinimum": 0},
    },
    "required": ["user_id", "from_currency", "to_currency", "amount"],
    "additionalProperties": False,
}

QUOTE_ACCEPT_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    "additionalProperties": False,
}

TRANSFER_REQUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "sender_id": {"type": "string", "minLength": 1},
        "recipient_id": {"type": "string", "minLength": 1},
        "currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "amount": {"type": "number", "exclusiveMinimum": 0},
        "note": {"type": "string", "maxLength": 255},
        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128},
    },
    "required": ["sender_id", "recipient_id", "currency", "amount"],
    "additionalProperties": False,
}

