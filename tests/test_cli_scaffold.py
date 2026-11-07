import io
import json
import sys

import pytest

from app.api.app import create_app
from app.cli import main
from app.registry import AgentRegistry
from app.runtime.runner import AgentRunner
from app.sdk.contracts import AgentMetadata, AgentRequest
from app.storage.repository import ExecutionRepository
from app.tools import ToolLoader, ToolRegistry, ToolRunner


def _run_cli(arguments):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(arguments, stdout=stdout, stderr=stderr)
    return code, stdout, stderr


def test_agent_scaffold_validates_loads_and_runs_through_api(tmp_path):
    root = str(tmp_path)
    code, stdout, stderr = _run_cli([
        "--project-root", root,
        "agents", "scaffold", "scaffold_demo_agent",
        "--name", "Scaffold Demo Agent",
        "--description", "A deterministic scaffold example",
    ])
    assert code == 0, stderr.getvalue()
    generated = json.loads(stdout.getvalue())
    manifest_path = tmp_path / "plugins/manifests/scaffold_demo_agent.yaml"
    assert generated["id"] == "scaffold_demo_agent"
    assert (tmp_path / "plugins/examples/scaffold_demo_agent/agent.py").is_file()
    assert (tmp_path / "plugins/examples/scaffold_demo_agent/__init__.py").is_file()
    assert (tmp_path / "plugins/examples/scaffold_demo_agent/example_input.json").is_file()
    assert manifest_path.is_file()

    code, _, stderr = _run_cli(["agents", "validate", str(manifest_path)])
    assert code == 0, stderr.getvalue()

    import plugins
    import plugins.examples
    plugins.__path__.append(str(tmp_path / "plugins"))
    plugins.examples.__path__.append(str(tmp_path / "plugins/examples"))
    # Use the actual HTTP application lifecycle to verify discovery, workflow execution,
    # and persisted node events without changing runner or graph-builder code.
    from fastapi.testclient import TestClient
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "api.db")), manifests_dir=tmp_path / "plugins/manifests")) as client:
        assert any(agent["id"] == "scaffold_demo_agent" for agent in client.get("/v1/agents").json())
        workflow = {
            "id": "scaffold_agent_flow",
            "nodes": [{
                "id": "scaffold",
                "type": "agent",
                "agent_id": "scaffold_demo_agent",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            }],
            "edges": [],
        }
        assert client.post("/v1/workflows", json=workflow).status_code == 200
        result = client.post("/v1/runs", json={"workflow_id": "scaffold_agent_flow", "inputs": {"text": "hello"}}).json()
        assert result["status"] == "succeeded"
        assert result["payload"]["final_output"]["result"] == "hello"
        events = client.get(f"/v1/runs/{result['run_id']}/events").json()
        assert any(event["node_id"] == "scaffold" for event in events)


def test_agent_scaffold_rejects_invalid_ids_and_never_overwrites(tmp_path):
    args = ["--project-root", str(tmp_path), "agents", "scaffold", "safe_agent", "--name", "Safe", "--description", "Example"]
    assert _run_cli(args)[0] == 0
    agent_file = tmp_path / "plugins/examples/safe_agent/agent.py"
    original = agent_file.read_text(encoding="utf-8")
    code, _, stderr = _run_cli(args)
    assert code == 2
    assert "already exists" in stderr.getvalue()
    assert agent_file.read_text(encoding="utf-8") == original
    code, _, stderr = _run_cli(["--project-root", str(tmp_path), "agents", "scaffold", "../escape", "--name", "Bad", "--description", "Bad"])
    assert code == 2
    assert "lowercase Python identifier" in stderr.getvalue()
    assert not (tmp_path.parent / "escape").exists()


@pytest.mark.asyncio
async def test_tool_scaffold_loads_and_runs_through_agent_context(tmp_path):
    code, stdout, stderr = _run_cli([
        "--project-root", str(tmp_path),
        "tools", "scaffold", "scaffold_text_tool",
        "--name", "Scaffold Text Tool",
        "--description", "A deterministic text capability",
    ])
    assert code == 0, stderr.getvalue()
    assert json.loads(stdout.getvalue())["id"] == "scaffold_text_tool"
    manifest_path = tmp_path / "plugins/tool_manifests/scaffold_text_tool.yaml"
    implementation_path = tmp_path / "plugins/tools/scaffold_text_tool.py"
    docs_path = tmp_path / "plugins/tools/scaffold_text_tool.md"
    assert manifest_path.is_file() and implementation_path.is_file() and docs_path.is_file()
    code, _, stderr = _run_cli(["tools", "validate", str(manifest_path)])
    assert code == 0, stderr.getvalue()

    import plugins
    import plugins.tools
    plugins.__path__.append(str(tmp_path / "plugins"))
    plugins.tools.__path__.append(str(tmp_path / "plugins/tools"))
    tool_registry = ToolRegistry()
    assert ToolLoader(tool_registry, tmp_path / "plugins/tool_manifests").load_all() == ["scaffold_text_tool"]
    records = []
    tool_runner = ToolRunner(tool_registry, execution_recorder=lambda *args: records.append(args))
    agents = AgentRegistry()
    async def use_tool(request, context):
        result = await context.call_tool("scaffold_text_tool", {"text": request.inputs["text"]})
        return result.model_dump()

    agents.register(
        AgentMetadata(
            id="scaffold_tool_user",
            name="Scaffold Tool User",
            execution={"allowed_tools": ["scaffold_text_tool"], "permissions": ["scaffold_text_tool.use"]},
        ),
        use_tool,
    )
    # The generic runner supports awaitable agent implementations, including this
    # small adapter that forwards the generated tool result.
    result = await AgentRunner(agents, tool_runner=tool_runner).run(
        "scaffold_tool_user",
        AgentRequest(run_id="scaffold-tool-run", inputs={"text": "Hello"}),
    )
    assert result.status == "succeeded"
    assert result.output["status"] == "succeeded"
    assert result.output["output"] == {"result": "Hello"}
    assert records[0][1:3] == ("tool:scaffold_text_tool", "succeeded")
