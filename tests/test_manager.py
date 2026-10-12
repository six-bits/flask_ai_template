"""Unit tests for ContainerOrchestratorManager and ContainerOrchestratorAdapter."""

import pytest

from app.adapter.db import InMemoryDatabase
from app.adapter.orchestrator_adapter import ContainerOrchestratorAdapter
from app.manager.entities import ScheduleContainerRequestEntity
from app.manager.orchestrator_manager import ContainerOrchestratorManager
from app.utils.constants import ContainerStatus, PlacementCriteria
from app.utils.exceptions import (
    ContainerAlreadyExistsError,
    ContainerAlreadyStoppedError,
    ContainerNotFoundError,
    InsufficientCapacityError,
)


@pytest.fixture
def manager():
    """Create an isolated manager with a fresh in-memory database."""
    db = InMemoryDatabase()
    adapter = ContainerOrchestratorAdapter(db=db)
    return ContainerOrchestratorManager(adapter=adapter)


def test_criteria_1_memory_tie_breaker(manager):
    """Test criteria 1 tie-breaking when two machines have identical free memory."""
    # Initial fleet: mA=16000 MB, mB=8000 MB, mC=32000 MB.
    # Fill mC with 28000 MB so mC has 4000 MB free.
    manager.schedule_container(
        ScheduleContainerRequestEntity(name="c_fill_mc", cpu=1, memory_mb=28000, criteria=PlacementCriteria.MEMORY_FIRST.value)
    )
    # Fill mA with 8000 MB so mA has 8000 MB free, tying with mB's 8000 MB free.
    manager.schedule_container(
        ScheduleContainerRequestEntity(name="c_fill_ma", cpu=1, memory_mb=8000, criteria=PlacementCriteria.MEMORY_FIRST.value)
    )

    # Now mA and mB both have 8000 MB free (the maximum in the fleet).
    # Scheduling with criteria 1 for 1000 MB ties mA and mB -> tie-break chooses mA (mA < mB)
    res = manager.schedule_container(
        ScheduleContainerRequestEntity(name="c_tie", cpu=1, memory_mb=1000, criteria=PlacementCriteria.MEMORY_FIRST.value)
    )
    assert res.machine_id == "mA"


def test_cpu_fits_but_memory_exceeds(manager):
    """Test rejection when CPU is available but memory exceeds all machines."""
    with pytest.raises(InsufficientCapacityError):
        manager.schedule_container(
            ScheduleContainerRequestEntity(name="c_exceed_mem", cpu=1, memory_mb=50000, criteria=PlacementCriteria.CPU_FIRST.value)
        )


def test_memory_fits_but_cpu_exceeds(manager):
    """Test rejection when memory is available but CPU exceeds all machines."""
    with pytest.raises(InsufficientCapacityError):
        manager.schedule_container(
            ScheduleContainerRequestEntity(name="c_exceed_cpu", cpu=10, memory_mb=1000, criteria=PlacementCriteria.MEMORY_FIRST.value)
        )


def test_duplicate_schedule_raises_exception(manager):
    """Test duplicate container name raises ContainerAlreadyExistsError."""
    manager.schedule_container(
        ScheduleContainerRequestEntity(name="c1", cpu=1, memory_mb=1000, criteria=0)
    )
    with pytest.raises(ContainerAlreadyExistsError):
        manager.schedule_container(
            ScheduleContainerRequestEntity(name="c1", cpu=1, memory_mb=1000, criteria=0)
        )


def test_stop_lifecycle_and_errors(manager):
    """Test stop container lifecycle transitions and error cases."""
    manager.schedule_container(
        ScheduleContainerRequestEntity(name="c1", cpu=2, memory_mb=1000, criteria=0)
    )

    # Valid stop
    stopped = manager.stop_container("c1")
    assert stopped.status == ContainerStatus.STOPPED.value

    # Double stop raises ContainerAlreadyStoppedError
    with pytest.raises(ContainerAlreadyStoppedError):
        manager.stop_container("c1")

    # Stopping non-existent container raises ContainerNotFoundError
    with pytest.raises(ContainerNotFoundError):
        manager.stop_container("c_unknown")


def test_get_container_details_and_not_found(manager):
    """Test retrieving container details."""
    manager.schedule_container(
        ScheduleContainerRequestEntity(name="c1", cpu=2, memory_mb=1000, criteria=0)
    )

    c = manager.get_container("c1")
    assert c.name == "c1"
    assert c.cpu == 2
    assert c.status == ContainerStatus.RUNNING.value

    # Stopped container can still be retrieved
    manager.stop_container("c1")
    c_stopped = manager.get_container("c1")
    assert c_stopped.status == ContainerStatus.STOPPED.value

    with pytest.raises(ContainerNotFoundError):
        manager.get_container("ghost")
