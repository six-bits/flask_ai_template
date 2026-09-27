# Problem Statement: Chat Service

## Raw User Request

Implement a set of APIs that can accomplish the following:
1. A user can join a chat room.
2. After joining, a user can send a message to that chat room.
3. A user can retrieve messages from a chat room that they have joined.
4. (Optional) A user can leave a chat room.
5. The server should support multiple chat rooms.

Take into account this API will be consumed by a basic chat app (think: Slack, Discord, Basecamp, etc.).

## Notes & Constraints
- **Framework**: Lightweight Flask API using Python.
- **Payloads**: JSON format with validation.
- **Storage**: In-memory data storage (no external database required).
- **Authentication**: No authentication required (identity supplied via request payload or query parameter, e.g., `user_id`).
- **Tooling**: Standard HTTP clients (cURL, Postman, HTTPie) can inspect responses.
- **Validation**: JSON Schema using `jsonschema`.
- **Architecture**: Follows template layered architecture (Service &rarr; Manager &rarr; Adapter) with one function per class and decoupled boundary entities.
