from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from typing import Any
import pytest
from fastapi.testclient import TestClient
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.langgraph import LangGraphPlugin
from temporalio.common import RetryPolicy

from app.api.app import create_app
from app.registry import AgentRegistry
from app.sdk.contracts import AgentMetadata
from app.runtime.runner import AgentRunner
from app.storage.repository import ExecutionRepository
from app.workflows.builder import WorkflowBuilder
from app.workflows.models import WorkflowDefinition, WorkflowNode, WorkflowEdge, Condition, MappingValue
from app.temporal import (
    TemporalConfig,
    set_temporal_client,
    DynamicLangGraphWorkflow,
    BatchLangGraphWorkflow,
    create_temporal_worker,
    create_temporal_schedule,
    get_temporal_schedule,
    list_temporal_schedules,
    pause_temporal_schedule,
    unpause_temporal_schedule,
    trigger_temporal_schedule,
    delete_temporal_schedule,
)


def _setup_test_registry() -> AgentRegistry:
    registry = AgentRegistry()

    def text_proc(req, ctx):
        return {"text": req.inputs.get("text", "")}

    def text_ana(req, ctx):
        return {"text": req.inputs.get("text", "")}

    registry.register(
        AgentMetadata(
            id="text_processor",
            name="Text Processor",
            description="Processes text",
        ),
        text_proc,
    )
    registry.register(
        AgentMetadata(
            id="text_analyzer",
            name="Text Analyzer",
            description="Analyzes text",
        ),
        text_ana,
    )
    return registry


@pytest.mark.asyncio
async def test_temporal_dynamic_workflow_execution():
    """Verify end-to-end execution of a registered workflow under Temporal Worker using LangGraphPlugin."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        registry = _setup_test_registry()
        repo = ExecutionRepository(":memory:")

        # Define a 2-node parallel workflow
        wf_def = WorkflowDefinition(
            id="dynamic_parallel_flow",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="node_proc",
                    type="agent",
                    agent_id="text_processor",
                    execute_in="activity",
                    timeout_seconds=30,
                    input_mappings={"text": MappingValue(path="workflow_input.text")},
                ),
                WorkflowNode(
                    id="node_ana",
                    type="agent",
                    agent_id="text_analyzer",
                    execute_in="activity",
                    timeout_seconds=30,
                    input_mappings={"text": MappingValue(path="workflow_input.text")},
                ),
            ],
            edges=[],  # Both execute in parallel from START to END
        )
        repo.save_workflow(wf_def.model_dump(by_alias=True))

        task_queue = "test-dynamic-queue"
        cfg = TemporalConfig(task_queue=task_queue)
        worker = create_temporal_worker(
            client=env.client,
            registry=registry,
            repository=repo,
            config=cfg,
        )

        async with worker:
            handle = await env.client.start_workflow(
                DynamicLangGraphWorkflow.run,
                {
                    "workflow_id": "dynamic_parallel_flow",
                    "workflow_version": "1.0.0",
                    "run_id": "dyn-run-1",
                    "workflow_input": {"text": "distributed agents"},
                },
                id="dyn-wf-1",
                task_queue=task_queue,
            )
            result = await handle.result()

            assert "node_proc" in result["node_outputs"]
            assert "node_ana" in result["node_outputs"]
            assert result["node_outputs"]["node_proc"]["text"] == "distributed agents"
            assert result["node_outputs"]["node_ana"]["text"] == "distributed agents"
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_temporal_conditional_routing_and_bounded_loops():
    """Verify conditional edge routing and bounded loop execution under Temporal and LangGraph."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        registry = _setup_test_registry()
        repo = ExecutionRepository(":memory:")

        # Workflow: START -> node_proc -> (if loop_counters.node_proc < 3: loop back to node_proc, else END)
        wf_def = WorkflowDefinition(
            id="looping_flow",
            version="1.0.0",
            max_steps=10,
            nodes=[
                WorkflowNode(
                    id="node_step",
                    type="agent",
                    agent_id="text_processor",
                    execute_in="activity",
                    input_mappings={"text": MappingValue(literal="loop text")},
                ),
            ],
            edges=[
                WorkflowEdge(
                    **{
                        "from": "node_step",
                        "to": "node_step",
                        "condition": Condition(
                            path="loop_counters.node_step",
                            operator="less_than",
                            value=3,
                        ),
                    }
                )
            ],
        )
        repo.save_workflow(wf_def.model_dump(by_alias=True))

        # 1. Direct LangGraph verification
        builder = WorkflowBuilder(registry)
        compiled = builder.build(wf_def)
        direct_res = await compiled.ainvoke(
            {
                "run_id": "loop-direct-1",
                "workflow_id": "looping_flow",
                "workflow_version": "1.0.0",
                "workflow_input": {},
            },
            {"configurable": {"thread_id": "loop-direct-1"}},
        )
        assert direct_res["loop_counters"]["node_step"] == 3

        # 2. Temporal execution verification
        task_queue = "loop-queue"
        cfg = TemporalConfig(task_queue=task_queue)
        worker = create_temporal_worker(
            client=env.client,
            registry=registry,
            repository=repo,
            config=cfg,
        )

        async with worker:
            handle = await env.client.start_workflow(
                DynamicLangGraphWorkflow.run,
                {
                    "workflow_id": "looping_flow",
                    "workflow_version": "1.0.0",
                    "run_id": "loop-temporal-1",
                    "workflow_input": {},
                },
                id="loop-wf-1",
                task_queue=task_queue,
            )
            result = await handle.result()
            assert result["loop_counters"]["node_step"] == 3
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_temporal_batch_workflow_concurrency():
    """Verify BatchLangGraphWorkflow coordinates bounded parallel execution over independent items."""
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        registry = _setup_test_registry()
        repo = ExecutionRepository(":memory:")

        wf_def = WorkflowDefinition(
            id="batch_target_flow",
            version="1.0.0",
            nodes=[
                WorkflowNode(
                    id="step",
                    type="agent",
                    agent_id="text_processor",
                    execute_in="activity",
                    input_mappings={"text": MappingValue(path="workflow_input.doc_name")},
                )
            ],
            edges=[],
        )
        repo.save_workflow(wf_def.model_dump(by_alias=True))

        task_queue = "batch-test-queue"
        cfg = TemporalConfig(task_queue=task_queue)
        worker = create_temporal_worker(
            client=env.client,
            registry=registry,
            repository=repo,
            config=cfg,
        )

        async with worker:
            items = [{"item_id": f"doc-{i}", "input": {"doc_name": f"Document {i}.pdf"}} for i in range(5)]
            handle = await env.client.start_workflow(
                BatchLangGraphWorkflow.run,
                {
                    "batch_id": "batch-101",
                    "workflow_id": "batch_target_flow",
                    "workflow_version": "1.0.0",
                    "items": items,
                    "concurrency": 2,
                },
                id="batch-parent-101",
                task_queue=task_queue,
            )
            batch_result = await handle.result()

            assert batch_result["total_items"] == 5
            assert batch_result["succeeded_count"] == 5
            assert batch_result["failed_count"] == 0
            assert len(batch_result["items"]) == 5
            assert batch_result["status"] == "succeeded"
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_temporal_schedules_crud_and_trigger():
    """Verify Temporal Schedules creation, describe, pause, unpause, trigger, and deletion."""
    env = await WorkflowEnvironment.start_local()
    try:
        task_queue = "schedule-crud-queue"
        schedule_id = "test-sched-1"

        # 1. Create schedule
        handle = await create_temporal_schedule(
            client=env.client,
            schedule_id=schedule_id,
            workflow_id="test_flow",
            cron_or_interval="1h",
            input_payload={"test": "val"},
            task_queue=task_queue,
            paused=False,
        )
        assert handle is not None

        # 2. Get schedule description
        desc = await get_temporal_schedule(env.client, schedule_id)
        assert desc["id"] == schedule_id
        assert desc["paused"] is False
        assert len(desc["next_run_times"]) > 0

        # 3. List schedules
        schedules = await list_temporal_schedules(env.client)
        assert any(s["id"] == schedule_id for s in schedules)

        # 4. Pause and unpause
        await pause_temporal_schedule(env.client, schedule_id)
        desc_p = await get_temporal_schedule(env.client, schedule_id)
        assert desc_p["paused"] is True

        await unpause_temporal_schedule(env.client, schedule_id)
        desc_u = await get_temporal_schedule(env.client, schedule_id)
        assert desc_u["paused"] is False

        # 5. Delete schedule
        await delete_temporal_schedule(env.client, schedule_id)
        with pytest.raises(Exception):
            await get_temporal_schedule(env.client, schedule_id)
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_api_execution_backends_and_schedules():
    """Verify FastAPI endpoints handle direct vs temporal execution and schedule operations."""
    env = await WorkflowEnvironment.start_local()
    try:
        set_temporal_client(env.client)
        repo = ExecutionRepository(":memory:")
        app = create_app(repository=repo)
        client = TestClient(app)

        # Register an agent and workflow in repository
        workflow = {
            "id": "api_test_flow",
            "version": "1.0.0",
            "nodes": [
                {
                    "id": "echo",
                    "type": "agent",
                    "agent_id": "email_summarizer",
                    "execute_in": "activity",
                    "input_mappings": {"emails": {"path": "workflow_input.emails"}},
                }
            ],
            "edges": [],
        }
        res_wf = client.post("/v1/workflows", json=workflow)
        assert res_wf.status_code == 200

        # 1. Test direct execution mode (default)
        res_direct = client.post(
            "/v1/runs",
            json={"workflow_id": "api_test_flow", "inputs": {"emails": [{"subject": "test"}]}, "execution_backend": "direct"},
        )
        assert res_direct.status_code == 200
        run_data = res_direct.json()
        assert run_data["status"] == "succeeded"
        assert run_data["execution_backend"] == "direct"

        # 2. Test temporal schedule API endpoints
        sched_res = client.post(
            "/v1/schedules",
            json={
                "schedule_id": "api-sched-1",
                "workflow_id": "api_test_flow",
                "cron_or_interval": "30m",
                "input_payload": {"msg": "scheduled run"},
            },
        )
        assert sched_res.status_code == 200
        sched_data = sched_res.json()
        assert sched_data["schedule_id"] == "api-sched-1"

        # List schedules
        list_res = client.get("/v1/schedules")
        assert list_res.status_code == 200
        assert any(s["schedule_id"] == "api-sched-1" for s in list_res.json())

        # Get schedule
        get_res = client.get("/v1/schedules/api-sched-1")
        assert get_res.status_code == 200
        assert get_res.json()["schedule_id"] == "api-sched-1"
        assert len(get_res.json().get("next_run_times", [])) > 0

        # Pause schedule
        pause_res = client.post("/v1/schedules/api-sched-1/pause")
        assert pause_res.status_code == 200
        assert pause_res.json()["status"] == "paused"

        # Unpause schedule
        unpause_res = client.post("/v1/schedules/api-sched-1/unpause")
        assert unpause_res.status_code == 200
        assert unpause_res.json()["status"] == "unpaused"

        # Delete schedule
        del_res = client.delete("/v1/schedules/api-sched-1")
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "deleted"

        # 3. Test backend-controlled execution backend defaulting to Temporal
        # Caller sends NO execution_backend and NO wait (exact frontend payload)
        os.environ["AGENT_PLATFORM_EXECUTION_BACKEND"] = "temporal"
        res_backend_default = client.post(
            "/v1/runs",
            json={"workflow_id": "api_test_flow", "inputs": {"emails": [{"subject": "test"}]}},
        )
        assert res_backend_default.status_code == 200
        default_run_data = res_backend_default.json()
        assert default_run_data["execution_backend"] == "temporal"
        assert default_run_data["status"] == "running"  # Returns immediately without waiting
        assert default_run_data["temporal_workflow_id"].startswith("wf-")

        # 4. Verify a Temporal Worker picks up and completes the task
        worker = create_temporal_worker(
            client=env.client,
            registry=app.state.registry,
            repository=repo,
            config=TemporalConfig(task_queue="agent-platform-queue"),
        )
        async with worker:
            run_id = default_run_data["run_id"]
            polled = None
            for _ in range(30):
                poll_res = client.get(f"/v1/runs/{run_id}")
                assert poll_res.status_code == 200
                polled = poll_res.json()
                if polled["status"] == "succeeded":
                    break
                await asyncio.sleep(0.1)
            assert polled is not None
            assert polled["status"] == "succeeded"

            # 5. Test batch execution uses configured backend (temporal)
            batch_res = client.post(
                "/v1/batch-runs",
                json={
                    "workflow_id": "api_test_flow",
                    "items": [{"emails": [{"subject": "batch1"}]}, {"emails": [{"subject": "batch2"}]}],
                    "concurrency": 2,
                },
            )
            assert batch_res.status_code == 200
            batch_data = batch_res.json()
            assert batch_data["execution_backend"] == "temporal"
            assert batch_data["status"] == "running"

            batch_id = batch_data["run_id"]
            polled_batch = None
            for _ in range(30):
                poll_res = client.get(f"/v1/runs/{batch_id}")
                assert poll_res.status_code == 200
                polled_batch = poll_res.json()
                if polled_batch["status"] == "succeeded":
                    break
                await asyncio.sleep(0.1)
            assert polled_batch is not None
            assert polled_batch["status"] == "succeeded"

        # 6. Test backend-controlled direct execution override via server setting
        os.environ["AGENT_PLATFORM_EXECUTION_BACKEND"] = "direct"
        res_backend_direct = client.post(
            "/v1/runs",
            json={"workflow_id": "api_test_flow", "inputs": {"emails": [{"subject": "test"}]}},
        )
        assert res_backend_direct.status_code == 200
        direct_run_data = res_backend_direct.json()
        assert direct_run_data["execution_backend"] == "direct"
        assert direct_run_data["status"] == "succeeded"

        # 7. Test direct batch execution when server is configured for direct
        res_batch_direct = client.post(
            "/v1/batch-runs",
            json={
                "workflow_id": "api_test_flow",
                "items": [{"emails": [{"subject": "direct1"}]}],
            },
        )
        assert res_batch_direct.status_code == 200
        assert res_batch_direct.json()["execution_backend"] == "direct"

    finally:
        set_temporal_client(None)
        await env.shutdown()


@pytest.mark.asyncio
async def test_temporal_unavailability_error_handling():
    """Verify that when Temporal is the configured backend but unavailable, FastAPI returns 503 and never falls back."""
    old_backend = os.environ.get("AGENT_PLATFORM_EXECUTION_BACKEND")
    old_host = os.environ.get("TEMPORAL_TARGET_HOST")
    try:
        os.environ["AGENT_PLATFORM_EXECUTION_BACKEND"] = "temporal"
        os.environ["TEMPORAL_TARGET_HOST"] = "127.0.0.1:1"
        set_temporal_client(None)

        repo = ExecutionRepository(":memory:")
        app = create_app(repository=repo)
        client = TestClient(app)

        workflow = {
            "id": "unavail_flow",
            "version": "1.0.0",
            "nodes": [
                {
                    "id": "echo",
                    "type": "agent",
                    "agent_id": "email_summarizer",
                    "execute_in": "activity",
                    "input_mappings": {"emails": {"path": "workflow_input.emails"}},
                }
            ],
            "edges": [],
        }
        res_wf = client.post("/v1/workflows", json=workflow)
        assert res_wf.status_code == 200

        # Calling start_run should fail with 503 and NOT silently succeed via direct execution
        res = client.post(
            "/v1/runs",
            json={"workflow_id": "unavail_flow", "inputs": {"emails": []}},
        )
        assert res.status_code == 503
        assert "Temporal" in res.json().get("detail", "")

        # Batch run should also fail with 503
        batch_res = client.post(
            "/v1/batch-runs",
            json={"workflow_id": "unavail_flow", "items": [{"emails": []}]},
        )
        assert batch_res.status_code == 503
        assert "Temporal" in batch_res.json().get("detail", "")
    finally:
        set_temporal_client(None)
        if old_backend is not None:
            os.environ["AGENT_PLATFORM_EXECUTION_BACKEND"] = old_backend
        else:
            os.environ.pop("AGENT_PLATFORM_EXECUTION_BACKEND", None)
        if old_host is not None:
            os.environ["TEMPORAL_TARGET_HOST"] = old_host
        else:
            os.environ.pop("TEMPORAL_TARGET_HOST", None)
