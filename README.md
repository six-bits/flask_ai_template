# Flask Layered Architecture Template

A minimalist Flask application template following the **Service &rarr; Manager &rarr; Adapter** layered architecture pattern.

> [!NOTE]
> **Example Reference Implementation**:
> The greeting functionality (`POST /hello`, `GreetingManager`, `GreetingAdapter`, and greeting entities) included in this repository is merely a **minimal working example** to demonstrate layer communication and entity contracts.
> 
> This repository is structured as a **reusable template foundation** for building more complex toy Flask applications (e.g., chat services, in-memory social feeds, notification engines, or mock microservices).

---

## Architectural Principles

1. **Strict Layer Separation**:
   $$\text{Service Layer (HTTP)} \longrightarrow \text{Manager Layer (Business Logic)} \longrightarrow \text{Adapter Layer (Data/External)}$$
2. **Distinct Entity Contracts**:
   - **Service &harr; Manager Contract**: Defined in [`app/manager/entities.py`](app/manager/entities.py). The Service layer only talks to the Manager using these entities.
   - **Manager &harr; Adapter Contract**: Defined in [`app/adapter/entities.py`](app/adapter/entities.py). The Adapter layer only talks to the Manager using these entities.
3. **Single Responsibility (One Function per Class)**:
   - To keep boilerplate minimal and testing straightforward, each component class exposes **one focused function** per workflow.

---

## Architecture & Data Flow (Greeting Example)

```text
┌──────────────────────────────────────┐
│            Service Layer             │  HTTP Routes, query params & JSON Schema validation
│         app/service/api.py           │
└──────────────────┬───────────────────┘
                   │  Contract: GreetingRequestEntity & GreetingResponseEntity
                   │            (defined in app/manager/entities.py)
                   ▼
┌──────────────────────────────────────┐
│            Manager Layer             │  Class GreetingManager: single function greet()
│    app/manager/greeting_manager.py   │  (translates service entities <-> adapter entities)
└──────────────────┬───────────────────┘
                   │  Contract: GreetingRecordEntity
                   │            (defined in app/adapter/entities.py)
                   ▼
┌──────────────────────────────────────┐
│            Adapter Layer             │  Class GreetingAdapter: single function save()
│    app/adapter/greeting_adapter.py   │  (in-memory storage / database / external client)
└──────────────────────────────────────┘
```

### Components Breakdown

| Layer | Directory / File | Role in Template | Example Implementation |
| :--- | :--- | :--- | :--- |
| **Service** | [`app/service/api.py`](app/service/api.py) | Parses HTTP, runs JSON Schema validation, calls Manager | Route: `POST /hello` |
| **Service Schema** | [`app/service/schema.py`](app/service/schema.py) | JSON Schema Draft 2020-12 input schemas | `GREETING_SCHEMA` |
| **Manager Contract** | [`app/manager/entities.py`](app/manager/entities.py) | Contract between Service and Manager | `GreetingRequestEntity`, `GreetingResponseEntity` |
| **Manager** | [`app/manager/greeting_manager.py`](app/manager/greeting_manager.py) | Business logic and entity translation | `GreetingManager.greet()` |
| **Adapter Contract** | [`app/adapter/entities.py`](app/adapter/entities.py) | Contract between Manager and Adapter | `GreetingRecordEntity` |
| **Adapter** | [`app/adapter/greeting_adapter.py`](app/adapter/greeting_adapter.py) | In-memory persistence / external clients | `GreetingAdapter.save()` |

---

## Extending This Template for Complex Applications

To build a more complex toy app (e.g., a Chat Service or Social Feed), follow the established pattern:

1. **Define Schema**: Add your JSON validation schema in [`app/service/schema.py`](app/service/schema.py).
2. **Define Manager Entities**: Add request/response dataclasses in [`app/manager/entities.py`](app/manager/entities.py).
3. **Define Adapter Entities**: Add storage/record dataclasses in [`app/adapter/entities.py`](app/adapter/entities.py).
4. **Implement Adapter**: Add persistence/integration methods in [`app/adapter/`](app/adapter/).
5. **Implement Manager**: Add business logic and entity translation in [`app/manager/`](app/manager/).
6. **Expose Endpoint**: Wire up the route in [`app/service/api.py`](app/service/api.py).
7. **Add Tests**: Write tests in [`tests/test_api.py`](tests/test_api.py).

---

## Quickstart

### 1. Activate the Virtual Environment
```bash
source .venv/bin/activate
```

### 2. Run the Development Server
```bash
python -m app.service.api
```
Starts at `http://127.0.0.1:5001`.

### 3. Run the Test Suite
```bash
pytest
```

---

## Example API Request (Greeting Demo)

```bash
curl -X POST "http://127.0.0.1:5001/hello?salutation=Welcome" \
  -H "Content-Type: application/json" \
  -d '{"name": "Alice Smith"}'
```

**Response (`200 OK`)**:
```json
{
  "id": 1,
  "message": "Welcome, Alice Smith!",
  "name": "Alice Smith",
  "salutation": "Welcome"
}
```
