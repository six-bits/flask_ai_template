# Problem Statement: Chat Service

## Raw User Request

Implement a set of APIs that can accomplish the following:
1. A user can join a chat room (`POST /rooms/<room_id>/join`).
2. After joining, a user can send a message to that chat room (`POST /rooms/<room_id>/messages`).
3. A user can retrieve messages from a chat room that they have joined (`GET /rooms/<room_id>/messages?user_id=<user_id>`).
4. (Optional) A user can leave a chat room (`POST /rooms/<room_id>/leave`).
5. The server should support multiple chat rooms.

Take into account this API will be consumed by a basic chat app (think: Slack, Discord, Basecamp, etc.).

## Notes & Constraints
- **Framework**: Lightweight Flask API using Python.
- **Strict API Scope**: Only the required chat APIs are exposed over HTTP. No extra HTTP APIs (such as user or room management endpoints) are added to the service layer.
- **Test Environment Provisioning**: The test environment is seeded in advance using Manager layer functions (`register_user`, `create_room`) to provision initial test users and rooms.
- **Payloads & Validation**: JSON format with validation via `jsonschema`.
- **Storage**: In-memory data storage (no external database required).
- **Authentication**: No authentication required (identity supplied via request payload or query parameter, e.g., `user_id`).
- **Error Mapping Invariants**:
  - `RoomNotFoundError` &rarr; `404 Not Found`
  - `UserNotFoundError` &rarr; `404 Not Found`
  - `UserNotMemberError` &rarr; `403 Forbidden`
  - `ValidationError` / `ChatManagerError` &rarr; `400 Bad Request`
  - Unhandled `Exception` &rarr; `500 Internal Server Error`
- **Architecture**: Follows template layered architecture (Service &rarr; Manager &rarr; Adapter) with decoupled boundary entities.
- **E2E Testing**: Full end-to-end integration tests orchestrating the complete Service &rarr; Manager &rarr; Adapter stack via HTTP client.




