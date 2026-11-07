import asyncio
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient
import yaml

from app.api.app import create_app
from app.cli import build_parser, main
from app.registry import AgentLoader, AgentRegistry
from app.registry.external_connector import project_plugin_namespace
from app.runtime.runner import AgentRunner
from app.sdk.contracts import AgentRequest
from app.storage.repository import ExecutionRepository


TEXT_ANALYSIS_SOURCE = '''\
from pathlib import Path

Path(__file__).with_name("imported.marker").write_text("module imported", encoding="utf-8")


class TextAnalysisAgent:
    def run(self, payload):
        text = payload.get("text", "")
        count = len(text.split())
        calls_file = Path(__file__).with_name("invocations.txt")
        calls = int(calls_file.read_text(encoding="utf-8")) if calls_file.exists() else 0
        calls_file.write_text(str(calls + 1), encoding="utf-8")
        return {
            "summary": text,
            "word_count": count,
            "character_count": len(text),
            "most_frequent_words": [{"word": "text", "count": 1}],
            "status": "success",
        }
'''


def _projects(tmp_path: Path):
    platform = tmp_path / "platform"
    external = tmp_path / "external_agent_demo"
    (platform / "plugins" / "manifests").mkdir(parents=True)
    (platform / "plugins" / "examples").mkdir(parents=True)
    (platform / "plugins" / "__init__.py").write_text('"""test plugins"""\n', encoding="utf-8")
    (platform / "plugins" / "examples" / "__init__.py").write_text('"""test examples"""\n', encoding="utf-8")
    external.mkdir()
    source = external / "agent.py"
    source.write_text(TEXT_ANALYSIS_SOURCE, encoding="utf-8")
    test_input = external / "input.json"
    test_input.write_text(json.dumps({"text": "This is sample text for analysis."}), encoding="utf-8")
    return platform, external, source, test_input


def _connect(platform: Path, external: Path, test_input: Path | None = None, *extra: str):
    stdout, stderr = io.StringIO(), io.StringIO()
    args = ["--project-root", str(platform), "agents", "connect", "--path", str(external)]
    if test_input is not None:
        args.extend(["--test-input", str(test_input)])
    args.extend(extra)
    code = main(args, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_connect_requires_explicit_trust_before_import_or_execution(tmp_path):
    platform, external, source, test_input = _projects(tmp_path)
    original_source = source.read_bytes()
    code, _, stderr = _connect(platform, external, test_input)
    assert code == 2
    assert "not been approved" in stderr
    assert not (external / "imported.marker").exists()
    assert not (platform / "plugins" / "manifests" / "external_text_analysis.yaml").exists()
    assert source.read_bytes() == original_source


def test_text_analysis_connects_runs_and_flows_through_api_workflow_and_history(tmp_path):
    platform, external, source, test_input = _projects(tmp_path)
    original_source = source.read_bytes()

    code, stdout, stderr = _connect(platform, external, test_input, "--trust")
    assert code == 0, stderr
    connected = json.loads(stdout)
    assert connected["id"] == "external_text_analysis"
    assert connected["entry_point"] == "agent.py:TextAnalysisAgent"
    assert connected["test_invocation"]["status"] == "succeeded"
    assert connected["test_invocation"]["output"] == {
        "summary": "This is sample text for analysis.",
        "word_count": 6,
        "character_count": len("This is sample text for analysis."),
        "most_frequent_words": [{"word": "text", "count": 1}],
        "status": "success",
    }
    manifest = platform / "plugins" / "manifests" / "external_text_analysis.yaml"
    adapter = platform / "plugins" / "examples" / "connected_external_text_analysis" / "adapter.py"
    assert manifest.is_file() and adapter.is_file()
    manifest_data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    assert manifest_data["input_schema"]["properties"]["text"] == {"type": "string"}
    assert "required" not in manifest_data["input_schema"]
    assert "invoke_python_agent" in adapter.read_text(encoding="utf-8")
    assert "class TextAnalysisAgent" not in adapter.read_text(encoding="utf-8")
    assert source.read_bytes() == original_source

    # Existing manifest validation discovers the ID locally without needing the API.
    validation_stdout = io.StringIO()
    validation_stderr = io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "validate", "external_text_analysis"],
        stdout=validation_stdout, stderr=validation_stderr,
    )
    assert code == 0, validation_stderr.getvalue()
    assert json.loads(validation_stdout.getvalue())["id"] == "external_text_analysis"

    with project_plugin_namespace(platform):
        registry = AgentRegistry()
        AgentLoader(registry, platform / "plugins" / "manifests").load_all()
        runner_result = asyncio.run(AgentRunner(registry).run(
            "external_text_analysis",
            AgentRequest(run_id="direct-run", inputs={"text": "Direct runner input."}),
        ))
        assert runner_result.status == "succeeded"
        assert runner_result.output["summary"] == "Direct runner input."

        repository = ExecutionRepository(str(tmp_path / "history.db"))
        with TestClient(create_app(repository, manifests_dir=platform / "plugins" / "manifests")) as client:
            listed = client.get("/v1/agents").json()
            assert any(item["id"] == "external_text_analysis" for item in listed)
            workflow = {
                "id": "external_analysis_flow",
                "nodes": [{
                    "id": "analyze",
                    "type": "agent",
                    "agent_id": "external_text_analysis",
                    "input_mappings": {"text": {"path": "workflow_input.text"}},
                }],
                "edges": [],
            }
            assert client.post("/v1/workflows", json=workflow).status_code == 200
            run = client.post("/v1/runs", json={"workflow_id": "external_analysis_flow", "inputs": {"text": "Workflow integration text."}}).json()
            assert run["status"] == "succeeded"
            output = run["payload"]["final_output"]
            assert output["summary"] == "Workflow integration text."
            assert output["word_count"] == 3
            events = client.get(f"/v1/runs/{run['run_id']}/events").json()
            assert any(event["node_id"] == "analyze" and event["status"] == "succeeded" for event in events)
            stored_run = repository.get_run(run["run_id"])
            assert stored_run["status"] == "succeeded"
            assert stored_run["payload"]["node_outputs"]["analyze"]["most_frequent_words"] == [{"word": "text", "count": 1}]


def test_connect_is_idempotent_and_disconnect_preserves_external_project(tmp_path):
    platform, external, source, test_input = _projects(tmp_path)
    original_source = source.read_bytes()
    code, stdout, stderr = _connect(platform, external, test_input, "--trust")
    assert code == 0, stderr
    assert (external / "invocations.txt").read_text(encoding="utf-8") == "1"
    manifest = platform / "plugins" / "manifests" / "external_text_analysis.yaml"
    manifest_data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    manifest_data["input_schema"]["required"] = ["text"]
    manifest.write_text(yaml.safe_dump(manifest_data, sort_keys=False), encoding="utf-8")

    code, stdout, stderr = _connect(platform, external, test_input, "--trust")
    assert code == 0, stderr
    repeated = json.loads(stdout)
    assert repeated["already_connected"] is True
    assert yaml.safe_load(manifest.read_text(encoding="utf-8"))["input_schema"]["required"] == ["text"]
    assert (external / "invocations.txt").read_text(encoding="utf-8") == "1"

    validation = io.StringIO()
    assert main(["--project-root", str(platform), "agents", "validate", "external_text_analysis"], stdout=validation, stderr=io.StringIO()) == 0
    code = main(["--project-root", str(platform), "agents", "disconnect", "external_text_analysis"], stdout=io.StringIO(), stderr=io.StringIO())
    assert code == 0
    assert not (platform / "plugins" / "manifests" / "external_text_analysis.yaml").exists()
    assert not (platform / "plugins" / "examples" / "connected_external_text_analysis" / "adapter.py").exists()
    assert external.is_dir() and source.read_bytes() == original_source


def test_connect_refuses_to_overwrite_unrelated_registration(tmp_path):
    platform, external, _, _ = _projects(tmp_path)
    manifest = platform / "plugins" / "manifests" / "external_text_analysis.yaml"
    original = "id: unrelated\nname: Do not replace\n"
    manifest.write_text(original, encoding="utf-8")
    code, _, stderr = _connect(platform, external, None, "--trust")
    assert code == 2 and "already exists" in stderr
    assert manifest.read_text(encoding="utf-8") == original
    assert not (platform / "plugins" / "examples" / "connected_external_text_analysis").exists()
    assert not (external / "imported.marker").exists()


def test_connected_agent_rejects_python_source_changed_after_approval(tmp_path):
    platform, external, source, test_input = _projects(tmp_path)
    code, _, stderr = _connect(platform, external, test_input, "--trust")
    assert code == 0, stderr
    source.write_text(source.read_text(encoding="utf-8") + "\n# changed after approval\n", encoding="utf-8")

    with project_plugin_namespace(platform):
        registry = AgentRegistry()
        AgentLoader(registry, platform / "plugins" / "manifests").load_all()
        result = asyncio.run(AgentRunner(registry).run(
            "external_text_analysis",
            AgentRequest(run_id="modified-source-run", inputs={"text": "must not execute"}),
        ))
    assert result.status == "failed"
    assert "source changed since connection approval" in result.error.message


def test_connect_reports_invalid_paths_ambiguous_entries_and_safe_ids(tmp_path):
    platform, external, _, _ = _projects(tmp_path)
    code, _, stderr = _connect(platform, tmp_path / "missing", None, "--trust")
    assert code == 2 and "does not exist" in stderr

    (external / "other.py").write_text(
        "class OtherAgent:\n    def run(self, payload):\n        return {'other': True}\n",
        encoding="utf-8",
    )
    code, _, stderr = _connect(platform, external, None, "--trust")
    assert code == 2 and "ambiguous" in stderr and "--entry-point" in stderr
    assert not (external / "imported.marker").exists()

    code, _, stderr = _connect(platform, external, None, "--entry-point", "agent.py:TextAnalysisAgent", "--id", "../escape", "--trust")
    assert code == 2 and "agent ID" in stderr
    assert not (tmp_path / "escape.yaml").exists()


def test_connect_supports_a_module_level_run_function(tmp_path):
    platform, external, _, _ = _projects(tmp_path)
    (external / "agent.py").write_text(
        "def run(payload):\n    return {'echo': payload.get('text', '')}\n",
        encoding="utf-8",
    )
    test_input = external / "function_input.json"
    test_input.write_text(json.dumps({"text": "function interface"}), encoding="utf-8")
    code, stdout, stderr = _connect(
        platform, external, test_input,
        "--entry-point", "agent.py:run", "--id", "external_function_agent", "--trust",
    )
    assert code == 0, stderr
    result = json.loads(stdout)
    assert result["entry_point"] == "agent.py:run"
    assert result["test_invocation"]["output"] == {"echo": "function interface"}


def test_connect_loads_package_relative_helpers_from_approved_source(tmp_path):
    platform, external, _, _ = _projects(tmp_path)
    (external / "agent.py").write_text(
        "from .helper import summarize\n\n"
        "class RelativeAgent:\n"
        "    def run(self, payload):\n"
        "        return summarize(payload['text'])\n",
        encoding="utf-8",
    )
    (external / "helper.py").write_text(
        "def summarize(text):\n"
        "    return {'summary': text, 'status': 'success'}\n",
        encoding="utf-8",
    )
    test_input = external / "relative_input.json"
    test_input.write_text(json.dumps({"text": "relative helper"}), encoding="utf-8")
    code, stdout, stderr = _connect(
        platform, external, test_input, "--id", "external_relative_agent", "--trust",
    )
    assert code == 0, stderr
    assert json.loads(stdout)["test_invocation"]["output"] == {
        "summary": "relative helper", "status": "success",
    }


def test_parser_exposes_connect_and_disconnect_commands():
    parsed = build_parser().parse_args([
        "--project-root", "C:/platform", "agents", "connect", "--path", "C:/external", "--trust",
    ])
    assert (parsed.command, parsed.action, parsed.trust) == ("agents", "connect", True)
    disconnected = build_parser().parse_args(["agents", "disconnect", "external_agent"])
    assert (disconnected.action, disconnected.agent_id) == ("disconnect", "external_agent")


def test_connect_by_agent_id_or_name_resolves_catalog_metadata_and_requires_trust(tmp_path):
    platform, external, source, test_input = _projects(tmp_path)
    original_source = source.read_bytes()
    (platform / "workflow_definitions").mkdir(parents=True, exist_ok=True)

    code, stdout, stderr = _connect(platform, external, test_input, "--trust")
    assert code == 0, stderr
    catalog_path = platform / "plugins" / "connection_catalog.json"
    assert catalog_path.is_file()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert "external_text_analysis" in catalog
    assert catalog["external_text_analysis"]["name"] == "Text Analysis Agent"
    assert catalog["external_text_analysis"]["project_path"] == str(external.resolve())
    assert catalog["external_text_analysis"]["entry_point"] == "agent.py:TextAnalysisAgent"

    # Save a workflow referencing external_text_analysis
    wf_file = platform / "workflow_definitions" / "text_flow.yaml"
    wf_file.write_text(
        yaml.safe_dump(
            {
                "id": "text_flow",
                "version": "1.0.0",
                "nodes": [
                    {
                        "id": "external_text_analysis",
                        "type": "agent",
                        "agent_id": "external_text_analysis",
                        "input_mappings": {"text": {"path": "workflow_input.text"}},
                    }
                ],
                "edges": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    # Normal disconnect removes manifest and adapter but preserves catalog entry
    disc_out, disc_err = io.StringIO(), io.StringIO()
    assert main(
        ["--project-root", str(platform), "agents", "disconnect", "external_text_analysis"],
        stdout=disc_out,
        stderr=disc_err,
    ) == 0
    assert not (platform / "plugins" / "manifests" / "external_text_analysis.yaml").exists()
    assert not (platform / "plugins" / "examples" / "connected_external_text_analysis").exists()
    assert "external_text_analysis" in json.loads(catalog_path.read_text(encoding="utf-8"))
    assert yaml.safe_load(wf_file.read_text(encoding="utf-8"))["nodes"][0]["status"] == "disconnected"

    invocations_file = external / "invocations.txt"
    assert invocations_file.read_text(encoding="utf-8") == "1"

    # 1. Non-interactive reconnect by ID without --trust is rejected before executing code
    out1, err1 = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect", "external_text_analysis"],
        stdout=out1,
        stderr=err1,
    )
    assert code == 2
    assert "not been approved" in err1.getvalue()
    assert "Resolved saved connection metadata" in err1.getvalue()
    assert str(external.resolve()) in err1.getvalue()
    assert "agent.py:TextAnalysisAgent" in err1.getvalue()
    assert invocations_file.read_text(encoding="utf-8") == "1"

    # 2. Interactive reconnect cancelled at trust prompt does not execute code
    out2, err2 = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect", "external_text_analysis"],
        stdout=out2,
        stderr=err2,
        input_fn=lambda prompt: "CANCEL",
    )
    assert code == 2
    assert "connection cancelled" in err2.getvalue()
    assert invocations_file.read_text(encoding="utf-8") == "1"

    # 3. Interactive reconnect with TRUST approval succeeds and restores workflow node
    out3, err3 = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect", "external_text_analysis"],
        stdout=out3,
        stderr=err3,
        input_fn=lambda prompt: "TRUST",
    )
    assert code == 0, err3.getvalue()
    reconnected = json.loads(out3.getvalue())
    assert reconnected["id"] == "external_text_analysis"
    assert reconnected["reconnected_from_catalog"] is True
    assert reconnected["already_connected"] is False
    assert reconnected["restored_workflows"] == {"text_flow": ["external_text_analysis"]}
    assert invocations_file.read_text(encoding="utf-8") == "2"
    assert (platform / "plugins" / "manifests" / "external_text_analysis.yaml").is_file()
    assert yaml.safe_load(wf_file.read_text(encoding="utf-8"))["nodes"][0]["status"] == "available"
    assert source.read_bytes() == original_source

    # 4. Reconnect by display name ("Text Analysis Agent") with --name override and --trust
    assert main(
        ["--project-root", str(platform), "agents", "disconnect", "external_text_analysis"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0
    out4, err4 = io.StringIO(), io.StringIO()
    code = main(
        [
            "--project-root", str(platform),
            "agents", "connect", "Text Analysis Agent",
            "--name", "Custom Text Analyzer",
            "--trust",
        ],
        stdout=out4,
        stderr=err4,
    )
    assert code == 0, err4.getvalue()
    reconnected_by_name = json.loads(out4.getvalue())
    assert reconnected_by_name["id"] == "external_text_analysis"
    assert reconnected_by_name["name"] == "Custom Text Analyzer"


def test_interactive_connect_menu_with_disconnected_agents_and_new_project_option(tmp_path):
    platform, external_one, _, test_input_one = _projects(tmp_path)
    external_two = tmp_path / "external_quality_demo"
    external_two.mkdir()
    (external_two / "agent.py").write_text(
        "class QualityCheckerAgent:\n"
        "    def run(self, payload):\n"
        "        return {'valid': True, 'summary': payload.get('text', '')}\n",
        encoding="utf-8",
    )
    (external_two / "input.json").write_text(json.dumps({"text": "sample"}), encoding="utf-8")

    external_three = tmp_path / "external_third_demo"
    external_three.mkdir()
    (external_three / "agent.py").write_text(
        "class ThirdAgent:\n"
        "    def run(self, payload):\n"
        "        return {'third': payload.get('text', '')}\n",
        encoding="utf-8",
    )
    (external_three / "input.json").write_text(json.dumps({"text": "third"}), encoding="utf-8")

    # Connect agent 1 and agent 2
    assert _connect(platform, external_one, test_input_one, "--trust")[0] == 0
    assert _connect(platform, external_two, external_two / "input.json", "--trust")[0] == 0

    # Disconnect only external_text_analysis; external_quality_checker stays actively connected
    assert main(
        ["--project-root", str(platform), "agents", "disconnect", "external_text_analysis"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0

    # 1. Interactive menu shows only disconnected external_text_analysis (not active external_quality_checker)
    answers = iter(["1", "TRUST"])
    out1, err1 = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect"],
        stdout=out1,
        stderr=err1,
        input_fn=lambda prompt: next(answers),
    )
    assert code == 0, err1.getvalue()
    menu_text = err1.getvalue()
    assert "Known disconnected agents available to connect:" in menu_text
    assert "1. external_text_analysis" in menu_text
    assert "2. Connect a new external agent project" in menu_text
    assert "external_quality_checker" not in menu_text
    assert json.loads(out1.getvalue())["id"] == "external_text_analysis"

    # 2. Disconnect again and select by agent ID in the interactive menu
    assert main(
        ["--project-root", str(platform), "agents", "disconnect", "external_text_analysis"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0
    answers_by_id = iter(["external_text_analysis", "TRUST"])
    out2, err2 = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect"],
        stdout=out2,
        stderr=err2,
        input_fn=lambda prompt: next(answers_by_id),
    )
    assert code == 0, err2.getvalue()
    assert json.loads(out2.getvalue())["id"] == "external_text_analysis"

    # 3. Disconnect again and choose option 2 ("Connect a new external agent project")
    assert main(
        ["--project-root", str(platform), "agents", "disconnect", "external_text_analysis"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0
    answers_new = iter(["2", str(external_three), "TRUST"])
    out3, err3 = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect"],
        stdout=out3,
        stderr=err3,
        input_fn=lambda prompt: next(answers_new),
    )
    assert code == 0, err3.getvalue()
    assert json.loads(out3.getvalue())["id"] == "external_third"
    assert (platform / "plugins" / "manifests" / "external_third.yaml").is_file()


def test_connect_detects_already_connected_agent_by_id_or_name(tmp_path):
    platform, external, _, test_input = _projects(tmp_path)
    assert _connect(platform, external, test_input, "--trust")[0] == 0
    assert (external / "invocations.txt").read_text(encoding="utf-8") == "1"

    # Connect by ID when already connected (even without --trust)
    out1, err1 = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect", "external_text_analysis"],
        stdout=out1,
        stderr=err1,
    )
    assert code == 0, err1.getvalue()
    payload = json.loads(out1.getvalue())
    assert payload["already_connected"] is True
    assert payload["status"] == "already_connected"
    assert "already connected" in payload["message"].lower()
    assert "already connected" in err1.getvalue().lower()
    assert (external / "invocations.txt").read_text(encoding="utf-8") == "1"

    # Connect by display name when already connected
    out2, err2 = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect", "Text Analysis Agent"],
        stdout=out2,
        stderr=err2,
    )
    assert code == 0, err2.getvalue()
    assert json.loads(out2.getvalue())["already_connected"] is True


def test_connect_unknown_id_and_missing_saved_source_folder(tmp_path):
    platform, external, _, test_input = _projects(tmp_path)

    # 1. Unknown agent ID explains how to connect a new project
    out_unk, err_unk = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect", "nonexistent_agent_id", "--trust"],
        stdout=out_unk,
        stderr=err_unk,
    )
    assert code == 2
    assert "unknown agent ID or name" in err_unk.getvalue()
    assert "agents connect --path" in err_unk.getvalue()

    # 2. Connect, normal-disconnect, then delete the external source directory
    assert _connect(platform, external, test_input, "--trust")[0] == 0
    assert main(
        ["--project-root", str(platform), "agents", "disconnect", "external_text_analysis"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0

    moved_external = tmp_path / "moved_external_demo"
    external.rename(moved_external)

    out_missing, err_missing = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect", "external_text_analysis", "--trust"],
        stdout=out_missing,
        stderr=err_missing,
    )
    assert code == 2
    assert "saved external project path for agent 'external_text_analysis' does not exist" in err_missing.getvalue()
    assert "agents connect --path" in err_missing.getvalue()

    # 3. Restore directory but break the saved entry point; verify validation fails before code import
    moved_external.rename(external)
    (external / "imported.marker").unlink(missing_ok=True)
    (external / "agent.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('imported.marker').write_text('imported', encoding='utf-8')\n"
        "class RenamedAgent:\n"
        "    def run(self, payload):\n"
        "        return {'ok': True}\n",
        encoding="utf-8",
    )
    out_ep, err_ep = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect", "external_text_analysis", "--trust"],
        stdout=out_ep,
        stderr=err_ep,
    )
    assert code == 2
    assert "entry point 'agent.py:TextAnalysisAgent' was not discovered" in err_ep.getvalue()
    assert not (external / "imported.marker").exists()


def test_purge_removes_catalog_entry_and_normal_disconnect_backfills_catalog(tmp_path):
    platform, external, _, test_input = _projects(tmp_path)
    assert _connect(platform, external, test_input, "--trust")[0] == 0
    catalog_path = platform / "plugins" / "connection_catalog.json"

    # Simulate legacy connected agent by deleting connection_catalog.json before normal disconnect
    catalog_path.unlink()
    assert not catalog_path.exists()

    # Normal disconnect extracts metadata from manifest + adapter and saves to catalog before removing files
    assert main(
        ["--project-root", str(platform), "agents", "disconnect", "external_text_analysis"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0
    assert catalog_path.is_file()
    assert "external_text_analysis" in json.loads(catalog_path.read_text(encoding="utf-8"))

    # Reconnect by ID using the backfilled catalog entry
    assert main(
        ["--project-root", str(platform), "agents", "connect", "external_text_analysis", "--trust"],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0

    # Permanent purge removes the catalog entry
    purge_out, purge_err = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "disconnect", "external_text_analysis", "--purge", "--yes"],
        stdout=purge_out,
        stderr=purge_err,
    )
    assert code == 0, purge_err.getvalue()
    purge_result = json.loads(purge_out.getvalue())
    assert purge_result["deleted"]["connection_catalog_entry"] is True
    assert "external_text_analysis" not in json.loads(catalog_path.read_text(encoding="utf-8"))

    # Reconnecting by ID now fails as unknown agent
    out_after, err_after = io.StringIO(), io.StringIO()
    code = main(
        ["--project-root", str(platform), "agents", "connect", "external_text_analysis", "--trust"],
        stdout=out_after,
        stderr=err_after,
    )
    assert code == 2
    assert "unknown agent ID or name" in err_after.getvalue()

