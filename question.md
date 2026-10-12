# Problem: In-Memory Container Orchestration Service

We're building an in-memory container orchestrator that schedules and manages containers across a fleet of cloud server machines (like EC2 or Azure VMs). 

Everything runs in memory with no external database. Your service must expose an API that allows clients to schedule containers, stop containers, and inspect live resource utilization across the fleet.

---

### Fleet and Resources

The orchestrator manages a fixed set of machines. Each machine has a globally unique ID, a total number of CPU units, and a total amount of memory in megabytes.

At any given moment, a machine's free capacity is defined as:
- Free CPU = Total CPU minus the sum of CPU units reserved by all active containers on that machine.
- Free Memory = Total Memory minus the sum of memory in MB reserved by all active containers on that machine.

A container cannot be scheduled on a machine unless that machine has both enough free CPU and enough free memory to satisfy the container's requested resources.

---

### Container Lifecycle

- **RUNNING**: When a container is successfully assigned to a machine, it enters the RUNNING state and reserves its requested CPU and memory on that machine.
- **STOPPED**: When a container is stopped, its CPU and memory are immediately released back to the host machine's free capacity. A container that is stopped reserves zero resources.
- **Uniqueness**: Container names are globally unique non-blank strings. The system must reject duplicate container names.
- **Validation**: CPU units and memory MB requested by a container must always be positive integers.

---

### Placement Criteria & Tie-Breaking

When scheduling a container, the caller provides a placement strategy:

- **Criteria 0 (CPU-First)**: Pick the eligible machine with the maximum spare CPU units available.
- **Criteria 1 (Memory-First)**: Pick the eligible machine with the maximum spare memory in MB available.
- **Tie-Breaking Rule**: If multiple machines are tied with the same maximum spare capacity for the chosen criteria, pick the machine with the lexicographically smallest machine ID (for example, pick `mA` over `mB`).
- **No Fit Condition**: If no machine in the fleet has sufficient free CPU and memory, the request must fail and allocate zero resources.

---

### Operations to Expose via API

Design and expose the following operations through your API:

1. **Schedule / Deploy Container**: Assigns a new container to the best-fit machine according to the requested criteria, reserves the resources, and marks it as RUNNING. Returns an error if the container name already exists or if no machine has enough resources.
2. **Stop Container**: Stops an active container and immediately releases its CPU and memory back to its host machine. Returns an error if the container does not exist or is already stopped.
3. **Inspect Fleet / Machines**: Retrieves live resource metrics for all machines in the fleet (total capacity, free capacity, and hosted containers).
4. **Inspect Container**: Retrieves the current status, resource requirements, and assigned host machine of a specific container.

---

### Starting Seed Data

Initialize your service with the following machine fleet:
- Machine `mA`: 8 CPU units, 16,000 MB memory
- Machine `mB`: 8 CPU units, 8,000 MB memory
- Machine `mC`: 4 CPU units, 32,000 MB memory

---

### Key Scenarios & Edge Cases to Handle

1. **CPU-First Placement with Tie-Breaker**:
   - Deploy `c1` (2 CPU, 2000 MB, criteria 0). Both `mA` and `mB` have 8 free CPU. Lexicographical tie-break assigns it to `mA`.
   - Deploy `c2` (6 CPU, 1000 MB, criteria 0). `mB` has 8 free CPU while `mA` has 6. Assigned to `mB`.
   - Deploy `c3` (3 CPU, 1000 MB, criteria 0). `mA` has 6 free CPU while `mB` has 2. Assigned to `mA`.

2. **Memory-First Placement and Rejection**:
   - Deploy `c4` (2 CPU, 9000 MB, criteria 1). `mC` has the most free memory (32,000 MB). Assigned to `mC`.
   - Deploy `c5` (2 CPU, 25000 MB, criteria 1). No machine has at least 25,000 MB free memory. Request fails.

3. **Stop & Reclaim Flow**:
   - Stop `c4`. Resources on `mC` are restored to 4 CPU and 32,000 MB.
   - Re-attempting to deploy `c5` (2 CPU, 25000 MB, criteria 1) now succeeds and lands on `mC`.
   - Stopping `c4` again (already stopped) or stopping a non-existent container returns an appropriate error.

4. **Concurrency & Race Conditions**:
   - Multiple concurrent scheduling requests competing for the last remaining resources on a machine must never over-allocate CPU or memory.
   - A container stop racing against a parallel container schedule on the same machine must correctly release and claim resources without deadlocks or inconsistent states.
