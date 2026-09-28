# Problem Statement: Chat Service

## Raw User Request

Implement a set of APIs that can accomplish the following:
1. A user can create a chat room.
2. A user can join an existing chat room.
3. After joining, a user can send a message to that chat room.
4. A user can retrieve messages from a chat room that they have joined.
5. (Optional) A user can leave a chat room.
6. The server should support multiple chat rooms.

Take into account this API will be consumed by a basic chat app (think: Slack, Discord, Basecamp, etc.).

## Notes & Constraints
- **Framework**: Lightweight Flask API using Python.
- **Payloads**: JSON format with validation.
- **Storage**: In-memory data storage (no external database required).
- **Authentication**: No authentication required (identity supplied via request payload or query parameter, e.g., `user_id`).
- **Room Lifecycle Invariant**: Rooms are NOT auto-created. A room must be explicitly created first via the room creation API. If a room does not exist, any operation on that room (`join`, `send_message`, `get_messages`, `leave`) MUST raise an error (`RoomNotFoundError` &rarr; `404 Not Found`).
- **Tooling**: Standard HTTP clients (cURL, Postman, HTTPie) can inspect responses.
- **Validation**: JSON Schema using `jsonschema`.
- **Architecture**: Follows template layered architecture (Service &rarr; Manager &rarr; Adapter) with decoupled boundary entities.
- **Persistence & Adapters**: In-memory persistence tracking room memberships and messages, isolated by room, with dedicated adapter contract entities.


