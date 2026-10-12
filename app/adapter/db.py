"""Thread-safe in-memory database with pre-seeded fleet capacity."""

from contextlib import contextmanager
import threading
from typing import Dict, List, Optional

from app.adapter.entities import ContainerRecordEntity, MachineRecordEntity
from app.utils.constants import ContainerStatus

# Seed fleet specifications as required
INITIAL_FLEET = [
    {"machine_id": "mA", "total_cpu": 8, "total_memory_mb": 16000},
    {"machine_id": "mB", "total_cpu": 8, "total_memory_mb": 8000},
    {"machine_id": "mC", "total_cpu": 4, "total_memory_mb": 32000},
]


class InMemoryDatabase:
    """In-memory database storing machine and container records thread-safely."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._machines: Dict[str, MachineRecordEntity] = {}
        self._containers: Dict[str, ContainerRecordEntity] = {}
        self.reset()

    @contextmanager
    def transaction(self):
        """Context manager providing reentrant synchronization across multi-step mutations."""
        with self._lock:
            yield

    def reset(self) -> None:
        """Reset the database to initial seed data and purge containers."""
        with self._lock:
            self._machines = {}
            for item in INITIAL_FLEET:
                self._machines[item["machine_id"]] = MachineRecordEntity(
                    machine_id=item["machine_id"],
                    total_cpu=item["total_cpu"],
                    total_memory_mb=item["total_memory_mb"],
                    free_cpu=item["total_cpu"],
                    free_memory_mb=item["total_memory_mb"],
                    containers=[],
                )
            self._containers = {}

    def get_machine(self, machine_id: str) -> Optional[MachineRecordEntity]:
        """Fetch a machine record by its ID."""
        with self._lock:
            machine = self._machines.get(machine_id)
            if machine is None:
                return None
            # Return a copy to prevent accidental mutation outside transaction
            return MachineRecordEntity(
                machine_id=machine.machine_id,
                total_cpu=machine.total_cpu,
                total_memory_mb=machine.total_memory_mb,
                free_cpu=machine.free_cpu,
                free_memory_mb=machine.free_memory_mb,
                containers=list(machine.containers),
            )

    def get_all_machines(self) -> List[MachineRecordEntity]:
        """Fetch all machines in the fleet sorted by machine_id."""
        with self._lock:
            sorted_keys = sorted(self._machines.keys())
            return [self.get_machine(mid) for mid in sorted_keys if self.get_machine(mid) is not None]

    def get_container(self, name: str) -> Optional[ContainerRecordEntity]:
        """Fetch a container record by its unique name."""
        with self._lock:
            c = self._containers.get(name)
            if c is None:
                return None
            return ContainerRecordEntity(
                name=c.name,
                cpu=c.cpu,
                memory_mb=c.memory_mb,
                status=c.status,
                machine_id=c.machine_id,
            )

    def get_all_containers(self) -> List[ContainerRecordEntity]:
        """Fetch all registered containers."""
        with self._lock:
            return [
                ContainerRecordEntity(
                    name=c.name,
                    cpu=c.cpu,
                    memory_mb=c.memory_mb,
                    status=c.status,
                    machine_id=c.machine_id,
                )
                for c in self._containers.values()
            ]

    def allocate_container(
        self, name: str, cpu: int, memory_mb: int, machine_id: str
    ) -> ContainerRecordEntity:
        """Atomically deduct machine capacity and register a RUNNING container."""
        with self._lock:
            machine = self._machines[machine_id]
            machine.free_cpu -= cpu
            machine.free_memory_mb -= memory_mb
            machine.containers.append(name)

            record = ContainerRecordEntity(
                name=name,
                cpu=cpu,
                memory_mb=memory_mb,
                status=ContainerStatus.RUNNING.value,
                machine_id=machine_id,
            )
            self._containers[name] = record
            return self.get_container(name)

    def release_container(self, name: str) -> ContainerRecordEntity:
        """Atomically restore machine capacity and mark container as STOPPED."""
        with self._lock:
            record = self._containers[name]
            if record.machine_id and record.machine_id in self._machines:
                machine = self._machines[record.machine_id]
                machine.free_cpu += record.cpu
                machine.free_memory_mb += record.memory_mb
                if name in machine.containers:
                    machine.containers.remove(name)

            record.status = ContainerStatus.STOPPED.value
            return self.get_container(name)


# Default singleton instance
in_memory_db = InMemoryDatabase()
