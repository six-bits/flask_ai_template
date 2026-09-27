"""JSON Schemas for Chat Service API request validation."""

JOIN_ROOM_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1, "maxLength": 50},
    },
    "required": ["user_id"],
    "additionalProperties": False,
}

SEND_MESSAGE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1, "maxLength": 50},
        "content": {"type": "string", "minLength": 1, "maxLength": 2000},
    },
    "required": ["user_id", "content"],
    "additionalProperties": False,
}

LEAVE_ROOM_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "user_id": {"type": "string", "minLength": 1, "maxLength": 50},
    },
    "required": ["user_id"],
    "additionalProperties": False,
}
