from concurrent.futures import ThreadPoolExecutor
import os

import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.runtime.runner import AgentRunner
from app.registry import AgentRegistry
from app.sdk.contracts import AgentMetadata, AgentRequest
from app.storage.repository import ExecutionRepository


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def token_config():
    return {
        "alice": "alice-token",
        "bob": {"token": "bob-token", "permissions": ["metadata.read", "runs.read", "approval.read", "approval.execute", "workflow.read"]},
        "observer": {"token": "observer-token", "permissions": ["runs.read"]},
    }


def approval_workflow():
    return {
        "id": "secure_approval",
        "version": "1.0.0",
        "nodes": [
            {"id": "draft_node", "type": "agent", "agent_id": "manifest_echo", "input_mappings": {"value": {"path": "workflow_input.value"}}},
            {"id": "approve_node", "type": "human_approval", "approval_payload_path": "node_outputs.draft_node"},
        ],
        "edges": [{"from": "draft_node", "to": "approve_node"}],
    }


def test_authentication_rejects_missing_and_invalid_credentials(tmp_path):
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "auth.db")), auth_mode="required", auth_tokens={"alice": "alice-token"})) as client:
        assert client.get("/v1/agents").status_code == 401
        response = client.get("/v1/agents", headers=headers("wrong-token"))
        assert response.status_code == 401
        assert "wrong-token" not in response.text


def test_authentication_defaults_fail_closed_without_explicit_dev_mode(monkeypatch):
    monkeypatch.delenv("AGENT_PLATFORM_API_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_PLATFORM_AUTH_TOKENS", raising=False)
    monkeypatch.setenv("AGENT_PLATFORM_AUTH_MODE", "required")
    monkeypatch.delenv("AGENT_PLATFORM_DEV_MODE", raising=False)
    repository = ExecutionRepository(":memory:")
    try:
        with pytest.raises(ValueError, match="token authentication is required"):
            create_app(repository)
    finally:
        repository.close()


def test_runs_are_owner_scoped_and_approval_requires_permission(tmp_path):
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "owners.db")), auth_mode="required", auth_tokens=token_config())) as client:
        workflow = approval_workflow()
        assert client.post("/v1/workflows", json=workflow, headers=headers("alice-token")).status_code == 200
        paused = client.post("/v1/runs", json={"workflow_id": "secure_approval", "inputs": {"value": "private"}}, headers=headers("alice-token")).json()
        run_id = paused["run_id"]
        assert paused["owner_id"] == "alice"
        assert client.get(f"/v1/runs/{run_id}", headers=headers("bob-token")).status_code == 404
        assert client.get(f"/v1/runs/{run_id}/events", headers=headers("bob-token")).status_code == 404
        assert client.post(f"/v1/runs/{run_id}/resume", json={"decision": "approve"}, headers=headers("bob-token")).status_code == 404
        assert client.post(f"/v1/runs/{run_id}/resume", json={"decision": "approve"}, headers=headers("observer-token")).status_code == 403
        assert client.get("/v1/approvals", headers=headers("bob-token")).json() == []
        assert client.delete(f"/v1/runs/{run_id}", headers=headers("alice-token")).status_code == 200
        assert client.get(f"/v1/runs/{run_id}", headers=headers("alice-token")).status_code == 404


def test_redaction_applies_to_api_payloads_database_and_agent_errors(tmp_path, caplog):
    db = tmp_path / "redaction.db"
    with TestClient(create_app(ExecutionRepository(str(db)), auth_mode="required", auth_tokens={"alice": "alice-token"})) as client:
        workflow = {
            "id": "redaction_flow",
            "nodes": [{"id": "echo_node", "type": "agent", "agent_id": "manifest_echo", "input_mappings": {"value": {"path": "workflow_input.api_token"}}}],
            "edges": [],
        }
        assert client.post("/v1/workflows", json=workflow, headers=headers("alice-token")).status_code == 200
        result = client.post("/v1/runs", json={"workflow_id": "redaction_flow", "inputs": {"api_token": "top-secret-token", "password": "top-secret-password"}}, headers=headers("alice-token"))
        assert result.status_code == 200
        assert "top-secret-token" not in result.text
        assert "top-secret-password" not in result.text
        run_id = result.json()["run_id"]
        events = client.get(f"/v1/runs/{run_id}/events", headers=headers("alice-token"))
        assert "top-secret-token" not in events.text
    with db.open("rb") as handle:
        assert b"top-secret-token" not in handle.read()
    checkpoint_db = tmp_path / "redaction_checkpoints.db"
    if checkpoint_db.exists():
        with checkpoint_db.open("rb") as handle:
            assert b"top-secret-token" not in handle.read()

    def leaking_agent(request, context):
        raise RuntimeError("password=top-secret-password")

    registry = AgentRegistry()
    registry.register(AgentMetadata(id="leaking_agent", name="Leak Test"), leaking_agent)
    result = __import__("asyncio").run(AgentRunner(registry).run("leaking_agent", AgentRequest(run_id="redaction-run")))
    assert result.status == "failed"
    assert "top-secret-password" not in result.error.message
    assert "top-secret-password" not in caplog.text


def test_concurrent_runs_have_distinct_owner_and_thread_state(tmp_path):
    db = tmp_path / "concurrent.db"
    with TestClient(create_app(ExecutionRepository(str(db)), auth_mode="required", auth_tokens={"alice": "alice-token"})) as client:
        workflow = {"id": "concurrent_flow", "nodes": [{"id": "echo_node", "type": "agent", "agent_id": "manifest_echo", "input_mappings": {"value": {"path": "workflow_input.value"}}}], "edges": []}
        assert client.post("/v1/workflows", json=workflow, headers=headers("alice-token")).status_code == 200

        def start(value):
            return client.post("/v1/runs", json={"workflow_id": "concurrent_flow", "inputs": {"value": value}}, headers=headers("alice-token"))

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(start, ["first", "second"]))
        assert [response.status_code for response in responses] == [200, 200]
        records = [response.json() for response in responses]
        assert records[0]["run_id"] != records[1]["run_id"]
        assert records[0]["thread_id"] != records[1]["thread_id"]
        assert {record["payload"]["final_output"]["echoed"] for record in records} == {"first", "second"}


def test_repeated_resume_has_one_winner(tmp_path):
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "resume.db")), auth_mode="required", auth_tokens={"alice": "alice-token"})) as client:
        workflow = {"id": "resume_once", "nodes": [{"id": "approve_node", "type": "human_approval", "approval_payload_path": "workflow_input"}], "edges": []}
        assert client.post("/v1/workflows", json=workflow, headers=headers("alice-token")).status_code == 200
        paused = client.post("/v1/runs", json={"workflow_id": "resume_once", "inputs": {"value": "approve"}}, headers=headers("alice-token")).json()

        def resume():
            return client.post(f"/v1/runs/{paused['run_id']}/resume", json={"decision": "approve"}, headers=headers("alice-token"))

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: resume(), [1, 2]))
        assert sorted(response.status_code for response in responses) == [200, 409]
        assert client.get(f"/v1/runs/{paused['run_id']}", headers=headers("alice-token")).json()["status"] == "succeeded"


def test_retention_and_explicit_run_deletion_are_available(tmp_path):
    repository = ExecutionRepository(str(tmp_path / "retention.db"))
    repository.start_run("old-run", "workflow", {"password": "secret"}, owner_id="alice")
    repository._connection.execute("UPDATE runs SET created_at='2000-01-01T00:00:00+00:00' WHERE run_id='old-run'")
    repository._connection.commit()
    assert repository.purge_expired(1) == 1
    assert repository.get_run("old-run") is None
    repository.start_run("delete-run", "workflow", {}, owner_id="alice")
    assert repository.delete_run("delete-run") is True
    assert repository.get_run("delete-run") is None
    repository.close()
