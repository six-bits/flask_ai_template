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

# Supported ISO currency codes
SUPPORTED_CURRENCIES = ["USD", "EUR", "GBP"]

# Quote creation schema: from_amount must be an integer >= 1 in minor units
CREATE_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
        "from_currency": {"type": "string", "enum": SUPPORTED_CURRENCIES},
        "to_currency": {"type": "string", "enum": SUPPORTED_CURRENCIES},
        "from_amount": {"type": "integer", "minimum": 1},
    },
    "required": ["user_id", "from_currency", "to_currency", "from_amount"],
    "additionalProperties": False,
}

# Quote acceptance schema
ACCEPT_QUOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1},
    },
    "required": ["user_id"],
    "additionalProperties": False,
}

# Peer-to-peer transfer schema: amount must be an integer >= 1 in minor units
TRANSFER_SCHEMA = {
    "type": "object",
    "properties": {
        "from_user_id": {"type": "string", "minLength": 1},
        "to_user_id": {"type": "string", "minLength": 1},
        "currency": {"type": "string", "enum": SUPPORTED_CURRENCIES},
        "amount": {"type": "integer", "minimum": 1},
    },
    "required": ["from_user_id", "to_user_id", "currency", "amount"],
    "additionalProperties": False,
}

# Outbox events acknowledgment schema
ACK_OUTBOX_EVENTS_SCHEMA = {
    "type": "object",
    "properties": {
        "event_ids": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "minItems": 1,
        }
    },
    "required": ["event_ids"],
    "additionalProperties": False,
}

