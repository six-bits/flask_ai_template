"""Domain entities for the manager layer defining contracts with Service layer."""

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ScheduleContainerRequestEntity:
    """Request entity to schedule a new container."""
    name: str
    cpu: int
    memory_mb: int
    criteria: int


@dataclass
class ContainerResponseEntity:
    """Response entity representing a container's state."""
    name: str
    cpu: int
    memory_mb: int
    status: str
    machine_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to dictionary."""
        return asdict(self)


@dataclass
class MachineInfoResponseEntity:
    """Response entity representing a machine's live state."""
    machine_id: str
    total_cpu: int
    total_memory_mb: int
    free_cpu: int
    free_memory_mb: int
    containers: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to dictionary."""
        return asdict(self)


@dataclass
class FleetInspectionResponseEntity:
    """Response entity representing all machines in the fleet."""
    machines: List[MachineInfoResponseEntity]

    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to dictionary."""
        return {"machines": [m.to_dict() for m in self.machines]}


@dataclass
class GreetingRequestEntity:
    """Entity representing an incoming greeting request (template demo)."""
    name: str
    salutation: str = "Hello"


@dataclass
class GreetingResponseEntity:
    """Entity representing a processed greeting response (template demo)."""
    message: str
    salutation: str
    name: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to a dictionary for JSON serialization."""
        return asdict(self)
