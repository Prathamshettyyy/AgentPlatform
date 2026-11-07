import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.registry import AgentRegistry
from app.runtime.runner import AgentRunner
from app.sdk.contracts import AgentMetadata
from app.workflows.builder import WorkflowBuilder
from app.workflows.models import WorkflowDefinition
from app.workflows.models import MappingValue
from app.storage.repository import ExecutionRepository
from plugins.examples.deterministic_agent import run


def registry():
    r = AgentRegistry()
    r.register(AgentMetadata(id="echo_agent", name="Echo"), run)
    return r


@pytest.mark.asyncio
async def test_configured_mapping_flows_between_agents():
    r = registry()
    def upper(req, ctx): return {"text": req.inputs["message"].upper()}
    r.register(AgentMetadata(id="upper_agent", name="Upper"), upper)
    workflow = WorkflowDefinition.model_validate({"id":"flow", "nodes":[
        {"id":"first", "type":"agent", "agent_id":"echo_agent", "input_mappings":{"message":{"path":"workflow_input.message"}}},
        {"id":"second", "type":"agent", "agent_id":"upper_agent", "input_mappings":{"message":{"path":"node_outputs.first.message"}}}],
        "edges":[{"from":"first","to":"second"}]})
    graph = WorkflowBuilder(r).build(workflow)
    result = await graph.ainvoke({"run_id":"run-1", "workflow_input":{"message":"hello"}, "node_outputs":{}}, {"configurable":{"thread_id":"run-1"}})
    assert result["node_outputs"]["second"]["text"] == "HELLO"


@pytest.mark.asyncio
async def test_human_approval_pauses_and_resumes():
    r = registry()
    workflow = WorkflowDefinition.model_validate({"id":"approval", "nodes":[
        {"id":"first", "type":"agent", "agent_id":"echo_agent", "input_mappings":{"message":{"path":"workflow_input.message"}}},
        {"id":"approve", "type":"human_approval", "approval_payload_path":"node_outputs.first"}],
        "edges":[{"from":"first","to":"approve"}]})
    graph = WorkflowBuilder(r).build(workflow)
    config = {"configurable":{"thread_id":"run-2"}}
    paused = await graph.ainvoke({"run_id":"run-2", "workflow_input":{"message":"review"}, "node_outputs":{}}, config)
    assert paused.get("__interrupt__") is not None
    resumed = await graph.ainvoke(Command(resume="approve"), config)
    assert resumed["node_outputs"]["approve"]["decision"] == "approve"


def test_invalid_workflows_are_rejected_before_compilation():
    r = registry()
    cases = [
        {"id":"unknown", "nodes":[{"id":"x","type":"agent","agent_id":"missing"}], "edges":[]},
        {"id":"missing_path", "nodes":[{"id":"x","type":"agent","agent_id":"echo_agent","input_mappings":{"message":{"path":"node_outputs.nope.value"}}}], "edges":[]},
        {"id":"cycle", "nodes":[{"id":"a","type":"agent","agent_id":"echo_agent"},{"id":"b","type":"agent","agent_id":"echo_agent"}], "edges":[{"from":"a","to":"b"},{"from":"b","to":"a"}]},
    ]
    for payload in cases:
        with pytest.raises(Exception): WorkflowBuilder(r).build(WorkflowDefinition.model_validate(payload))


def test_mapping_validation_accepts_legacy_path_with_null_literal():
    mapping = MappingValue.model_validate({"path": "workflow_input.message", "literal": None})
    assert mapping.path == "workflow_input.message"


def test_mapping_validation_preserves_literals_and_rejects_ambiguous_values():
    assert MappingValue.model_validate({"literal": "fixed"}).literal == "fixed"
    assert MappingValue.model_validate({"literal": None}).literal is None
    with pytest.raises(ValueError, match="exactly one"):
        MappingValue.model_validate({"path": "workflow_input.message", "literal": "fixed"})
    with pytest.raises(ValueError, match="exactly one"):
        MappingValue.model_validate({})


def test_repository_normalizes_legacy_mapping_null_without_discarding_workflow(tmp_path):
    repository = ExecutionRepository(str(tmp_path / "legacy-workflow.db"))
    workflow = {"id": "legacy_flow", "version": "1.0.0", "nodes": [
        {"id": "echo_node", "type": "agent", "agent_id": "echo_agent", "input_mappings": {"message": {"path": "workflow_input.message", "literal": None}}}], "edges": []}
    repository.save_workflow(workflow)
    stored = repository.get_workflow("legacy_flow", "1.0.0")
    assert stored["nodes"][0]["input_mappings"]["message"] == {"path": "workflow_input.message"}
    assert WorkflowDefinition.model_validate(stored).id == "legacy_flow"
    repository.close()


def test_converging_dag_is_valid_but_cycles_are_not():
    r = registry()
    workflow = WorkflowDefinition.model_validate({"id":"converging", "nodes":[
        {"id":"node_a", "type":"agent", "agent_id":"echo_agent"},
        {"id":"node_b", "type":"agent", "agent_id":"echo_agent"},
        {"id":"node_c", "type":"agent", "agent_id":"echo_agent"},
        {"id":"node_d", "type":"agent", "agent_id":"echo_agent"}],
        "edges":[{"from":"node_a","to":"node_b"},{"from":"node_a","to":"node_c"},{"from":"node_b","to":"node_d"},{"from":"node_c","to":"node_d"}]})
    WorkflowBuilder(r).build(workflow)


def test_downstream_mapping_is_rejected_before_execution():
    r = registry()
    workflow = WorkflowDefinition.model_validate({"id":"bad_mapping", "nodes":[
        {"id":"first", "type":"agent", "agent_id":"echo_agent", "input_mappings":{"message":{"path":"node_outputs.second.value"}}},
        {"id":"second", "type":"agent", "agent_id":"echo_agent"}],
        "edges":[{"from":"first","to":"second"}]})
    with pytest.raises(Exception, match="upstream"):
        WorkflowBuilder(r).build(workflow)


@pytest.mark.asyncio
async def test_rejection_option_cannot_authorize_sender_when_not_first():
    r = registry()
    def sender(req, ctx): return {"sent": True}
    r.register(AgentMetadata(id="sender_agent", name="Sender"), sender)
    workflow = WorkflowDefinition.model_validate({"id":"ordered_reject", "nodes":[
        {"id":"approve", "type":"human_approval", "approval_payload_path":"workflow_input", "approval_options":["reject", "approve"]},
        {"id":"send", "type":"agent", "agent_id":"sender_agent"}], "edges":[{"from":"approve","to":"send"}]})
    graph = WorkflowBuilder(r).build(workflow)
    config = {"configurable":{"thread_id":"ordered-reject-run"}}
    await graph.ainvoke({"run_id":"ordered-reject-run","workflow_input":{"value":1},"node_outputs":{}}, config)
    result = await graph.ainvoke(Command(resume="reject"), config)
    assert result["node_outputs"]["approve"]["decision"] == "reject"
    assert "send" not in result["node_outputs"]


@pytest.mark.asyncio
async def test_rejection_is_a_valid_recorded_decision():
    r = registry()
    workflow = WorkflowDefinition.model_validate({"id":"reject", "nodes":[
        {"id":"approve","type":"human_approval","approval_payload_path":"workflow_input"}], "edges":[]})
    graph = WorkflowBuilder(r).build(workflow)
    config = {"configurable":{"thread_id":"reject-run"}}
    paused = await graph.ainvoke({"run_id":"reject-run","workflow_input":{"value":1},"node_outputs":{}}, config)
    assert paused.get("__interrupt__")
    result = await graph.ainvoke(Command(resume="reject"), config)
    assert result["node_outputs"]["approve"]["decision"] == "reject"


@pytest.mark.asyncio
async def test_rejection_does_not_run_following_agent():
    r = registry()
    def sender(req, ctx): return {"sent": True}
    r.register(AgentMetadata(id="sender_agent", name="Sender"), sender)
    workflow = WorkflowDefinition.model_validate({"id":"reject_sender", "nodes":[
        {"id":"approve","type":"human_approval","approval_payload_path":"workflow_input"},
        {"id":"send","type":"agent","agent_id":"sender_agent"}], "edges":[{"from":"approve","to":"send"}]})
    graph = WorkflowBuilder(r).build(workflow)
    config = {"configurable":{"thread_id":"reject-sender-run"}}
    await graph.ainvoke({"run_id":"reject-sender-run","workflow_input":{"value":1},"node_outputs":{}}, config)
    result = await graph.ainvoke(Command(resume="reject"), config)
    assert result["node_outputs"]["approve"]["decision"] == "reject"
    assert "send" not in result["node_outputs"]

