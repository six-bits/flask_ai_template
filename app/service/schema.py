"""JSON Schemas for API request validation."""

# JSON Schema: validates container scheduling request payload
SCHEDULE_CONTAINER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "pattern": r"^\S+$",
        },
        "cpu": {
            "type": "integer",
            "minimum": 1,
        },
        "memory_mb": {
            "type": "integer",
            "minimum": 1,
        },
        "criteria": {
            "type": "integer",
            "enum": [0, 1],
        },
    },
    "required": ["name", "cpu", "memory_mb", "criteria"],
    "additionalProperties": False,
}

# Greeting schema for template backward compatibility
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
