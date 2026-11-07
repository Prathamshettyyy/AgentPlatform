import io
import shutil
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.cli import main
from app.storage.repository import ExecutionRepository
from app.workflows.models import WorkflowDefinition


def _project_with_manifests(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "plugins").mkdir(parents=True)
    shutil.copytree(Path(__file__).resolve().parent / "sample_platform/plugins/manifests", root / "plugins/manifests")
    return root


def _run_cli(arguments):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(arguments, stdout=stdout, stderr=stderr)
    return code, stdout, stderr


def test_workflow_scaffold_generates_safe_valid_template(tmp_path):
    root = _project_with_manifests(tmp_path)
    code, stdout, stderr = _run_cli([
        "--project-root", str(root),
        "workflows", "scaffold", "code_analysis",
        "--agents", "source_inspector,code_reviewer",
    ])
    assert code == 0, stderr.getvalue()
    generated_path = root / "workflow_definitions/code_analysis.yaml"
    assert generated_path.is_file()
    content = generated_path.read_text(encoding="utf-8")
    assert "Complete each node's input_mappings" in content
    assert "Optional human approval extension" in content
    raw = yaml.safe_load(content)
    workflow = WorkflowDefinition.model_validate(raw)
    assert [node.id for node in workflow.nodes] == ["source_inspector", "code_reviewer"]
    assert [(edge.from_node, edge.to) for edge in workflow.edges] == [("source_inspector", "code_reviewer")]


def test_workflow_scaffold_rejects_unknown_invalid_and_existing_targets(tmp_path):
    root = _project_with_manifests(tmp_path)
    unknown_args = ["--project-root", str(root), "workflows", "scaffold", "unknown_flow", "--agents", "missing_agent"]
    code, _, stderr = _run_cli(unknown_args)
    assert code == 2
    assert "unknown or disabled agent" in stderr.getvalue()
    invalid_args = ["--project-root", str(root), "workflows", "scaffold", "../escape", "--agents", "source_inspector"]
    code, _, stderr = _run_cli(invalid_args)
    assert code == 2
    assert "workflow ID" in stderr.getvalue()
    assert not (root.parent / "escape.yaml").exists()

    valid_args = ["--project-root", str(root), "workflows", "scaffold", "safe_flow", "--agents", "source_inspector"]
    assert _run_cli(valid_args)[0] == 0
    code, _, stderr = _run_cli(valid_args)
    assert code == 2
    assert "already exists" in stderr.getvalue()


def test_completed_scaffolded_workflow_runs_with_generic_approval(tmp_path):
    root = _project_with_manifests(tmp_path)
    code, _, stderr = _run_cli([
        "--project-root", str(root),
        "workflows", "scaffold", "generated_review",
        "--agents", "source_inspector,code_reviewer",
    ])
    assert code == 0, stderr.getvalue()
    path = root / "workflow_definitions/generated_review.yaml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    workflow["nodes"][0]["input_mappings"] = {"source_code": {"path": "workflow_input.source_code"}}
    workflow["nodes"][1]["input_mappings"] = {"inspection": {"path": "node_outputs.source_inspector"}}
    workflow["nodes"].append({
        "id": "approve",
        "type": "human_approval",
        "approval_payload_path": "node_outputs.code_reviewer",
        "approval_options": ["approve", "reject"],
    })
    workflow["edges"].append({"from": "code_reviewer", "to": "approve"})
    path.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")
    assert WorkflowDefinition.model_validate(workflow).id == "generated_review"

    with TestClient(create_app(
        ExecutionRepository(str(tmp_path / "generated-workflow.db")),
        manifests_dir=root / "plugins/manifests",
    )) as client:
        registered = client.post("/v1/workflows", json=workflow)
        assert registered.status_code == 200
        paused = client.post("/v1/runs", json={
            "workflow_id": "generated_review",
            "inputs": {"source_code": "def f(value):\n    return value\n"},
        }).json()
        assert paused["status"] == "waiting_for_approval"
        resumed = client.post(f"/v1/runs/{paused['run_id']}/resume", json={"decision": "approve"}).json()
        assert resumed["status"] == "succeeded"
        assert resumed["payload"]["node_outputs"]["approve"]["decision"] == "approve"
        events = client.get(f"/v1/runs/{paused['run_id']}/events").json()
        assert {event["node_id"] for event in events} >= {"source_inspector", "code_reviewer"}
