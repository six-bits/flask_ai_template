# Problem: In-Memory Container Orchestration Service

## Problem Statement

Build an in-memory container orchestrator that schedules and manages containers across a fleet of cloud server machines (such as EC2 or Azure VMs). The system runs entirely in memory with no external database.

The service must expose an API allowing clients to:
1. Schedule / deploy containers across the fleet based on specific placement strategies.
2. Stop active containers and immediately reclaim their CPU and memory capacity.
3. Inspect live resource utilization across all machines in the fleet.
4. Inspect the status and resource requirements of individual containers.

---

## Fleet & Machine Constraints

- Fixed set of machines initialized with pre-seeded data:
  - **Machine `mA`**: 8 CPU units, 16,000 MB memory
  - **Machine `mB`**: 8 CPU units, 8,000 MB memory
  - **Machine `mC`**: 4 CPU units, 32,000 MB memory
- Machine Capacity:
  - $\text{Free CPU} = \text{Total CPU} - \sum(\text{CPU reserved by active containers on that machine})$
  - $\text{Free Memory} = \text{Total Memory} - \sum(\text{Memory reserved by active containers on that machine})$
- Eligibility: A machine can host a container if and only if $\text{Free CPU} \ge \text{Container Requested CPU}$ and $\text{Free Memory} \ge \text{Container Requested Memory}$.

---

## Container Lifecycle & Validation

- **RUNNING**: Assigned to a machine; actively reserves requested CPU and memory.
- **STOPPED**: Stopped container; immediately releases reserved CPU and memory back to the host machine. Reserves zero resources.
- **Uniqueness**: Container names are globally unique non-blank strings. Duplicate names must be rejected.
- **Validation**: CPU units and memory MB must always be positive integers ($> 0$).

---

## Placement Strategies & Tie-Breaking

When scheduling a container, the client provides a placement strategy:
- **Criteria 0 (CPU-First)**: Select the eligible machine with the maximum spare CPU units.
- **Criteria 1 (Memory-First)**: Select the eligible machine with the maximum spare memory in MB.
- **Tie-Breaking Rule**: If multiple machines tie with the same maximum spare capacity for the chosen criteria, select the machine with the lexicographically smallest `machine_id` (e.g., `mA` before `mB`).
- **No Fit Condition**: If no machine has sufficient free CPU and memory, the request must fail and allocate zero resources.

---

## Key Scenarios & Edge Cases

1. **CPU-First Placement with Tie-Breaker**:
   - `c1` (2 CPU, 2,000 MB, criteria 0) &rarr; `mA` and `mB` tie at 8 CPU &rarr; Lexicographical tie-break chooses `mA`.
   - `c2` (6 CPU, 1,000 MB, criteria 0) &rarr; `mB` has 8 free CPU, `mA` has 6 &rarr; Chooses `mB`.
   - `c3` (3 CPU, 1,000 MB, criteria 0) &rarr; `mA` has 6 free CPU, `mB` has 2 &rarr; Chooses `mA`.
2. **Memory-First Placement and Rejection**:
   - `c4` (2 CPU, 9,000 MB, criteria 1) &rarr; `mC` has 32,000 MB free &rarr; Chooses `mC`.
   - `c5` (2 CPU, 25,000 MB, criteria 1) &rarr; No machine has at least 25,000 MB free &rarr; Fails with no allocation.
3. **Stop & Reclaim Flow**:
   - Stop `c4` &rarr; Resources on `mC` are restored to 4 CPU and 32,000 MB.
   - Re-attempting `c5` (2 CPU, 25,000 MB, criteria 1) now succeeds and lands on `mC`.
   - Stopping `c4` again (already stopped) or stopping a non-existent container returns an appropriate error.
4. **Concurrency & Thread-Safety**:
   - Multiple concurrent scheduling requests competing for remaining resources must never over-allocate capacity.
   - Stop racing with schedule operations must execute atomically without inconsistent states or deadlocks.
