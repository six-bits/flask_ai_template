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

### Step 3: Specification Content Requirements
Each specification document MUST detail the layered architecture:
1. **Overview**: Purpose and functional requirements of the service.
2. **Service Layer (`app/service/`)**:
   - HTTP routes, methods, path parameters, and query parameters.
   - JSON Schema definition to be placed in `app/service/schema.py`.
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
7. **Test Plan (`tests/test_api.py`)**:
   - Test cases covering valid requests, validation errors, edge cases, and layer entity interactions.

### Step 4: Review Before Implementation
- Present the generated specification file to the user for review before making code changes across the codebase.
