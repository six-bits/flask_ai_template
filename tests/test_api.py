"""Comprehensive tests for the Container Orchestration Service across all layers and scenarios."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from app.adapter.entities import ContainerRecordEntity, MachineRecordEntity
from app.adapter.orchestrator_adapter import ContainerOrchestratorAdapter
from app.manager.entities import (
    ContainerResponseEntity,
    FleetInspectionResponseEntity,
    ScheduleContainerRequestEntity,
)
from app.manager.orchestrator_manager import ContainerOrchestratorManager
from app.utils.constants import ContainerStatus, PlacementCriteria
from app.utils.exceptions import (
    ContainerAlreadyExistsError,
    ContainerAlreadyStoppedError,
    ContainerNotFoundError,
    InsufficientCapacityError,
)
from app.service.api import app


def test_health(client):
    """Test health check returns status ok."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Scenario 1: CPU-First Placement with Tie-Breaker
# ---------------------------------------------------------------------------


def test_scenario_1_cpu_first_placement_and_tie_breaking(client):
    """Scenario 1 from requirements:

    1. Deploy c1 (2 CPU, 2000 MB, criteria 0). Both mA and mB have 8 free CPU.
       Lexicographical tie-break assigns it to mA.
    2. Deploy c2 (6 CPU, 1000 MB, criteria 0). mB has 8 free CPU while mA has 6.
       Assigned to mB.
    3. Deploy c3 (3 CPU, 1000 MB, criteria 0). mA has 6 free CPU while mB has 2.
       Assigned to mA.
    """
    # 1. Deploy c1
    res1 = client.post(
        "/containers",
        json={"name": "c1", "cpu": 2, "memory_mb": 2000, "criteria": 0},
    )
    assert res1.status_code == 201
    data1 = res1.get_json()
    assert data1["name"] == "c1"
    assert data1["machine_id"] == "mA"
    assert data1["status"] == "RUNNING"

    # 2. Deploy c2
    res2 = client.post(
        "/containers",
        json={"name": "c2", "cpu": 6, "memory_mb": 1000, "criteria": 0},
    )
    assert res2.status_code == 201
    data2 = res2.get_json()
    assert data2["name"] == "c2"
    assert data2["machine_id"] == "mB"
    assert data2["status"] == "RUNNING"

    # 3. Deploy c3
    res3 = client.post(
        "/containers",
        json={"name": "c3", "cpu": 3, "memory_mb": 1000, "criteria": 0},
    )
    assert res3.status_code == 201
    data3 = res3.get_json()
    assert data3["name"] == "c3"
    assert data3["machine_id"] == "mA"
    assert data3["status"] == "RUNNING"

    # Verify fleet metrics after Scenario 1
    fleet_res = client.get("/fleet")
    assert fleet_res.status_code == 200
    machines = {m["machine_id"]: m for m in fleet_res.get_json()["machines"]}

    # mA: had 8 CPU - (2 + 3) = 3 free CPU, 16000 - (2000 + 1000) = 13000 free MB
    assert machines["mA"]["free_cpu"] == 3
    assert machines["mA"]["free_memory_mb"] == 13000
    assert sorted(machines["mA"]["containers"]) == ["c1", "c3"]

    # mB: had 8 CPU - 6 = 2 free CPU, 8000 - 1000 = 7000 free MB
    assert machines["mB"]["free_cpu"] == 2
    assert machines["mB"]["free_memory_mb"] == 7000
    assert machines["mB"]["containers"] == ["c2"]

    # mC: untouched (4 CPU, 32000 MB)
    assert machines["mC"]["free_cpu"] == 4
    assert machines["mC"]["free_memory_mb"] == 32000
    assert machines["mC"]["containers"] == []


# ---------------------------------------------------------------------------
# Scenario 2: Memory-First Placement and Rejection
# ---------------------------------------------------------------------------


def test_scenario_2_memory_first_placement_and_rejection(client):
    """Scenario 2 from requirements:

    1. Deploy c4 (2 CPU, 9000 MB, criteria 1). mC has the most free memory (32000 MB).
       Assigned to mC.
    2. Deploy c5 (2 CPU, 25000 MB, criteria 1). No machine has >= 25000 MB free memory.
       Request fails and zero resources are allocated.
    """
    # 1. Deploy c4
    res4 = client.post(
        "/containers",
        json={"name": "c4", "cpu": 2, "memory_mb": 9000, "criteria": 1},
    )
    assert res4.status_code == 201
    data4 = res4.get_json()
    assert data4["name"] == "c4"
    assert data4["machine_id"] == "mC"
    assert data4["status"] == "RUNNING"

    # 2. Deploy c5 (insufficient memory across fleet)
    res5 = client.post(
        "/containers",
        json={"name": "c5", "cpu": 2, "memory_mb": 25000, "criteria": 1},
    )
    assert res5.status_code == 422
    data5 = res5.get_json()
    assert data5["error"] == "Insufficient capacity"

    # Verify mC capacity: 32000 - 9000 = 23000 free MB
    fleet_res = client.get("/fleet")
    machines = {m["machine_id"]: m for m in fleet_res.get_json()["machines"]}
    assert machines["mC"]["free_cpu"] == 2
    assert machines["mC"]["free_memory_mb"] == 23000
    assert machines["mC"]["containers"] == ["c4"]


# ---------------------------------------------------------------------------
# Scenario 3: Stop & Reclaim Flow
# ---------------------------------------------------------------------------


def test_scenario_3_stop_and_reclaim_flow(client):
    """Scenario 3 from requirements:

    1. Deploy c4 (2 CPU, 9000 MB, criteria 1) on mC.
    2. Attempt c5 (2 CPU, 25000 MB, criteria 1) -> Fails (422).
    3. Stop c4 -> Resources on mC restored to 4 CPU and 32000 MB.
    4. Re-attempt c5 (2 CPU, 25000 MB, criteria 1) -> Succeeds on mC.
    5. Stopping c4 again (already stopped) -> 400 Bad Request.
    6. Stopping non-existent container -> 404 Not Found.
    """
    # Deploy c4
    client.post(
        "/containers",
        json={"name": "c4", "cpu": 2, "memory_mb": 9000, "criteria": 1},
    )

    # c5 fails
    res_c5_fail = client.post(
        "/containers",
        json={"name": "c5", "cpu": 2, "memory_mb": 25000, "criteria": 1},
    )
    assert res_c5_fail.status_code == 422

    # Stop c4
    res_stop_c4 = client.post("/containers/c4/stop")
    assert res_stop_c4.status_code == 200
    data_stop = res_stop_c4.get_json()
    assert data_stop["name"] == "c4"
    assert data_stop["status"] == "STOPPED"

    # Check mC capacity fully restored
    fleet_res = client.get("/fleet")
    machines = {m["machine_id"]: m for m in fleet_res.get_json()["machines"]}
    assert machines["mC"]["free_cpu"] == 4
    assert machines["mC"]["free_memory_mb"] == 32000
    assert machines["mC"]["containers"] == []

    # Retry c5 -> Now succeeds on mC
    res_c5_retry = client.post(
        "/containers",
        json={"name": "c5", "cpu": 2, "memory_mb": 25000, "criteria": 1},
    )
    assert res_c5_retry.status_code == 201
    assert res_c5_retry.get_json()["machine_id"] == "mC"
    assert res_c5_retry.get_json()["status"] == "RUNNING"

    # Stopping c4 again -> 400 Bad Request
    res_double_stop = client.post("/containers/c4/stop")
    assert res_double_stop.status_code == 400
    assert "already stopped" in res_double_stop.get_json()["message"]

    # Stopping non-existent container -> 404 Not Found
    res_non_existent = client.post("/containers/non_existent_c99/stop")
    assert res_non_existent.status_code == 404
    assert "not found" in res_non_existent.get_json()["message"]


# ---------------------------------------------------------------------------
# Scenario 4: Inspect Endpoints
# ---------------------------------------------------------------------------


def test_inspect_container_and_fleet(client):
    """Test inspecting specific container and full fleet."""
    # Deploy c1
    client.post(
        "/containers",
        json={"name": "c1", "cpu": 2, "memory_mb": 2000, "criteria": 0},
    )

    # Inspect c1
    res = client.get("/containers/c1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["name"] == "c1"
    assert data["cpu"] == 2
    assert data["memory_mb"] == 2000
    assert data["status"] == "RUNNING"
    assert data["machine_id"] == "mA"

    # Inspect non-existent container
    res_404 = client.get("/containers/ghost")
    assert res_404.status_code == 404

    # Inspect fleet
    res_fleet = client.get("/fleet")
    assert res_fleet.status_code == 200
    machines = res_fleet.get_json()["machines"]
    assert len(machines) == 3
    machine_ids = [m["machine_id"] for m in machines]
    assert machine_ids == ["mA", "mB", "mC"]


# ---------------------------------------------------------------------------
# Scenario 5: Validation & Error Handling
# ---------------------------------------------------------------------------


def test_schedule_validation_errors(client):
    """Test various payload validation errors."""
    # Blank name
    res = client.post(
        "/containers",
        json={"name": "", "cpu": 1, "memory_mb": 1000, "criteria": 0},
    )
    assert res.status_code == 400

    # Whitespace in name
    res = client.post(
        "/containers",
        json={"name": "c 1", "cpu": 1, "memory_mb": 1000, "criteria": 0},
    )
    assert res.status_code == 400

    # Negative / zero CPU
    res = client.post(
        "/containers",
        json={"name": "c1", "cpu": 0, "memory_mb": 1000, "criteria": 0},
    )
    assert res.status_code == 400

    # Negative / zero memory
    res = client.post(
        "/containers",
        json={"name": "c1", "cpu": 1, "memory_mb": -100, "criteria": 0},
    )
    assert res.status_code == 400

    # Invalid criteria
    res = client.post(
        "/containers",
        json={"name": "c1", "cpu": 1, "memory_mb": 1000, "criteria": 2},
    )
    assert res.status_code == 400

    # Missing required field
    res = client.post(
        "/containers",
        json={"name": "c1", "cpu": 1, "criteria": 0},
    )
    assert res.status_code == 400

    # Extra unexpected fields
    res = client.post(
        "/containers",
        json={"name": "c1", "cpu": 1, "memory_mb": 1000, "criteria": 0, "extra": "field"},
    )
    assert res.status_code == 400

    # Malformed JSON
    res = client.post(
        "/containers",
        data="{invalid_json",
        content_type="application/json",
    )
    assert res.status_code == 400


def test_duplicate_container_name_rejected(client):
    """Test duplicate container name returns 409 Conflict."""
    res1 = client.post(
        "/containers",
        json={"name": "c_dup", "cpu": 1, "memory_mb": 1000, "criteria": 0},
    )
    assert res1.status_code == 201

    res2 = client.post(
        "/containers",
        json={"name": "c_dup", "cpu": 2, "memory_mb": 2000, "criteria": 0},
    )
    assert res2.status_code == 409
    assert "already exists" in res2.get_json()["message"]


# ---------------------------------------------------------------------------
# Scenario 6: Concurrency & Over-Allocation Safety
# ---------------------------------------------------------------------------


def test_concurrent_scheduling_prevents_over_allocation(client):
    """Stress test: 20 concurrent schedule requests competing for limited fleet capacity.

    Total fleet capacity:
    - mA: 8 CPU, 16000 MB
    - mB: 8 CPU, 8000 MB
    - mC: 4 CPU, 32000 MB
    Total CPU across fleet = 20 CPU.
    Each request asks for 2 CPU and 2000 MB.
    At most 10 requests can succeed before CPU is exhausted.
    Remaining requests must return 422 Unprocessable Entity.
    No machine's free capacity must ever drop below 0!
    """
    def schedule_call(i):
        with app.test_client() as thread_client:
            return thread_client.post(
                "/containers",
                json={
                    "name": f"concurrent_c_{i}",
                    "cpu": 2,
                    "memory_mb": 2000,
                    "criteria": 0,
                },
            )

    num_requests = 16
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(schedule_call, i) for i in range(num_requests)]
        results = [f.result() for f in as_completed(futures)]

    successes = [r for r in results if r.status_code == 201]
    rejections = [r for r in results if r.status_code == 422]

    # Total fleet CPU = 20 (mA: 8, mB: 8, mC: 4). Each container takes 2 CPU and 2000 MB.
    # Exactly 10 containers fit across the fleet (mA: 4, mB: 4, mC: 2).
    # All 10 must succeed, and the remaining 6 must be rejected with 422 (no false rejections).
    assert len(successes) == 10
    assert len(rejections) == 6
    assert len(successes) + len(rejections) == num_requests

    # Verify no machine has negative capacity and invariants hold
    fleet_res = client.get("/fleet")
    for machine in fleet_res.get_json()["machines"]:
        assert machine["free_cpu"] >= 0
        assert machine["free_memory_mb"] >= 0
        assert machine["free_cpu"] <= machine["total_cpu"]
        assert machine["free_memory_mb"] <= machine["total_memory_mb"]


def test_concurrent_schedule_and_stop_race(client):
    """Stress test: Concurrent schedules and stops racing simultaneously."""
    # Pre-populate 5 containers
    for i in range(5):
        client.post(
            "/containers",
            json={"name": f"race_c_{i}", "cpu": 1, "memory_mb": 1000, "criteria": 0},
        )

    def do_work(i):
        with app.test_client() as thread_client:
            if i % 2 == 0:
                # Try to stop an existing container
                return thread_client.post(f"/containers/race_c_{i // 2}/stop")
            else:
                # Try to schedule a new container
                return thread_client.post(
                    "/containers",
                    json={"name": f"new_race_c_{i}", "cpu": 1, "memory_mb": 1000, "criteria": 1},
                )

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(do_work, i) for i in range(10)]
        results = [f.result() for f in as_completed(futures)]

    # All requests should return valid HTTP status codes (200, 201, 400, 422) without crashing
    for r in results:
        assert r.status_code in (200, 201, 400, 422)

    # Invariants must hold on fleet
    fleet_res = client.get("/fleet")
    for machine in fleet_res.get_json()["machines"]:
        assert machine["free_cpu"] >= 0
        assert machine["free_memory_mb"] >= 0
        assert machine["free_cpu"] <= machine["total_cpu"]
        assert machine["free_memory_mb"] <= machine["total_memory_mb"]


# ---------------------------------------------------------------------------
# Layer Contract Unit Tests
# ---------------------------------------------------------------------------


def test_layer_contracts_and_manager_adapter_flow():
    """Unit test verifying Service <-> Manager <-> Adapter contracts directly."""
    adapter = ContainerOrchestratorAdapter()
    adapter.reset()
    manager = ContainerOrchestratorManager(adapter=adapter)

    # 1. Service -> Manager contract
    req = ScheduleContainerRequestEntity(
        name="unit_c1", cpu=2, memory_mb=1000, criteria=PlacementCriteria.CPU_FIRST.value
    )
    resp = manager.schedule_container(req)
    assert isinstance(resp, ContainerResponseEntity)
    assert resp.name == "unit_c1"
    assert resp.machine_id == "mA"
    assert resp.status == ContainerStatus.RUNNING.value

    # 2. Manager -> Adapter contract
    record = adapter.get_container("unit_c1")
    assert isinstance(record, ContainerRecordEntity)
    assert record.name == "unit_c1"
    assert record.cpu == 2
    assert record.machine_id == "mA"

    # 3. Manager fleet inspection contract
    fleet_resp = manager.get_fleet()
    assert isinstance(fleet_resp, FleetInspectionResponseEntity)
    assert len(fleet_resp.machines) == 3
