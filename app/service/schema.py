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

AUTHORIZATION_SCHEMA = {
    "type": "object",
    "properties": {
        "card_id": {"type": "string", "minLength": 1},
        "amount": {"type": "number", "exclusiveMinimum": 0},
        "merchant": {"type": "string", "minLength": 1},
    },
    "required": ["card_id", "amount", "merchant"],
    "additionalProperties": False,
}

CLEARING_SCHEMA = {
    "type": "object",
    "properties": {
        "card_id": {"type": "string", "minLength": 1},
        "amount": {"type": "number", "exclusiveMinimum": 0},
        "merchant": {"type": "string", "minLength": 1},
        "authorization_id": {"type": "string", "minLength": 1},
    },
    "required": ["card_id", "amount", "merchant"],
    "additionalProperties": False,
}

REVERSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "card_id": {"type": "string", "minLength": 1},
        "amount": {"type": "number", "exclusiveMinimum": 0},
    },
    "required": ["card_id"],
    "additionalProperties": False,
}

