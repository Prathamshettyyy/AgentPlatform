"""Comprehensive tests for normal disconnect and permanent purge disconnection modes."""
import io
import json
from pathlib import Path
import sqlite3

import pytest
import yaml

from app.cli import build_parser, main
from app.storage.repository import ExecutionRepository
from app.workflows.models import WorkflowDefinition

AGENT_ONE_SOURCE = '''\
class AgentOne:
    def run(self, payload):
        text = payload.get("text", "")
        return {"summary": text, "count": len(text.split())}
'''

AGENT_TWO_SOURCE = '''\
class AgentTwo:
    def run(self, payload):
        text = payload.get("original_text", "")
        summary = payload.get("summary", "")
        return {"valid": bool(summary), "original": text}
'''


def _setup_isolated_platform(tmp_path: Path):
    platform = tmp_path / "platform"
    (platform / "plugins" / "manifests").mkdir(parents=True)
    (platform / "plugins" / "examples").mkdir(parents=True)
    (platform / "plugins" / "__init__.py").write_text('"""test plugins"""\n', encoding="utf-8")
    (platform / "plugins" / "examples" / "__init__.py").write_text('"""test examples"""\n', encoding="utf-8")
    (platform / "workflow_definitions").mkdir(parents=True)

    external_one = tmp_path / "external_agent_one"
    external_one.mkdir()
    (external_one / "agent.py").write_text(AGENT_ONE_SOURCE, encoding="utf-8")
    (external_one / "input.json").write_text(json.dumps({"text": "Hello world"}), encoding="utf-8")

    external_two = tmp_path / "external_agent_two"
    external_two.mkdir()
    (external_two / "agent.py").write_text(AGENT_TWO_SOURCE, encoding="utf-8")
    (external_two / "input.json").write_text(json.dumps({"original_text": "Hello world", "summary": "Hello"}), encoding="utf-8")

    return platform, external_one, external_two


def _connect_agent(platform: Path, external: Path, agent_id: str):
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        [
            "--project-root", str(platform),
            "agents", "connect",
            "--path", str(external),
            "--id", agent_id,
            "--test-input", str(external / "input.json"),
            "--trust",
        ],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0, stderr.getvalue()


def test_parser_exposes_purge_yes_and_db_options():
    parser = build_parser()
    args = parser.parse_args(["agents", "disconnect", "some_agent", "--purge", "--yes", "--db", "custom.db"])
    assert args.command == "agents"
    assert args.action == "disconnect"
    assert args.agent_id == "some_agent"
    assert args.purge is True
    assert args.yes is True
    assert args.db == "custom.db"

    args_default = parser.parse_args(["agents", "disconnect", "some_agent"])
    assert args_default.purge is False
    assert args_default.yes is False
    assert args_default.db is None


def test_normal_disconnect_preserves_history_and_workflows_and_warns(tmp_path):
    platform, external_one, _ = _setup_isolated_platform(tmp_path)
    original_source = (external_one / "agent.py").read_bytes()
    _connect_agent(platform, external_one, "agent_one")

    db_path = platform / "agent_platform.db"
    repo = ExecutionRepository(str(db_path))
    repo.start_run("direct-run-1", None, {"agent_id": "agent_one", "input": "test"})
    repo.add_event("direct-run-1", "agent_one", "succeeded", {"result": "ok"})
    repo.update_run("direct-run-1", "succeeded", {"agent_id": "agent_one", "final_output": {"summary": "test"}})

    # Saved workflow referencing agent_one
    wf_dict = {
        "id": "analysis_pipeline",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "agent_one",
                "type": "agent",
                "agent_id": "agent_one",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            }
        ],
        "edges": [],
        "max_steps": 100,
    }
    repo.save_workflow(wf_dict)
    repo.close()

    wf_file = platform / "workflow_definitions" / "analysis_pipeline.yaml"
    wf_file.write_text(yaml.safe_dump(wf_dict, sort_keys=False), encoding="utf-8")
    original_wf_content = wf_file.read_text(encoding="utf-8")

    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_one"],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0, stderr.getvalue()
    result = json.loads(stdout.getvalue())

    assert result["id"] == "agent_one"
    assert result["status"] == "disconnected"
    assert result["external_project_modified"] is False
    assert result["retained"]["history"] is True
    assert result["retained"]["workflow_definitions"] is True
    assert "analysis_pipeline" in result["retained"]["referenced_by_workflows"]
    assert any("analysis_pipeline" in w for w in result["warnings"])
    assert "Warning:" in stderr.getvalue()
    assert "retained" in result["message"].lower()

    # Manifest and adapter removed
    assert not (platform / "plugins" / "manifests" / "agent_one.yaml").exists()
    assert not (platform / "plugins" / "examples" / "connected_agent_one" / "adapter.py").exists()

    # External source project unmodified
    assert (external_one / "agent.py").read_bytes() == original_source

    # Workflow file on disk marks the node as disconnected while preserving node config, mappings, and edges
    disk_wf = yaml.safe_load(wf_file.read_text(encoding="utf-8"))
    assert len(disk_wf["nodes"]) == 1
    assert disk_wf["nodes"][0]["id"] == "agent_one"
    assert disk_wf["nodes"][0]["agent_id"] == "agent_one"
    assert disk_wf["nodes"][0]["status"] == "disconnected"
    assert disk_wf["nodes"][0]["input_mappings"] == {"text": {"path": "workflow_input.text"}}
    assert disk_wf["edges"] == []
    assert result["workflows_updated"] == {"analysis_pipeline": ["agent_one"]}

    # Database records preserved and workflow node marked disconnected in DB
    check_repo = ExecutionRepository(str(db_path))
    assert check_repo.get_run("direct-run-1") is not None
    assert len(check_repo.events("direct-run-1")) == 1
    db_wf = check_repo.get_workflow("analysis_pipeline")
    assert db_wf is not None
    assert db_wf["nodes"][0]["status"] == "disconnected"
    assert db_wf["nodes"][0]["input_mappings"] == {"text": {"path": "workflow_input.text"}}
    check_repo.close()


def test_purge_requires_confirmation_when_yes_not_passed(tmp_path):
    platform, external_one, _ = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")

    # Non-interactive without --yes fails closed
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_one", "--purge"],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 2
    assert "purge requires explicit confirmation" in stderr.getvalue()
    assert (platform / "plugins" / "manifests" / "agent_one.yaml").exists()

    # Interactive cancellation makes no changes
    stderr = io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_one", "--purge"],
        stdout=io.StringIO(),
        stderr=stderr,
        input_fn=lambda prompt: "CANCEL",
    )
    assert code == 2
    assert "purge cancelled" in stderr.getvalue()
    assert "Preview of platform-managed data" in stderr.getvalue()
    assert (platform / "plugins" / "manifests" / "agent_one.yaml").exists()
    assert (platform / "plugins" / "examples" / "connected_agent_one" / "adapter.py").exists()


def test_purge_with_yes_removes_agent_data_and_checkpoints_preserves_unrelated(tmp_path):
    platform, external_one, external_two = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")
    _connect_agent(platform, external_two, "agent_two")

    db_path = platform / "agent_platform.db"
    cp_path = platform / "agent_platform_checkpoints.db"
    repo = ExecutionRepository(str(db_path))

    # Direct run for agent_one
    repo.start_run("run-agent-1", None, {"agent_id": "agent_one"}, thread_id="thread-agent-1")
    repo.add_event("run-agent-1", "agent_one", "succeeded", {"out": 1})
    repo.update_run("run-agent-1", "succeeded", {"agent_id": "agent_one"})

    # Direct run for agent_two
    repo.start_run("run-agent-2", None, {"agent_id": "agent_two"}, thread_id="thread-agent-2")
    repo.add_event("run-agent-2", "agent_two", "succeeded", {"out": 2})
    repo.update_run("run-agent-2", "succeeded", {"agent_id": "agent_two"})

    # Shared workflow run
    repo.start_run("run-shared", "shared_flow", {"text": "hello"}, thread_id="thread-shared")
    repo.add_event("run-shared", "shared_node", "succeeded", {"shared": True})
    repo.close()

    # Set up checkpoints DB with checkpoints for both threads
    with sqlite3.connect(str(cp_path)) as cp_conn:
        cp_conn.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, parent_checkpoint_id TEXT, type TEXT, checkpoint BLOB, metadata BLOB, PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id))")
        cp_conn.execute("CREATE TABLE writes (thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, task_id TEXT, idx INTEGER, channel TEXT, type TEXT, value BLOB, PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx))")
        cp_conn.execute("INSERT INTO checkpoints VALUES ('thread-agent-1', '', 'cp1', NULL, 't', X'00', X'00')")
        cp_conn.execute("INSERT INTO writes VALUES ('thread-agent-1', '', 'cp1', 'task1', 0, 'c', 't', X'00')")
        cp_conn.execute("INSERT INTO checkpoints VALUES ('thread-agent-2', '', 'cp2', NULL, 't', X'00', X'00')")
        cp_conn.execute("INSERT INTO writes VALUES ('thread-agent-2', '', 'cp2', 'task2', 0, 'c', 't', X'00')")
        cp_conn.commit()

    # Execute purge on agent_one
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_one", "--purge", "--yes"],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0, stderr.getvalue()
    result = json.loads(stdout.getvalue())

    assert result["id"] == "agent_one"
    assert result["status"] == "purged"
    assert result["deleted"]["direct_runs"] == 1
    assert result["deleted"]["events"] >= 1
    assert result["deleted"]["checkpoints"] == 2
    assert "agent_two" in result["retained"]["unrelated_agents"]
    assert result["retained"]["shared_runs"] == 1
    assert result["external_project_modified"] is False

    # agent_one files removed; agent_two files remain
    assert not (platform / "plugins" / "manifests" / "agent_one.yaml").exists()
    assert not (platform / "plugins" / "examples" / "connected_agent_one").exists()
    assert (platform / "plugins" / "manifests" / "agent_two.yaml").exists()
    assert (platform / "plugins" / "examples" / "connected_agent_two" / "adapter.py").exists()

    # External directories intact
    assert (external_one / "agent.py").exists()
    assert (external_two / "agent.py").exists()

    # Check database: agent_one direct run gone, agent_two and shared run intact
    check_repo = ExecutionRepository(str(db_path))
    assert check_repo.get_run("run-agent-1") is None
    assert check_repo.get_run("run-agent-2") is not None
    assert check_repo.get_run("run-shared") is not None
    assert len(check_repo.events("run-agent-2")) == 1
    check_repo.close()

    # Check checkpoints: thread-agent-1 gone, thread-agent-2 intact
    with sqlite3.connect(str(cp_path)) as cp_conn:
        c1 = cp_conn.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id='thread-agent-1'").fetchone()[0]
        c2 = cp_conn.execute("SELECT COUNT(*) FROM checkpoints WHERE thread_id='thread-agent-2'").fetchone()[0]
        assert c1 == 0
        assert c2 == 1


def test_purge_aborts_when_workflow_dependencies_cannot_be_safely_removed(tmp_path):
    platform, external_one, external_two = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")
    _connect_agent(platform, external_two, "agent_two")

    # Workflow where agent_two depends on agent_one
    dependent_wf = {
        "id": "pipeline_two_stage",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "first",
                "type": "agent",
                "agent_id": "agent_one",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            },
            {
                "id": "second",
                "type": "agent",
                "agent_id": "agent_two",
                "input_mappings": {
                    "original_text": {"path": "workflow_input.text"},
                    "summary": {"path": "node_outputs.first.summary"},
                },
            },
        ],
        "edges": [{"from": "first", "to": "second"}],
        "max_steps": 100,
    }
    wf_file = platform / "workflow_definitions" / "pipeline_two_stage.yaml"
    wf_file.write_text(yaml.safe_dump(dependent_wf, sort_keys=False), encoding="utf-8")

    stderr = io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_one", "--purge", "--yes"],
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == 2
    err_text = stderr.getvalue()
    assert "cannot safely purge agent 'agent_one'" in err_text
    assert "pipeline_two_stage" in err_text
    assert "node_outputs.first.summary" in err_text
    assert "Resolve workflow dependencies before purging" in err_text

    # Nothing was deleted
    assert (platform / "plugins" / "manifests" / "agent_one.yaml").exists()
    assert (platform / "plugins" / "examples" / "connected_agent_one" / "adapter.py").exists()
    assert wf_file.exists()


def test_purge_aborts_when_workflow_only_contains_the_purged_agent(tmp_path):
    platform, external_one, _ = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")

    single_wf = {
        "id": "single_step",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "only_step",
                "type": "agent",
                "agent_id": "agent_one",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            }
        ],
        "edges": [],
        "max_steps": 100,
    }
    wf_file = platform / "workflow_definitions" / "single_step.yaml"
    wf_file.write_text(yaml.safe_dump(single_wf, sort_keys=False), encoding="utf-8")

    stderr = io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_one", "--purge", "--yes"],
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == 2
    err_text = stderr.getvalue()
    assert "cannot safely purge agent 'agent_one'" in err_text
    assert "empty workflow" in err_text
    assert (platform / "plugins" / "manifests" / "agent_one.yaml").exists()


def test_purge_safely_updates_workflow_when_node_removal_leaves_valid_definition(tmp_path):
    platform, external_one, external_two = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")
    _connect_agent(platform, external_two, "agent_two")

    db_path = platform / "agent_platform.db"
    repo = ExecutionRepository(str(db_path))

    # Workflow where agent_two is a leaf node and agent_one does NOT depend on agent_two
    wf_data = {
        "id": "removable_leaf_flow",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "main_node",
                "type": "agent",
                "agent_id": "agent_one",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            },
            {
                "id": "extra_node",
                "type": "agent",
                "agent_id": "agent_two",
                "input_mappings": {
                    "original_text": {"path": "workflow_input.text"},
                    "summary": {"literal": "constant"},
                },
            },
        ],
        "edges": [{"from": "main_node", "to": "extra_node"}],
        "max_steps": 100,
    }
    wf_file = platform / "workflow_definitions" / "removable_leaf_flow.yaml"
    wf_file.write_text(yaml.safe_dump(wf_data, sort_keys=False), encoding="utf-8")
    repo.save_workflow(wf_data)
    repo.close()

    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_two", "--purge", "--yes"],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0, stderr.getvalue()
    result = json.loads(stdout.getvalue())

    assert result["status"] == "purged"
    assert "removable_leaf_flow" in result["deleted"]["workflows_updated"]

    # Workflow definition on disk updated
    updated_disk_wf = yaml.safe_load(wf_file.read_text(encoding="utf-8"))
    assert updated_disk_wf["version"] == "1.0.1"
    assert len(updated_disk_wf["nodes"]) == 1
    assert updated_disk_wf["nodes"][0]["id"] == "main_node"
    assert updated_disk_wf["edges"] == []

    # Database updated
    check_repo = ExecutionRepository(str(db_path))
    db_wf = check_repo.get_workflow("removable_leaf_flow")
    assert db_wf["version"] == "1.0.1"
    assert len(db_wf["nodes"]) == 1
    check_repo.close()


def test_unknown_agent_and_repeated_disconnects(tmp_path):
    platform, external_one, _ = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")

    # Unknown agent
    stderr = io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "unknown_agent"],
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == 2
    assert "connected agent is not registered: unknown_agent" in stderr.getvalue()

    # Disconnect agent_one
    assert main(["--project-root", str(platform), "agents", "disconnect", "agent_one"], stdout=io.StringIO(), stderr=io.StringIO()) == 0

    # Repeated disconnect predictably errors
    stderr_repeated = io.StringIO()
    code_repeated = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_one"],
        stdout=io.StringIO(),
        stderr=stderr_repeated,
    )
    assert code_repeated == 2
    assert "connected agent is not registered: agent_one" in stderr_repeated.getvalue()

    # Repeated purge predictably errors
    stderr_purge_repeated = io.StringIO()
    code_purge_repeated = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_one", "--purge", "--yes"],
        stdout=io.StringIO(),
        stderr=stderr_purge_repeated,
    )
    assert code_purge_repeated == 2
    assert "connected agent is not registered: agent_one" in stderr_purge_repeated.getvalue()


def test_purge_rollback_on_database_failure(tmp_path, monkeypatch):
    platform, external_one, _ = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")

    db_path = platform / "agent_platform.db"
    repo = ExecutionRepository(str(db_path))
    repo.start_run("run-1", None, {"agent_id": "agent_one"})
    repo.close()

    def failing_purge(*args, **kwargs):
        raise sqlite3.OperationalError("simulated database failure")

    monkeypatch.setattr(ExecutionRepository, "purge_agent_records", failing_purge)

    stderr = io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_one", "--purge", "--yes"],
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert code == 2
    assert "purge failed and was rolled back" in stderr.getvalue()

    # Files must still exist due to rollback
    assert (platform / "plugins" / "manifests" / "agent_one.yaml").exists()
    assert (platform / "plugins" / "examples" / "connected_agent_one" / "adapter.py").exists()


def test_disconnect_marks_nodes_across_multiple_workflows_and_leaves_unrelated_unchanged(tmp_path):
    platform, external_one, external_two = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")
    _connect_agent(platform, external_two, "agent_two")

    db_path = platform / "agent_platform.db"
    repo = ExecutionRepository(str(db_path))

    wf_one = {
        "id": "workflow_one",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "step_analyze",
                "type": "agent",
                "agent_id": "agent_one",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            },
            {
                "id": "step_validate",
                "type": "agent",
                "agent_id": "agent_two",
                "input_mappings": {
                    "original_text": {"path": "workflow_input.text"},
                    "summary": {"path": "node_outputs.step_analyze.summary"},
                },
            },
        ],
        "edges": [{"from": "step_analyze", "to": "step_validate"}],
        "max_steps": 100,
    }
    wf_two = {
        "id": "workflow_two",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "primary_analyzer",
                "type": "agent",
                "agent_id": "agent_one",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            }
        ],
        "edges": [],
        "max_steps": 100,
    }
    wf_unrelated = {
        "id": "unrelated_workflow",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "only_two",
                "type": "agent",
                "agent_id": "agent_two",
                "input_mappings": {
                    "original_text": {"path": "workflow_input.original_text"},
                    "summary": {"path": "workflow_input.summary"},
                },
            }
        ],
        "edges": [],
        "max_steps": 100,
    }

    for wf in (wf_one, wf_two, wf_unrelated):
        path = platform / "workflow_definitions" / f"{wf['id']}.yaml"
        path.write_text(yaml.safe_dump(wf, sort_keys=False), encoding="utf-8")
        repo.save_workflow(wf)
    repo.close()

    unrelated_path = platform / "workflow_definitions" / "unrelated_workflow.yaml"
    unrelated_bytes_before = unrelated_path.read_bytes()

    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_one"],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0, stderr.getvalue()
    result = json.loads(stdout.getvalue())

    assert result["workflows_updated"] == {
        "workflow_one": ["step_analyze"],
        "workflow_two": ["primary_analyzer"],
    }
    assert "unrelated_workflow" not in result["workflows_updated"]
    assert "unrelated_workflow" not in result["retained"]["referenced_by_workflows"]

    # Unrelated workflow is byte-for-byte unchanged on disk and in DB
    assert unrelated_path.read_bytes() == unrelated_bytes_before

    disk_wf_one = yaml.safe_load((platform / "workflow_definitions" / "workflow_one.yaml").read_text(encoding="utf-8"))
    assert len(disk_wf_one["nodes"]) == 2
    assert disk_wf_one["nodes"][0]["id"] == "step_analyze"
    assert disk_wf_one["nodes"][0]["status"] == "disconnected"
    assert disk_wf_one["nodes"][0]["input_mappings"] == {"text": {"path": "workflow_input.text"}}
    assert disk_wf_one["nodes"][1]["id"] == "step_validate"
    assert disk_wf_one["nodes"][1].get("status", "available") == "available"
    assert disk_wf_one["nodes"][1]["input_mappings"] == {
        "original_text": {"path": "workflow_input.text"},
        "summary": {"path": "node_outputs.step_analyze.summary"},
    }
    assert disk_wf_one["edges"] == [{"from": "step_analyze", "to": "step_validate"}]

    disk_wf_two = yaml.safe_load((platform / "workflow_definitions" / "workflow_two.yaml").read_text(encoding="utf-8"))
    assert disk_wf_two["nodes"][0]["id"] == "primary_analyzer"
    assert disk_wf_two["nodes"][0]["status"] == "disconnected"

    check_repo = ExecutionRepository(str(db_path))
    assert check_repo.get_workflow("workflow_one")["nodes"][0]["status"] == "disconnected"
    assert check_repo.get_workflow("workflow_two")["nodes"][0]["status"] == "disconnected"
    assert "status" not in check_repo.get_workflow("unrelated_workflow")["nodes"][0]
    check_repo.close()


def test_disconnected_workflow_prevents_execution_and_reports_exact_unavailable_nodes(tmp_path):
    from fastapi.testclient import TestClient
    from app.api.app import create_app
    from app.registry.external_connector import project_plugin_namespace

    platform, external_one, external_two = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")
    _connect_agent(platform, external_two, "agent_two")

    db_path = platform / "agent_platform.db"
    repo = ExecutionRepository(str(db_path))
    pipeline = {
        "id": "two_stage_pipeline",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "first_stage",
                "type": "agent",
                "agent_id": "agent_one",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            },
            {
                "id": "second_stage",
                "type": "agent",
                "agent_id": "agent_two",
                "input_mappings": {
                    "original_text": {"path": "workflow_input.text"},
                    "summary": {"path": "node_outputs.first_stage.summary"},
                },
            },
        ],
        "edges": [{"from": "first_stage", "to": "second_stage"}],
        "max_steps": 100,
    }
    wf_path = platform / "workflow_definitions" / "two_stage_pipeline.yaml"
    wf_path.write_text(yaml.safe_dump(pipeline, sort_keys=False), encoding="utf-8")
    repo.save_workflow(pipeline)

    input_file = tmp_path / "run_input.json"
    input_file.write_text(json.dumps({"text": "Hello from test"}), encoding="utf-8")

    # Disconnect agent_one
    assert main(["--project-root", str(platform), "agents", "disconnect", "agent_one"], stdout=io.StringIO(), stderr=io.StringIO()) == 0

    # Offline workflow validate reports exact unavailable node
    val_stderr = io.StringIO()
    val_code = main(
        ["--project-root", str(platform), "workflows", "validate", str(wf_path)],
        stdout=io.StringIO(),
        stderr=val_stderr,
    )
    assert val_code == 2
    assert "first_stage" in val_stderr.getvalue()
    assert "agent_one" in val_stderr.getvalue()
    assert "second_stage" not in val_stderr.getvalue()

    # Disconnect agent_two as well so both nodes are unavailable
    assert main(["--project-root", str(platform), "agents", "disconnect", "agent_two"], stdout=io.StringIO(), stderr=io.StringIO()) == 0

    with project_plugin_namespace(platform):
        with TestClient(create_app(repo, manifests_dir=platform / "plugins" / "manifests")) as client:
            # CLI workflows show reflects disconnected status on both nodes
            show_stdout = io.StringIO()
            assert main(["workflows", "show", "two_stage_pipeline"], client=client, stdout=show_stdout, stderr=io.StringIO()) == 0
            shown_wf = json.loads(show_stdout.getvalue())
            assert [n["status"] for n in shown_wf["nodes"]] == ["disconnected", "disconnected"]

            # CLI runs start with --input file is blocked and reports both unavailable node IDs
            run_stderr = io.StringIO()
            run_code = main(
                ["runs", "start", "--workflow", "two_stage_pipeline", "--input", str(input_file)],
                client=client,
                stdout=io.StringIO(),
                stderr=run_stderr,
            )
            assert run_code == 2
            err_msg = run_stderr.getvalue()
            assert "first_stage" in err_msg
            assert "second_stage" in err_msg
            assert "unavailable" in err_msg

            # CLI runs start with --interactive is blocked before prompting and reports both unavailable node IDs
            inter_stderr = io.StringIO()
            inter_code = main(
                ["runs", "start", "--workflow", "two_stage_pipeline", "--interactive"],
                client=client,
                stdout=io.StringIO(),
                stderr=inter_stderr,
                input_fn=lambda prompt: (_ for _ in ()).throw(AssertionError("should not prompt for input when nodes are disconnected")),
            )
            assert inter_code == 2
            assert "first_stage" in inter_stderr.getvalue()
            assert "second_stage" in inter_stderr.getvalue()


def test_reconnect_restores_workflow_nodes_and_reenables_execution(tmp_path):
    from fastapi.testclient import TestClient
    from app.api.app import create_app
    from app.registry.external_connector import project_plugin_namespace

    platform, external_one, external_two = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")
    _connect_agent(platform, external_two, "agent_two")

    db_path = platform / "agent_platform.db"
    repo = ExecutionRepository(str(db_path))
    pipeline = {
        "id": "reconnect_pipeline",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "node_one",
                "type": "agent",
                "agent_id": "agent_one",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            },
            {
                "id": "node_two",
                "type": "agent",
                "agent_id": "agent_two",
                "input_mappings": {
                    "original_text": {"path": "workflow_input.text"},
                    "summary": {"path": "node_outputs.node_one.summary"},
                },
            },
        ],
        "edges": [{"from": "node_one", "to": "node_two"}],
        "max_steps": 100,
    }
    wf_path = platform / "workflow_definitions" / "reconnect_pipeline.yaml"
    wf_path.write_text(yaml.safe_dump(pipeline, sort_keys=False), encoding="utf-8")
    repo.save_workflow(pipeline)

    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps({"text": "Reconnect test message"}), encoding="utf-8")

    # Disconnect both agents
    assert main(["--project-root", str(platform), "agents", "disconnect", "agent_one"], stdout=io.StringIO(), stderr=io.StringIO()) == 0
    assert main(["--project-root", str(platform), "agents", "disconnect", "agent_two"], stdout=io.StringIO(), stderr=io.StringIO()) == 0

    # Reconnect only agent_one first
    reconnect_one_out = io.StringIO()
    assert main(
        [
            "--project-root", str(platform),
            "agents", "connect",
            "--path", str(external_one),
            "--id", "agent_one",
            "--test-input", str(external_one / "input.json"),
            "--trust",
        ],
        stdout=reconnect_one_out,
        stderr=io.StringIO(),
    ) == 0
    reconnect_one_data = json.loads(reconnect_one_out.getvalue())
    assert reconnect_one_data["restored_workflows"] == {"reconnect_pipeline": ["node_one"]}

    # Verify node_one is available, but node_two is still disconnected
    partial_wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    assert partial_wf["nodes"][0]["status"] == "available"
    assert partial_wf["nodes"][1]["status"] == "disconnected"

    # Validation still fails, reporting ONLY node_two as unavailable
    val_stderr = io.StringIO()
    assert main(["--project-root", str(platform), "workflows", "validate", str(wf_path)], stdout=io.StringIO(), stderr=val_stderr) == 2
    assert "node_two" in val_stderr.getvalue()
    assert "node_one" not in val_stderr.getvalue()

    # Now reconnect agent_two with the same ID
    reconnect_two_out = io.StringIO()
    assert main(
        [
            "--project-root", str(platform),
            "agents", "connect",
            "--path", str(external_two),
            "--id", "agent_two",
            "--test-input", str(external_two / "input.json"),
            "--trust",
        ],
        stdout=reconnect_two_out,
        stderr=io.StringIO(),
    ) == 0
    reconnect_two_data = json.loads(reconnect_two_out.getvalue())
    assert reconnect_two_data["restored_workflows"] == {"reconnect_pipeline": ["node_two"]}

    # Both nodes are now available on disk and in DB
    restored_wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    assert [n["status"] for n in restored_wf["nodes"]] == ["available", "available"]
    assert [n["status"] for n in repo.get_workflow("reconnect_pipeline")["nodes"]] == ["available", "available"]

    # Offline validation succeeds
    assert main(["--project-root", str(platform), "workflows", "validate", str(wf_path)], stdout=io.StringIO(), stderr=io.StringIO()) == 0

    # End-to-end execution succeeds and produces both agents' outputs
    with project_plugin_namespace(platform):
        with TestClient(create_app(repo, manifests_dir=platform / "plugins" / "manifests")) as client:
            run_out = io.StringIO()
            run_err = io.StringIO()
            code = main(
                ["runs", "start", "--workflow", "reconnect_pipeline", "--input", str(input_file)],
                client=client,
                stdout=run_out,
                stderr=run_err,
            )
            assert code == 0, run_err.getvalue()
            run_data = json.loads(run_out.getvalue())
            assert run_data["status"] == "succeeded"
            assert run_data["agent_outputs"]["node_one"] == {"summary": "Reconnect test message", "count": 3}
            assert run_data["agent_outputs"]["node_two"] == {"valid": True, "original": "Reconnect test message"}
            assert run_data["final_output"] == {"valid": True, "original": "Reconnect test message"}


def test_partial_execution_runs_available_agent_when_quality_checker_is_disconnected(tmp_path):
    from fastapi.testclient import TestClient
    from app.api.app import create_app
    from app.registry.external_connector import project_plugin_namespace

    platform = tmp_path / "platform"
    (platform / "plugins" / "manifests").mkdir(parents=True)
    (platform / "plugins" / "examples").mkdir(parents=True)
    (platform / "plugins" / "__init__.py").write_text('"""test plugins"""\n', encoding="utf-8")
    (platform / "plugins" / "examples" / "__init__.py").write_text('"""test examples"""\n', encoding="utf-8")
    (platform / "workflow_definitions").mkdir(parents=True)

    ext_analysis = tmp_path / "ext_analysis"
    ext_analysis.mkdir()
    (ext_analysis / "agent.py").write_text(
        "from pathlib import Path\n"
        "class TextAnalysisAgent:\n"
        "    def run(self, payload):\n"
        "        count_file = Path(__file__).with_name('calls.txt')\n"
        "        c = int(count_file.read_text()) if count_file.exists() else 0\n"
        "        count_file.write_text(str(c + 1))\n"
        "        text = payload.get('text', '')\n"
        "        words = text.split()\n"
        "        return {\n"
        "            'summary': text,\n"
        "            'word_count': len(words),\n"
        "            'character_count': len(text),\n"
        "            'most_frequent_words': [{'word': w.lower(), 'count': 1} for w in words[:2]],\n"
        "            'status': 'success',\n"
        "        }\n",
        encoding="utf-8",
    )
    (ext_analysis / "input.json").write_text(json.dumps({"text": "Initial verification text"}), encoding="utf-8")

    ext_checker = tmp_path / "ext_checker"
    ext_checker.mkdir()
    (ext_checker / "agent.py").write_text(
        "from pathlib import Path\n"
        "class QualityCheckerAgent:\n"
        "    def run(self, payload):\n"
        "        count_file = Path(__file__).with_name('calls.txt')\n"
        "        c = int(count_file.read_text()) if count_file.exists() else 0\n"
        "        count_file.write_text(str(c + 1))\n"
        "        return {'overall_valid': True, 'status': 'success', 'checked_summary': payload.get('summary')}\n",
        encoding="utf-8",
    )
    (ext_checker / "input.json").write_text(
        json.dumps({
            "original_text": "Initial verification text",
            "summary": "Initial verification text",
            "word_count": 3,
            "character_count": 25,
            "most_frequent_words": [{"word": "initial", "count": 1}],
            "analysis_status": "success",
        }),
        encoding="utf-8",
    )

    _connect_agent(platform, ext_analysis, "external_text_analysis")
    _connect_agent(platform, ext_checker, "external_text_analysis_quality_checker")

    db_path = platform / "agent_platform.db"
    repo = ExecutionRepository(str(db_path))

    wf_def = {
        "id": "text_analysis_validation",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "external_text_analysis",
                "type": "agent",
                "agent_id": "external_text_analysis",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            },
            {
                "id": "external_text_analysis_quality_checker",
                "type": "agent",
                "agent_id": "external_text_analysis_quality_checker",
                "input_mappings": {
                    "original_text": {"path": "workflow_input.text"},
                    "summary": {"path": "node_outputs.external_text_analysis.summary"},
                    "word_count": {"path": "node_outputs.external_text_analysis.word_count"},
                    "character_count": {"path": "node_outputs.external_text_analysis.character_count"},
                    "most_frequent_words": {"path": "node_outputs.external_text_analysis.most_frequent_words"},
                    "analysis_status": {"path": "node_outputs.external_text_analysis.status"},
                },
            },
        ],
        "edges": [{"from": "external_text_analysis", "to": "external_text_analysis_quality_checker"}],
        "max_steps": 100,
    }
    unrelated_wf = {
        "id": "standalone_text_analysis",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "only_analysis",
                "type": "agent",
                "agent_id": "external_text_analysis",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            }
        ],
        "edges": [],
        "max_steps": 100,
    }
    wf_file = platform / "workflow_definitions" / "text_analysis_validation.yaml"
    wf_file.write_text(yaml.safe_dump(wf_def, sort_keys=False), encoding="utf-8")
    unrelated_file = platform / "workflow_definitions" / "standalone_text_analysis.yaml"
    unrelated_file.write_text(yaml.safe_dump(unrelated_wf, sort_keys=False), encoding="utf-8")
    unrelated_bytes_before = unrelated_file.read_bytes()

    repo.save_workflow(wf_def)
    repo.save_workflow(unrelated_wf)

    with project_plugin_namespace(platform):
        with TestClient(create_app(repo, manifests_dir=platform / "plugins" / "manifests")) as client:
            # 1. When both agents are available, the complete workflow succeeds.
            full_out = io.StringIO()
            full_err = io.StringIO()
            full_code = main(
                ["runs", "start", "--workflow", "text_analysis_validation", "--interactive"],
                client=client,
                stdout=full_out,
                stderr=full_err,
                input_fn=lambda prompt: "Complete workflow sample text",
            )
            assert full_code == 0, full_err.getvalue()
            full_run = json.loads(full_out.getvalue())
            assert full_run["status"] == "succeeded"
            assert "external_text_analysis" in full_run["agent_outputs"]
            assert "external_text_analysis_quality_checker" in full_run["agent_outputs"]
            assert full_run["final_output"]["overall_valid"] is True
            historical_run_id = full_run["run_id"]

            # Disconnect Quality Checker
            assert main(
                ["--project-root", str(platform), "agents", "disconnect", "external_text_analysis_quality_checker"],
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            ) == 0

            analysis_calls_before = int((ext_analysis / "calls.txt").read_text())
            checker_calls_before = int((ext_checker / "calls.txt").read_text())

            # 2. Normal command (default automatic partial execution, without --allow-partial)
            # automatically executes Text Analysis, skips Quality Checker, and returns partially_succeeded.
            partial_out, partial_err = io.StringIO(), io.StringIO()
            partial_code = main(
                [
                    "runs", "start",
                    "--workflow", "text_analysis_validation",
                    "--interactive",
                ],
                client=client,
                stdout=partial_out,
                stderr=partial_err,
                input_fn=lambda prompt: "Partial execution sample text",
            )
            assert partial_code == 0, partial_err.getvalue()
            partial_run = json.loads(partial_out.getvalue())

            # Status is explicitly partially_succeeded, NOT succeeded
            assert partial_run["status"] == "partially_succeeded"
            assert partial_run["status"] != "succeeded"

            # Text Analysis executed once and its output is preserved
            assert int((ext_analysis / "calls.txt").read_text()) == analysis_calls_before + 1
            assert "external_text_analysis" in partial_run["agent_outputs"]
            analysis_output = partial_run["agent_outputs"]["external_text_analysis"]
            assert analysis_output["summary"] == "Partial execution sample text"
            assert analysis_output["word_count"] == 4
            assert analysis_output["status"] == "success"
            assert partial_run["final_output"] == analysis_output

            # Quality Checker was NOT executed
            assert int((ext_checker / "calls.txt").read_text()) == checker_calls_before
            assert "external_text_analysis_quality_checker" not in partial_run["agent_outputs"]

            # Blocked/skipped reporting and clear message that quality validation did not run
            assert partial_run["blocked_by_node"] == "external_text_analysis_quality_checker"
            assert len(partial_run["blocked_nodes"]) == 1
            assert partial_run["blocked_nodes"][0]["node_id"] == "external_text_analysis_quality_checker"
            assert "disconnected" in partial_run["blocked_nodes"][0]["reason"]
            assert len(partial_run["skipped_nodes"]) == 1
            assert partial_run["skipped_nodes"][0]["node_id"] == "external_text_analysis_quality_checker"
            assert "Quality validation did not run" in partial_run["message"]

            # Verify runs show and runs events record the partial execution accurately
            partial_run_id = partial_run["run_id"]
            show_out = io.StringIO()
            assert main(["runs", "show", partial_run_id], client=client, stdout=show_out, stderr=io.StringIO()) == 0
            shown = json.loads(show_out.getvalue())
            assert shown["status"] == "partially_succeeded"
            assert shown["agent_outputs"] == {"external_text_analysis": analysis_output}
            assert shown["blocked_by_node"] == "external_text_analysis_quality_checker"
            assert "Quality validation did not run" in shown["message"]

            events_out = io.StringIO()
            assert main(["runs", "events", partial_run_id], client=client, stdout=events_out, stderr=io.StringIO()) == 0
            events_list = json.loads(events_out.getvalue())
            assert [(e["node_id"], e["status"]) for e in events_list] == [
                ("external_text_analysis", "succeeded"),
                ("external_text_analysis_quality_checker", "blocked"),
            ]
            assert "disconnected" in events_list[1]["reason"]

            # 3. Strict mode (--strict) rejects the entire workflow before any agent runs.
            analysis_calls_before_strict = int((ext_analysis / "calls.txt").read_text())
            strict_out, strict_err = io.StringIO(), io.StringIO()
            strict_code = main(
                ["runs", "start", "--workflow", "text_analysis_validation", "--interactive", "--strict"],
                client=client,
                stdout=strict_out,
                stderr=strict_err,
                input_fn=lambda prompt: (_ for _ in ()).throw(AssertionError("should not prompt in strict mode")),
            )
            assert strict_code == 2
            assert "external_text_analysis_quality_checker" in strict_err.getvalue()
            assert "unavailable" in strict_err.getvalue()
            assert int((ext_analysis / "calls.txt").read_text()) == analysis_calls_before_strict
            assert int((ext_checker / "calls.txt").read_text()) == checker_calls_before

            input_file = tmp_path / "strict_input.json"
            input_file.write_text(json.dumps({"text": "File input strict mode"}), encoding="utf-8")
            strict_file_err = io.StringIO()
            assert main(
                ["runs", "start", "--workflow", "text_analysis_validation", "--input", str(input_file), "--strict"],
                client=client,
                stdout=io.StringIO(),
                stderr=strict_file_err,
            ) == 2
            assert "external_text_analysis_quality_checker" in strict_file_err.getvalue()
            assert int((ext_analysis / "calls.txt").read_text()) == analysis_calls_before_strict
            assert int((ext_checker / "calls.txt").read_text()) == checker_calls_before

            # 4. Historical data and unrelated workflows remain unchanged.
            historical_record = repo.get_run(historical_run_id)
            assert historical_record is not None
            assert historical_record["status"] == "succeeded"
            assert "external_text_analysis_quality_checker" in historical_record["agent_outputs"]
            assert unrelated_file.read_bytes() == unrelated_bytes_before


def test_partial_execution_does_not_execute_downstream_nodes_of_disconnected_node(tmp_path):
    from fastapi.testclient import TestClient
    from app.api.app import create_app
    from app.registry.external_connector import project_plugin_namespace

    platform, external_one, external_two = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")
    _connect_agent(platform, external_two, "agent_two")

    # Add a third agent that depends on agent_two
    external_three = tmp_path / "external_agent_three"
    external_three.mkdir()
    (external_three / "agent.py").write_text(
        "from pathlib import Path\n"
        "class AgentThree:\n"
        "    def run(self, payload):\n"
        "        Path(__file__).with_name('ran.marker').write_text('ran')\n"
        "        return {'final_report': str(payload.get('valid'))}\n",
        encoding="utf-8",
    )
    (external_three / "input.json").write_text(json.dumps({"valid": True}), encoding="utf-8")
    _connect_agent(platform, external_three, "agent_three")

    db_path = platform / "agent_platform.db"
    repo = ExecutionRepository(str(db_path))

    three_stage = {
        "id": "three_stage_flow",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "stage_one",
                "type": "agent",
                "agent_id": "agent_one",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            },
            {
                "id": "stage_two",
                "type": "agent",
                "agent_id": "agent_two",
                "input_mappings": {
                    "original_text": {"path": "workflow_input.text"},
                    "summary": {"path": "node_outputs.stage_one.summary"},
                },
            },
            {
                "id": "stage_three",
                "type": "agent",
                "agent_id": "agent_three",
                "input_mappings": {"valid": {"path": "node_outputs.stage_two.valid"}},
            },
        ],
        "edges": [
            {"from": "stage_one", "to": "stage_two"},
            {"from": "stage_two", "to": "stage_three"},
        ],
        "max_steps": 100,
    }
    wf_file = platform / "workflow_definitions" / "three_stage_flow.yaml"
    wf_file.write_text(yaml.safe_dump(three_stage, sort_keys=False), encoding="utf-8")
    repo.save_workflow(three_stage)

    # Remove ran marker from connect verification
    (external_three / "ran.marker").unlink(missing_ok=True)

    # Disconnect only the middle agent (agent_two); agent_three remains connected
    assert main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_two"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0

    input_file = tmp_path / "three_stage_input.json"
    input_file.write_text(json.dumps({"text": "Three stage partial test"}), encoding="utf-8")

    with project_plugin_namespace(platform):
        with TestClient(create_app(repo, manifests_dir=platform / "plugins" / "manifests")) as client:
            # Default run (without --allow-partial) executes stage_one, blocks stage_two, and skips stage_three
            out, err = io.StringIO(), io.StringIO()
            code = main(
                ["runs", "start", "--workflow", "three_stage_flow", "--input", str(input_file)],
                client=client,
                stdout=out,
                stderr=err,
            )
            assert code == 0, err.getvalue()
            res = json.loads(out.getvalue())

            assert res["status"] == "partially_succeeded"
            assert list(res["agent_outputs"].keys()) == ["stage_one"]
            assert res["agent_outputs"]["stage_one"] == {"summary": "Three stage partial test", "count": 4}
            assert not (external_three / "ran.marker").exists()

            assert res["blocked_by_node"] == "stage_two"
            assert [b["node_id"] for b in res["blocked_nodes"]] == ["stage_two"]
            assert [s["node_id"] for s in res["skipped_nodes"]] == ["stage_two", "stage_three"]
            assert "stage_two" in res["skipped_nodes"][1]["reason"]


def test_partial_execution_continues_independent_branches_and_handles_disabled_agents(tmp_path):
    from fastapi.testclient import TestClient
    from app.api.app import create_app
    from app.registry.external_connector import project_plugin_namespace

    platform, external_one, external_two = _setup_isolated_platform(tmp_path)
    _connect_agent(platform, external_one, "agent_one")
    _connect_agent(platform, external_two, "agent_two")

    external_three = tmp_path / "external_agent_three"
    external_three.mkdir()
    (external_three / "agent.py").write_text(
        "class IndependentBranchAgent:\n"
        "    def run(self, payload):\n"
        "        return {'branch_summary': payload.get('summary', '').upper(), 'branch_ok': True}\n",
        encoding="utf-8",
    )
    (external_three / "input.json").write_text(json.dumps({"summary": "demo"}), encoding="utf-8")
    _connect_agent(platform, external_three, "agent_three")

    db_path = platform / "agent_platform.db"
    repo = ExecutionRepository(str(db_path))

    # DAG: root -> disconnected_branch -> dependent_leaf
    #      root -> independent_branch
    branching_wf = {
        "id": "branching_flow",
        "version": "1.0.0",
        "nodes": [
            {
                "id": "root_node",
                "type": "agent",
                "agent_id": "agent_one",
                "input_mappings": {"text": {"path": "workflow_input.text"}},
            },
            {
                "id": "disconnected_branch",
                "type": "agent",
                "agent_id": "agent_two",
                "input_mappings": {
                    "original_text": {"path": "workflow_input.text"},
                    "summary": {"path": "node_outputs.root_node.summary"},
                },
            },
            {
                "id": "dependent_leaf",
                "type": "agent",
                "agent_id": "agent_three",
                "input_mappings": {"summary": {"path": "node_outputs.disconnected_branch.original"}},
            },
            {
                "id": "independent_branch",
                "type": "agent",
                "agent_id": "agent_three",
                "input_mappings": {"summary": {"path": "node_outputs.root_node.summary"}},
            },
        ],
        "edges": [
            {"from": "root_node", "to": "disconnected_branch"},
            {"from": "disconnected_branch", "to": "dependent_leaf"},
            {"from": "root_node", "to": "independent_branch"},
        ],
        "max_steps": 100,
    }
    wf_file = platform / "workflow_definitions" / "branching_flow.yaml"
    wf_file.write_text(yaml.safe_dump(branching_wf, sort_keys=False), encoding="utf-8")
    repo.save_workflow(branching_wf)

    # Disconnect agent_two so disconnected_branch is unavailable
    assert main(
        ["--project-root", str(platform), "agents", "disconnect", "agent_two"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0

    with project_plugin_namespace(platform):
        with TestClient(create_app(repo, manifests_dir=platform / "plugins" / "manifests")) as client:
            out, err = io.StringIO(), io.StringIO()
            code = main(
                ["runs", "start", "--workflow", "branching_flow", "--interactive"],
                client=client,
                stdout=out,
                stderr=err,
                input_fn=lambda prompt: "Branch execution text",
            )
            assert code == 0, err.getvalue()
            res = json.loads(out.getvalue())

            assert res["status"] == "partially_succeeded"
            # root_node and independent_branch both executed
            assert "root_node" in res["agent_outputs"]
            assert "independent_branch" in res["agent_outputs"]
            assert res["agent_outputs"]["root_node"] == {"summary": "Branch execution text", "count": 3}
            assert res["agent_outputs"]["independent_branch"] == {
                "branch_summary": "BRANCH EXECUTION TEXT",
                "branch_ok": True,
            }
            # disconnected_branch and dependent_leaf did not execute
            assert "disconnected_branch" not in res["agent_outputs"]
            assert "dependent_leaf" not in res["agent_outputs"]
            assert [b["node_id"] for b in res["blocked_nodes"]] == ["disconnected_branch"]
            assert {s["node_id"] for s in res["skipped_nodes"]} == {"disconnected_branch", "dependent_leaf"}
            assert "'root_node'" in res["message"]
            assert "'independent_branch'" in res["message"]



