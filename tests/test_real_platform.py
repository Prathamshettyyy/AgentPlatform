"""Verify the shipped application contains only the two connected external agents."""
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

import app.api.app as api_module
from app.storage.repository import ExecutionRepository
from app.workflows.models import WorkflowDefinition

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_AGENTS = {
    "external_text_analysis",
    "external_text_analysis_quality_checker",
    "geotechnical_analysis",
}


def _expected_connected_agents() -> set[str]:
    wf_path = ROOT / "workflow_definitions" / "text_analysis_validation.yaml"
    workflow = WorkflowDefinition.model_validate(yaml.safe_load(wf_path.read_text(encoding="utf-8")))
    connected = {
        node.agent_id
        for node in workflow.nodes
        if node.type == "agent" and node.agent_id and node.status != "disconnected"
    }
    connected.add("geotechnical_analysis")
    return connected & REQUIRED_AGENTS


def test_real_manifest_directory_contains_only_required_agents():
    manifests = sorted(path.stem for path in (ROOT / "plugins" / "manifests").glob("*.y*ml"))
    assert set(manifests) <= REQUIRED_AGENTS
    assert set(manifests) == _expected_connected_agents()


def test_real_tool_manifest_directory_has_no_example_tools():
    assert not list((ROOT / "plugins" / "tool_manifests").glob("*.y*ml"))


def test_real_workflow_directory_contains_only_text_analysis_validation():
    paths = sorted((ROOT / "workflow_definitions").glob("*.y*ml"))
    assert "text_analysis_validation" in [path.stem for path in paths]
    wf_path = ROOT / "workflow_definitions" / "text_analysis_validation.yaml"
    workflow = WorkflowDefinition.model_validate(yaml.safe_load(wf_path.read_text(encoding="utf-8")))
    assert [node.id for node in workflow.nodes] == ["external_text_analysis", "external_text_analysis_quality_checker"]
    assert [(edge.from_node, edge.to) for edge in workflow.edges] == [
        ("external_text_analysis", "external_text_analysis_quality_checker")
    ]
    checker = workflow.nodes[1]
    assert set(checker.input_mappings) == {
        "original_text", "summary", "word_count", "character_count", "most_frequent_words", "analysis_status",
    }


def test_real_api_registry_has_exactly_required_agents_on_repeated_startup(tmp_path):
    expected = _expected_connected_agents()
    for attempt in range(2):
        repository = ExecutionRepository(str(tmp_path / "startup.db"))
        with TestClient(api_module.create_app_unpatched(repository)) as client:
            agents = {item["id"] for item in client.get("/v1/agents").json()}
            assert agents == expected, f"attempt {attempt}"
            assert client.get("/v1/tools").json() == []
