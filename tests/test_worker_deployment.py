from __future__ import annotations

import asyncio
import os
import signal
import socket
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from temporalio.testing import WorkflowEnvironment

from app.registry import AgentRegistry
from app.sdk.contracts import AgentMetadata
from app.storage.repository import ExecutionRepository, init_db
from app.temporal.config import TemporalConfig
from app.temporal.worker import (
    create_temporal_worker,
    get_worker_identity,
    configure_worker_logging,
    run_worker,
)
from app.temporal.workflows import DynamicLangGraphWorkflow
from app.workflows.models import WorkflowDefinition, WorkflowNode, MappingValue


def _setup_mock_registry() -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(
        AgentMetadata(id="test_worker_agent", name="Test Worker Agent", description="Echo text"),
        lambda req, ctx: {"output": req.inputs.get("text", "")},
    )
    return registry


# -----------------------------------------------------------------------------
# 1. Worker Identity and Logging Tests
# -----------------------------------------------------------------------------
def test_worker_identity_metadata():
    """Verify worker identity contains instance ID, hostname, and PID."""
    os.environ["WORKER_INSTANCE"] = "3"
    try:
        identity = get_worker_identity()
        assert identity["instance_id"] == "3"
        assert identity["hostname"] == socket.gethostname()
        assert identity["pid"] == os.getpid()
        assert identity["formatted"] == f"worker-3@{socket.gethostname()}:{os.getpid()}"
    finally:
        os.environ.pop("WORKER_INSTANCE", None)

    # Explicit instance ID override
    override_id = get_worker_identity("99")
    assert override_id["instance_id"] == "99"
    assert override_id["formatted"] == f"worker-99@{socket.gethostname()}:{os.getpid()}"


def test_worker_logging_configuration():
    """Verify worker logging configuration sets custom identity format without crashing."""
    configure_worker_logging("worker-test@host:1234")
    # Verify logger handles call cleanly
    import logging
    test_logger = logging.getLogger("test_worker")
    test_logger.info("Test log line with worker identity")


# -----------------------------------------------------------------------------
# 2. Database Path Configuration & Validation Tests
# -----------------------------------------------------------------------------
def test_database_path_configuration(tmp_path: Path):
    """Verify AGENT_PLATFORM_DB_PATH environment variable is respected."""
    db_file = tmp_path / "custom_platform.db"
    old_env = os.environ.get("AGENT_PLATFORM_DB_PATH")
    try:
        os.environ["AGENT_PLATFORM_DB_PATH"] = str(db_file)
        repo = ExecutionRepository()
        assert repo.path == str(db_file.resolve())
        assert db_file.exists()
    finally:
        if old_env is not None:
            os.environ["AGENT_PLATFORM_DB_PATH"] = old_env
        else:
            os.environ.pop("AGENT_PLATFORM_DB_PATH", None)


def test_database_path_invalid_parent_directory():
    """Verify clear error if configured DB path parent directory does not exist."""
    invalid_path = "/non_existent_folder_abc123/database.db"
    with pytest.raises(ValueError, match="parent directory does not exist"):
        ExecutionRepository(invalid_path)


def test_database_production_requires_existing_db(tmp_path: Path):
    """Verify production workers fail clearly if unintended rogue DB would be created."""
    non_existent_db = tmp_path / "missing_prod.db"
    old_env = os.environ.get("AGENT_PLATFORM_ENV")
    try:
        os.environ["AGENT_PLATFORM_ENV"] = "production"
        with pytest.raises(ValueError, match="Production environment requires pre-existing database"):
            ExecutionRepository(str(non_existent_db))

        # init_db explicitly permits initializing the database in production
        repo = init_db(str(non_existent_db))
        assert non_existent_db.exists()
        repo.close()
    finally:
        if old_env is not None:
            os.environ["AGENT_PLATFORM_ENV"] = old_env
        else:
            os.environ.pop("AGENT_PLATFORM_ENV", None)


# -----------------------------------------------------------------------------
# 3. SQLite Concurrency & Exponential Backoff Retry Tests
# -----------------------------------------------------------------------------
def test_sqlite_retry_on_transient_lock():
    """Verify _execute_with_retry retries on transient SQLite locked errors and succeeds."""
    repo = ExecutionRepository(":memory:")
    call_count = 0

    def flaky_action():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise sqlite3.OperationalError("database is locked")
        return "success"

    result = repo._execute_with_retry(flaky_action, max_retries=5, initial_delay=0.01)
    assert result == "success"
    assert call_count == 3


def test_sqlite_retry_exceeds_max_retries():
    """Verify persistent lock contention raises OperationalError after bounded retries."""
    repo = ExecutionRepository(":memory:")
    call_count = 0

    def always_locked():
        nonlocal call_count
        call_count += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        repo._execute_with_retry(always_locked, max_retries=3, initial_delay=0.01)

    assert call_count == 3


def test_concurrent_writes_across_threads(tmp_path: Path):
    """Verify multiple concurrent writes succeed with WAL mode and busy timeout."""
    import concurrent.futures
    db_file = tmp_path / "concurrent_test.db"
    repo = ExecutionRepository(str(db_file))

    def write_events(worker_num: int):
        thread_repo = ExecutionRepository(str(db_file))
        for i in range(15):
            thread_repo.add_event(f"run-{worker_num}", f"node-{i}", "succeeded", {"count": i})
        thread_repo.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(write_events, w) for w in range(4)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    rows = repo._connection.execute("SELECT COUNT(*) FROM events").fetchone()
    assert rows[0] == 4 * 15
    repo.close()


# -----------------------------------------------------------------------------
# 4. Multi-Worker Scaling on Same Task Queue Tests
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_two_workers_polling_same_task_queue():
    """Verify two independent Temporal Worker instances poll and execute tasks from the same queue."""
    env = await WorkflowEnvironment.start_local()
    try:
        registry = _setup_mock_registry()
        repo = ExecutionRepository(":memory:")

        wf_def = WorkflowDefinition(
            id="multi_worker_flow",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="step",
                    type="agent",
                    agent_id="test_worker_agent",
                    execute_in="activity",
                    input_mappings={"text": MappingValue(path="workflow_input.text")},
                )
            ],
            edges=[],
        )
        repo.save_workflow(wf_def.model_dump(by_alias=True))

        task_queue = "shared-worker-queue"
        cfg1 = TemporalConfig(task_queue=task_queue)
        cfg2 = TemporalConfig(task_queue=task_queue)

        client2 = await env.connect_client()
        worker1 = create_temporal_worker(client=env.client, registry=registry, repository=repo, config=cfg1, identity="worker-proc-1")
        worker2 = create_temporal_worker(client=client2, registry=registry, repository=repo, config=cfg2, identity="worker-proc-2")

        # Run both workers simultaneously polling the same task queue
        async with worker1, worker2:
            handles = []
            for i in range(4):
                handle = await env.client.start_workflow(
                    DynamicLangGraphWorkflow.run,
                    {
                        "workflow_id": "multi_worker_flow",
                        "workflow_version": "1.0.0",
                        "run_id": f"multi-run-{i}",
                        "workflow_input": {"text": f"payload-{i}"},
                    },
                    id=f"wf-multi-{i}",
                    task_queue=task_queue,
                )
                handles.append(handle)

            results = await asyncio.gather(*[h.result() for h in handles])
            assert len(results) == 4
            for i, res in enumerate(results):
                assert res["node_outputs"]["step"]["output"] == f"payload-{i}"
    finally:
        await env.shutdown()


# -----------------------------------------------------------------------------
# 5. Graceful Shutdown & Worker Recovery Tests
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_worker_graceful_shutdown():
    """Verify worker shuts down cleanly when stop_event is triggered."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        registry = _setup_mock_registry()
        repo = ExecutionRepository(":memory:")

        task_queue = "shutdown-test-queue"
        cfg = TemporalConfig(task_queue=task_queue, worker_shutdown_timeout_seconds=5.0)

        stop_event = asyncio.Event()

        # Launch run_worker with custom stop_event
        worker_task = asyncio.create_task(
            run_worker(
                client=env.client,
                config=cfg,
                repository_path=":memory:",
                instance_id="test-graceful-1",
                stop_event=stop_event,
            )
        )

        # Give worker a moment to start
        await asyncio.sleep(0.2)
        assert not worker_task.done()

        # Signal graceful shutdown
        stop_event.set()

        # Worker should finish gracefully without timeout error
        await asyncio.wait_for(worker_task, timeout=10.0)
        assert worker_task.done()
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_unexpected_worker_crash_and_restart():
    """Verify that when a worker fails mid-execution, a restarted worker resumes execution."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        registry = _setup_mock_registry()
        repo = ExecutionRepository(":memory:")

        wf_def = WorkflowDefinition(
            id="failover_flow",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="step",
                    type="agent",
                    agent_id="test_worker_agent",
                    execute_in="activity",
                    input_mappings={"text": MappingValue(path="workflow_input.text")},
                )
            ],
            edges=[],
        )
        repo.save_workflow(wf_def.model_dump(by_alias=True))

        task_queue = "failover-test-queue"
        cfg = TemporalConfig(task_queue=task_queue)

        # 1. Start workflow when NO worker is active
        handle = await env.client.start_workflow(
            DynamicLangGraphWorkflow.run,
            {
                "workflow_id": "failover_flow",
                "workflow_version": "1.0.0",
                "run_id": "failover-run-1",
                "workflow_input": {"text": "recovered task"},
            },
            id="wf-failover-1",
            task_queue=task_queue,
        )

        # 2. Worker 1 starts up, simulates a crash by exiting
        worker1 = create_temporal_worker(client=env.client, registry=registry, repository=repo, config=cfg)
        async with worker1:
            pass  # Exits immediately, simulating crash before completing tasks

        # 3. Worker 2 (restarted worker) starts up and picks up the queued task
        worker2 = create_temporal_worker(client=env.client, registry=registry, repository=repo, config=cfg)
        async with worker2:
            result = await handle.result()
            assert result["node_outputs"]["step"]["output"] == "recovered task"
    finally:
        await env.shutdown()
