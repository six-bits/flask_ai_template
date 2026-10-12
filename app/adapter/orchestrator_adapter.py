"""Adapter layer providing persistence operations for container orchestration."""

from typing import List, Optional

from app.adapter.db import InMemoryDatabase, in_memory_db
from app.adapter.entities import ContainerRecordEntity, MachineRecordEntity


class ContainerOrchestratorAdapter:
    """Adapter interacting with the in-memory database."""

    def __init__(self, db: Optional[InMemoryDatabase] = None) -> None:
        self.db = db or in_memory_db

    def transaction(self):
        """Provide a reentrant context manager for multi-step mutations."""
        return self.db.transaction()

    def get_all_machines(self) -> List[MachineRecordEntity]:
        """Fetch all machines in the fleet."""
        return self.db.get_all_machines()

    def get_machine(self, machine_id: str) -> Optional[MachineRecordEntity]:
        """Fetch a specific machine by ID."""
        return self.db.get_machine(machine_id)

    def get_container(self, name: str) -> Optional[ContainerRecordEntity]:
        """Fetch a container by its unique name."""
        return self.db.get_container(name)

    def get_all_containers(self) -> List[ContainerRecordEntity]:
        """Fetch all containers."""
        return self.db.get_all_containers()

    def allocate_container(
        self, name: str, cpu: int, memory_mb: int, machine_id: str
    ) -> ContainerRecordEntity:
        """Reserve resources on machine and store active container."""
        return self.db.allocate_container(name, cpu, memory_mb, machine_id)

    def release_container(self, name: str) -> ContainerRecordEntity:
        """Release container resources and mark as stopped."""
        return self.db.release_container(name)

    def reset(self) -> None:
        """Reset the fleet and database."""
        self.db.reset()


# Default singleton instance
orchestrator_adapter = ContainerOrchestratorAdapter()
