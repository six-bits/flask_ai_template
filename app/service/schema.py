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

# FX Quote Creation Schema
CREATE_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
        "from_currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "to_currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "from_amount": {"type": "integer", "minimum": 1},
    },
    "required": ["user_id", "from_currency", "to_currency", "from_amount"],
    "additionalProperties": False,
}

# FX Quote Acceptance Schema (Must accept quote_id)
ACCEPT_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "quote_id": {"type": "string", "minLength": 1},
        "user_id": {"type": "string", "minLength": 1},
    },
    "required": ["quote_id", "user_id"],
    "additionalProperties": False,
}

# P2P Money Transfer Schema
P2P_TRANSFER_SCHEMA = {
    "type": "object",
    "properties": {
        "sender_user_id": {"type": "string", "minLength": 1},
        "recipient_user_id": {"type": "string", "minLength": 1},
        "currency": {"type": "string", "minLength": 3, "maxLength": 3},
        "amount": {"type": "integer", "minimum": 1},
    },
    "required": ["sender_user_id", "recipient_user_id", "currency", "amount"],
    "additionalProperties": False,
}
