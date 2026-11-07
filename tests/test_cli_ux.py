"""Tests for CLI developer experience, sensible defaults, interactive prompts, aliases, and --help output."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.cli import main
from app.registry.external_connector import project_plugin_namespace
from app.storage.repository import ExecutionRepository
from tests.test_workflow_compose import (
    QUALITY_INPUT,
    QUALITY_SOURCE,
    TEXT_ANALYSIS_SOURCE,
    TOKENS,
    _externals,
    _write_platform,
    answers,
    cli,
)


@pytest.fixture
def ux_env(tmp_path: Path):
    platform = _write_platform(tmp_path)
    external_a, external_b = _externals(tmp_path)
    with project_plugin_namespace(platform):
        for external in (external_a, external_b):
            code, _, stderr = cli(platform, ["agents", "connect", str(external), "--trust"])
            assert code == 0, stderr
        repository = ExecutionRepository(str(tmp_path / "ux.db"))
        app = create_app(
            repository,
            manifests_dir=platform / "plugins" / "manifests",
            auth_mode="required",
            auth_tokens={
                **TOKENS,
                "readonly": {"token": "readonly-token", "permissions": ["workflow.read", "metadata.read"]},
            },
        )
        with TestClient(app) as client:
            yield SimpleNamespace(
                platform=platform,
                external_a=external_a,
                external_b=external_b,
                client=client,
                repository=repository,
                tmp_path=tmp_path,
                run=lambda args, **kwargs: cli(
                    platform,
                    args,
                    client=client,
                    token=kwargs.pop("token", "alice-token"),
                    **kwargs,
                ),
            )


def test_workflows_create_assigns_default_version_and_infers_mappings(ux_env):
    # Create a single-agent workflow without specifying --version; version defaults to 1.0.0
    code, stdout, stderr = ux_env.run([
        "workflows", "create", "single_flow", "--agents", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["id"] == "single_flow"
    assert report["version"] == "1.0.0"
    assert report["nodes"] == ["external_text_analysis"]
    assert report["registered"] == {"id": "single_flow", "version": "1.0.0"}

    wf_file = ux_env.platform / "workflow_definitions" / "single_flow.yaml"
    saved = yaml.safe_load(wf_file.read_text(encoding="utf-8"))
    assert saved["version"] == "1.0.0"
    assert saved["nodes"][0]["id"] == "external_text_analysis"
    assert saved["nodes"][0]["input_mappings"] == {"text": {"path": "workflow_input.text"}}

    # Create a multi-agent workflow using positional agent IDs; both nodes' mappings are inferred
    code, stdout, stderr = ux_env.run([
        "workflows", "create", "multi_flow", "external_text_analysis", "external_quality_checker", "--register",
    ])
    assert code == 0, stderr
    multi_report = json.loads(stdout)
    assert multi_report["version"] == "1.0.0"
    assert multi_report["nodes"] == ["external_text_analysis", "external_quality_checker"]

    multi_saved = yaml.safe_load((ux_env.platform / "workflow_definitions" / "multi_flow.yaml").read_text(encoding="utf-8"))
    assert multi_saved["edges"] == [{"from": "external_text_analysis", "to": "external_quality_checker"}]
    assert multi_saved["nodes"][1]["input_mappings"] == {
        "original_text": {"path": "workflow_input.text"},
        "summary": {"path": "node_outputs.external_text_analysis.summary"},
        "word_count": {"path": "node_outputs.external_text_analysis.word_count"},
        "character_count": {"path": "node_outputs.external_text_analysis.character_count"},
        "most_frequent_words": {"path": "node_outputs.external_text_analysis.most_frequent_words"},
        "analysis_status": {"path": "node_outputs.external_text_analysis.status"},
    }

    # Execute the created workflow using positional WORKFLOW_ID and automatic interactive mode
    reader = answers("Defaults make CLI workflows easy")
    code, stdout, stderr = ux_env.run(["runs", "start", "multi_flow"], input_fn=reader)
    assert code == 0, stderr
    run_res = json.loads(stdout)
    assert run_res["status"] == "succeeded"
    assert run_res["agent_outputs"]["external_text_analysis"]["summary"] == "Defaults make CLI workflows easy"
    assert run_res["final_output"]["quality"] == "ok"


def test_workflows_create_supports_version_override_and_interactive_agent_selection(ux_env):
    # Interactive prompt when --agents is omitted:
    # First asks "How would you like to create this workflow?" (1 = Create with agents, 2 = Create empty workflow)
    # Then prompts for agent selection ("2,1" selects external_text_analysis then external_quality_checker)
    reader = answers("1", "external_text_analysis,external_quality_checker")
    code, stdout, stderr = ux_env.run(
        ["workflows", "create", "interactive_flow", "--version", "2.1.0"],
        input_fn=reader,
    )
    assert code == 0, stderr
    assert "How would you like to create this workflow?" in stderr
    assert "1. Create with agents" in stderr
    assert "2. Create empty workflow and add agents later" in stderr
    assert "Available registered agents:" in stderr
    report = json.loads(stdout)
    assert report["version"] == "2.1.0"
    assert report["empty"] is False
    assert report["nodes"] == ["external_text_analysis", "external_quality_checker"]
    assert "How would you like to create this workflow?" in reader.prompts[0]
    assert "Select agent(s)" in reader.prompts[1]


def test_workflows_create_interactive_option_2_creates_empty_draft_without_agent_prompt(ux_env):
    # Option 2: Create empty workflow and add agents later — must NOT prompt for agent selection
    reader = answers("2")
    code, stdout, stderr = ux_env.run(
        ["workflows", "create", "empty_interactive_flow"],
        input_fn=reader,
    )
    assert code == 0, stderr
    assert "How would you like to create this workflow?" in stderr
    assert "1. Create with agents" in stderr
    assert "2. Create empty workflow and add agents later" in stderr
    assert len(reader.prompts) == 1  # No second prompt for agents!

    report = json.loads(stdout)
    assert report["id"] == "empty_interactive_flow"
    assert report["version"] == "1.0.0"
    assert report["empty"] is True
    assert report["status"] == "draft"
    assert report["nodes"] == []
    assert report["edges"] == []

    wf_path = ux_env.platform / "workflow_definitions" / "empty_interactive_flow.yaml"
    assert wf_path.is_file()
    saved = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    assert saved["id"] == "empty_interactive_flow"
    assert saved["version"] == "1.0.0"
    assert saved["nodes"] == []
    assert saved["edges"] == []


def test_empty_workflow_draft_via_flag_and_adding_first_and_second_agents(ux_env):
    # 1. Create empty draft non-interactively with --empty
    code, stdout, stderr = ux_env.run(["workflows", "create", "step_by_step_flow", "--empty"])
    assert code == 0, stderr
    draft = json.loads(stdout)
    assert draft["id"] == "step_by_step_flow"
    assert draft["version"] == "1.0.0"
    assert draft["empty"] is True
    assert draft["nodes"] == []

    # 2. Add the FIRST agent to the empty workflow draft
    code, stdout, stderr = ux_env.run([
        "workflows", "add-agent", "step_by_step_flow", "external_text_analysis",
    ])
    assert code == 0, stderr
    first_add = json.loads(stdout)
    assert first_add["workflow"] == "step_by_step_flow"
    assert first_add["agent_id"] == "external_text_analysis"
    assert first_add["node_id"] == "external_text_analysis"
    assert first_add["after"] is None
    assert first_add["node_added"] is True
    assert first_add["edge_added"] is False
    assert first_add["previous_version"] == "1.0.0"
    assert first_add["version"] == "1.0.1"
    assert first_add["mappings"] == [
        {"field": "text", "path": "workflow_input.text", "origin": "inferred", "type_check": "verified"}
    ]

    # 3. Add the SECOND agent to the workflow
    code, stdout, stderr = ux_env.run([
        "workflows", "add-agent", "step_by_step_flow", "external_quality_checker",
    ])
    assert code == 0, stderr
    second_add = json.loads(stdout)
    assert second_add["agent_id"] == "external_quality_checker"
    assert second_add["after"] == "external_text_analysis"
    assert second_add["node_added"] is True
    assert second_add["edge_added"] is True
    assert second_add["previous_version"] == "1.0.1"
    assert second_add["version"] == "1.0.2"

    # 4. Run the composed workflow end-to-end
    reader = answers("Built from an empty workflow draft")
    code, stdout, stderr = ux_env.run(["runs", "start", "--workflow", "step_by_step_flow", "--interactive"], input_fn=reader)
    assert code == 0, stderr
    run_res = json.loads(stdout)
    assert run_res["status"] == "succeeded"
    assert run_res["agent_outputs"]["external_text_analysis"]["summary"] == "Built from an empty workflow draft"
    assert run_res["agent_outputs"]["external_quality_checker"]["quality"] == "ok"
    assert run_res["final_output"]["quality"] == "ok"


def test_empty_workflows_rejected_during_validation_registration_and_execution(ux_env, tmp_path: Path):
    code, _, stderr = ux_env.run(["workflows", "create", "empty_draft", "--empty"])
    assert code == 0, stderr

    # 1. Validation rejects empty workflow
    code, _, stderr = ux_env.run(["workflows", "validate", "empty_draft"])
    assert code == 2
    assert "no valid nodes" in stderr

    # 2. Registration via CLI rejects empty workflow
    code, _, stderr = ux_env.run(["workflows", "register", "empty_draft"])
    assert code == 2
    assert "no valid nodes" in stderr

    # 3. Registration via API directly rejects empty workflow
    resp = ux_env.client.post(
        "/v1/workflows",
        json={"id": "empty_draft", "version": "1.0.0", "nodes": [], "edges": []},
        headers={"Authorization": "Bearer alice-token"},
    )
    assert resp.status_code == 422
    assert "no valid nodes" in resp.text

    # 4. Execution via CLI (interactive and --input file) rejects empty workflow draft
    code, _, stderr = ux_env.run(
        ["runs", "start", "--workflow", "empty_draft", "--interactive"],
        input_fn=answers("some text"),
    )
    assert code == 2
    assert "no valid nodes" in stderr

    input_file = tmp_path / "run_input.json"
    input_file.write_text(json.dumps({"text": "hello"}), encoding="utf-8")
    code, _, stderr = ux_env.run([
        "runs", "start", "--workflow", "empty_draft", "--input", str(input_file),
    ])
    assert code == 2
    assert "no valid nodes" in stderr

    # 5. Even if an empty workflow is persisted directly in the repository, API and CLI reject execution
    ux_env.repository.save_workflow({"id": "persisted_empty", "version": "1.0.0", "nodes": [], "edges": []})
    api_run = ux_env.client.post(
        "/v1/runs",
        json={"workflow_id": "persisted_empty", "inputs": {"text": "hello"}},
        headers={"Authorization": "Bearer alice-token"},
    )
    assert api_run.status_code == 409
    assert "no valid nodes" in api_run.text

    code, _, stderr = ux_env.run(
        ["runs", "start", "--workflow", "persisted_empty", "--interactive"],
        input_fn=answers("some text"),
    )
    assert code == 2
    assert "no valid nodes" in stderr


def test_workflows_create_non_interactive_without_mode_and_duplicate_id_protection(ux_env):
    # Non-interactive without agents or --empty fails immediately with actionable guidance
    code, _, stderr = ux_env.run(["workflows", "create", "ambiguous_mode_flow"])
    assert code == 2
    assert "non-interactive mode" in stderr
    assert "--empty" in stderr
    assert "--agents" in stderr
    assert not (ux_env.platform / "workflow_definitions" / "ambiguous_mode_flow.yaml").exists()

    # Conflicting --empty and agents is rejected
    code, _, stderr = ux_env.run([
        "workflows", "create", "conflict_flow", "--empty", "--agents", "external_text_analysis",
    ])
    assert code == 2
    assert "cannot combine --empty" in stderr

    # Duplicate workflow IDs are rejected without overwriting existing workflows
    code, _, stderr = ux_env.run(["workflows", "create", "dup_flow", "--empty"])
    assert code == 0, stderr
    wf_file = ux_env.platform / "workflow_definitions" / "dup_flow.yaml"
    original_bytes = wf_file.read_bytes()

    code, _, stderr = ux_env.run([
        "workflows", "create", "dup_flow", "--agents", "external_text_analysis",
    ])
    assert code == 2
    assert "already exists" in stderr
    assert wf_file.read_bytes() == original_bytes


def test_workflows_create_never_guesses_ambiguous_mappings(ux_env):
    # Connect an agent with an ambiguous 'count' input (matches word_count and character_count)
    ambiguous_dir = ux_env.tmp_path / "count_checker"
    ambiguous_dir.mkdir()
    (ambiguous_dir / "agent.py").write_text(QUALITY_SOURCE, encoding="utf-8")
    (ambiguous_dir / "sample.json").write_text(json.dumps({"count": 1}), encoding="utf-8")
    code, _, stderr = cli(ux_env.platform, ["agents", "connect", str(ambiguous_dir), "--id", "count_checker", "--trust"])
    assert code == 0, stderr

    # Non-interactive create refuses to guess and does not write the file
    code, _, stderr = ux_env.run([
        "workflows", "create", "ambiguous_flow", "--agents", "external_text_analysis,count_checker",
    ])
    assert code == 2
    assert "count (optional) is ambiguous" in stderr
    assert not (ux_env.platform / "workflow_definitions" / "ambiguous_flow.yaml").exists()

    # Interactive create asks for clarification and applies the chosen mapping
    reader = answers("1")
    code, stdout, stderr = ux_env.run(
        ["workflows", "create", "ambiguous_flow", "--agents", "external_text_analysis,count_checker"],
        input_fn=reader,
    )
    assert code == 0, stderr
    saved = yaml.safe_load((ux_env.platform / "workflow_definitions" / "ambiguous_flow.yaml").read_text(encoding="utf-8"))
    assert saved["nodes"][1]["input_mappings"]["count"]["path"] in {
        "node_outputs.external_text_analysis.word_count",
        "node_outputs.external_text_analysis.character_count",
    }


def test_workflows_validate_register_and_list_by_workflow_id_with_auto_version_bump(ux_env):
    code, _, stderr = ux_env.run([
        "workflows", "create", "versioned_flow", "--agents", "external_text_analysis",
    ])
    assert code == 0, stderr

    # Validate by WORKFLOW_ID (not file path)
    code, stdout, stderr = ux_env.run(["workflows", "validate", "versioned_flow"])
    assert code == 0, stderr
    assert json.loads(stdout)["id"] == "versioned_flow"

    # Register by WORKFLOW_ID
    code, stdout, stderr = ux_env.run(["workflows", "register", "versioned_flow"])
    assert code == 0, stderr
    assert json.loads(stdout)["version"] == "1.0.0"

    # Modify the workflow file locally without bumping version, then run 'workflows register versioned_flow'
    wf_path = ux_env.platform / "workflow_definitions" / "versioned_flow.yaml"
    raw = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    raw["nodes"].append({
        "id": "external_quality_checker",
        "type": "agent",
        "agent_id": "external_quality_checker",
        "input_mappings": {"summary": {"path": "node_outputs.external_text_analysis.summary"}},
    })
    raw["edges"].append({"from": "external_text_analysis", "to": "external_quality_checker"})
    wf_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    # Registering the modified workflow automatically increments version to 1.0.1
    code, stdout, stderr = ux_env.run(["workflows", "register", "versioned_flow"])
    assert code == 0, stderr
    registered = json.loads(stdout)
    assert registered["version"] == "1.0.1"
    assert yaml.safe_load(wf_path.read_text(encoding="utf-8"))["version"] == "1.0.1"

    # List workflows
    code, stdout, stderr = ux_env.run(["workflows", "list"])
    assert code == 0, stderr
    listed = json.loads(stdout)
    assert any(item["id"] == "versioned_flow" and item["version"] == "1.0.1" for item in listed)


def test_add_agent_interactive_agent_selection(ux_env):
    code, _, stderr = ux_env.run([
        "workflows", "create", "add_interactive", "--agents", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr

    # Omit AGENT_ID in interactive mode; select external_quality_checker from prompt
    reader = answers("external_quality_checker")
    code, stdout, stderr = ux_env.run(["workflows", "add-agent", "add_interactive"], input_fn=reader)
    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["agent_id"] == "external_quality_checker"
    assert report["version"] == "1.0.1"


def test_agents_and_tools_create_with_sensible_defaults_and_compatibility_aliases(tmp_path: Path):
    # 'agents create' with zero flags derives name and description automatically
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(["--project-root", str(tmp_path), "agents", "create", "quick_summarizer"], stdout=stdout, stderr=stderr)
    assert code == 0, stderr.getvalue()
    agent_info = json.loads(stdout.getvalue())
    assert agent_info["id"] == "quick_summarizer"
    assert agent_info["name"] == "Quick Summarizer"
    assert "Quick Summarizer" in agent_info["description"]

    # Validate by agent ID
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(["--project-root", str(tmp_path), "agents", "validate", "quick_summarizer"], stdout=stdout, stderr=stderr)
    assert code == 0, stderr.getvalue()

    # 'tools create' with zero flags derives name and description automatically
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(["--project-root", str(tmp_path), "tools", "create", "token_counter"], stdout=stdout, stderr=stderr)
    assert code == 0, stderr.getvalue()
    tool_info = json.loads(stdout.getvalue())
    assert tool_info["id"] == "token_counter"
    assert tool_info["name"] == "Token Counter"

    # Validate tool by TOOL_ID (not just file path)
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(["--project-root", str(tmp_path), "tools", "validate", "token_counter"], stdout=stdout, stderr=stderr)
    assert code == 0, stderr.getvalue()
    assert json.loads(stdout.getvalue())["id"] == "token_counter"

    # Compatibility aliases ('agents scaffold' and 'tools scaffold') still work with zero flags
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(["--project-root", str(tmp_path), "agents", "scaffold", "legacy_agent"], stdout=stdout, stderr=stderr)
    assert code == 0, stderr.getvalue()

    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(["--project-root", str(tmp_path), "tools", "scaffold", "legacy_tool"], stdout=stdout, stderr=stderr)
    assert code == 0, stderr.getvalue()


@pytest.mark.parametrize(
    "help_args",
    [
        ["--help"],
        ["agents", "--help"],
        ["agents", "create", "--help"],
        ["agents", "connect", "--help"],
        ["agents", "disconnect", "--help"],
        ["agents", "delete", "--help"],
        ["agents", "run", "--help"],
        ["tools", "--help"],
        ["tools", "create", "--help"],
        ["workflows", "--help"],
        ["workflows", "create", "--help"],
        ["workflows", "add-agent", "--help"],
        ["workflows", "validate", "--help"],
        ["workflows", "register", "--help"],
        ["workflows", "disconnect", "--help"],
        ["workflows", "delete", "--help"],
        ["runs", "--help"],
        ["runs", "start", "--help"],
        ["approvals", "--help"],
        ["approvals", "resume", "--help"],
    ],
)
def test_help_output_is_clear_and_includes_examples(help_args, capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(help_args)
    assert exc_info.value.code == 0
    captured = capsys.readouterr().out
    assert "Example" in captured
    assert "usage:" in captured


def test_invalid_conflicting_arguments_fail_cleanly(ux_env):
    code, _, stderr = ux_env.run(["runs", "start", "flow", "--workflow", "flow", "--interactive"])
    assert code == 2 and "not both" in stderr

    code, _, stderr = ux_env.run(["agents", "connect", str(ux_env.external_a), "--path", str(ux_env.external_a)])
    assert code == 2 and "not both" in stderr

    code, _, stderr = ux_env.run(["approvals", "resume", "run-123", "approve", "--decision", "reject"])
    assert code == 2 and "not both" in stderr


def test_workflows_delete_removes_server_registration_local_yaml_and_all_history(ux_env):
    # Create, register, and execute a workflow so run and event records exist
    code, _, stderr = ux_env.run([
        "workflows", "create", "del_flow", "external_text_analysis", "external_quality_checker", "--register",
    ])
    assert code == 0, stderr

    wf_file = ux_env.platform / "workflow_definitions" / "del_flow.yaml"
    assert wf_file.is_file()

    reader = answers("History should be purged with workflow deletion")
    code, stdout, stderr = ux_env.run(["runs", "start", "del_flow"], input_fn=reader)
    assert code == 0, stderr
    run_id = json.loads(stdout)["run_id"]

    # Verify run and events exist before deletion
    assert ux_env.repository.get_run(run_id) is not None
    assert len(ux_env.repository.events(run_id)) >= 1

    # Delete the workflow with --yes
    code, stdout, stderr = ux_env.run(["workflows", "delete", "del_flow", "--yes"])
    assert code == 0, stderr
    deleted = json.loads(stdout)
    assert deleted["id"] == "del_flow"
    assert deleted["workflow_id"] == "del_flow"
    assert deleted["status"] == "deleted"
    assert deleted["deleted"] is True
    assert deleted["deleted_from_server"] is True
    assert deleted["deleted_local_file"] == str(wf_file.resolve())
    assert deleted["deleted_runs"] >= 1
    assert deleted["deleted_events"] >= 2

    # Local YAML file and server registration are both gone
    assert not wf_file.exists()
    assert ux_env.repository.get_workflow("del_flow") is None

    code, _, stderr = ux_env.run(["workflows", "show", "del_flow"])
    assert code == 2 and "API 404:" in stderr

    code, stdout, stderr = ux_env.run(["workflows", "list"])
    assert code == 0, stderr
    assert all(item["id"] != "del_flow" for item in json.loads(stdout))

    # Run and event records are now deleted
    assert ux_env.repository.get_run(run_id) is None

    # Recreating the workflow with default version 1.0.0 works cleanly without conflict
    code, stdout, stderr = ux_env.run([
        "workflows", "create", "del_flow", "--agents", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr
    assert json.loads(stdout)["version"] == "1.0.0"


def test_workflows_delete_confirmation_interactive_and_non_interactive(ux_env):
    code, _, stderr = ux_env.run([
        "workflows", "create", "confirm_flow", "--agents", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr
    wf_file = ux_env.platform / "workflow_definitions" / "confirm_flow.yaml"

    # Non-interactive without --yes fails closed
    code, _, stderr = ux_env.run(["workflows", "delete", "confirm_flow"])
    assert code == 2
    assert "explicit confirmation" in stderr
    assert wf_file.is_file()
    assert ux_env.repository.get_workflow("confirm_flow") is not None

    # Interactive cancellation ('n') leaves both local YAML and server registration untouched
    code, _, stderr = ux_env.run(["workflows", "delete", "confirm_flow"], input_fn=answers("n"))
    assert code == 2
    assert "cancelled" in stderr
    assert wf_file.is_file()
    assert ux_env.repository.get_workflow("confirm_flow") is not None

    # Interactive confirmation ('yes') deletes both local YAML and server registration
    code, stdout, stderr = ux_env.run(["workflows", "delete", "confirm_flow"], input_fn=answers("yes"))
    assert code == 0, stderr
    assert "Workflow to delete: confirm_flow" in stderr
    report = json.loads(stdout)
    assert report["deleted"] is True
    assert report["deleted_from_server"] is True
    assert not wf_file.exists()
    assert ux_env.repository.get_workflow("confirm_flow") is None


def test_workflows_delete_nonexistent_and_local_or_server_consistency(ux_env):
    # Deleting a nonexistent workflow fails with a clear error
    code, _, stderr = ux_env.run(["workflows", "delete", "missing_workflow", "--yes"])
    assert code == 2
    assert "workflow not found: missing_workflow" in stderr

    # Deleting an unregistered local workflow draft removes the local file cleanly
    code, _, stderr = ux_env.run(["workflows", "create", "draft_only", "--empty"])
    assert code == 0, stderr
    draft_file = ux_env.platform / "workflow_definitions" / "draft_only.yaml"
    assert draft_file.is_file()

    code, stdout, stderr = ux_env.run(["workflows", "delete", "draft_only", "--yes"])
    assert code == 0, stderr
    draft_report = json.loads(stdout)
    assert draft_report["deleted"] is True
    assert draft_report["deleted_from_server"] is False
    assert draft_report["deleted_local_file"] == str(draft_file.resolve())
    assert not draft_file.exists()

    # Deleting a server-only workflow (where local YAML was already removed) removes server registration
    code, _, stderr = ux_env.run([
        "workflows", "create", "server_only", "--agents", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr
    server_only_file = ux_env.platform / "workflow_definitions" / "server_only.yaml"
    server_only_file.unlink()

    code, stdout, stderr = ux_env.run(["workflows", "delete", "server_only", "--yes"])
    assert code == 0, stderr
    server_report = json.loads(stdout)
    assert server_report["deleted"] is True
    assert server_report["deleted_from_server"] is True
    assert server_report["deleted_local_file"] is None
    assert ux_env.repository.get_workflow("server_only") is None

    # Consistency when server deletion is rejected (403): local YAML is NOT deleted
    code, _, stderr = ux_env.run([
        "workflows", "create", "protected_flow", "--agents", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr
    protected_file = ux_env.platform / "workflow_definitions" / "protected_flow.yaml"

    code, _, stderr = ux_env.run(
        ["workflows", "delete", "protected_flow", "--yes"],
        token="readonly-token",
    )
    assert code == 2
    assert "API 403:" in stderr
    assert protected_file.is_file()
    assert ux_env.repository.get_workflow("protected_flow") is not None


def test_workflows_delete_preview_distinguishes_deleted_and_preserved_and_handles_ctrl_c(ux_env):
    code, _, stderr = ux_env.run([
        "workflows", "create", "preview_flow", "--agents", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr
    wf_file = ux_env.platform / "workflow_definitions" / "preview_flow.yaml"

    # Default No on empty Enter response
    code, _, stderr = ux_env.run(["workflows", "delete", "preview_flow"], input_fn=answers(""))
    assert code == 2
    assert "WARNING: This permanently deletes the workflow 'preview_flow'" in stderr
    assert "Preserved resources (will NOT be deleted):" in stderr
    assert "Workflow execution runs:" in stderr
    assert "will be permanently deleted" in stderr
    assert "cancelled" in stderr
    assert wf_file.is_file()

    # Ctrl+C (KeyboardInterrupt) cancels cleanly without deleting
    def raise_ctrl_c(_prompt):
        raise KeyboardInterrupt()

    code, _, stderr = ux_env.run(["workflows", "delete", "preview_flow"], input_fn=raise_ctrl_c)
    assert code == 2
    assert "cancelled" in stderr
    assert wf_file.is_file()
    assert ux_env.repository.get_workflow("preview_flow") is not None

    # --yes still prints the deletion preview summary to stderr
    code, stdout, stderr = ux_env.run(["workflows", "delete", "preview_flow", "--yes"])
    assert code == 0, stderr
    assert "WARNING: This permanently deletes the workflow 'preview_flow'" in stderr
    assert json.loads(stdout)["deleted"] is True


def test_workflows_disconnect_unregisters_workflow_preserves_local_yaml_and_history(ux_env):
    # Create, register, and run a workflow
    code, _, stderr = ux_env.run([
        "workflows", "create", "disc_flow", "external_text_analysis", "external_quality_checker", "--register",
    ])
    assert code == 0, stderr
    wf_file = ux_env.platform / "workflow_definitions" / "disc_flow.yaml"
    original_yaml = wf_file.read_text(encoding="utf-8")

    code, stdout, stderr = ux_env.run(["runs", "start", "disc_flow"], input_fn=answers("Run before disconnect"))
    assert code == 0, stderr
    run_id = json.loads(stdout)["run_id"]

    # Non-interactive without --yes requires confirmation
    code, _, stderr = ux_env.run(["workflows", "disconnect", "disc_flow"])
    assert code == 2
    assert "explicit confirmation" in stderr
    assert ux_env.repository.get_workflow("disc_flow") is not None

    # Interactive cancellation ('') preserves active registration
    code, _, stderr = ux_env.run(["workflows", "disconnect", "disc_flow"], input_fn=answers(""))
    assert code == 2
    assert "cancelled" in stderr
    assert ux_env.repository.get_workflow("disc_flow") is not None

    # Interactive confirmation ('y') disconnects the workflow from the active API registry
    code, stdout, stderr = ux_env.run(["workflows", "disconnect", "disc_flow"], input_fn=answers("y"))
    assert code == 0, stderr
    assert "Summary of workflow disconnection for 'disc_flow':" in stderr
    assert "Preserved resources (will NOT be deleted):" in stderr
    report = json.loads(stdout)
    assert report["id"] == "disc_flow"
    assert report["status"] == "disconnected"
    assert report["already_disconnected"] is False
    assert report["registered"] is False
    assert report["registration_status"] == "disconnected"
    assert report["unregistered_from_server"] is True
    assert report["retained"]["history"] is True
    assert set(report["retained"]["agents"]) == {"external_text_analysis", "external_quality_checker"}

    # Local YAML file, node configuration, and mappings are preserved unchanged
    assert wf_file.is_file()
    assert wf_file.read_text(encoding="utf-8") == original_yaml

    # Agents used by the workflow are still registered and intact
    code, stdout, stderr = ux_env.run(["agents", "list"])
    assert code == 0, stderr
    agent_ids = {item["id"] for item in json.loads(stdout)}
    assert {"external_text_analysis", "external_quality_checker"} <= agent_ids

    # New runs via the API are disabled (404)
    input_file = ux_env.tmp_path / "disc_input.json"
    input_file.write_text(json.dumps({"text": "Blocked run"}), encoding="utf-8")
    code, _, stderr = ux_env.run(["runs", "start", "disc_flow", "--input", str(input_file)])
    assert code == 2
    assert "API 404:" in stderr

    # Historical execution records remain intact
    code, stdout, stderr = ux_env.run(["runs", "show", run_id])
    assert code == 0, stderr
    assert json.loads(stdout)["status"] == "succeeded"

    # workflows list and workflows show clearly indicate disconnected state
    code, stdout, stderr = ux_env.run(["workflows", "list"])
    assert code == 0, stderr
    listed_map = {item["id"]: item for item in json.loads(stdout)}
    assert "disc_flow" in listed_map
    assert listed_map["disc_flow"]["registered"] is False
    assert listed_map["disc_flow"]["registration_status"] == "disconnected"

    code, stdout, stderr = ux_env.run(["workflows", "show", "disc_flow"])
    assert code == 0, stderr
    shown = json.loads(stdout)
    assert shown["id"] == "disc_flow"
    assert shown["registered"] is False
    assert shown["registration_status"] == "disconnected"
    assert len(shown["nodes"]) == 2

    # Disconnecting an already disconnected workflow reports cleanly without error
    code, stdout, stderr = ux_env.run(["workflows", "disconnect", "disc_flow"])
    assert code == 0, stderr
    already = json.loads(stdout)
    assert already["already_disconnected"] is True
    assert already["status"] == "disconnected"
    assert "already disconnected" in stderr

    # Re-registering restores registered state
    code, stdout, stderr = ux_env.run(["workflows", "register", "disc_flow"])
    assert code == 0, stderr
    code, stdout, stderr = ux_env.run(["workflows", "show", "disc_flow"])
    assert code == 0, stderr
    assert json.loads(stdout)["registered"] is True


def test_agents_delete_preview_confirmation_and_cleanup_across_workflows(ux_env):
    original_external_source = (ux_env.external_a / "agent.py").read_bytes()

    # 1. Create a direct run for external_text_analysis
    code, stdout, stderr = ux_env.run(
        ["agents", "run", "external_text_analysis"],
        input_fn=answers("Direct run for agent to be deleted"),
    )
    assert code == 0, stderr
    direct_run_id = json.loads(stdout)["run_id"]

    # 2. Create three workflows:
    #    - solo_flow: references ONLY external_text_analysis
    #    - combo_flow: references external_text_analysis -> external_quality_checker
    #    - unrelated_flow: references ONLY external_quality_checker
    code, _, stderr = ux_env.run([
        "workflows", "create", "solo_flow", "--agents", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr

    code, _, stderr = ux_env.run([
        "workflows", "create", "combo_flow", "external_text_analysis", "external_quality_checker", "--register",
    ])
    assert code == 0, stderr

    code, _, stderr = ux_env.run([
        "workflows", "create", "unrelated_flow", "--agents", "external_quality_checker", "--register",
    ])
    assert code == 0, stderr

    # Run combo_flow so shared workflow execution history exists
    code, stdout, stderr = ux_env.run(["runs", "start", "combo_flow"], input_fn=answers("Shared workflow run"))
    assert code == 0, stderr
    shared_run_id = json.loads(stdout)["run_id"]

    # 3. Non-interactive without --yes fails closed after showing preview
    code, _, stderr = ux_env.run(["agents", "delete", "external_text_analysis"])
    assert code == 2
    assert "WARNING: This permanently deletes the agent 'external_text_analysis'" in stderr
    assert "solo_flow" in stderr
    assert "combo_flow" in stderr
    assert "External project source files on disk (will remain untouched):" in stderr
    assert "explicit confirmation" in stderr

    # 4. Interactive cancellation ('', 'n', 'invalid', Ctrl+C) makes no changes
    for bad_input in ("", "n", "invalid"):
        code, _, stderr = ux_env.run(
            ["agents", "delete", "external_text_analysis"],
            input_fn=answers(bad_input),
        )
        assert code == 2
        assert "cancelled" in stderr
        assert (ux_env.platform / "plugins" / "manifests" / "external_text_analysis.yaml").is_file()

    def raise_ctrl_c(_prompt):
        raise KeyboardInterrupt()

    code, _, stderr = ux_env.run(["agents", "delete", "external_text_analysis"], input_fn=raise_ctrl_c)
    assert code == 2
    assert "cancelled" in stderr

    # 5. Confirm permanent deletion interactively ('y')
    code, stdout, stderr = ux_env.run(
        ["agents", "delete", "external_text_analysis", "--db", str(ux_env.tmp_path / "ux.db")],
        input_fn=answers("y"),
    )
    assert code == 0, stderr
    del_report = json.loads(stdout)
    assert del_report["id"] == "external_text_analysis"
    assert del_report["status"] == "deleted"
    assert del_report["deleted"]["connection_catalog_entry"] is True
    assert del_report["deleted"]["direct_runs"] >= 1
    assert del_report["external_project_modified"] is False
    assert "solo_flow" in del_report["deleted"]["workflows_affected"]
    assert "combo_flow" in del_report["deleted"]["workflows_affected"]
    assert del_report["deleted"]["workflows_affected"]["solo_flow"]["fate"] == "converted_to_empty_draft_and_unregistered"
    assert del_report["deleted"]["workflows_affected"]["combo_flow"]["fate"] == "updated_and_registered"

    # 6. Verify manifest, adapter directory, and connection catalog entry are removed
    assert not (ux_env.platform / "plugins" / "manifests" / "external_text_analysis.yaml").exists()
    assert not (ux_env.platform / "plugins" / "examples" / "connected_external_text_analysis").exists()
    catalog_path = ux_env.platform / "plugins" / "connection_catalog.json"
    assert "external_text_analysis" not in json.loads(catalog_path.read_text(encoding="utf-8"))

    # 7. External project directory and source files on disk remain completely untouched
    assert (ux_env.external_a / "agent.py").read_bytes() == original_external_source

    # 8. agents list and agents show reflect deletion; unrelated agent remains
    code, stdout, stderr = ux_env.run(["agents", "list"])
    assert code == 0, stderr
    remaining_agent_ids = [item["id"] for item in json.loads(stdout)]
    assert "external_text_analysis" not in remaining_agent_ids
    assert "external_quality_checker" in remaining_agent_ids

    code, _, stderr = ux_env.run(["agents", "show", "external_text_analysis"])
    assert code == 2 and "API 404:" in stderr

    # 9. solo_flow was converted to an empty draft locally and unregistered from the active server registry
    solo_yaml = yaml.safe_load((ux_env.platform / "workflow_definitions" / "solo_flow.yaml").read_text(encoding="utf-8"))
    assert solo_yaml["nodes"] == []
    assert solo_yaml["version"] == "1.0.1"
    assert ux_env.repository.get_workflow("solo_flow") is None

    # 10. combo_flow had external_text_analysis and dependent mappings removed, version bumped, and remains valid
    combo_yaml = yaml.safe_load((ux_env.platform / "workflow_definitions" / "combo_flow.yaml").read_text(encoding="utf-8"))
    assert combo_yaml["version"] == "1.0.1"
    assert [n["id"] for n in combo_yaml["nodes"]] == ["external_quality_checker"]
    assert combo_yaml["edges"] == []
    code, _, stderr = ux_env.run(["workflows", "validate", "combo_flow"])
    assert code == 0, stderr

    # 11. Unrelated workflow and shared workflow execution history are preserved
    unrelated_yaml = yaml.safe_load((ux_env.platform / "workflow_definitions" / "unrelated_flow.yaml").read_text(encoding="utf-8"))
    assert unrelated_yaml["version"] == "1.0.0"
    assert [n["id"] for n in unrelated_yaml["nodes"]] == ["external_quality_checker"]

    code, stdout, stderr = ux_env.run(["runs", "show", shared_run_id])
    assert code == 0, stderr
    assert json.loads(stdout)["run_id"] == shared_run_id

    # Direct run for deleted agent was purged
    assert ux_env.repository.get_run(direct_run_id) is None


def test_agents_delete_nonexistent_and_authorization_failure_rollback(ux_env):
    # Nonexistent agent returns clear error
    code, _, stderr = ux_env.run(["agents", "delete", "nonexistent_agent", "--yes"])
    assert code == 2
    assert "agent not found: nonexistent_agent" in stderr

    # Authorization failure (403) aborts before deleting local manifest or adapter
    code, _, stderr = ux_env.run(
        ["agents", "delete", "external_quality_checker", "--yes"],
        token="readonly-token",
    )
    assert code == 2
    assert "API 403:" in stderr
    assert (ux_env.platform / "plugins" / "manifests" / "external_quality_checker.yaml").is_file()
    assert (ux_env.platform / "plugins" / "examples" / "connected_external_quality_checker" / "adapter.py").is_file()


def test_workflows_create_auto_registers_by_default(ux_env):
    # Creating a workflow with agents automatically registers with the API server by default
    code, stdout, stderr = ux_env.run([
        "workflows", "create", "auto_flow", "--agents", "external_text_analysis",
    ])
    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["id"] == "auto_flow"
    assert report["version"] == "1.0.0"
    assert report["registered"] == {"id": "auto_flow", "version": "1.0.0"}
    assert report["registration_status"] == "registered"

    # Verifying via workflows show confirms server registration is active
    code, stdout, stderr = ux_env.run(["workflows", "show", "auto_flow"])
    assert code == 0, stderr
    shown = json.loads(stdout)
    assert shown["registered"] is True
    assert shown["registration_status"] == "registered"

    # Verifying via workflows list confirms auto_flow is listed as registered
    code, stdout, stderr = ux_env.run(["workflows", "list"])
    assert code == 0, stderr
    listed = {item["id"]: item for item in json.loads(stdout)}
    assert listed["auto_flow"]["registered"] is True
    assert listed["auto_flow"]["registration_status"] == "registered"


def test_workflows_create_no_register_flag_and_conflicting_options(ux_env):
    # --no-register saves locally but skips API server registration
    code, stdout, stderr = ux_env.run([
        "workflows", "create", "local_flow", "--agents", "external_text_analysis", "--no-register",
    ])
    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["id"] == "local_flow"
    assert report["registered"] is False
    assert report["registration_status"] == "disconnected"

    # Local file exists on disk
    wf_file = ux_env.platform / "workflow_definitions" / "local_flow.yaml"
    assert wf_file.is_file()

    # workflows show indicates it is disconnected/not registered
    code, stdout, stderr = ux_env.run(["workflows", "show", "local_flow"])
    assert code == 0, stderr
    shown = json.loads(stdout)
    assert shown["registered"] is False
    assert shown["registration_status"] == "disconnected"

    # Cannot combine --register and --no-register
    code, _, stderr = ux_env.run([
        "workflows", "create", "bad_flow", "--agents", "external_text_analysis", "--register", "--no-register",
    ])
    assert code == 2
    assert "cannot combine --register and --no-register" in stderr


def test_workflows_create_offline_server_fallback_and_scaffold(ux_env):
    import io
    from app.cli import _create_workflow, ApiClient, CliError

    # Offline client pointing to an unreachable port
    dead_client = ApiClient(base_url="http://127.0.0.1:59999", timeout=0.2)
    err_stream = io.StringIO()

    # Default auto-registration gracefully catches offline server, saves YAML, notes on stderr
    res = _create_workflow(
        project_root=ux_env.platform,
        workflow_id="offline_flow",
        agent_list=["external_text_analysis"],
        api=dead_client,
        error_output=err_stream,
    )
    assert res["id"] == "offline_flow"
    assert res["registered"] is False
    assert res["registration_status"] == "disconnected"
    assert (ux_env.platform / "workflow_definitions" / "offline_flow.yaml").is_file()
    assert "Note: API server is offline; workflow 'offline_flow' was saved locally" in err_stream.getvalue()

    # Explicit --register strictly fails when API server cannot be reached
    with pytest.raises(CliError) as exc_info:
        _create_workflow(
            project_root=ux_env.platform,
            workflow_id="strict_offline_flow",
            agent_list=["external_text_analysis"],
            register=True,
            api=dead_client,
        )
    assert "could not connect to" in str(exc_info.value)
    # File was created before registration attempt
    assert (ux_env.platform / "workflow_definitions" / "strict_offline_flow.yaml").is_file()

    # workflows scaffold alias generates template with no_register=True
    code, stdout, stderr = ux_env.run([
        "workflows", "scaffold", "scaffolded_flow", "--agents", "external_text_analysis",
    ])
    assert code == 0, stderr
    scaffold_res = json.loads(stdout)
    assert scaffold_res["id"] == "scaffolded_flow"
    assert scaffold_res["registered"] is False
    assert scaffold_res["registration_status"] == "disconnected"


def test_workflows_delete_purges_all_associated_data(ux_env):
    # Create, register, and run a workflow
    code, _, stderr = ux_env.run([
        "workflows", "create", "purge_flow", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr
    wf_file = ux_env.platform / "workflow_definitions" / "purge_flow.yaml"
    assert wf_file.is_file()

    code, stdout, stderr = ux_env.run(["runs", "start", "purge_flow"], input_fn=answers("testing purge"))
    assert code == 0, stderr
    run_id = json.loads(stdout)["run_id"]

    # Verify run and events exist in repo
    assert ux_env.repository.get_run(run_id) is not None
    assert len(ux_env.repository.events(run_id)) >= 1

    # Delete with --yes
    code, stdout, stderr = ux_env.run(["workflows", "delete", "purge_flow", "--yes"])
    assert code == 0, stderr
    del_report = json.loads(stdout)
    assert del_report["deleted"] is True
    assert del_report["deleted_runs"] >= 1
    assert del_report["deleted_events"] >= 1
    assert not wf_file.exists()
    assert ux_env.repository.get_workflow("purge_flow") is None
    assert ux_env.repository.get_run(run_id) is None
    assert ux_env.repository.events(run_id) == []


def test_workflows_delete_does_not_affect_other_workflow_runs(ux_env):
    # Create and run workflow A
    code, _, stderr = ux_env.run([
        "workflows", "create", "flow_a", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr
    code, stdout, stderr = ux_env.run(["runs", "start", "flow_a"], input_fn=answers("flow a input"))
    assert code == 0, stderr
    run_a = json.loads(stdout)["run_id"]

    # Create and run workflow B
    code, _, stderr = ux_env.run([
        "workflows", "create", "flow_b", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr
    code, stdout, stderr = ux_env.run(["runs", "start", "flow_b"], input_fn=answers("flow b input"))
    assert code == 0, stderr
    run_b = json.loads(stdout)["run_id"]

    # Delete workflow A
    code, stdout, stderr = ux_env.run(["workflows", "delete", "flow_a", "--yes"])
    assert code == 0, stderr

    # Flow A data is purged
    assert ux_env.repository.get_workflow("flow_a") is None
    assert ux_env.repository.get_run(run_a) is None
    assert ux_env.repository.events(run_a) == []

    # Flow B data is completely intact
    assert ux_env.repository.get_workflow("flow_b") is not None
    assert ux_env.repository.get_run(run_b) is not None
    assert len(ux_env.repository.events(run_b)) >= 1
    code, stdout, stderr = ux_env.run(["runs", "show", run_b])
    assert code == 0, stderr
    assert json.loads(stdout)["workflow_id"] == "flow_b"


def test_workflows_add_agent_to_empty_draft_auto_registers(ux_env):
    # Step 1: Create empty workflow draft
    code, stdout, stderr = ux_env.run(["workflows", "create", "empty_to_auto", "--empty"])
    assert code == 0, stderr
    draft = json.loads(stdout)
    assert draft["id"] == "empty_to_auto"
    assert draft["registered"] is False
    assert draft["registration_status"] == "disconnected"

    # Verify workflows show reports disconnected / unregistered
    code, stdout, stderr = ux_env.run(["workflows", "show", "empty_to_auto"])
    assert code == 0, stderr
    show_draft = json.loads(stdout)
    assert show_draft["registered"] is False
    assert show_draft["registration_status"] == "disconnected"

    # Step 2: Add agent to empty draft
    code, stdout, stderr = ux_env.run([
        "workflows", "add-agent", "empty_to_auto", "external_text_analysis",
    ])
    assert code == 0, stderr
    add_report = json.loads(stdout)
    assert add_report["validated"] is True
    assert add_report["registered"]["id"] == "empty_to_auto"

    # Step 3: Verify it is now registered on server
    code, stdout, stderr = ux_env.run(["workflows", "show", "empty_to_auto"])
    assert code == 0, stderr
    show_report = json.loads(stdout)
    assert show_report["registered"] is True
    assert show_report["registration_status"] == "registered"

    # Step 4: Verify it can be run
    code, stdout, stderr = ux_env.run(["runs", "start", "empty_to_auto"], input_fn=answers("auto registered run"))
    assert code == 0, stderr
    run_id = json.loads(stdout)["run_id"]
    assert ux_env.repository.get_run(run_id) is not None


def test_workflows_delete_preview_shows_data_to_be_deleted(ux_env):
    # Create, register, and run a workflow
    code, _, stderr = ux_env.run([
        "workflows", "create", "preview_details_flow", "external_text_analysis", "--register",
    ])
    assert code == 0, stderr
    code, _, stderr = ux_env.run(["runs", "start", "preview_details_flow"], input_fn=answers("preview input"))
    assert code == 0, stderr

    # Cancel interactive deletion with 'n'
    reader = answers("n")
    code, _, stderr = ux_env.run(
        ["workflows", "delete", "preview_details_flow", "--db", str(ux_env.tmp_path / "ux.db")],
        input_fn=reader,
    )
    assert code == 2
    assert "WARNING: This permanently deletes the workflow 'preview_details_flow'" in stderr
    assert "Workflow execution runs: 1 run(s) (will be permanently deleted)" in stderr
    assert "Execution events:" in stderr
    assert "(will be permanently deleted)" in stderr
    assert "LangGraph checkpoints:" in stderr
    assert "Preserved resources (will NOT be deleted):" in stderr
    assert "Referenced agents (remain untouched):" in stderr
    assert "This will permanently delete the workflow and its associated data. Continue? [y/N]: " in reader.prompts[0]
    assert "cancelled" in stderr





