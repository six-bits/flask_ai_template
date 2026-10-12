"""Adapter entities defining the data contract between Manager and Adapter layers."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ContainerRecordEntity:
    """Storage record for a container."""
    name: str
    cpu: int
    memory_mb: int
    status: str
    machine_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert container entity to dictionary."""
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
        """Convert machine entity to dictionary."""
        return asdict(self)


@dataclass
class GreetingRecordEntity:
    """Storage/persistence entity for greeting records in the template adapter."""
    name: str
    salutation: str
    message: str
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert adapter entity to dictionary."""
        return asdict(self)
