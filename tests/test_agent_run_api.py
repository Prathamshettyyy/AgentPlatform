from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.storage.repository import ExecutionRepository


def _agent_manifest(tmp_path):
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir()
    (manifest_dir / "direct_echo.yaml").write_text(
        """id: direct_echo
name: Direct Echo
version: '1.0.0'
description: Test direct single-agent execution.
capabilities: [testing]
adapter_type: python_callable
entrypoint: plugins.examples.manifest_echo:run
enabled: true
input_schema:
  type: object
  required: [value]
  properties:
    value: {type: string}
output_schema: {type: object}
""",
        encoding="utf-8",
    )
    return manifest_dir


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_direct_agent_run_uses_runner_and_persists_normal_history(tmp_path):
    repository = ExecutionRepository(str(tmp_path / "direct-runs.db"))
    with TestClient(create_app(
        repository,
        manifests_dir=_agent_manifest(tmp_path),
        auth_mode="required",
        auth_tokens={"alice": "alice-token"},
    )) as client:
        response = client.post(
            "/v1/agents/direct_echo/runs",
            json={"inputs": {"value": "single agent"}},
            headers=_headers("alice-token"),
        )
        assert response.status_code == 200
        record = response.json()
        assert record["status"] == "succeeded"
        assert record["workflow_id"] is None
        assert record["thread_id"] == record["run_id"]
        assert record["owner_id"] == "alice"
        assert record["payload"]["agent_id"] == "direct_echo"
        assert record["payload"]["final_output"]["echoed"] == "single agent"
        assert record["payload"]["execution"]["duration_ms"] >= 0

        inspected = client.get(f"/v1/runs/{record['run_id']}", headers=_headers("alice-token"))
        events = client.get(f"/v1/runs/{record['run_id']}/events", headers=_headers("alice-token"))
        workflows = client.get("/v1/workflows", headers=_headers("alice-token"))
        assert inspected.status_code == 200
        assert events.status_code == 200
        assert events.json()[0]["node_id"] == "direct_echo"
        assert events.json()[0]["status"] == "succeeded"
        assert events.json()[0]["payload"]["output"]["echoed"] == "single agent"
        assert workflows.json() == []
        assert repository.get_run(record["run_id"])["status"] == "succeeded"


def test_direct_agent_run_rejects_schema_invalid_input_without_creating_run(tmp_path):
    repository = ExecutionRepository(str(tmp_path / "invalid-input.db"))
    with TestClient(create_app(
        repository,
        manifests_dir=_agent_manifest(tmp_path),
        auth_mode="required",
        auth_tokens={"alice": "alice-token"},
    )) as client:
        response = client.post(
            "/v1/agents/direct_echo/runs",
            json={"inputs": {"value": 17}},
            headers=_headers("alice-token"),
        )
        assert response.status_code == 422
        assert response.json()["detail"]["path"] == ["value"]
        assert repository.list_runs(owner_id="alice") == []


def test_direct_agent_run_preserves_authentication_and_permission_boundaries(tmp_path):
    repository = ExecutionRepository(str(tmp_path / "agent-auth.db"))
    with TestClient(create_app(
        repository,
        manifests_dir=_agent_manifest(tmp_path),
        auth_mode="required",
        auth_tokens={
            "alice": "alice-token",
            "reader": {"token": "reader-token", "permissions": ["metadata.read", "runs.read"]},
            "bob": "bob-token",
        },
    )) as client:
        payload = {"inputs": {"value": "private"}}
        assert client.post("/v1/agents/direct_echo/runs", json=payload).status_code == 401
        invalid = client.post("/v1/agents/direct_echo/runs", json=payload, headers=_headers("wrong-token"))
        assert invalid.status_code == 401
        assert "wrong-token" not in invalid.text
        assert client.post("/v1/agents/direct_echo/runs", json=payload, headers=_headers("reader-token")).status_code == 403

        started = client.post("/v1/agents/direct_echo/runs", json=payload, headers=_headers("alice-token"))
        assert started.status_code == 200
        run_id = started.json()["run_id"]
        assert client.get(f"/v1/runs/{run_id}", headers=_headers("bob-token")).status_code == 404
        assert client.get(f"/v1/runs/{run_id}/events", headers=_headers("bob-token")).status_code == 404
