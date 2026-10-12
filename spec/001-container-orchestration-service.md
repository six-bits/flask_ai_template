# Specification: In-Memory Container Orchestration Service

**Specification ID**: `001-container-orchestration-service`  
**Scope**: `Full Stack (Service -> Manager -> Adapter)`

---

## 1. Overview & Scope

### 1.1 Purpose
Build a lightweight, thread-safe, in-memory container orchestrator in Flask that schedules, manages, and tracks container allocations across a fixed fleet of machines.

### 1.2 Declared Scope
- **Service Layer (`app/service/`)**: In Scope. Exposes REST API endpoints, validates requests against JSON Schema, and maps domain exceptions to standard HTTP error codes.
- **Cross-Cutting Utilities (`app/utils/`)**: In Scope. Shared enums, constants, and domain exceptions used across layers.
- **Service &harr; Manager Contract (`app/manager/entities.py`)**: In Scope. Typed dataclasses for input/output between Service and Manager.
- **Manager Layer (`app/manager/`)**: In Scope. Cohesive business logic in a single manager class (`ContainerOrchestratorManager`): candidate filtering, placement scoring (CPU-first vs Memory-first), lexicographical tie-breaking, and container lifecycle transitions executed within atomic storage transactions.
- **Manager &harr; Adapter Contract (`app/adapter/entities.py`)**: In Scope. Typed dataclasses for low-level storage entities (`ContainerRecordEntity`, `MachineRecordEntity`).
- **Adapter & Storage Layer (`app/adapter/`)**: In Scope. Cohesive adapter (`ContainerOrchestratorAdapter`) backed by a thread-safe, pre-seeded in-memory database (`InMemoryDatabase` in `app/adapter/db.py`) exposing reentrant transaction locking.
- **Concurrency & Over-Allocation Prevention**: In Scope. Explicit atomic transaction boundary spanning Check &rarr; Select &rarr; Reserve to eliminate TOCTOU race conditions.
- **Test Plan (`tests/`)**: In Scope. Comprehensive unit and end-to-end integration tests covering criteria 0/1 placement, tie-breakers, rejections, stop/reclaim flow, edge cases, and concurrency stress tests.

---

## 2. API Design & Service Layer (`app/service/`)

### 2.1 Route Definitions

| Method | Endpoint | Description | Success Code | Error Codes |
| :--- | :--- | :--- | :--- | :--- |
| `POST` | `/containers` | Schedule and deploy a container | `201 Created` | `400 Bad Request` (Invalid JSON / Schema)<br>`409 Conflict` (Duplicate container name)<br>`422 Unprocessable Entity` (Insufficient capacity) |
| `POST` | `/containers/<name>/stop` | Stop a running container and release resources | `200 OK` | `404 Not Found` (Container does not exist)<br>`400 Bad Request` (Container already stopped) |
| `GET` | `/containers/<name>` | Inspect status and host of a specific container | `200 OK` | `404 Not Found` (Container does not exist) |
| `GET` | `/fleet` | Inspect live resource metrics and containers across all machines | `200 OK` | None |
| `GET` | `/health` | Liveness health check probe | `200 OK` | None |

---

### 2.2 Endpoint Details & Request / Response Payloads

#### 1. Schedule Container: `POST /containers`
- **Request Body**:
  ```json
  {
    "name": "c1",
    "cpu": 2,
    "memory_mb": 2000,
    "criteria": 0
  }
  ```
- **Response (`201 Created`)**:
  ```json
  {
    "name": "c1",
    "cpu": 2,
    "memory_mb": 2000,
    "status": "RUNNING",
    "machine_id": "mA"
  }
  ```
- **Error Responses**:
  - `400 Bad Request`: Schema validation failure (e.g. `cpu <= 0`, blank name, missing fields, invalid criteria).
    ```json
    {"error": "Validation error", "message": "'cpu' must be greater than 0"}
    ```
  - `409 Conflict`: Duplicate container name.
    ```json
    {"error": "Conflict", "message": "Container 'c1' already exists"}
    ```
  - `422 Unprocessable Entity`: No machine in the fleet has enough CPU and memory. Zero resources are allocated.
    ```json
    {"error": "Insufficient capacity", "message": "No eligible machine found with 2 CPU units and 25000 MB memory"}
    ```

#### 2. Stop Container: `POST /containers/<name>/stop`
- **Path Parameter**: `name` (string) - globally unique container name.
- **Request Body**: None.
- **Response (`200 OK`)**:
  ```json
  {
    "name": "c1",
    "cpu": 2,
    "memory_mb": 2000,
    "status": "STOPPED",
    "machine_id": "mA"
  }
  ```
- **Error Responses**:
  - `404 Not Found`:
    ```json
    {"error": "Not found", "message": "Container 'c99' not found"}
    ```
  - `400 Bad Request`:
    ```json
    {"error": "Bad request", "message": "Container 'c1' is already stopped"}
    ```

#### 3. Inspect Container: `GET /containers/<name>`
- **Path Parameter**: `name` (string)
- **Response (`200 OK`)**:
  ```json
  {
    "name": "c1",
    "cpu": 2,
    "memory_mb": 2000,
    "status": "RUNNING",
    "machine_id": "mA"
  }
  ```
- **Error Response**:
  - `404 Not Found`:
    ```json
    {"error": "Not found", "message": "Container 'c1' not found"}
    ```

#### 4. Inspect Fleet: `GET /fleet`
- **Response (`200 OK`)**:
  ```json
  {
    "machines": [
      {
        "machine_id": "mA",
        "total_cpu": 8,
        "total_memory_mb": 16000,
        "free_cpu": 6,
        "free_memory_mb": 14000,
        "containers": ["c1"]
      },
      {
        "machine_id": "mB",
        "total_cpu": 8,
        "total_memory_mb": 8000,
        "free_cpu": 8,
        "free_memory_mb": 8000,
        "containers": []
      },
      {
        "machine_id": "mC",
        "total_cpu": 4,
        "total_memory_mb": 32000,
        "free_cpu": 4,
        "free_memory_mb": 32000,
        "containers": []
      }
    ]
  }
  ```

---

### 2.3 JSON Schema Definition (`app/service/schema.py`)

```python
SCHEDULE_CONTAINER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "minLength": 1,
            "pattern": r"^\S+$"  # non-blank, no leading/trailing whitespace
        },
        "cpu": {
            "type": "integer",
            "minimum": 1
        },
        "memory_mb": {
            "type": "integer",
            "minimum": 1
        },
        "criteria": {
            "type": "integer",
            "enum": [0, 1]
        }
    },
    "required": ["name", "cpu", "memory_mb", "criteria"],
    "additionalProperties": False,
}
```

---

## 3. Cross-Cutting Utilities (`app/utils/`)

To keep clean separation without cyclical dependencies, cross-cutting constants and domain exceptions live in `app/utils/`:

### 3.1 Constants & Enums (`app/utils/constants.py`)
```python
from enum import Enum, IntEnum

class PlacementCriteria(IntEnum):
    CPU_FIRST = 0
    MEMORY_FIRST = 1

class ContainerStatus(str, Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
```

### 3.2 Domain Exceptions (`app/utils/exceptions.py`)
```python
class ContainerOrchestratorException(Exception):
    """Base domain exception."""

class ContainerAlreadyExistsError(ContainerOrchestratorException):
    """Raised when scheduling a container with an existing name."""

class InsufficientCapacityError(ContainerOrchestratorException):
    """Raised when no machine has enough CPU and Memory."""

class ContainerNotFoundError(ContainerOrchestratorException):
    """Raised when requested container is not registered."""

class ContainerAlreadyStoppedError(ContainerOrchestratorException):
    """Raised when attempting to stop an already stopped container."""
```

---

## 4. Service &harr; Manager Contract (`app/manager/entities.py`)

Dataclasses defining communication between HTTP Service and Manager layers:

```python
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

@dataclass
class ScheduleContainerRequestEntity:
    name: str
    cpu: int
    memory_mb: int
    criteria: int  # 0: CPU-first, 1: Memory-first

@dataclass
class ContainerResponseEntity:
    name: str
    cpu: int
    memory_mb: int
    status: str
    machine_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class MachineInfoResponseEntity:
    machine_id: str
    total_cpu: int
    total_memory_mb: int
    free_cpu: int
    free_memory_mb: int
    containers: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class FleetInspectionResponseEntity:
    machines: List[MachineInfoResponseEntity]

    def to_dict(self) -> Dict[str, Any]:
        return {"machines": [m.to_dict() for m in self.machines]}
```

---

## 5. Manager Layer (`app/manager/orchestrator_manager.py`)

A single, cohesive manager class `ContainerOrchestratorManager` coordinates business rules and executes mutations inside atomic transactions:

### 5.1 Responsibilities & Algorithms
1. **`schedule_container(request: ScheduleContainerRequestEntity) -> ContainerResponseEntity`**:
   - Executes under `with self.adapter.transaction():`:
     - Checks if container name already exists &rarr; raises `ContainerAlreadyExistsError`.
     - Queries all machines from adapter snapshot.
     - Filters candidates where `free_cpu >= request.cpu` AND `free_memory_mb >= request.memory_mb`.
     - If candidate list is empty &rarr; raises `InsufficientCapacityError`.
     - Sorts candidates:
       - **Criteria 0 (CPU-First)**: Order by `(-m.free_cpu, m.machine_id)`.
       - **Criteria 1 (Memory-First)**: Order by `(-m.free_memory_mb, m.machine_id)`.
       - Lexicographical tie-breaking is inherently satisfied by `m.machine_id` ascending as secondary sort key.
     - Selects top candidate `best_machine = candidates[0]`.
     - Atomically commits placement via adapter `allocate_container(...)`.
   - Returns mapped `ContainerResponseEntity`.

2. **`stop_container(name: str) -> ContainerResponseEntity`**:
   - Executes under `with self.adapter.transaction():`:
     - Fetches container via adapter.
     - If container does not exist &rarr; raises `ContainerNotFoundError`.
     - If container status is already `STOPPED` &rarr; raise `ContainerAlreadyStoppedError`.
     - Commits release via adapter `release_container(name)`.
   - Returns updated `ContainerResponseEntity`.

3. **`get_container(name: str) -> ContainerResponseEntity`**:
   - Executes under `with self.adapter.transaction():`:
     - Fetches container via adapter.
     - If container does not exist &rarr; raises `ContainerNotFoundError`.
   - Returns mapped `ContainerResponseEntity`.

4. **`get_fleet() -> FleetInspectionResponseEntity`**:
   - Executes under `with self.adapter.transaction():`:
     - Fetches all machines from adapter sorted by `machine_id` ascending.
   - Returns mapped `FleetInspectionResponseEntity`.

---

## 6. Lowest-Level Entities & Contracts (`app/adapter/entities.py`)

The lowest-level domain entities represent storage records managed by the Adapter and In-Memory Database:

```python
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class ContainerRecordEntity:
    """Storage record for a container."""
    name: str
    cpu: int
    memory_mb: int
    status: str              # 'RUNNING' or 'STOPPED'
    machine_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class MachineRecordEntity:
    """Storage record for a server machine in the fleet."""
    machine_id: str
    total_cpu: int
    total_memory_mb: int
    free_cpu: int
    free_memory_mb: int
    containers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

---

## 7. Adapter & In-Memory Database Layer (`app/adapter/`)

### 7.1 In-Memory Database (`app/adapter/db.py`)
Class `InMemoryDatabase` holds runtime fleet state and provides synchronization using a reentrant lock (`threading.RLock()`):

- **Pre-Seeded Fleet Data**:
  - `mA`: 8 CPU, 16,000 MB memory
  - `mB`: 8 CPU, 8,000 MB memory
  - `mC`: 4 CPU, 32,000 MB memory
- **Data Stores**:
  - `_machines: Dict[str, MachineRecordEntity]`
  - `_containers: Dict[str, ContainerRecordEntity]`
  - `_lock: threading.RLock`
- **Context Manager**:
  - `transaction()`: Reentrant context manager `with self._lock:` guarding state transitions.
- **Methods**:
  - `reset()`: Resets fleet to original pre-seeded capacities and clears containers.
  - `get_machine(machine_id: str) -> Optional[MachineRecordEntity]`
  - `get_all_machines() -> List[MachineRecordEntity]`
  - `get_container(name: str) -> Optional[ContainerRecordEntity]`
  - `allocate_container(name: str, cpu: int, memory_mb: int, machine_id: str) -> ContainerRecordEntity`:
    Deducts machine free capacity (`free_cpu -= cpu`, `free_memory_mb -= memory_mb`), appends container name to machine's `containers` list, and stores container with `status="RUNNING"`.
  - `release_container(name: str) -> ContainerRecordEntity`:
    Restores machine free capacity (`free_cpu += cpu`, `free_memory_mb += memory_mb`), removes container name from machine's `containers` list, and marks container with `status="STOPPED"`.

### 7.2 Adapter Class (`app/adapter/orchestrator_adapter.py`)
Single adapter class `ContainerOrchestratorAdapter` exposing data access methods and the transaction context to the Manager:
- `transaction()`: Context manager delegating directly to `InMemoryDatabase.transaction()`.
- `get_all_machines() -> List[MachineRecordEntity]`
- `get_machine(machine_id: str) -> Optional[MachineRecordEntity]`
- `get_container(name: str) -> Optional[ContainerRecordEntity]`
- `allocate_container(name: str, cpu: int, memory_mb: int, machine_id: str) -> ContainerRecordEntity`
- `release_container(name: str) -> ContainerRecordEntity`
- `reset() -> None`

---

## 8. Concurrency Model & Over-Allocation Prevention

### 8.1 The Race Condition (TOCTOU)
In a multi-threaded web server, a Time-of-Check to Time-of-Use race occurs if candidate evaluation is decoupled from resource reservation:
1. Thread 1 and Thread 2 both check `mA` simultaneously and find 8 free CPU.
2. Both threads independently select `mA` for a 6 CPU container.
3. If reservation is not atomic with selection, `mA` is assigned 12 CPU &rarr; **Over-allocation**.
4. Even with a post-check in DB, Thread 2 would fail, ignoring `mB` which had 8 free CPU &rarr; **False Rejection**.

### 8.2 The Solution: Atomic Transaction Boundary
Over-allocation is prevented by expanding the critical section across the entire scheduling sequence:
$$\text{Acquire Lock} \longrightarrow \text{Validate Uniqueness} \longrightarrow \text{Find Eligible} \longrightarrow \text{Score \& Tie-Break} \longrightarrow \text{Reserve Resources} \longrightarrow \text{Release Lock}$$

```text
Thread 1 (c1: 6 CPU)                  Thread 2 (c2: 6 CPU)
────────────────────                  ────────────────────
[Acquires Lock]                       [Blocks waiting for Lock]
• Checks fleet: mA=8, mB=8            ...
• Picks mA; free_cpu: 8 -> 2          ...
• Saves c1 (RUNNING on mA)            ...
[Releases Lock]                       [Acquires Lock]
                                      • Checks fleet: mA=2, mB=8
                                      • mA ineligible! Picks mB (8 free)
                                      • Saves c2 (RUNNING on mB)
                                      [Releases Lock]
```

### 8.3 Invariants & Guarantees
1. **Capacity Invariant**: For every machine $M$, $0 \le \text{free\_cpu} \le \text{total\_cpu}$ and $0 \le \text{free\_memory\_mb} \le \text{total\_memory\_mb}$ at all times.
2. **Stop vs. Schedule Race**: A `stop` request releases resources atomically. If it completes before a racing `schedule`, the scheduled container can claim the released capacity immediately. If it completes after, resources are reclaimed without desynchronizing counters.
3. **Deadlock Immunity**: All operations acquire only a single lock (`threading.RLock`) in a uniform direction and release it immediately. No nested locks or circular dependencies exist.

---

## 9. Test Plan (`tests/`)

### 9.1 Unit Tests (`tests/test_manager.py` / `tests/test_adapter.py`)
- **Placement Logic**: Verify criteria 0 picks max spare CPU, criteria 1 picks max spare memory, and tie-breaking selects smallest machine ID alphabetically.
- **Rejection**: Test `InsufficientCapacityError` when requested CPU or memory exceeds all available machines.
- **State Transitions**: Test valid stop updates capacity and double-stop raises `ContainerAlreadyStoppedError`.
- **Duplicate Prevention**: Test duplicate name raises `ContainerAlreadyExistsError`.

### 9.2 End-to-End API Integration Tests (`tests/test_api.py`)
- **Scenario 1 (CPU-First Placement with Tie-Breaker)**:
  - Deploy `c1` (2 CPU, 2000 MB, criteria 0) &rarr; Expect `mA` (8 vs 8 tie broken by `mA` < `mB`).
  - Deploy `c2` (6 CPU, 1000 MB, criteria 0) &rarr; Expect `mB` (free CPU 8 > 6).
  - Deploy `c3` (3 CPU, 1000 MB, criteria 0) &rarr; Expect `mA` (free CPU 6 > 2).
- **Scenario 2 (Memory-First Placement and Rejection)**:
  - Deploy `c4` (2 CPU, 9000 MB, criteria 1) &rarr; Expect `mC` (free memory 32,000 MB).
  - Deploy `c5` (2 CPU, 25000 MB, criteria 1) &rarr; Expect `422 Unprocessable Entity` (zero resources allocated).
- **Scenario 3 (Stop & Reclaim Flow)**:
  - Stop `c4` &rarr; Expect `200 OK`, `status="STOPPED"`. Inspect `/fleet` &rarr; `mC` has 4 CPU and 32,000 MB free.
  - Retry deploying `c5` (2 CPU, 25000 MB, criteria 1) &rarr; Expect `201 Created` assigned to `mC`.
  - Stopping `c4` again &rarr; Expect `400 Bad Request`.
  - Stopping non-existent `c99` &rarr; Expect `404 Not Found`.
- **Scenario 4 (Inspect Endpoints)**:
  - `GET /containers/c1` &rarr; Expect correct details.
  - `GET /containers/unknown` &rarr; Expect `404 Not Found`.
  - `GET /fleet` &rarr; Expect list of all 3 machines with correct active containers and free capacity.
- **Scenario 5 (Validation & Error Handling)**:
  - Invalid types, negative/zero CPU or memory, missing parameters, malformed JSON &rarr; Expect `400 Bad Request`.
  - Duplicate container schedule &rarr; Expect `409 Conflict`.
- **Scenario 6 (Concurrency Stress & Over-Allocation Safety)**:
  - Concurrent scheduling using `ThreadPoolExecutor` competing for limited resources &rarr; Assert no machine's free capacity drops below 0 and sum of allocated resources never exceeds total capacity.
  - Concurrent schedule + stop races &rarr; Assert fleet capacities remain mathematically consistent and no deadlocks occur.
