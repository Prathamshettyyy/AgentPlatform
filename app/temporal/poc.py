from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.langgraph import LangGraphPlugin, graph


def _merge_lists(left: list[Any] | None, right: list[Any] | None) -> list[Any]:
    return list(left or []) + list(right or [])


def _merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(left or {})
    if right:
        merged.update(right)
    return merged


class POCState(TypedDict, total=False):
    run_id: str
    input_text: str
    target_route: str
    loop_limit: int
    loop_count: int
    branch_a_output: str
    branch_b_output: str
    branch_c_output: str
    combined_output: dict[str, Any]
    loop_results: Annotated[list[str], _merge_lists]
    status: str
    final_message: str


# Node implementations
# Activity nodes: simulate external computation, LLM, or mock agent
async def node_branch_a(state: POCState) -> dict[str, Any]:
    text = state.get("input_text", "")
    return {"branch_a_output": f"A:{text.upper()}"}


async def node_branch_b(state: POCState) -> dict[str, Any]:
    text = state.get("input_text", "")
    return {"branch_b_output": f"B:{len(text)}"}


async def node_branch_c(state: POCState) -> dict[str, Any]:
    text = state.get("input_text", "")
    return {"branch_c_output": f"C:{text[::-1]}"}


# Workflow-level node: deterministic combination of outputs
async def node_combine(state: POCState) -> dict[str, Any]:
    combined = {
        "a": state.get("branch_a_output", ""),
        "b": state.get("branch_b_output", ""),
        "c": state.get("branch_c_output", ""),
    }
    return {"combined_output": combined}


# Conditional routing function (must be async and deterministic in Temporal workflow context)
async def route_after_combine(state: POCState) -> str:
    target = state.get("target_route", "loop")
    if target == "direct":
        return "direct_finish"
    return "loop_step"


# Activity node inside loop: performs iteration computation
async def node_loop_step(state: POCState) -> dict[str, Any]:
    count = state.get("loop_count", 0) + 1
    item = f"iter_{count}"
    return {
        "loop_count": count,
        "loop_results": [item],
    }


# Conditional loop router with bounded loop guard (must be async in Temporal workflow context)
async def route_loop(state: POCState) -> str:
    count = state.get("loop_count", 0)
    limit = state.get("loop_limit", 3)
    # Hard boundary to protect against runaway infinite loops
    max_safety_limit = 50
    if count >= limit or count >= max_safety_limit:
        return "finish_step"
    return "loop_step"


async def node_direct_finish(state: POCState) -> dict[str, Any]:
    return {
        "status": "succeeded",
        "final_message": "Direct routing completed without loop",
    }


async def node_finish_step(state: POCState) -> dict[str, Any]:
    count = state.get("loop_count", 0)
    return {
        "status": "succeeded",
        "final_message": f"Loop completed successfully with {count} iterations",
    }


def build_poc_graph(
    *,
    activity_timeout: timedelta = timedelta(seconds=30),
    retry_policy: RetryPolicy | None = None,
) -> StateGraph:
    """Build the demonstration LangGraph StateGraph with parallel branches, fan-in,

    conditional routing, and a bounded loop.
    """
    g = StateGraph(POCState)

    default_retry = retry_policy or RetryPolicy(
        maximum_attempts=3,
        initial_interval=timedelta(milliseconds=100),
    )

    # 1. Three parallel branches executing as Temporal Activities
    g.add_node(
        "branch_a",
        node_branch_a,
        metadata={
            "execute_in": "activity",
            "start_to_close_timeout": activity_timeout,
            "retry_policy": default_retry,
        },
    )
    g.add_node(
        "branch_b",
        node_branch_b,
        metadata={
            "execute_in": "activity",
            "start_to_close_timeout": activity_timeout,
            "retry_policy": default_retry,
        },
    )
    g.add_node(
        "branch_c",
        node_branch_c,
        metadata={
            "execute_in": "activity",
            "start_to_close_timeout": activity_timeout,
            "retry_policy": default_retry,
        },
    )

    # 2. Fan-in aggregation node (runs deterministically in workflow)
    g.add_node("combine", node_combine, metadata={"execute_in": "workflow"})

    # 3. Loop step executing as Activity
    g.add_node(
        "loop_step",
        node_loop_step,
        metadata={
            "execute_in": "activity",
            "start_to_close_timeout": activity_timeout,
            "retry_policy": default_retry,
        },
    )

    # 4. Finish nodes
    g.add_node("direct_finish", node_direct_finish, metadata={"execute_in": "workflow"})
    g.add_node("finish_step", node_finish_step, metadata={"execute_in": "workflow"})

    # Graph Edges
    # Fan-out from START to A, B, C concurrently
    g.add_edge(START, "branch_a")
    g.add_edge(START, "branch_b")
    g.add_edge(START, "branch_c")

    # Fan-in from A, B, C into combine using LangGraph multi-source barrier edge
    g.add_edge(["branch_a", "branch_b", "branch_c"], "combine")

    # Conditional routing after combine
    g.add_conditional_edges(
        "combine",
        route_after_combine,
        {
            "direct_finish": "direct_finish",
            "loop_step": "loop_step",
        },
    )

    # Bounded loop routing
    g.add_conditional_edges(
        "loop_step",
        route_loop,
        {
            "loop_step": "loop_step",
            "finish_step": "finish_step",
        },
    )

    g.add_edge("direct_finish", END)
    g.add_edge("finish_step", END)

    return g


# Temporal Workflow Definition for the POC
@workflow.defn(name="POCLangGraphWorkflow")
class POCLangGraphWorkflow:
    @workflow.run
    async def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        # Retrieve graph registered with LangGraphPlugin
        g = graph("poc_graph")
        # In-memory checkpointer is used inside the Temporal workflow
        # while Temporal manages the durable history & activity orchestration.
        compiled = g.compile(checkpointer=InMemorySaver())

        state_input: POCState = {
            "run_id": input_payload.get("run_id", "poc-run-1"),
            "input_text": input_payload.get("input_text", "hello temporal langgraph"),
            "target_route": input_payload.get("target_route", "loop"),
            "loop_limit": input_payload.get("loop_limit", 3),
            "loop_count": 0,
            "loop_results": [],
        }

        result = await compiled.ainvoke(
            state_input,
            {"configurable": {"thread_id": state_input["run_id"]}},
        )
        return dict(result)
