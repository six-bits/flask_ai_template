"""Manager layer coordinating container orchestration business logic."""

from typing import Optional

from app.adapter.orchestrator_adapter import (
    ContainerOrchestratorAdapter,
    orchestrator_adapter,
)
from app.manager.entities import (
    ContainerResponseEntity,
    FleetInspectionResponseEntity,
    MachineInfoResponseEntity,
    ScheduleContainerRequestEntity,
)
from app.utils.constants import ContainerStatus, PlacementCriteria
from app.utils.exceptions import (
    ContainerAlreadyExistsError,
    ContainerAlreadyStoppedError,
    ContainerNotFoundError,
    InsufficientCapacityError,
)


class ContainerOrchestratorManager:
    """Manager coordinating candidate selection, placement criteria, and lifecycle transitions."""

    def __init__(self, adapter: Optional[ContainerOrchestratorAdapter] = None) -> None:
        self.adapter = adapter or orchestrator_adapter

    def schedule_container(
        self, request: ScheduleContainerRequestEntity
    ) -> ContainerResponseEntity:
        """Schedule and deploy a container across the machine fleet atomically."""
        with self.adapter.transaction():
            # 1. Uniqueness check
            existing = self.adapter.get_container(request.name)
            if existing is not None:
                raise ContainerAlreadyExistsError(
                    f"Container '{request.name}' already exists"
                )

            # 2. Filter eligible machines
            all_machines = self.adapter.get_all_machines()
            eligible = [
                m
                for m in all_machines
                if m.free_cpu >= request.cpu and m.free_memory_mb >= request.memory_mb
            ]
            if not eligible:
                raise InsufficientCapacityError(
                    f"No eligible machine found with {request.cpu} CPU units "
                    f"and {request.memory_mb} MB memory"
                )

            # 3. Placement scoring with tie-breaker
            if request.criteria == PlacementCriteria.CPU_FIRST.value:
                eligible.sort(key=lambda m: (-m.free_cpu, m.machine_id))
            else:
                eligible.sort(key=lambda m: (-m.free_memory_mb, m.machine_id))

            chosen_machine = eligible[0]

            # 4. Atomic allocation
            saved = self.adapter.allocate_container(
                name=request.name,
                cpu=request.cpu,
                memory_mb=request.memory_mb,
                machine_id=chosen_machine.machine_id,
            )

            return ContainerResponseEntity(
                name=saved.name,
                cpu=saved.cpu,
                memory_mb=saved.memory_mb,
                status=saved.status,
                machine_id=saved.machine_id,
            )

    def stop_container(self, name: str) -> ContainerResponseEntity:
        """Stop an active container and reclaim host machine resources."""
        with self.adapter.transaction():
            container = self.adapter.get_container(name)
            if container is None:
                raise ContainerNotFoundError(f"Container '{name}' not found")

            if container.status == ContainerStatus.STOPPED.value:
                raise ContainerAlreadyStoppedError(
                    f"Container '{name}' is already stopped"
                )

            stopped = self.adapter.release_container(name)
            return ContainerResponseEntity(
                name=stopped.name,
                cpu=stopped.cpu,
                memory_mb=stopped.memory_mb,
                status=stopped.status,
                machine_id=stopped.machine_id,
            )

    def get_container(self, name: str) -> ContainerResponseEntity:
        """Fetch status and assigned machine of a specific container."""
        with self.adapter.transaction():
            container = self.adapter.get_container(name)
            if container is None:
                raise ContainerNotFoundError(f"Container '{name}' not found")

            return ContainerResponseEntity(
                name=container.name,
                cpu=container.cpu,
                memory_mb=container.memory_mb,
                status=container.status,
                machine_id=container.machine_id,
            )

    def get_fleet(self) -> FleetInspectionResponseEntity:
        """Retrieve live metrics and hosted containers for all fleet machines."""
        with self.adapter.transaction():
            machines = self.adapter.get_all_machines()
            machine_entities = [
                MachineInfoResponseEntity(
                    machine_id=m.machine_id,
                    total_cpu=m.total_cpu,
                    total_memory_mb=m.total_memory_mb,
                    free_cpu=m.free_cpu,
                    free_memory_mb=m.free_memory_mb,
                    containers=list(m.containers),
                )
                for m in machines
            ]
            return FleetInspectionResponseEntity(machines=machine_entities)


# Default singleton instance
orchestrator_manager = ContainerOrchestratorManager()
