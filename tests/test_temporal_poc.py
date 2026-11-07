from __future__ import annotations

import asyncio
from datetime import timedelta
import pytest
import temporalio.workflow
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
)
from temporalio.common import RetryPolicy
from temporalio.langgraph import LangGraphPlugin, graph
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from langgraph.graph import StateGraph, START, END

from app.temporal.poc import (
    POCLangGraphWorkflow,
    build_poc_graph,
    node_branch_a,
    node_branch_b,
    node_branch_c,
    node_combine,
    node_loop_step,
    POCState,
)
from langgraph.checkpoint.memory import InMemorySaver


# Module-level workflow definition for retry testing
@temporalio.workflow.defn(name="POCRetryWorkflow")
class POCRetryWorkflow:
    @temporalio.workflow.run
    async def run(self, payload: dict) -> dict:
        graph_obj = graph("retry_graph")
        compiled = graph_obj.compile(checkpointer=InMemorySaver())
        return await compiled.ainvoke(
            payload,
            {"configurable": {"thread_id": payload.get("run_id", "retry-thread")}},
        )


_retry_attempt_counter = 0


async def failing_branch_a(state: POCState) -> dict:
    global _retry_attempt_counter
    _retry_attempt_counter += 1
    if _retry_attempt_counter < 3:
        raise RuntimeError("Transient connection blip")
    return {"branch_a_output": "A:RECOVERED"}


@pytest.mark.asyncio
async def test_poc_langgraph_direct_parallel_and_loop():
    """Verify that the POC graph executes natively in LangGraph with parallel branches,

    fan-in combination, conditional routing, and bounded loops.
    """
    g = build_poc_graph()
    compiled = g.compile(checkpointer=InMemorySaver())

    # Case 1: Loop branch with limit 3
    res_loop = await compiled.ainvoke(
        {
            "run_id": "test-direct-1",
            "input_text": "hello",
            "target_route": "loop",
            "loop_limit": 3,
            "loop_count": 0,
            "loop_results": [],
        },
        {"configurable": {"thread_id": "t1"}},
    )

    assert res_loop["branch_a_output"] == "A:HELLO"
    assert res_loop["branch_b_output"] == "B:5"
    assert res_loop["branch_c_output"] == "C:olleh"
    assert res_loop["combined_output"] == {"a": "A:HELLO", "b": "B:5", "c": "C:olleh"}
    assert res_loop["loop_count"] == 3
    assert res_loop["loop_results"] == ["iter_1", "iter_2", "iter_3"]
    assert res_loop["status"] == "succeeded"

    # Case 2: Direct conditional route (skip loop)
    res_direct = await compiled.ainvoke(
        {
            "run_id": "test-direct-2",
            "input_text": "skip",
            "target_route": "direct",
            "loop_limit": 3,
            "loop_count": 0,
            "loop_results": [],
        },
        {"configurable": {"thread_id": "t2"}},
    )
    assert res_direct["branch_a_output"] == "A:SKIP"
    assert res_direct["loop_count"] == 0
    assert "Direct routing" in res_direct["final_message"]


@pytest.mark.asyncio
async def test_poc_temporal_worker_and_execution():
    """Verify that Temporal executes the LangGraph workflow with activities,

    parallel distribution, fan-in, and bounded loops under LangGraphPlugin.
    """
    env = await WorkflowEnvironment.start_time_skipping()
    try:
        poc_graph = build_poc_graph()
        plugin = LangGraphPlugin(graphs={"poc_graph": poc_graph})
        task_queue = "poc-test-queue"

        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[POCLangGraphWorkflow],
            plugins=[plugin],
        ):
            # Test 1: Loop execution through Temporal
            handle = await env.client.start_workflow(
                POCLangGraphWorkflow.run,
                {
                    "run_id": "poc-temporal-run-1",
                    "input_text": "temporal agent",
                    "target_route": "loop",
                    "loop_limit": 2,
                },
                id="poc-workflow-1",
                task_queue=task_queue,
            )
            result = await handle.result()

            assert result["branch_a_output"] == "A:TEMPORAL AGENT"
            assert result["branch_b_output"] == "B:14"
            assert result["branch_c_output"] == "C:tnega laropmet"
            assert result["combined_output"] == {
                "a": "A:TEMPORAL AGENT",
                "b": "B:14",
                "c": "C:tnega laropmet",
            }
            assert result["loop_count"] == 2
            assert result["loop_results"] == ["iter_1", "iter_2"]
            assert result["status"] == "succeeded"

            # Test 2: Conditional direct branch through Temporal
            handle_direct = await env.client.start_workflow(
                POCLangGraphWorkflow.run,
                {
                    "run_id": "poc-temporal-run-2",
                    "input_text": "direct test",
                    "target_route": "direct",
                },
                id="poc-workflow-2",
                task_queue=task_queue,
            )
            res_dir = await handle_direct.result()
            assert res_dir["branch_a_output"] == "A:DIRECT TEST"
            assert res_dir["loop_count"] == 0
            assert "Direct routing" in res_dir["final_message"]
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_poc_temporal_activity_retry():
    """Verify Temporal automatic Activity retries on transient activity failures."""
    global _retry_attempt_counter
    _retry_attempt_counter = 0

    env = await WorkflowEnvironment.start_local()
    try:
        g = StateGraph(POCState)
        g.add_node(
            "branch_a",
            failing_branch_a,
            metadata={
                "execute_in": "activity",
                "start_to_close_timeout": timedelta(seconds=10),
                "retry_policy": RetryPolicy(
                    maximum_attempts=4,
                    initial_interval=timedelta(milliseconds=50),
                ),
            },
        )
        g.add_edge(START, "branch_a")
        g.add_edge("branch_a", END)

        plugin = LangGraphPlugin(graphs={"retry_graph": g})
        task_queue = "retry-queue"

        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[POCRetryWorkflow],
            plugins=[plugin],
        ):
            handle = await env.client.start_workflow(
                POCRetryWorkflow.run,
                {"input_text": "retry test"},
                id="retry-wf-1",
                task_queue=task_queue,
            )
            result = await handle.result()
            assert result["branch_a_output"] == "A:RECOVERED"
            assert _retry_attempt_counter == 3  # Failed twice, succeeded on 3rd attempt
    finally:
        await env.shutdown()


@pytest.mark.asyncio
async def test_poc_temporal_schedule():
    """Verify Temporal Schedule creation, manual triggering, and deletion for LangGraph workflows."""
    env = await WorkflowEnvironment.start_local()
    try:
        poc_graph = build_poc_graph()
        plugin = LangGraphPlugin(graphs={"poc_graph": poc_graph})
        task_queue = "schedule-test-queue"

        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[POCLangGraphWorkflow],
            plugins=[plugin],
        ):
            schedule_id = "poc-schedule-1"
            action = ScheduleActionStartWorkflow(
                POCLangGraphWorkflow.run,
                {
                    "run_id": "scheduled-run-1",
                    "input_text": "scheduled test",
                    "target_route": "direct",
                },
                id="scheduled-workflow-instance",
                task_queue=task_queue,
            )

            # Create schedule
            handle = await env.client.create_schedule(
                schedule_id,
                Schedule(
                    action=action,
                    spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))]),
                ),
            )

            desc = await handle.describe()
            assert desc.id == schedule_id

            # Trigger an immediate run of the schedule
            await handle.trigger()
            await asyncio.sleep(1.5)

            # Pause and delete
            await handle.pause(note="paused for test")
            desc_paused = await handle.describe()
            assert desc_paused.schedule.state.paused is True

            await handle.delete()
    finally:
        await env.shutdown()
