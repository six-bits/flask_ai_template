# Specification Workflow Rule

When working on a problem statement, feature request, or toy service provided by the user, you MUST follow this specification workflow before writing implementation code:

## 1. Directory Structure

Ensure a `spec/` directory is created at the project root (`flask_ai_template/spec/`):

```text
flask_ai_template/
└── spec/
    ├── problem.md                           # Raw problem statement & requirements
    └── 001-instagram-comment-service.md     # Sequential technical specification
```

## 2. Workflow Steps

### Step 1: Capture the Problem Statement
- Create or update `spec/problem.md`.
- Document the raw user request, goals, constraints, and expected input/output behaviors.

### Step 2: Create the Numbered Specification File
- Naming convention: `NNN-<service-name>.md` with a 3-digit sequential number.
  - Examples:
    - `spec/001-instagram-comment-service.md`
    - `spec/002-twitter-timeline-service.md`
    - `spec/003-chat-messaging-service.md`
- Inspect existing files in `spec/` to determine the next sequential number (starts at `001`).

### Step 3: Scope & Phased Implementation Flexibility
A specification can target either the **entire stack** or **one layer at a time**:
- **Declare Implementation Scope** at the top of the spec:
  - `Scope: Full Stack` (Service &rarr; Manager &rarr; Adapter)
  - `Scope: Adapter Layer Only` (Storage/integration & adapter entities)
  - `Scope: Manager Layer Only` (Business logic, manager entities & stubbed/mocked adapter)
  - `Scope: Service Layer Only` (HTTP routes, schema validation & stubbed/mocked manager)
  - `Scope: Phased` (e.g. Phase 1: Adapter, Phase 2: Manager, Phase 3: Service)

### Step 4: Specification Content Requirements
Each specification document MUST detail the relevant layered architecture (mark layers as *In Scope* or *Deferred* based on Step 3):

1. **Overview & Scope**: Purpose, goals, and explicitly declared layer scope.
2. **Service Layer (`app/service/`)**:
   - HTTP routes, methods, path/query parameters.
   - JSON Schema definition for `app/service/schema.py`.
3. **Service &harr; Manager Contract (`app/manager/entities.py`)**:
   - Dataclass entities exchanged between Service and Manager (e.g. `CommentRequestEntity`, `CommentResponseEntity`).
4. **Manager Layer (`app/manager/`)**:
   - Business logic coordination.
   - Follow the **one function per class** pattern.
5. **Manager &harr; Adapter Contract (`app/adapter/entities.py`)**:
   - Dataclass entities exchanged between Manager and Adapter (e.g. `CommentRecordEntity`).
6. **Adapter Layer (`app/adapter/`)**:
   - In-memory persistence / external integration.
   - Follow the **one function per class** pattern.
7. **Test Plan (`tests/`)**:
   - If single layer: Unit tests targeting the isolated layer using mocks/stubs for adjacent layers.
   - If full stack: Integration tests covering the entire Service &rarr; Manager &rarr; Adapter flow.

### Step 5: Review Before Implementation
- Present the generated specification file (including the declared layer scope) to the user for review before writing implementation code.
