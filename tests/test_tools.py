import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.app import create_app
from app.registry import AgentRegistry
from app.runtime.runner import AgentRunner
from app.sdk.contracts import AgentMetadata, AgentRequest
from app.storage.repository import ExecutionRepository
from app.tools import ToolMetadata, ToolRegistry, ToolRequest, ToolRunner
from app.runtime.errors import AgentDisabledError, AgentNotFoundError


def metadata(tool_id="test_tool", **kwargs):
    return ToolMetadata(
        id=tool_id,
        name="Test Tool",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}, "required": ["result"]},
        **kwargs,
    )


def request(tool_id="test_tool", inputs=None, agent_id="test_agent"):
    actual_inputs = {"value": "ok"} if inputs is None else inputs
    return ToolRequest(tool_id=tool_id, inputs=actual_inputs, execution_context={"run_id": "tool-run", "agent_id": agent_id})


def test_tool_metadata_and_registry_validation():
    with pytest.raises(ValidationError):
        ToolMetadata(id="bad", name="Bad", input_schema={"type": "not-json-schema"})
    with pytest.raises(ValidationError):
        ToolMetadata(id="bad_adapter", name="Bad", adapter_type="shell")
    registry = ToolRegistry()
    registry.register(metadata(), lambda req, ctx: {"result": req.inputs["value"]})
    with pytest.raises(ValueError): registry.register(metadata(), lambda req, ctx: {"result": "duplicate"})
    with pytest.raises(AgentNotFoundError): registry.get("missing")
    registry.disable("test_tool")
    with pytest.raises(AgentDisabledError): registry.get("test_tool")


@pytest.mark.asyncio
async def test_tool_runner_validates_permission_input_output_and_records_execution(caplog):
    records = []
    registry = ToolRegistry()
    registry.register(metadata(required_permissions=["demo.use"]), lambda req, ctx: {"result": req.inputs["value"]})
    runner = ToolRunner(registry, execution_recorder=lambda *args: records.append(args))
    result = await runner.run(request(), allowed_tools={"test_tool"}, permissions={"demo.use"})
    assert result.status == "succeeded"
    assert result.output["result"] == "ok"
    assert result.metadata["duration_ms"] >= 0
    assert records[0][1:3] == ("tool:test_tool", "succeeded")

    secret_registry = ToolRegistry()
    secret_registry.register(ToolMetadata(
        id="secret_tool", name="Secret Tool",
        input_schema={"type":"object", "properties":{"api_token":{"type":"string"}}, "required":["api_token"]},
        output_schema={"type":"object"},
    ), lambda req, ctx: {"result": "ok"})
    caplog.set_level("INFO")
    await ToolRunner(secret_registry).run(
        ToolRequest(tool_id="secret_tool", inputs={"api_token":"super-secret"}, execution_context={"run_id":"secret-run", "agent_id":"secret-agent"}),
        allowed_tools={"secret_tool"},
    )
    assert "super-secret" not in caplog.text
    tool_record = next(record for record in caplog.records if record.name == "agent_platform.tools")
    assert tool_record.inputs["api_token"] == "[REDACTED]"

    denied = await runner.run(request(), allowed_tools=set(), permissions={"demo.use"})
    assert denied.status == "failed"
    assert denied.error.code == "ToolPermissionError"
    invalid_input = await runner.run(request(inputs={}), allowed_tools={"test_tool"}, permissions={"demo.use"})
    assert invalid_input.error.code == "ToolValidationError"
    bad_output_registry = ToolRegistry()
    bad_output_registry.register(metadata("bad_output"), lambda req, ctx: {"wrong": "value"})
    bad_output = await ToolRunner(bad_output_registry).run(request("bad_output"), allowed_tools={"bad_output"})
    assert bad_output.error.code == "ToolValidationError"


@pytest.mark.asyncio
async def test_tool_timeout_and_non_idempotent_no_retry():
    calls = 0
    async def slow(req, ctx):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"result": "late"}
    registry = ToolRegistry()
    registry.register(metadata(timeout_seconds=0.01, max_retries=2), slow)
    result = await ToolRunner(registry).run(request(), allowed_tools={"test_tool"})
    assert result.status == "failed"
    assert result.error.code == "TimeoutError"
    assert calls == 3

    calls = 0
    registry = ToolRegistry()
    registry.register(metadata(timeout_seconds=0.01, max_retries=2, idempotent=False), slow)
    result = await ToolRunner(registry).run(request(), allowed_tools={"test_tool"})
    assert result.error.code == "TimeoutError"
    assert calls == 1


@pytest.mark.asyncio
async def test_two_independent_agents_can_reuse_one_tool():
    tool_registry = ToolRegistry()
    tool_registry.register(metadata("shared_tool"), lambda req, ctx: {"result": req.inputs["value"] + "!"})
    tool_runner = ToolRunner(tool_registry)
    agent_registry = AgentRegistry()
    agent_metadata = AgentMetadata(id="tool_agent", name="Tool Agent", execution={"allowed_tools": ["shared_tool"]})

    async def agent(request, context):
        result = await context.call_tool("shared_tool", {"value": request.inputs["value"]})
        if result.status == "failed": raise RuntimeError(result.error.message)
        return result.output

    agent_registry.register(agent_metadata, agent)
    runner = AgentRunner(agent_registry, tool_runner=tool_runner)
    first = await runner.run("tool_agent", AgentRequest(run_id="one", inputs={"value": "one"}))
    second = await runner.run("tool_agent", AgentRequest(run_id="two", inputs={"value": "two"}))
    assert first.output["result"] == "one!"
    assert second.output["result"] == "two!"


def test_email_tools_require_approval_before_mock_send(tmp_path):
    workflow = yaml.safe_load((Path(__file__).resolve().parent / "sample_platform/workflow_definitions/email_assistant.yaml").read_text(encoding="utf-8"))
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "email-tools.db")))) as client:
        assert client.post("/v1/workflows", json=workflow).status_code == 200
        paused = client.post("/v1/runs", json={"workflow_id":"email_assistant","inputs":{}}).json()
        assert paused["status"] == "waiting_for_approval"
        paused_events = client.get(f"/v1/runs/{paused['run_id']}/events").json()
        assert any(event["node_id"] == "tool:email_search" for event in paused_events)
        assert any(event["node_id"] == "tool:email_read" for event in paused_events)
        assert not any(event["node_id"] == "tool:email_send" for event in paused_events)
        completed = client.post(f"/v1/runs/{paused['run_id']}/resume", json={"decision":"approve"}).json()
        assert completed["status"] == "succeeded"
        assert completed["payload"]["node_outputs"]["send_reply"]["sent"] is True
        events = client.get(f"/v1/runs/{paused['run_id']}/events").json()
        assert any(event["node_id"] == "tool:email_send" for event in events)


def test_manifest_discovered_tool_runs_through_existing_agent_api(tmp_path):
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "manifest-tool.db")))) as client:
        agents = client.get("/v1/agents").json()
        assert any(agent["id"] == "tool_client_agent" for agent in agents)
        workflow = {
            "id": "manifest_tool_flow",
            "nodes": [{
                "id": "use_tool",
                "type": "agent",
                "agent_id": "tool_client_agent",
                "input_mappings": {"value": {"path": "workflow_input.value"}},
            }],
            "edges": [],
        }
        assert client.post("/v1/workflows", json=workflow).status_code == 200
        result = client.post(
            "/v1/runs",
            json={"workflow_id": "manifest_tool_flow", "inputs": {"value": "manifest value"}},
        ).json()
        assert result["status"] == "succeeded"
        assert result["payload"]["final_output"] == {"result": "manifest value"}
        events = client.get(f"/v1/runs/{result['run_id']}/events").json()
        assert any(event["node_id"] == "tool:tool_echo" for event in events)
