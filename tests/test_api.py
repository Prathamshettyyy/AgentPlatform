import json

from fastapi.testclient import TestClient
from app.api.app import create_app
from app.storage.repository import ExecutionRepository

def test_api_lists_agents_and_creates_workflow(tmp_path):
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "runs.db")))) as client:
        assert client.get("/v1/agents").status_code == 200
        assert any(tool["id"] == "email_search" for tool in client.get("/v1/tools").json())
        workflow = {"id":"api_flow","nodes":[{"id":"echo","type":"agent","agent_id":"email_summarizer","input_mappings":{"emails":{"path":"workflow_input.emails"}}}],"edges":[]}
        assert client.post("/v1/workflows", json=workflow).status_code == 200
        response = client.post("/v1/runs", json={"workflow_id":"api_flow","inputs":{"emails":[]}})
        assert response.status_code == 200
        assert response.json()["status"] == "succeeded"
        assert client.get(f"/v1/runs/{response.json()['run_id']}/events").json()


def test_paused_run_resumes_after_new_app_instance(tmp_path):
    db = tmp_path / "durable.db"
    workflow = {"id":"approval_flow","version":"1.0.0","nodes":[
        {"id":"draft","type":"agent","agent_id":"email_reply_writer","input_mappings":{"email_summary":{"path":"workflow_input.summary"}}},
        {"id":"approve","type":"human_approval","approval_payload_path":"node_outputs.draft"}],"edges":[{"from":"draft","to":"approve"}]}
    with TestClient(create_app(ExecutionRepository(str(db)))) as first:
        assert first.post("/v1/workflows", json=workflow).status_code == 200
        paused = first.post("/v1/runs", json={"workflow_id":"approval_flow","inputs":{"summary":"review me"}}).json()
        assert paused["status"] == "waiting_for_approval"
    with TestClient(create_app(ExecutionRepository(str(db)))) as second:
        assert second.get("/v1/approvals").json()[0]["run_id"] == paused["run_id"]
        resumed = second.post(f"/v1/runs/{paused['run_id']}/resume", json={"decision":"approve"})
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "succeeded"


def test_resume_uses_the_persisted_workflow_version_after_restart(tmp_path):
    db = tmp_path / "versioned.db"
    version_one = {"id":"versioned_flow","version":"1.0.0","nodes":[
        {"id":"draft","type":"agent","agent_id":"email_reply_writer", "input_mappings":{"email_summary":{"path":"workflow_input.summary"}}},
        {"id":"approve","type":"human_approval","approval_payload_path":"node_outputs.draft"}], "edges":[{"from":"draft","to":"approve"}]}
    version_two = {"id":"versioned_flow","version":"2.0.0","nodes":[
        {"id":"echo","type":"agent","agent_id":"manifest_echo", "input_mappings":{"value":{"path":"workflow_input.summary"}}},
        {"id":"approve","type":"human_approval","approval_payload_path":"node_outputs.echo"}], "edges":[{"from":"echo","to":"approve"}]}
    with TestClient(create_app(ExecutionRepository(str(db)))) as first:
        assert first.post("/v1/workflows", json=version_one).status_code == 200
        paused = first.post("/v1/runs", json={"workflow_id":"versioned_flow","inputs":{"summary":"version one"}}).json()
        assert paused["workflow_version"] == "1.0.0"
        assert first.post("/v1/workflows", json=version_two).status_code == 200
    with TestClient(create_app(ExecutionRepository(str(db)))) as second:
        resumed = second.post(f"/v1/runs/{paused['run_id']}/resume", json={"decision":"approve"})
        assert resumed.status_code == 200
        record = resumed.json()
        assert record["workflow_version"] == "1.0.0"
        assert "draft" in record["payload"]["node_outputs"]
        assert "echo" not in record["payload"]["node_outputs"]


def test_memory_repository_uses_memory_checkpointing(tmp_path):
    with TestClient(create_app(ExecutionRepository(":memory:"))) as client:
        workflow = {"id":"memory_flow","nodes":[{"id":"echo","type":"agent","agent_id":"manifest_echo","input_mappings":{"value":{"path":"workflow_input.value"}}}],"edges":[]}
        assert client.post("/v1/workflows", json=workflow).status_code == 200
        result = client.post("/v1/runs", json={"workflow_id":"memory_flow","inputs":{"value":"ok"}})
        assert result.status_code == 200
        assert result.json()["status"] == "succeeded"


def test_api_loads_legacy_persisted_path_mapping_with_null_literal(tmp_path):
    db = tmp_path / "legacy-startup.db"
    repository = ExecutionRepository(str(db))
    legacy_workflow = {
        "id": "legacy_startup_flow",
        "version": "1.0.0",
        "nodes": [{
            "id": "echo",
            "type": "agent",
            "agent_id": "manifest_echo",
            "input_mappings": {
                "value": {"path": "workflow_input.value", "literal": None}
            },
        }],
        "edges": [],
    }
    raw_definition = json.dumps(legacy_workflow)
    repository._connection.execute(
        "INSERT INTO workflows(workflow_id,version,definition,created_at) VALUES (?,?,?,?)",
        (legacy_workflow["id"], legacy_workflow["version"], raw_definition, "2026-01-01T00:00:00+00:00"),
    )
    repository._connection.execute(
        "INSERT INTO workflow_versions(workflow_id,version,definition,created_at) VALUES (?,?,?,?)",
        (legacy_workflow["id"], legacy_workflow["version"], raw_definition, "2026-01-01T00:00:00+00:00"),
    )
    repository._connection.commit()
    repository.close()

    with TestClient(create_app(ExecutionRepository(str(db)))) as client:
        response = client.get("/v1/workflows")
        assert response.status_code == 200
        assert any(item["id"] == "legacy_startup_flow" for item in response.json())


def test_manifest_discovered_agent_runs_through_api_without_bootstrap_registration(tmp_path):
    with TestClient(create_app(ExecutionRepository(str(tmp_path / "manifest.db")))) as client:
        agents = client.get("/v1/agents").json()
        assert any(agent["id"] == "manifest_echo" for agent in agents)
        workflow = {"id":"manifest_flow","nodes":[{"id":"echo","type":"agent","agent_id":"manifest_echo","input_mappings":{"value":{"path":"workflow_input.value"}}}],"edges":[]}
        assert client.post("/v1/workflows", json=workflow).status_code == 200
        result = client.post("/v1/runs", json={"workflow_id":"manifest_flow","inputs":{"value":"from manifest"}}).json()
        assert result["status"] == "succeeded"
        assert result["payload"]["final_output"]["echoed"] == "from manifest"
        assert client.get(f"/v1/runs/{result['run_id']}/events").json()[0]["node_id"] == "echo"

