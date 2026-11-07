"""Runtime data-flow verification between the two connected external agents.

A test-only spy wraps ``invoke_python_agent`` inside each generated adapter so the
real inputs and outputs of both agents can be asserted during an actual workflow
execution. Nothing is logged or recorded by the application itself.
"""
import importlib
import io
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import app.api.app as api_module
from app.cli import main
from app.registry.external_connector import invoke_python_agent as real_invoke, project_plugin_namespace
from app.storage.repository import ExecutionRepository

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_ID = "external_text_analysis"
CHECKER_ID = "external_text_analysis_quality_checker"
EXTERNAL_PROJECTS = {
    ANALYSIS_ID: ROOT.parent / "external_agent_demo",
    CHECKER_ID: ROOT.parent / "external_text_insight_demo",
}
ADAPTER_MODULES = {
    ANALYSIS_ID: "plugins.examples.connected_external_text_analysis.adapter",
    CHECKER_ID: "plugins.examples.connected_external_text_analysis_quality_checker.adapter",
}
USER_TEXT = (
    "Artificial intelligence is changing software development. "
    "Python is widely used for automation. "
    "Developers use automated tests to improve code quality."
)


@pytest.fixture
def isolated_dataflow_env(tmp_path, monkeypatch):
    """Set up an isolated platform in tmp_path with both external agents connected and spied."""
    platform = tmp_path / "isolated_platform"
    (platform / "plugins" / "manifests").mkdir(parents=True)
    (platform / "plugins" / "examples").mkdir(parents=True)
    (platform / "plugins" / "__init__.py").write_text('"""test plugins"""\n', encoding="utf-8")
    (platform / "plugins" / "examples" / "__init__.py").write_text('"""test examples"""\n', encoding="utf-8")
    (platform / "workflow_definitions").mkdir(parents=True)

    for agent_id, project in EXTERNAL_PROJECTS.items():
        if not project.is_dir():
            pytest.skip(f"connected external project is not available: {project}")
        code = main(
            [
                "--project-root", str(platform),
                "agents", "connect",
                "--path", str(project),
                "--id", agent_id,
                "--trust",
            ],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
        assert code == 0

    raw_wf = yaml.safe_load((ROOT / "workflow_definitions" / "text_analysis_validation.yaml").read_text(encoding="utf-8"))
    for node in raw_wf.get("nodes", []):
        if isinstance(node, dict) and node.get("status") == "disconnected":
            node["status"] = "available"

    calls = []
    with project_plugin_namespace(platform):
        for agent_id, module_name in ADAPTER_MODULES.items():
            module = importlib.import_module(module_name)

            async def recording(configuration, inputs, _agent_id=agent_id):
                output = await real_invoke(configuration, inputs)
                calls.append({"agent_id": _agent_id, "inputs": dict(inputs), "output": output})
                return output

            monkeypatch.setattr(module, "invoke_python_agent", recording)
        yield platform, raw_wf, calls


def test_quality_checker_receives_original_text_and_agent_one_actual_output(tmp_path, isolated_dataflow_env):
    platform, workflow, spy = isolated_dataflow_env
    repository = ExecutionRepository(str(tmp_path / "dataflow.db"))
    with TestClient(api_module.create_app_unpatched(repository, manifests_dir=platform / "plugins" / "manifests")) as client:
        assert client.post("/v1/workflows", json=workflow).status_code == 200
        response = client.post("/v1/runs", json={"workflow_id": "text_analysis_validation", "inputs": {"text": USER_TEXT}})
        assert response.status_code == 200, response.text
        run = response.json()

    assert run["status"] == "succeeded", run
    assert [call["agent_id"] for call in spy] == [ANALYSIS_ID, CHECKER_ID]
    analysis, checker = spy

    # Agent 1 received exactly the user's text.
    assert analysis["inputs"] == {"text": USER_TEXT}
    first = analysis["output"]
    assert first["status"] == "success"

    # Agent 2 received exactly the original text plus Agent 1's actual output fields.
    assert set(checker["inputs"]) == {
        "original_text", "summary", "word_count", "character_count", "most_frequent_words", "analysis_status",
    }
    assert checker["inputs"]["original_text"] == USER_TEXT
    assert checker["inputs"]["summary"] == first["summary"]
    assert checker["inputs"]["word_count"] == first["word_count"]
    assert checker["inputs"]["character_count"] == first["character_count"]
    assert checker["inputs"]["most_frequent_words"] == first["most_frequent_words"]
    assert checker["inputs"]["analysis_status"] == first["status"]

    # The values are real, not placeholders.
    assert first["summary"] and first["word_count"] == len(USER_TEXT.split()) and first["character_count"] == len(USER_TEXT)
    assert first["most_frequent_words"]

    # Agent 2 validates the valid input, and the workflow returns its result.
    assert checker["output"]["overall_valid"] is True
    assert checker["output"]["status"] == "success"
    final_output = run.get("final_output") or run.get("payload", {}).get("final_output")
    assert final_output == checker["output"]

    # Verify agent_outputs field in workflow run response
    assert "agent_outputs" in run
    assert run["agent_outputs"][ANALYSIS_ID] == first
    assert run["agent_outputs"][CHECKER_ID] == checker["output"]


def test_cli_workflow_run_displays_both_agent_outputs_and_final_output(tmp_path, isolated_dataflow_env):
    platform, workflow, spy = isolated_dataflow_env
    repository = ExecutionRepository(str(tmp_path / "cli_dataflow.db"))
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps({"text": USER_TEXT}), encoding="utf-8")

    with TestClient(api_module.create_app_unpatched(repository, manifests_dir=platform / "plugins" / "manifests")) as client:
        assert client.post("/v1/workflows", json=workflow).status_code == 200

        # 1. runs start displays both agent outputs and final output
        stdout, stderr = io.StringIO(), io.StringIO()
        code = main(
            ["runs", "start", "--workflow", "text_analysis_validation", "--input", str(input_file)],
            client=client,
            stdout=stdout,
            stderr=stderr,
        )
        assert code == 0, stderr.getvalue()
        start_result = json.loads(stdout.getvalue())

        assert start_result["status"] == "succeeded"
        assert "agent_outputs" in start_result
        assert ANALYSIS_ID in start_result["agent_outputs"]
        assert CHECKER_ID in start_result["agent_outputs"]

        # Verify real values from Agent 1 and Agent 2
        agent_1_out = start_result["agent_outputs"][ANALYSIS_ID]
        agent_2_out = start_result["agent_outputs"][CHECKER_ID]
        assert agent_1_out["status"] == "success"
        assert agent_1_out["word_count"] == len(USER_TEXT.split())
        assert agent_2_out["status"] == "success"
        assert agent_2_out["overall_valid"] is True

        # final_output preserves backward compatibility and matches final node
        assert start_result["final_output"] == agent_2_out

        # 2. runs show also displays both agent outputs and final output
        run_id = start_result["run_id"]
        stdout, stderr = io.StringIO(), io.StringIO()
        assert main(["runs", "show", run_id], client=client, stdout=stdout, stderr=stderr) == 0
        show_result = json.loads(stdout.getvalue())
        assert show_result["agent_outputs"][ANALYSIS_ID] == agent_1_out
        assert show_result["agent_outputs"][CHECKER_ID] == agent_2_out
        assert show_result["final_output"] == agent_2_out

        # 3. runs events preserves security model: only includes node details when requested
        stdout, stderr = io.StringIO(), io.StringIO()
        assert main(["runs", "events", run_id], client=client, stdout=stdout, stderr=stderr) == 0
        events_default = json.loads(stdout.getvalue())
        assert len(events_default) >= 2
        assert all("payload" not in ev for ev in events_default)

        stdout, stderr = io.StringIO(), io.StringIO()
        assert main(["runs", "events", run_id, "--include-payload"], client=client, stdout=stdout, stderr=stderr) == 0
        events_full = json.loads(stdout.getvalue())
        node_payloads = {ev["node_id"]: ev.get("payload") for ev in events_full}
        assert node_payloads.get(ANALYSIS_ID) == agent_1_out
        assert node_payloads.get(CHECKER_ID) == agent_2_out

