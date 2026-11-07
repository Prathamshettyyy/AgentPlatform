from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.storage.repository import ExecutionRepository


def code_review_workflow() -> dict:
    return yaml.safe_load((Path(__file__).resolve().parent / "sample_platform/workflow_definitions/code_review.yaml").read_text(encoding="utf-8"))


def test_code_review_domain_is_discovered_and_runs_through_generic_api(tmp_path):
    source = "def calculate(value):\n    return eval(value)\n"
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "code-review.db")))) as client:
        agents = {agent["id"] for agent in client.get("/v1/agents").json()}
        assert {"source_inspector", "code_reviewer", "review_validator"} <= agents
        assert client.post("/v1/workflows", json=code_review_workflow()).status_code == 200

        paused = client.post(
            "/v1/runs",
            json={"workflow_id": "code_review", "inputs": {"source_code": source}},
        ).json()

        assert paused["status"] == "waiting_for_approval"
        outputs = paused["payload"]["node_outputs"]
        assert outputs["inspect"]["function_names"] == ["calculate"]
        assert outputs["review"]["finding_count"] == 1
        assert outputs["review"]["findings"][0]["severity"] == "high"
        assert outputs["validate"] == {"valid": True, "errors": [], "checked_findings": 1}
        events = client.get(f"/v1/runs/{paused['run_id']}/events").json()
        assert {event["node_id"] for event in events} >= {"inspect", "review", "validate"}

        completed = client.post(
            f"/v1/runs/{paused['run_id']}/resume",
            json={"decision": "approve"},
        ).json()
        assert completed["status"] == "succeeded"
        assert completed["payload"]["node_outputs"]["approve"]["decision"] == "approve"


def test_code_review_rejection_uses_generic_approval_and_does_not_add_custom_nodes(tmp_path):
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "code-review-reject.db")))) as client:
        client.post("/v1/workflows", json=code_review_workflow())
        paused = client.post(
            "/v1/runs",
            json={"workflow_id": "code_review", "inputs": {"source_code": "value = 1\n"}},
        ).json()
        rejected = client.post(
            f"/v1/runs/{paused['run_id']}/resume",
            json={"decision": "reject"},
        ).json()

        assert rejected["status"] == "succeeded"
        assert rejected["payload"]["node_outputs"]["approve"]["decision"] == "reject"
        assert set(rejected["payload"]["node_outputs"]) == {"inspect", "review", "validate", "approve"}


def test_code_review_input_failure_is_recorded_by_the_api(tmp_path):
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "code-review-failure.db")))) as client:
        client.post("/v1/workflows", json=code_review_workflow())
        failed = client.post(
            "/v1/runs",
            json={"workflow_id": "code_review", "inputs": {}},
        ).json()

        assert failed["status"] == "failed"
        events = client.get(f"/v1/runs/{failed['run_id']}/events").json()
        assert events[-1]["node_id"] == "workflow"
        assert events[-1]["status"] == "failed"
