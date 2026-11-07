from __future__ import annotations

import asyncio
from typing import Any
import pytest

from app.registry import AgentRegistry
from app.runtime.runner import AgentRunner
from app.sdk.contracts import AgentMetadata, AgentRequest
from app.storage.repository import ExecutionRepository
from app.workflows.builder import WorkflowBuilder
from app.workflows.models import WorkflowDefinition
from app.workflows.validator import WorkflowValidationError, validate_workflow
from app.temporal import TemporalConfig, create_temporal_worker, DynamicLangGraphWorkflow


def make_registry() -> AgentRegistry:
    reg = AgentRegistry()
    reg.register(AgentMetadata(id="echo_agent", name="Echo"), lambda req, ctx: {"val": "ok"})
    return reg


@pytest.mark.asyncio
async def test_parallel_branches_concurrent_execution_and_barrier_join():
    """
    Regression test covering:
    - One node branching into two independent nodes.
    - Both branches executing concurrently (verified deterministically with asyncio.Barrier(2)).
    - Downstream join node executing only after both branches finish.
    - Join node executing exactly once.
    - Join node receiving outputs from both branches.
    """
    reg = make_registry()
    barrier = asyncio.Barrier(2)
    branch_a_finished = False
    branch_b_finished = False
    join_execution_count = 0

    def start_fn(req: AgentRequest, ctx: Any):
        return {"init_val": "seed_data"}

    async def branch_a_fn(req: AgentRequest, ctx: Any):
        nonlocal branch_a_finished
        # Concurrency proof: If not executing concurrently with branch_b,
        # waiting on barrier(2) would block/timeout forever.
        await barrier.wait()
        branch_a_finished = True
        return {"result_a": "result_from_a"}

    async def branch_b_fn(req: AgentRequest, ctx: Any):
        nonlocal branch_b_finished
        # Concurrency proof: Enters barrier concurrently with branch_a
        await barrier.wait()
        branch_b_finished = True
        return {"result_b": "result_from_b"}

    def join_fn(req: AgentRequest, ctx: Any):
        nonlocal join_execution_count
        join_execution_count += 1
        # Barrier invariant: both predecessor branches must be finished
        assert branch_a_finished is True, "branch_a must be finished before join executes"
        assert branch_b_finished is True, "branch_b must be finished before join executes"
        assert req.inputs.get("from_a") == "result_from_a"
        assert req.inputs.get("from_b") == "result_from_b"
        return {"combined": f"{req.inputs['from_a']} + {req.inputs['from_b']}"}

    reg.register(AgentMetadata(id="start_agent", name="Start Agent"), start_fn)
    reg.register(AgentMetadata(id="branch_a_agent", name="Branch A Agent"), branch_a_fn)
    reg.register(AgentMetadata(id="branch_b_agent", name="Branch B Agent"), branch_b_fn)
    reg.register(AgentMetadata(id="join_agent", name="Join Agent"), join_fn)

    workflow_dict = {
        "id": "parallel_flow",
        "nodes": [
            {"id": "start_node", "type": "agent", "agent_id": "start_agent"},
            {
                "id": "branch_a",
                "type": "agent",
                "agent_id": "branch_a_agent",
                "input_mappings": {"init": {"path": "node_outputs.start_node.init_val"}},
            },
            {
                "id": "branch_b",
                "type": "agent",
                "agent_id": "branch_b_agent",
                "input_mappings": {"init": {"path": "node_outputs.start_node.init_val"}},
            },
            {
                "id": "join_node",
                "type": "agent",
                "agent_id": "join_agent",
                "input_mappings": {
                    "from_a": {"path": "node_outputs.branch_a.result_a"},
                    "from_b": {"path": "node_outputs.branch_b.result_b"},
                },
            },
        ],
        "edges": [
            {"from": "start_node", "to": "branch_a"},
            {"from": "start_node", "to": "branch_b"},
            {"from": "branch_a", "to": "join_node"},
            {"from": "branch_b", "to": "join_node"},
        ],
    }

    workflow = WorkflowDefinition.model_validate(workflow_dict)
    builder = WorkflowBuilder(reg)

    # Verify StateGraph construction uses LangGraph's multi-source waiting_edges
    sg = builder.build_state_graph(workflow)
    waiting_edges = getattr(sg, "waiting_edges", set())
    assert (("branch_a", "branch_b"), "join_node") in waiting_edges or (("branch_b", "branch_a"), "join_node") in waiting_edges, (
        f"Expected multi-source waiting edge for join_node, got: {waiting_edges}"
    )

    compiled = builder.build(workflow)
    config = {"configurable": {"thread_id": "parallel-test-1"}}
    state = {
        "run_id": "run-parallel-1",
        "workflow_id": "parallel_flow",
        "workflow_version": "1.0.0",
        "workflow_input": {},
        "node_outputs": {},
    }

    result = await compiled.ainvoke(state, config=config)

    # Verifications:
    # 1. Join node executed exactly once
    assert join_execution_count == 1, f"Expected join node to execute exactly once, got {join_execution_count}"

    # 2. Join node received merged outputs from both branches
    assert result["node_outputs"]["join_node"]["combined"] == "result_from_a + result_from_b"

    # 3. All node outputs are preserved in state
    assert "start_node" in result["node_outputs"]
    assert "branch_a" in result["node_outputs"]
    assert "branch_b" in result["node_outputs"]
    assert "join_node" in result["node_outputs"]


@pytest.mark.asyncio
async def test_fan_out_multiple_branches_without_join():
    """Verify fan-out to multiple parallel branches that terminate independently at END."""
    reg = make_registry()
    barrier = asyncio.Barrier(3)
    executed_branches: list[str] = []

    def start_fn(req, ctx):
        return {"seed": 100}

    async def worker_fn(req, ctx):
        await barrier.wait()
        executed_branches.append(req.node_id)
        return {"worker": req.node_id}

    reg.register(AgentMetadata(id="start_agent", name="Start"), start_fn)
    reg.register(AgentMetadata(id="worker_agent", name="Worker"), worker_fn)

    workflow_dict = {
        "id": "fanout_flow",
        "nodes": [
            {"id": "start_node", "type": "agent", "agent_id": "start_agent"},
            {"id": "branch_1", "type": "agent", "agent_id": "worker_agent"},
            {"id": "branch_2", "type": "agent", "agent_id": "worker_agent"},
            {"id": "branch_3", "type": "agent", "agent_id": "worker_agent"},
        ],
        "edges": [
            {"from": "start_node", "to": "branch_1"},
            {"from": "start_node", "to": "branch_2"},
            {"from": "start_node", "to": "branch_3"},
        ],
    }

    workflow = WorkflowDefinition.model_validate(workflow_dict)
    compiled = WorkflowBuilder(reg).build(workflow)
    state = {
        "run_id": "run-fanout-1",
        "workflow_id": "fanout_flow",
        "workflow_version": "1.0.0",
        "workflow_input": {},
        "node_outputs": {},
    }

    res = await compiled.ainvoke(state, config={"configurable": {"thread_id": "fanout-1"}})
    assert len(executed_branches) == 3
    assert set(executed_branches) == {"branch_1", "branch_2", "branch_3"}
    assert "branch_1" in res["node_outputs"]
    assert "branch_2" in res["node_outputs"]
    assert "branch_3" in res["node_outputs"]


def test_ambiguous_join_mixed_conditional_and_unconditional_rejected():
    """
    Verify ambiguous graphs where a node has both conditional and unconditional
    incoming edges from distinct nodes are rejected before compilation.
    """
    reg = make_registry()
    workflow_dict = {
        "id": "ambiguous_flow",
        "nodes": [
            {"id": "start_node", "type": "agent", "agent_id": "echo_agent"},
            {"id": "branch_u", "type": "agent", "agent_id": "echo_agent"},
            {"id": "branch_c", "type": "agent", "agent_id": "echo_agent"},
            {"id": "join_node", "type": "agent", "agent_id": "echo_agent"},
        ],
        "edges": [
            {"from": "start_node", "to": "branch_u"},
            {"from": "start_node", "to": "branch_c"},
            {"from": "branch_u", "to": "join_node"},  # unconditional
            {
                "from": "branch_c",
                "to": "join_node",
                "condition": {"path": "workflow_input.flag", "operator": "equals", "value": True},
            },  # conditional
        ],
    }

    workflow = WorkflowDefinition.model_validate(workflow_dict)
    with pytest.raises(WorkflowValidationError, match="ambiguous incoming edges for node 'join_node'"):
        validate_workflow(workflow, reg)

    with pytest.raises(WorkflowValidationError, match="ambiguous incoming edges for node 'join_node'"):
        WorkflowBuilder(reg).build_state_graph(workflow)


def test_ambiguous_join_mixed_human_approval_and_unconditional_rejected():
    """Verify that human approval (which is conditional) mixed with an unconditional edge is rejected."""
    reg = make_registry()
    workflow_dict = {
        "id": "ambiguous_approval_flow",
        "nodes": [
            {"id": "start_node", "type": "agent", "agent_id": "echo_agent"},
            {"id": "branch_u", "type": "agent", "agent_id": "echo_agent"},
            {"id": "approve_node", "type": "human_approval", "approval_payload_path": "workflow_input"},
            {"id": "join_node", "type": "agent", "agent_id": "echo_agent"},
        ],
        "edges": [
            {"from": "start_node", "to": "branch_u"},
            {"from": "start_node", "to": "approve_node"},
            {"from": "branch_u", "to": "join_node"},      # unconditional
            {"from": "approve_node", "to": "join_node"},   # conditional router
        ],
    }

    workflow = WorkflowDefinition.model_validate(workflow_dict)
    with pytest.raises(WorkflowValidationError, match="ambiguous incoming edges for node 'join_node'"):
        validate_workflow(workflow, reg)


@pytest.mark.asyncio
async def test_pure_conditional_convergence_or_join_allowed():
    """
    Verify that pure conditional convergence (where all incoming edges are conditional)
    remains valid and functional.
    """
    reg = make_registry()
    classifier_fn = lambda req, ctx: {"score": req.inputs.get("score", 0)}
    high_fn = lambda req, ctx: {"status": "high"}
    low_fn = lambda req, ctx: {"status": "low"}
    summary_fn = lambda req, ctx: {"final": "done"}

    reg.register(AgentMetadata(id="classifier_agent", name="Classifier"), classifier_fn)
    reg.register(AgentMetadata(id="high_agent", name="High"), high_fn)
    reg.register(AgentMetadata(id="low_agent", name="Low"), low_fn)
    reg.register(AgentMetadata(id="summary_agent", name="Summary"), summary_fn)

    workflow_dict = {
        "id": "conditional_or_join",
        "nodes": [
            {"id": "classifier", "type": "agent", "agent_id": "classifier_agent", "input_mappings": {"score": {"path": "workflow_input.score"}}},
            {"id": "branch_high", "type": "agent", "agent_id": "high_agent"},
            {"id": "branch_low", "type": "agent", "agent_id": "low_agent"},
            {"id": "summary", "type": "agent", "agent_id": "summary_agent"},
        ],
        "edges": [
            {"from": "classifier", "to": "branch_high", "condition": {"path": "node_outputs.classifier.score", "operator": "greater_than", "value": 50}},
            {"from": "classifier", "to": "branch_low", "condition": {"path": "node_outputs.classifier.score", "operator": "less_than_or_equals", "value": 50}},
            {"from": "branch_high", "to": "summary", "condition": {"path": "node_outputs.branch_high.status", "operator": "equals", "value": "high"}},
            {"from": "branch_low", "to": "summary", "condition": {"path": "node_outputs.branch_low.status", "operator": "equals", "value": "low"}},
        ],
    }

    workflow = WorkflowDefinition.model_validate(workflow_dict)
    # Must validate cleanly
    validate_workflow(workflow, reg)
    compiled = WorkflowBuilder(reg).build(workflow)

    # Score 80 -> classifier -> branch_high -> summary
    res_high = await compiled.ainvoke(
        {"run_id": "r-high", "workflow_id": "conditional_or_join", "workflow_version": "1.0.0", "workflow_input": {"score": 80}, "node_outputs": {}},
        config={"configurable": {"thread_id": "thread-high"}},
    )
    assert "branch_high" in res_high["node_outputs"]
    assert "branch_low" not in res_high["node_outputs"]
    assert "summary" in res_high["node_outputs"]


@pytest.mark.asyncio
async def test_parallel_join_with_temporal_worker():
    """
    Verify that a parallel fan-out / fan-in StateGraph with a multi-source barrier edge
    executes cleanly under Temporal worker and DynamicLangGraphWorkflow.
    """
    from temporalio.testing import WorkflowEnvironment

    env = await WorkflowEnvironment.start_time_skipping()
    try:
        reg = make_registry()
        reg.register(AgentMetadata(id="step_a_agent", name="A"), lambda req, ctx: {"from_a": 10})
        reg.register(AgentMetadata(id="step_b_agent", name="B"), lambda req, ctx: {"from_b": 20})
        reg.register(
            AgentMetadata(id="step_join_agent", name="Join"),
            lambda req, ctx: {"sum": req.inputs["a_val"] + req.inputs["b_val"]},
        )

        workflow_dict = {
            "id": "temporal_parallel_flow",
            "version": "1.0.0",
            "nodes": [
                {"id": "node_a", "type": "agent", "agent_id": "step_a_agent"},
                {"id": "node_b", "type": "agent", "agent_id": "step_b_agent"},
                {
                    "id": "node_join",
                    "type": "agent",
                    "agent_id": "step_join_agent",
                    "input_mappings": {
                        "a_val": {"path": "node_outputs.node_a.from_a"},
                        "b_val": {"path": "node_outputs.node_b.from_b"},
                    },
                },
            ],
            "edges": [
                {"from": "node_a", "to": "node_join"},
                {"from": "node_b", "to": "node_join"},
            ],
        }

        workflow = WorkflowDefinition.model_validate(workflow_dict)
        repo = ExecutionRepository(":memory:")
        repo.save_workflow(workflow.model_dump(by_alias=True))

        tq = "temporal-parallel-tq"
        cfg = TemporalConfig(task_queue=tq)
        worker = create_temporal_worker(
            client=env.client,
            registry=reg,
            repository=repo,
            config=cfg,
        )

        async with worker:
            handle = await env.client.start_workflow(
                DynamicLangGraphWorkflow.run,
                {
                    "workflow_id": "temporal_parallel_flow",
                    "workflow_version": "1.0.0",
                    "run_id": "temporal-par-run-1",
                    "workflow_input": {},
                },
                id="wf-temporal-parallel",
                task_queue=tq,
            )
            res = await handle.result()
            assert res["node_outputs"]["node_join"]["sum"] == 30
            assert "node_a" in res["node_outputs"]
            assert "node_b" in res["node_outputs"]
    finally:
        await env.shutdown()
