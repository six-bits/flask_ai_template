"""Cross-cutting constants and enums."""

from enum import Enum, IntEnum


class PlacementCriteria(IntEnum):
    """Container scheduling placement criteria."""
    CPU_FIRST = 0
    MEMORY_FIRST = 1


class ContainerStatus(str, Enum):
    """Container lifecycle status."""
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
