"""Tests for dashboard API endpoints: health, overview, runs list, events list, workflow drafts and preview."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from app.api.app import create_app
from app.storage.repository import ExecutionRepository

@pytest.fixture
def dashboard_app(tmp_path):
    repo = ExecutionRepository(str(tmp_path / "dashboard_test.db"))
    app = create_app(
        repo,
        auth_mode="required",
        auth_tokens={"alice": {"token": "alice-token", "permissions": ["*"]}},
    )
    return app, repo, tmp_path

def test_health_endpoint_is_public(dashboard_app):
    app, _, _ = dashboard_app
    with TestClient(app) as client:
        # /v1/health does not require Bearer token
        res = client.get("/v1/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["service"] == "agent-platform"

def test_overview_and_runs_and_events_endpoints(dashboard_app):
    app, repo, _ = dashboard_app
    headers = {"Authorization": "Bearer alice-token"}
    with TestClient(app) as client:
        # Overview stats
        res = client.get("/v1/overview", headers=headers)
        assert res.status_code == 200
        stats = res.json()
        assert "agents_count" in stats
        assert "workflows_total" in stats
        assert "runs_total" in stats
        assert "tools_count" in stats

        # List runs (empty initially)
        res = client.get("/v1/runs", headers=headers)
        assert res.status_code == 200
        assert isinstance(res.json(), list)

        # Start a direct run or manually record one to test /v1/runs and /v1/events
        repo.start_run("test-run-1", "test_flow", {"text": "hello"}, "1.0.0", "thread-1", "alice")
        repo.add_event("test-run-1", "node-1", "succeeded", {"result": "ok"})
        repo.update_run("test-run-1", "succeeded", {"final_output": {"result": "ok"}})

        # List runs
        res = client.get("/v1/runs", headers=headers)
        assert res.status_code == 200
        runs = res.json()
        assert len(runs) >= 1
        assert runs[0]["run_id"] == "test-run-1"

        # List events
        res = client.get("/v1/events", headers=headers)
        assert res.status_code == 200
        events = res.json()
        assert len(events) >= 1
        assert events[0]["run_id"] == "test-run-1"
        assert events[0]["node_id"] == "node-1"

def test_workflow_draft_and_preview_delete(dashboard_app):
    app, repo, tmp_path = dashboard_app
    headers = {"Authorization": "Bearer alice-token"}
    with TestClient(app) as client:
        # Save draft
        res = client.post(
            "/v1/workflows/draft",
            json={"id": "test_draft_ui", "version": "1.0.0", "nodes": [], "edges": []},
            headers=headers,
        )
        assert res.status_code == 200
        assert res.json()["status"] == "draft"

        # Preview delete
        res = client.get("/v1/workflows/test_draft_ui/preview-delete", headers=headers)
        assert res.status_code == 200
        preview = res.json()
        assert preview["workflow_id"] == "test_draft_ui"
        assert preview["has_local_file"] is True

        # Clean up local file created in test
        wf_file = tmp_path.parents[0] / "workflow_definitions" / "test_draft_ui.yaml"
        if wf_file.exists():
            wf_file.unlink()

def test_workflow_registration_and_extra_fields_tolerance(dashboard_app):
    app, repo, tmp_path = dashboard_app
    headers = {"Authorization": "Bearer alice-token"}
    wf_file = None
    try:
        with TestClient(app) as client:
            # 1. Post workflow with extra client/telemetry fields (should be tolerated, not 422 extra_forbidden)
            flow_payload = {
                "id": "ui_test_flow",
                "version": "1.0.0",
                "nodes": [
                    {
                        "id": "node_a",
                        "type": "agent",
                        "agent_id": "email_summarizer",
                        "input_mappings": {"emails": {"path": "workflow_input.emails"}},
                        "status": "available",
                    }
                ],
                "edges": [],
                "registered": False,
                "registration_status": "disconnected",
                "workflow_file": "C:\\some\\path.yaml",
            }
            # Save draft on disk
            draft_res = client.post("/v1/workflows/draft", json=flow_payload, headers=headers)
            assert draft_res.status_code == 200
            wf_file = Path(draft_res.json()["workflow_file"])
            # Re-write full flow_payload into the draft file so nodes & edges match
            import yaml
            wf_file.write_text(yaml.safe_dump(flow_payload, sort_keys=False), encoding="utf-8")

            res = client.post("/v1/workflows", json=flow_payload, headers=headers)
            assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
            data = res.json()
            assert data["id"] == "ui_test_flow"
            assert data["registered"] is True

            # 2. Get workflow detail
            res = client.get("/v1/workflows/ui_test_flow", headers=headers)
            assert res.status_code == 200
            assert res.json()["registered"] is True

            # 3. Disconnect workflow
            res = client.post("/v1/workflows/ui_test_flow/disconnect", headers=headers)
            assert res.status_code == 200
            assert res.json()["registered"] is False

            # 4. Disconnected workflow returns 404 on /v1/workflows/{id}, but local draft on disk is in include_drafts=true
            res = client.get("/v1/workflows/ui_test_flow", headers=headers)
            assert res.status_code == 404

            res = client.get("/v1/workflows?include_drafts=true", headers=headers)
            assert res.status_code == 200
            drafts = {w["id"]: w for w in res.json()}
            assert "ui_test_flow" in drafts
            assert drafts["ui_test_flow"]["registered"] is False

            # 5. Register by ID via /v1/workflows/{id}/register
            res = client.post("/v1/workflows/ui_test_flow/register", headers=headers)
            assert res.status_code == 200
            assert res.json()["registered"] is True
            assert res.json()["registration_status"] == "registered"
    finally:
        if wf_file is not None and wf_file.exists():
            wf_file.unlink()


def test_workflow_complete_deletion_purges_db_and_disk(dashboard_app):
    app, repo, tmp_path = dashboard_app
    headers = {"Authorization": "Bearer alice-token"}
    wf_id = "purge_flow_test"
    wf_file = None

    try:
        with TestClient(app) as client:
            # 1. Create and register a workflow with a run and events
            flow_payload = {
                "id": wf_id,
                "version": "1.0.0",
                "nodes": [
                    {
                        "id": "node_1",
                        "type": "agent",
                        "agent_id": "email_summarizer",
                        "input_mappings": {"emails": {"path": "workflow_input.emails"}},
                    }
                ],
                "edges": [],
            }
            # Save draft file
            res = client.post("/v1/workflows/draft", json=flow_payload, headers=headers)
            assert res.status_code == 200
            wf_file = Path(res.json()["workflow_file"])
            assert wf_file.exists()

            # Register
            res = client.post("/v1/workflows", json=flow_payload, headers=headers)
            assert res.status_code == 200

            # Record run and events
            run_id = f"run_{wf_id}_1"
            repo.start_run(run_id, wf_id, {"workflow_input": {"emails": "test"}}, "1.0.0", "thread-p", "alice")
            repo.add_event(run_id, "node_1", "succeeded", {"data": 123})
            repo.update_run(run_id, "succeeded", {"final_output": {"ok": True}})

            # Check preview-delete
            res = client.get(f"/v1/workflows/{wf_id}/preview-delete", headers=headers)
            assert res.status_code == 200
            preview = res.json()
            assert preview["workflow_id"] == wf_id
            assert preview["has_local_file"] is True
            assert preview["run_count"] >= 1
            assert preview["event_count"] >= 1

            # Execute permanent delete
            del_res = client.delete(f"/v1/workflows/{wf_id}", headers=headers)
            assert del_res.status_code == 200
            del_data = del_res.json()
            assert del_data["deleted"] is True
            assert del_data["workflow_id"] == wf_id
            assert del_data["deleted_runs"] >= 1
            assert del_data["deleted_events"] >= 1

            # Verify local file is completely removed from disk
            assert not wf_file.exists()

            # Verify workflow is not found anywhere
            assert client.get(f"/v1/workflows/{wf_id}", headers=headers).status_code == 404
            drafts = client.get("/v1/workflows?include_drafts=true", headers=headers).json()
            assert not any(w["id"] == wf_id for w in drafts)

            # Verify DB runs and events are purged
            assert len([r for r in repo.list_runs() if r.get("workflow_id") == wf_id]) == 0
            assert len(repo.list_events(run_id=run_id)) == 0
    finally:
        if wf_file is not None and wf_file.exists():
            wf_file.unlink()


def test_agent_complete_deletion_purges_all_related_data(dashboard_app):
    import json
    from tests.conftest import SAMPLE_PLATFORM

    app, repo, tmp_path = dashboard_app
    headers = {"Authorization": "Bearer alice-token"}
    agent_id = "test_purge_agent_xyz"

    manifest_dir = SAMPLE_PLATFORM / "plugins" / "manifests"
    manifest_file = manifest_dir / f"{agent_id}.yaml"
    adapter_dir = SAMPLE_PLATFORM / "plugins" / "examples" / f"connected_{agent_id}"
    catalog_file = SAMPLE_PLATFORM / "plugins" / "connection_catalog.json"

    # Setup mock disk artifacts
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(
        f"id: {agent_id}\nname: Purge Agent\nversion: 1.0.0\nentrypoint: plugins.examples.connected_{agent_id}.agent:entry\nenabled: true\n",
        encoding="utf-8",
    )

    adapter_dir.mkdir(parents=True, exist_ok=True)
    (adapter_dir / "agent.py").write_text("def entry(): pass\n", encoding="utf-8")

    # Add to connection catalog in plugins/
    catalog = {}
    if catalog_file.is_file():
        try:
            catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
        except Exception:
            catalog = {}
    catalog[agent_id] = {"name": "Purge Agent", "connected_at": "2026-01-01"}
    catalog_file.write_text(json.dumps(catalog, indent=2), encoding="utf-8")

    try:
        with TestClient(app) as client:
            # Record direct run and event for this agent
            run_id = f"direct_run_{agent_id}_1"
            repo.start_run(run_id, None, {"agent_id": agent_id, "inputs": {}}, "1.0.0", "thread-a", "alice")
            repo.add_event(run_id, agent_id, "succeeded", {"res": "done"})
            repo.update_run(run_id, "succeeded", {"final_output": {"ok": True}})

            # Check preview-delete
            preview_res = client.get(f"/v1/agents/{agent_id}/preview-delete", headers=headers)
            assert preview_res.status_code == 200
            preview = preview_res.json()
            assert preview["agent_id"] == agent_id
            assert preview["direct_run_count"] >= 1
            assert preview["event_count"] >= 1
            assert preview["has_manifest"] is True
            assert preview["has_adapter"] is True
            assert preview["has_catalog_entry"] is True

            # Permanently delete agent
            del_res = client.delete(f"/v1/agents/{agent_id}", headers=headers)
            assert del_res.status_code == 200
            del_data = del_res.json()
            assert del_data["deleted"] is True
            assert del_data["agent_id"] == agent_id
            assert del_data["purged_records"]["deleted_runs"] >= 1
            assert del_data["purged_records"]["deleted_events"] >= 1

            # Assert disk artifacts were purged
            assert not manifest_file.exists()
            assert not adapter_dir.exists()

            # Assert catalog was updated
            if catalog_file.is_file():
                updated_cat = json.loads(catalog_file.read_text(encoding="utf-8"))
                assert agent_id not in updated_cat

            # Assert database runs & events were purged
            assert len(repo.list_events(run_id=run_id)) == 0
            runs = repo.list_runs()
            assert not any(r["run_id"] == run_id for r in runs)
    finally:
        if manifest_file.exists():
            manifest_file.unlink()
        if adapter_dir.exists():
            import shutil
            shutil.rmtree(adapter_dir, ignore_errors=True)
        if catalog_file.is_file():
            try:
                cat = json.loads(catalog_file.read_text(encoding="utf-8"))
                cat.pop(agent_id, None)
                catalog_file.write_text(json.dumps(cat, indent=2), encoding="utf-8")
            except Exception:
                pass


def test_workflow_update_and_add_agent_and_remove_node(dashboard_app):
    app, repo, tmp_path = dashboard_app
    headers = {"Authorization": "Bearer alice-token"}
    wf_id = "test_interactive_draft"
    wf_file = None

    try:
        with TestClient(app) as client:
            # 1. Create an empty draft workflow
            res = client.post("/v1/workflows/draft", json={"id": wf_id, "nodes": [], "edges": []}, headers=headers)
            assert res.status_code == 200
            wf_file = Path(res.json()["workflow_file"])
            assert wf_file.exists()

            # 2. Add an agent to the draft workflow via /v1/workflows/{id}/add-agent
            add_res = client.post(
                f"/v1/workflows/{wf_id}/add-agent",
                json={
                    "agent_id": "email_summarizer",
                    "input_mappings": {"emails": {"path": "workflow_input.emails"}},
                },
                headers=headers,
            )
            assert add_res.status_code == 200
            data = add_res.json()
            assert len(data["nodes"]) == 1
            assert data["nodes"][0]["agent_id"] == "email_summarizer"
            assert "emails" in data["nodes"][0]["input_mappings"]

            # 3. Update definition via PUT /v1/workflows/{id}
            data["version"] = "1.1.0"
            put_res = client.put(f"/v1/workflows/{wf_id}", json=data, headers=headers)
            assert put_res.status_code == 200
            assert put_res.json()["version"] == "1.1.0"

            # 4. Register the workflow
            reg_res = client.post(f"/v1/workflows/{wf_id}/register", headers=headers)
            assert reg_res.status_code == 200
            assert reg_res.json()["registered"] is True

            # 5. Remove the node via DELETE /v1/workflows/{id}/nodes/{node_id}
            del_node_res = client.delete(
                f"/v1/workflows/{wf_id}/nodes/{data['nodes'][0]['id']}",
                headers=headers,
            )
            assert del_node_res.status_code == 200
            node_data = del_node_res.json()
            assert len(node_data["nodes"]) == 0
            # Since 0 nodes remain, it should automatically be unlinked/draft
            assert node_data["registered"] is False
    finally:
        if wf_file is not None and wf_file.exists():
            wf_file.unlink()


