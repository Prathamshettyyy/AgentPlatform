"""Tests for simplified agent connection, add-agent workflow composition and interactive runs."""

import io
import json
from types import SimpleNamespace

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.cli import main
from app.registry.external_connector import project_plugin_namespace
from app.storage.repository import ExecutionRepository
from app.workflows.composer import name_score, types_compatible


TEXT_ANALYSIS_SOURCE = '''\
from pathlib import Path

Path(__file__).with_name("imported.marker").write_text("module imported", encoding="utf-8")


class TextAnalysisAgent:
    def run(self, payload):
        text = payload.get("text", "")
        return {
            "summary": text,
            "word_count": len(text.split()),
            "character_count": len(text),
            "most_frequent_words": [{"word": "text", "count": 1}],
            "status": "success",
        }
'''

QUALITY_SOURCE = '''\
class QualityCheckerAgent:
    def run(self, payload):
        return {"quality": "ok", "received": sorted(payload)}
'''

QUALITY_INPUT = {
    "original_text": "sample",
    "summary": "sample",
    "word_count": 1,
    "character_count": 6,
    "most_frequent_words": [{"word": "sample", "count": 1}],
    "analysis_status": "success",
}

BASE_WORKFLOW = {
    "id": "flow",
    "version": "1.0.0",
    "nodes": [{
        "id": "external_text_analysis", "type": "agent", "agent_id": "external_text_analysis",
        "input_mappings": {"text": {"path": "workflow_input.text"}},
    }],
    "edges": [],
}

TOKENS = {"alice": "alice-token", "bob": "bob-token"}


def _write_platform(tmp_path):
    platform = tmp_path / "platform"
    (platform / "plugins" / "manifests").mkdir(parents=True)
    (platform / "plugins" / "examples").mkdir(parents=True)
    (platform / "plugins" / "__init__.py").write_text('"""test plugins"""\n', encoding="utf-8")
    (platform / "plugins" / "examples" / "__init__.py").write_text('"""test examples"""\n', encoding="utf-8")
    (platform / "workflow_definitions").mkdir()
    return platform


def _externals(tmp_path):
    external_a = tmp_path / "external_agent_demo"
    external_a.mkdir()
    (external_a / "agent.py").write_text(TEXT_ANALYSIS_SOURCE, encoding="utf-8")
    (external_a / "input.json").write_text(json.dumps({"text": "Sample text for analysis."}), encoding="utf-8")
    external_b = tmp_path / "quality_checker_demo"
    external_b.mkdir()
    (external_b / "agent.py").write_text(QUALITY_SOURCE, encoding="utf-8")
    (external_b / "example_input.json").write_text(json.dumps(QUALITY_INPUT), encoding="utf-8")
    return external_a, external_b


def cli(platform, args, *, client=None, input_fn=None, token=None):
    stdout, stderr = io.StringIO(), io.StringIO()
    prefix = ["--project-root", str(platform)]
    if token:
        prefix += ["--token", token]
    code = main(prefix + list(args), client=client, stdout=stdout, stderr=stderr, input_fn=input_fn)
    return code, stdout.getvalue(), stderr.getvalue()


def answers(*values):
    pending = list(values)
    prompts: list[str] = []

    def reader(prompt=""):
        prompts.append(prompt)
        if not pending:
            raise AssertionError(f"unexpected prompt: {prompt}")
        return pending.pop(0)

    reader.prompts = prompts
    return reader


@pytest.fixture
def env(tmp_path):
    platform = _write_platform(tmp_path)
    external_a, external_b = _externals(tmp_path)
    with project_plugin_namespace(platform):
        # Zero-argument connections: ID, name, entry point and example input are all inferred.
        for external in (external_a, external_b):
            code, _, stderr = cli(platform, ["agents", "connect", "--path", str(external)], input_fn=answers("TRUST"))
            assert code == 0, stderr
        workflow_path = platform / "workflow_definitions" / "flow.yaml"
        workflow_path.write_text("# header comment\n" + yaml.safe_dump(BASE_WORKFLOW, sort_keys=False), encoding="utf-8")
        repository = ExecutionRepository(str(tmp_path / "history.db"))
        app = create_app(
            repository, manifests_dir=platform / "plugins" / "manifests",
            auth_mode="required", auth_tokens=TOKENS,
        )
        with TestClient(app) as client:
            registered = client.post("/v1/workflows", json=BASE_WORKFLOW, headers={"Authorization": "Bearer alice-token"})
            assert registered.status_code == 200, registered.text
            yield SimpleNamespace(
                platform=platform, external_a=external_a, external_b=external_b, client=client,
                repository=repository, workflow_path=workflow_path, tmp_path=tmp_path,
                run=lambda args, **kwargs: cli(platform, args, client=client, token=kwargs.pop("token", "alice-token"), **kwargs),
            )


def _workflow(env):
    return yaml.safe_load(env.workflow_path.read_text(encoding="utf-8"))


def _node(workflow, node_id):
    return next(item for item in workflow["nodes"] if item["id"] == node_id)


# --------------------------------------------------------------------------- connect


def test_connect_infers_id_name_entry_point_and_example_input_after_trust(env):
    manifest = yaml.safe_load((env.platform / "plugins" / "manifests" / "external_quality_checker.yaml").read_text(encoding="utf-8"))
    assert manifest["name"] == "Quality Checker Agent"
    assert set(manifest["input_schema"]["properties"]) == set(QUALITY_INPUT)
    text_manifest = yaml.safe_load((env.platform / "plugins" / "manifests" / "external_text_analysis.yaml").read_text(encoding="utf-8"))
    # The observed output shape is recorded for later workflow mapping.
    assert set(text_manifest["output_schema"]["properties"]) == {
        "summary", "word_count", "character_count", "most_frequent_words", "status",
    }


def test_connect_prompts_for_trust_and_does_not_execute_without_it(tmp_path):
    platform = _write_platform(tmp_path)
    external_a, _ = _externals(tmp_path)
    for reply in ("no", "trust"):
        code, _, stderr = cli(platform, ["agents", "connect", "--path", str(external_a)], input_fn=answers(reply))
        assert code == 2 and "cancelled" in stderr
        assert "not sandboxed" in stderr
        assert "'external_text_analysis'" in stderr and "agent.py:TextAnalysisAgent" in stderr
        assert not (external_a / "imported.marker").exists()
        assert not list((platform / "plugins" / "manifests").iterdir())

    reader = answers("TRUST")
    code, stdout, stderr = cli(platform, ["agents", "connect", "--path", str(external_a)], input_fn=reader)
    assert code == 0, stderr
    result = json.loads(stdout)
    assert result["id"] == "external_text_analysis"
    assert result["entry_point"] == "agent.py:TextAnalysisAgent"
    assert result["verification_input"].startswith("detected example file")
    assert "input.json" in result["verification_input"]
    assert "not sandboxed" in stderr


def test_connect_requests_sample_input_when_no_example_exists(tmp_path):
    platform = _write_platform(tmp_path)
    external_a, _ = _externals(tmp_path)
    (external_a / "input.json").unlink()
    reader = answers('{"text": "typed sample"}', "TRUST")
    code, stdout, stderr = cli(platform, ["agents", "connect", "--path", str(external_a)], input_fn=reader)
    assert code == 0, stderr
    result = json.loads(stdout)
    assert result["verification_input"] == "interactive sample"
    assert result["test_invocation"]["output"]["summary"] == "typed sample"
    assert "sample input" in reader.prompts[0].lower()


def test_connect_without_example_or_prompt_keeps_backward_compatible_default(tmp_path):
    platform = _write_platform(tmp_path)
    external_a, _ = _externals(tmp_path)
    (external_a / "input.json").unlink()
    code, stdout, stderr = cli(platform, ["agents", "connect", "--path", str(external_a), "--trust"])
    assert code == 0, stderr
    assert json.loads(stdout)["verification_input"] == "built-in default text sample"


def test_connect_ambiguous_examples_need_an_explicit_choice_and_overrides_still_work(tmp_path):
    platform = _write_platform(tmp_path)
    external_a, _ = _externals(tmp_path)
    (external_a / "input.json").unlink()
    (external_a / "case_one_input.json").write_text(json.dumps({"text": "one"}), encoding="utf-8")
    (external_a / "case_two_input.json").write_text(json.dumps({"text": "two"}), encoding="utf-8")
    code, _, stderr = cli(platform, ["agents", "connect", "--path", str(external_a), "--trust"])
    assert code == 2 and "multiple example input files" in stderr and "--test-input" in stderr
    assert not (external_a / "imported.marker").exists()

    code, stdout, stderr = cli(platform, [
        "agents", "connect", "--path", str(external_a), "--trust",
        "--test-input", str(external_a / "case_two_input.json"),
        "--id", "custom_analysis", "--name", "Custom Analysis", "--entry-point", "agent.py:TextAnalysisAgent",
    ])
    assert code == 0, stderr
    result = json.loads(stdout)
    assert (result["id"], result["name"]) == ("custom_analysis", "Custom Analysis")
    assert result["test_invocation"]["output"]["summary"] == "two"


def test_connect_ambiguous_entry_points_are_reported_without_execution(tmp_path):
    platform = _write_platform(tmp_path)
    external_a, _ = _externals(tmp_path)
    (external_a / "other.py").write_text("class OtherAgent:\n    def run(self, payload):\n        return {}\n", encoding="utf-8")
    code, _, stderr = cli(platform, ["agents", "connect", "--path", str(external_a), "--trust"])
    assert code == 2 and "ambiguous" in stderr and "--entry-point" in stderr
    assert not (external_a / "imported.marker").exists()


# --------------------------------------------------------------------------- add-agent


def test_add_agent_infers_expected_mappings_validates_persists_and_registers(env):
    original_text = env.workflow_path.read_text(encoding="utf-8")
    code, stdout, stderr = env.run(["workflows", "add-agent", "flow", "external_quality_checker", "--after", "external_text_analysis"])
    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["node_added"] and report["edge_added"] and report["changed"]
    assert report["validated"] is True
    assert report["version"] == "1.0.1" and report["previous_version"] == "1.0.0"
    assert report["registered"] == {"id": "flow", "version": "1.0.1"}
    assert report["unmapped_optional_fields"] == []
    assert {item["origin"] for item in report["mappings"]} == {"inferred"}

    saved_text = env.workflow_path.read_text(encoding="utf-8")
    assert saved_text.startswith("# header comment\n") and saved_text != original_text
    saved = _workflow(env)
    assert saved["edges"] == [{"from": "external_text_analysis", "to": "external_quality_checker"}]
    assert _node(saved, "external_quality_checker")["input_mappings"] == {
        "original_text": {"path": "workflow_input.text"},
        "summary": {"path": "node_outputs.external_text_analysis.summary"},
        "word_count": {"path": "node_outputs.external_text_analysis.word_count"},
        "character_count": {"path": "node_outputs.external_text_analysis.character_count"},
        "most_frequent_words": {"path": "node_outputs.external_text_analysis.most_frequent_words"},
        "analysis_status": {"path": "node_outputs.external_text_analysis.status"},
    }
    assert _node(saved, "external_text_analysis") == BASE_WORKFLOW["nodes"][0]
    assert all(item["type_check"] == "verified" for item in report["mappings"])

    registered = env.client.get("/v1/workflows/flow", headers={"Authorization": "Bearer alice-token"}).json()
    assert registered["version"] == "1.0.1" and len(registered["nodes"]) == 2

    # The composed workflow really runs through the API and LangGraph runtime.
    code, stdout, stderr = env.run(["runs", "start", "--workflow", "flow", "--interactive"], input_fn=answers("Hello brave new world"))
    assert code == 0, stderr
    run = json.loads(stdout)
    assert run["status"] == "succeeded"
    assert run["final_output"]["received"] == sorted(QUALITY_INPUT)


def test_add_agent_is_idempotent_and_never_duplicates(env):
    args = ["workflows", "add-agent", "flow", "external_quality_checker", "--after", "external_text_analysis"]
    assert env.run(args)[0] == 0
    first = env.workflow_path.read_bytes()
    code, stdout, stderr = env.run(args)
    assert code == 0, stderr
    report = json.loads(stdout)
    assert report["changed"] is False and not report["node_added"] and not report["edge_added"]
    assert {item["origin"] for item in report["mappings"]} == {"existing"}
    assert report["registered"]["version"] == "1.0.1"
    assert env.workflow_path.read_bytes() == first
    saved = _workflow(env)
    assert len(saved["nodes"]) == 2 and len(saved["edges"]) == 1
    # --after may be omitted on repeat because the existing edge identifies it.
    assert env.run(["workflows", "add-agent", "flow", "external_quality_checker"])[0] == 0
    assert env.workflow_path.read_bytes() == first


def test_add_agent_defaults_after_to_the_single_terminal_node(env):
    code, stdout, stderr = env.run(["workflows", "add-agent", "flow", "external_quality_checker"])
    assert code == 0, stderr
    assert json.loads(stdout)["after"] == "external_text_analysis"


def test_add_agent_reports_unknown_agents_nodes_and_conflicts_without_changes(env):
    before = env.workflow_path.read_bytes()
    for args, message in (
        (["workflows", "add-agent", "flow", "missing_agent"], "unknown or disabled agent"),
        (["workflows", "add-agent", "flow", "external_quality_checker", "--after", "nope"], "--after node not found"),
        (["workflows", "add-agent", "flow", "external_text_analysis", "--after", "external_text_analysis"], "after itself"),
        (["workflows", "add-agent", "missing_flow", "external_quality_checker"], "not found"),
        (["workflows", "add-agent", "flow", "external_quality_checker", "--node-id", "external_text_analysis", "--after", "external_text_analysis"], "already exists"),
        (["workflows", "add-agent", "flow", "external_quality_checker", "--map", "bogus=workflow_input.text"], "not an input field"),
    ):
        code, _, stderr = env.run(args)
        assert code == 2 and message in stderr, (args, stderr)
        assert env.workflow_path.read_bytes() == before


def test_add_agent_refuses_to_branch_from_a_node_that_already_has_a_successor(env):
    assert env.run(["workflows", "add-agent", "flow", "external_quality_checker"])[0] == 0
    before = env.workflow_path.read_bytes()
    code, _, stderr = env.run([
        "workflows", "add-agent", "flow", "external_quality_checker", "--node-id", "second_checker",
        "--after", "external_text_analysis",
    ])
    assert code == 2 and "already has outgoing edges" in stderr
    assert env.workflow_path.read_bytes() == before


def _connect_variant(env, agent_id, sample):
    external = env.tmp_path / agent_id
    external.mkdir()
    (external / "agent.py").write_text(QUALITY_SOURCE, encoding="utf-8")
    (external / "sample.json").write_text(json.dumps(sample), encoding="utf-8")
    code, _, stderr = cli(env.platform, ["agents", "connect", "--path", str(external), "--id", agent_id, "--trust"])
    assert code == 0, stderr


def _restarted_client(env):
    _restarted_client.count = getattr(_restarted_client, "count", 0) + 1
    app = create_app(
        ExecutionRepository(str(env.tmp_path / f"restart_{_restarted_client.count}.db")),
        manifests_dir=env.platform / "plugins" / "manifests", auth_mode="required", auth_tokens=TOKENS,
    )
    return TestClient(app)


def test_ambiguous_mapping_is_not_guessed_and_can_be_answered_or_overridden(env):
    _connect_variant(env, "count_checker", {"count": 1})
    before = env.workflow_path.read_bytes()
    with _restarted_client(env) as client:
        def run(args, **kwargs):
            return cli(env.platform, args, client=client, token="alice-token", **kwargs)

        code, _, stderr = run(["workflows", "add-agent", "flow", "count_checker"])
        assert code == 2 and "count (optional) is ambiguous" in stderr
        assert "word_count" in stderr and "character_count" in stderr and "--map" in stderr
        assert env.workflow_path.read_bytes() == before

        reader = answers("2")
        code, stdout, stderr = run(["workflows", "add-agent", "flow", "count_checker"], input_fn=reader)
        assert code == 0, stderr
        mapping = next(item for item in json.loads(stdout)["mappings"] if item["field"] == "count")
        assert mapping["path"] == "node_outputs.external_text_analysis.character_count"
        assert mapping["origin"] == "answered"

    env.workflow_path.write_bytes(before)
    with _restarted_client(env) as client:
        code, stdout, stderr = cli(
            env.platform,
            ["workflows", "add-agent", "flow", "count_checker", "--map", "count=node_outputs.external_text_analysis.word_count"],
            client=client, token="alice-token",
        )
        assert code == 0, stderr
        assert json.loads(stdout)["mappings"][0]["origin"] == "override"


def test_schema_mismatch_is_reported_and_never_mapped_silently(env):
    _connect_variant(env, "string_count_checker", {"word_count": "many"})
    with _restarted_client(env) as client:
        base = ["workflows", "add-agent", "flow", "string_count_checker"]
        code, stdout, stderr = cli(env.platform, base + ["--map", "word_count=node_outputs.external_text_analysis.word_count"], client=client, token="alice-token")
        assert code == 2 and "schema mismatch" in stderr and "integer" in stderr
        # Without an override the incompatible field is skipped, and the report says so.
        code, stdout, stderr = cli(env.platform, base, client=client, token="alice-token")
        assert code == 0, stderr
        report = json.loads(stdout)
        assert report["unmapped_optional_fields"] == ["word_count"]
        assert _node(_workflow(env), "string_count_checker")["input_mappings"] == {}


def test_required_input_with_no_source_asks_the_developer_or_accepts_a_literal(env):
    manifest = yaml.safe_load((env.platform / "plugins" / "manifests" / "external_quality_checker.yaml").read_text(encoding="utf-8"))
    manifest.update(id="tenant_checker", name="Tenant Checker")
    manifest["input_schema"] = {"type": "object", "required": ["tenant"], "properties": {"tenant": {"type": "string"}}}
    (env.platform / "plugins" / "manifests" / "tenant_checker.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    before = env.workflow_path.read_bytes()
    with _restarted_client(env) as client:
        def run(args, **kwargs):
            return cli(env.platform, args, client=client, token="alice-token", **kwargs)

        code, _, stderr = run(["workflows", "add-agent", "flow", "tenant_checker"])
        assert code == 2 and "tenant (required) has no matching source" in stderr
        assert env.workflow_path.read_bytes() == before

        code, _, stderr = run(["workflows", "add-agent", "flow", "tenant_checker"], input_fn=answers("", "", "", ))
        assert code == 2 and "no valid mapping" in stderr
        assert env.workflow_path.read_bytes() == before

        code, stdout, stderr = run(["workflows", "add-agent", "flow", "tenant_checker"], input_fn=answers('literal:"acme"'))
        assert code == 0, stderr
        assert _node(_workflow(env), "tenant_checker")["input_mappings"] == {"tenant": {"literal": "acme"}}


def test_registration_failure_is_reported_and_a_repeat_completes_registration(env):
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "unknown agent"})

    client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(failing))
    code, _, stderr = cli(
        env.platform, ["workflows", "add-agent", "flow", "external_quality_checker"], client=client, token="alice-token",
    )
    assert code == 2 and "registration failed" in stderr and "422" in stderr and "repeat the command" in stderr
    assert len(_workflow(env)["nodes"]) == 2  # validated and persisted

    code, stdout, stderr = env.run(["workflows", "add-agent", "flow", "external_quality_checker"])
    assert code == 0, stderr
    assert json.loads(stdout)["changed"] is False and json.loads(stdout)["registered"]["version"] == "1.0.1"


def test_api_rejects_a_changed_definition_under_an_existing_version_without_corrupting_state(env):
    headers = {"Authorization": "Bearer alice-token"}
    first = {**BASE_WORKFLOW, "id": "versioned"}
    assert env.client.post("/v1/workflows", json=first, headers=headers).status_code == 200
    changed = {**first, "nodes": first["nodes"] + [{
        "id": "extra", "type": "agent", "agent_id": "external_quality_checker", "input_mappings": {},
    }], "edges": [{"from": "external_text_analysis", "to": "extra"}]}
    response = env.client.post("/v1/workflows", json=changed, headers=headers)
    assert response.status_code == 409
    assert len(env.client.get("/v1/workflows/versioned", headers=headers).json()["nodes"]) == 1


def test_unusable_workflow_is_reported_before_anything_changes(env):
    broken = {**BASE_WORKFLOW, "nodes": [{**BASE_WORKFLOW["nodes"][0], "agent_id": "does_not_exist"}]}
    env.workflow_path.write_text(yaml.safe_dump(broken), encoding="utf-8")
    before = env.workflow_path.read_bytes()
    code, _, stderr = env.run(["workflows", "add-agent", "flow", "external_quality_checker"])
    assert code == 2 and "existing workflow is invalid" in stderr
    assert env.workflow_path.read_bytes() == before


# ----------------------------------------------------------------- interactive runs


def test_interactive_run_prompts_for_inferred_input_and_records_history(env):
    assert env.run(["workflows", "add-agent", "flow", "external_quality_checker"])[0] == 0
    reader = answers("Interactive workflow text")
    code, stdout, stderr = env.run(["runs", "start", "--workflow", "flow", "--interactive"], input_fn=reader)
    assert code == 0, stderr
    assert reader.prompts == ["Enter the text you want to analyze: "]
    summary = json.loads(stdout)
    run_id = summary["run_id"]
    assert summary["status"] == "succeeded" and summary["workflow_id"] == "flow"

    stored = env.repository.get_run(run_id)
    assert stored["owner_id"] == "alice" and stored["status"] == "succeeded"
    assert stored["payload"]["node_outputs"]["external_text_analysis"]["summary"] == "Interactive workflow text"
    events = env.repository.events(run_id)
    assert [(item["node_id"], item["status"]) for item in events] == [
        ("external_text_analysis", "succeeded"), ("external_quality_checker", "succeeded"),
    ]
    code, stdout, _ = env.run(["runs", "events", run_id])
    assert code == 0 and len(json.loads(stdout)) == 2


def test_file_input_mode_is_still_supported_and_preserves_ownership(env, tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps({"text": "from a file"}), encoding="utf-8")
    code, stdout, stderr = env.run(["runs", "start", "--workflow", "flow", "--input", str(input_path)])
    assert code == 0, stderr
    summary = json.loads(stdout)
    assert summary["final_output"]["summary"] == "from a file"
    assert env.repository.get_run(summary["run_id"])["owner_id"] == "alice"


def test_run_start_requires_exactly_one_input_mode(env, tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli(env.platform, ["runs", "start", "--workflow", "flow"])
    with pytest.raises(SystemExit):
        cli(env.platform, ["runs", "start", "--workflow", "flow", "--input", str(input_path), "--interactive"])


def test_interactive_run_enforces_authentication_and_ownership(env):
    reader = answers("secret text")
    code, _, stderr = env.run(["runs", "start", "--workflow", "flow", "--interactive"], token=None, input_fn=reader)
    assert code == 2 and "401" in stderr
    assert reader.prompts == []  # nothing is prompted before the authenticated workflow lookup succeeds

    code, stdout, stderr = env.run(["runs", "start", "--workflow", "flow", "--interactive"], input_fn=answers("alice text"))
    assert code == 0, stderr
    run_id = json.loads(stdout)["run_id"]
    code, _, stderr = env.run(["runs", "show", run_id], token="bob-token")
    assert code == 2 and "404" in stderr
    code, _, stderr = env.run(["runs", "events", run_id], token="bob-token")
    assert code == 2 and "404" in stderr
    code, _, _ = env.run(["runs", "show", run_id])
    assert code == 0


def test_interactive_run_reports_unknown_workflow_and_failed_runs(env):
    code, _, stderr = env.run(["runs", "start", "--workflow", "nope", "--interactive"], input_fn=answers("x"))
    assert code == 2 and "404" in stderr

    (env.external_a / "agent.py").write_text(TEXT_ANALYSIS_SOURCE + "\n# edited after approval\n", encoding="utf-8")
    code, stdout, stderr = env.run(["runs", "start", "--workflow", "flow", "--interactive"], input_fn=answers("text"))
    assert code == 0, stderr
    failed = json.loads(stdout)
    assert failed["status"] == "failed" and "source changed" in str(failed["error"])
    assert [item["status"] for item in env.repository.events(failed["run_id"])] == ["failed"]


def test_interactive_run_supports_approval_and_resume(env):
    approval = {
        "id": "approval_flow", "version": "1.0.0",
        "nodes": [
            BASE_WORKFLOW["nodes"][0],
            {"id": "approve", "type": "human_approval", "approval_payload_path": "node_outputs.external_text_analysis"},
        ],
        "edges": [{"from": "external_text_analysis", "to": "approve"}],
    }
    path = env.tmp_path / "approval_flow.yaml"
    path.write_text(yaml.safe_dump(approval, sort_keys=False), encoding="utf-8")
    code, _, stderr = env.run(["workflows", "register", str(path)])
    assert code == 0, stderr

    code, stdout, stderr = env.run(["runs", "start", "--workflow", "approval_flow", "--interactive"], input_fn=answers("needs approval"))
    assert code == 0, stderr
    paused = json.loads(stdout)
    assert paused["status"] == "waiting_for_approval"
    assert f"approvals resume {paused['run_id']}" in stderr

    code, _, _ = env.run(["approvals", "resume", paused["run_id"], "--decision", "approve"], token="bob-token")
    assert code == 2
    code, stdout, stderr = env.run(["approvals", "resume", paused["run_id"], "--decision", "approve"])
    assert code == 0, stderr
    assert json.loads(stdout)["status"] == "succeeded"


def test_interactive_run_falls_back_to_a_json_prompt_when_fields_cannot_be_inferred():
    workflow = {
        "id": "nested", "version": "1.0.0",
        "nodes": [{"id": "step", "type": "agent", "agent_id": "any_agent", "input_mappings": {"value": {"path": "workflow_input.payload.value"}}}],
        "edges": [],
    }
    posted = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/workflows/nested":
            return httpx.Response(200, json=workflow)
        if request.url.path == "/v1/agents/any_agent":
            return httpx.Response(200, json={"input_schema": {"type": "object", "properties": {"value": {"type": "string"}}}})
        if request.url.path == "/v1/runs":
            posted.append(json.loads(request.content))
            return httpx.Response(200, json={"run_id": "r-1", "workflow_id": "nested", "status": "succeeded", "payload": {"final_output": {"ok": True}}})
        return httpx.Response(500, json={"detail": "unexpected"})

    client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handler))
    stdout, stderr = io.StringIO(), io.StringIO()
    reader = answers('{"payload": {"value": "x"}}')
    code = main(["runs", "start", "--workflow", "nested", "--interactive"], client=client, stdout=stdout, stderr=stderr, input_fn=reader)
    assert code == 0, stderr.getvalue()
    assert "JSON object" in reader.prompts[0]
    assert posted == [{"workflow_id": "nested", "inputs": {"payload": {"value": "x"}}}]
    assert json.loads(stdout.getvalue())["run_id"] == "r-1"


def test_interactive_run_rejects_invalid_json_input():
    workflow = {"id": "nested", "nodes": [{"id": "step", "type": "agent", "agent_id": "a", "input_mappings": {"v": {"path": "workflow_input.a.b"}}}], "edges": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/workflows/nested":
            return httpx.Response(200, json=workflow)
        return httpx.Response(404, json={"detail": "agent not found"})

    client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handler))
    stderr = io.StringIO()
    code = main(["runs", "start", "--workflow", "nested", "--interactive"], client=client, stdout=io.StringIO(), stderr=stderr, input_fn=answers("not json"))
    assert code == 2 and "JSON object" in stderr.getvalue()


# ------------------------------------------------------------------ pure helpers


def test_name_matching_and_type_compatibility_rules():
    assert name_score("summary", "summary") == 3
    assert name_score("analysis_status", "status") == 2
    assert name_score("original_text", "text") == 2
    assert name_score("word_count", "character_count") == 0
    assert name_score("count", "word_count") == 2
    assert types_compatible(frozenset({"integer"}), frozenset({"number"})) is True
    assert types_compatible(frozenset({"number"}), frozenset({"integer"})) is False
    assert types_compatible(None, frozenset({"string"})) is None
