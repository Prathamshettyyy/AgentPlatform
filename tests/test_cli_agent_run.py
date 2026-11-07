import io
import json
from pathlib import Path

import httpx

from app.cli import build_parser, main


def _client(metadata, run_record, *, error_status: int | None = None):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if error_status is not None:
            return httpx.Response(error_status, json={"detail": "invalid credentials"})
        if request.method == "GET" and request.url.path == "/v1/agents/external_text_analysis":
            return httpx.Response(200, json=metadata)
        if request.method == "POST" and request.url.path == "/v1/agents/external_text_analysis/runs":
            return httpx.Response(200, json=run_record)
        if request.method == "GET" and request.url.path == f"/v1/runs/{run_record['run_id']}":
            return httpx.Response(200, json=run_record)
        if request.method == "GET" and request.url.path == f"/v1/runs/{run_record['run_id']}/events":
            return httpx.Response(200, json=[{
                "run_id": run_record["run_id"],
                "node_id": run_record["payload"]["agent_id"],
                "status": run_record["status"],
                "created_at": "now",
                "payload": {"output": run_record["payload"].get("final_output", {})},
            }])
        return httpx.Response(404, json={"detail": "not found"})

    client = httpx.Client(
        base_url="http://testserver",
        transport=httpx.MockTransport(handler),
    )
    return client, requests


def _metadata():
    return {
        "id": "external_text_analysis",
        "name": "External Text Analysis",
        "input_schema": {
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
    }


def _record(output):
    return {
        "run_id": "direct-run-1",
        "workflow_id": None,
        "workflow_version": None,
        "thread_id": "direct-run-1",
        "owner_id": "alice",
        "status": "succeeded",
        "payload": {"agent_id": "external_text_analysis", "final_output": output},
    }


def test_cli_agents_run_interactive_prompts_from_schema_and_displays_output():
    output = {
        "summary": "The supplied text is factual.",
        "word_count": 5,
        "character_count": 32,
        "most_frequent_words": [{"word": "factual", "count": 1}],
        "status": "success",
    }
    client, requests = _client(_metadata(), _record(output))
    stdout, stderr, prompts = io.StringIO(), io.StringIO(), []
    answers = iter(["The supplied text is factual."])
    code = main(
        ["--token", "local-dev-token-2026", "agents", "run", "external_text_analysis", "--interactive"],
        client=client,
        stdout=stdout,
        stderr=stderr,
        input_fn=lambda prompt: (prompts.append(prompt), next(answers))[1],
    )
    assert code == 0, stderr.getvalue()
    assert prompts == ["Enter the text you want to analyze: "]
    assert requests[0].method == "GET"
    assert requests[1].method == "POST"
    assert requests[1].headers["Authorization"] == "Bearer local-dev-token-2026"
    assert json.loads(requests[1].content)["inputs"] == {"text": "The supplied text is factual."}
    result = json.loads(stdout.getvalue())
    assert result["run_id"] == "direct-run-1"
    assert result["agent_id"] == "external_text_analysis"
    assert result["final_output"] == output
    show_stdout, events_stdout = io.StringIO(), io.StringIO()
    assert main(["runs", "show", "direct-run-1"], client=client, stdout=show_stdout, stderr=stderr) == 0
    assert json.loads(show_stdout.getvalue())["final_output"] == output
    assert main(["runs", "events", "direct-run-1"], client=client, stdout=events_stdout, stderr=stderr) == 0
    assert json.loads(events_stdout.getvalue())[0]["node_id"] == "external_text_analysis"


def test_cli_agents_run_accepts_json_file_and_uses_same_api_path(tmp_path: Path):
    input_file = tmp_path / "input.json"
    input_file.write_text(json.dumps({"text": "From a JSON file."}), encoding="utf-8")
    client, requests = _client(_metadata(), _record({"summary": "From a JSON file."}))
    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(
        ["agents", "run", "external_text_analysis", "--input-file", str(input_file)],
        client=client,
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0, stderr.getvalue()
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/agents/external_text_analysis/runs"
    assert json.loads(requests[0].content)["inputs"] == {"text": "From a JSON file."}
    assert json.loads(stdout.getvalue())["final_output"]["summary"] == "From a JSON file."


def test_cli_interactive_uses_json_when_schema_is_missing_or_ambiguous():
    metadata = {"id": "external_text_analysis", "name": "External Agent", "input_schema": {}}
    client, requests = _client(metadata, _record({"status": "success"}))
    stdout, stderr, prompts = io.StringIO(), io.StringIO(), []
    answers = iter(['{"custom": "value"}'])
    code = main(
        ["agents", "run", "external_text_analysis", "--interactive"],
        client=client,
        stdout=stdout,
        stderr=stderr,
        input_fn=lambda prompt: (prompts.append(prompt), next(answers))[1],
    )
    assert code == 0, stderr.getvalue()
    assert prompts == ["Enter agent input as a JSON object: "]
    assert json.loads(requests[1].content)["inputs"] == {"custom": "value"}


def test_cli_interactive_rejects_non_object_json_for_ambiguous_schema():
    metadata = {"id": "external_text_analysis", "name": "External Agent", "input_schema": {}}
    client, requests = _client(metadata, _record({}))
    stderr = io.StringIO()
    code = main(
        ["agents", "run", "external_text_analysis", "--interactive"],
        client=client,
        stderr=stderr,
        input_fn=lambda _: '["not", "an", "object"]',
    )
    assert code == 2
    assert "must be a JSON object" in stderr.getvalue()
    assert len(requests) == 1


def test_cli_agents_run_reports_authentication_failure_without_fallback_server(tmp_path: Path):
    input_file = tmp_path / "input.json"
    input_file.write_text('{"text":"hello"}', encoding="utf-8")
    client, requests = _client(_metadata(), _record({}), error_status=401)
    stderr = io.StringIO()
    code = main(
        ["agents", "run", "external_text_analysis", "--input-file", str(input_file)],
        client=client,
        stderr=stderr,
    )
    assert code == 2
    assert "API 401" in stderr.getvalue()
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/agents/external_text_analysis/runs"


def test_cli_agents_run_reports_server_unavailable(tmp_path: Path):
    input_file = tmp_path / "input.json"
    input_file.write_text('{"text":"hello"}', encoding="utf-8")
    def offline(_: httpx.Request):
        raise httpx.ConnectError("offline")

    client = httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(offline))
    stderr = io.StringIO()
    code = main(
        ["agents", "run", "external_text_analysis", "--input-file", str(input_file)],
        client=client,
        stderr=stderr,
    )
    assert code == 2
    assert "could not connect" in stderr.getvalue()


def test_cli_parser_supports_direct_agent_run_modes():
    interactive = build_parser().parse_args(["agents", "run", "external_text_analysis", "--interactive"])
    assert interactive.action == "run" and interactive.interactive is True
    from_file = build_parser().parse_args(["agents", "run", "external_text_analysis", "--input-file", "input.json"])
    assert from_file.input_file == "input.json"
