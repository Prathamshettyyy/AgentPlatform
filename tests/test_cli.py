import io
import json
from pathlib import Path

import httpx

from app.cli import build_parser, main


def mock_client(handler):
    return httpx.Client(base_url="http://testserver", transport=httpx.MockTransport(handler))


def test_cli_parser_supports_documented_commands():
    parsed = build_parser().parse_args(["--base-url", "http://localhost:9000", "runs", "start", "--workflow", "code_review", "--input", "input.json"])
    assert parsed.command == "runs"
    assert parsed.action == "start"
    assert parsed.workflow == "code_review"
    parsed_wf = build_parser().parse_args(["workflows", "show", "text_analysis_validation"])
    assert parsed_wf.command == "workflows"
    assert parsed_wf.action == "show"
    assert parsed_wf.workflow_id == "text_analysis_validation"


def test_cli_lists_agents_and_tools_and_handles_api_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/agents":
            return httpx.Response(200, json=[{"id": "source_inspector", "capabilities": ["static_analysis"]}])
        if request.url.path == "/v1/tools":
            return httpx.Response(200, json=[{"id": "tool_echo", "name": "Echo"}])
        if request.url.path == "/v1/agents/missing":
            return httpx.Response(404, json={"detail": "agent not found"})
        return httpx.Response(500, json={"detail": "unexpected path"})

    client = mock_client(handler)
    stdout, stderr = io.StringIO(), io.StringIO()
    assert main(["agents", "list"], client=client, stdout=stdout, stderr=stderr) == 0
    assert json.loads(stdout.getvalue())[0]["id"] == "source_inspector"
    stdout.seek(0); stdout.truncate(0)
    assert main(["tools", "list"], client=client, stdout=stdout, stderr=stderr) == 0
    assert json.loads(stdout.getvalue())[0]["id"] == "tool_echo"
    assert main(["agents", "show", "missing"], client=client, stdout=stdout, stderr=stderr) == 2
    assert "404" in stderr.getvalue()


def test_cli_validates_manifests_and_workflow_without_server():
    stdout, stderr = io.StringIO(), io.StringIO()
    root = Path(__file__).resolve().parent / "sample_platform"
    assert main(["agents", "validate", str(root / "plugins/manifests/manifest_echo.yaml")], stdout=stdout, stderr=stderr) == 0
    assert json.loads(stdout.getvalue())["id"] == "manifest_echo"
    stdout.seek(0); stdout.truncate(0)
    assert main(["tools", "validate", str(root / "plugins/tool_manifests/tool_echo.yaml")], stdout=stdout, stderr=stderr) == 0
    assert json.loads(stdout.getvalue())["id"] == "tool_echo"
    stdout.seek(0); stdout.truncate(0)
    assert main(["--project-root", str(root), "workflows", "validate", str(root / "workflow_definitions/code_review.yaml")], stdout=stdout, stderr=stderr) == 0
    assert json.loads(stdout.getvalue())["id"] == "code_review"


def test_cli_reports_unavailable_server_and_invalid_workflow(tmp_path):
    def offline(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    stderr = io.StringIO()
    assert main(["agents", "list"], client=mock_client(offline), stderr=stderr) == 2
    assert "could not connect" in stderr.getvalue()

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("id: [", encoding="utf-8")
    stderr.seek(0); stderr.truncate(0)
    assert main(["workflows", "validate", str(invalid)], stderr=stderr) == 2
    assert "could not read" in stderr.getvalue()


def test_cli_registers_starts_inspects_events_and_resumes_approval(tmp_path):
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps({"source_code": "def f(): return 1", "api_token": "secret"}), encoding="utf-8")
    workflow_path = Path(__file__).resolve().parent / "sample_platform/workflow_definitions/code_review.yaml"
    run = {
        "run_id": "run-123",
        "workflow_id": "code_review",
        "workflow_version": "1.0.0",
        "thread_id": "run-123",
        "status": "waiting_for_approval",
        "payload": {"__interrupt__": [{"node_id": "approve", "options": ["approve", "reject"]}]},
    }
    events = [{"run_id": "run-123", "node_id": "inspect", "status": "succeeded", "created_at": "now", "payload": {"api_token": "secret"}}]
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST" and request.url.path == "/v1/workflows":
            submitted = json.loads(request.content)
            assert "literal" not in submitted["nodes"][0]["input_mappings"]["source_code"]
            return httpx.Response(200, json={"id": "code_review", "version": "1.0.0"})
        if request.method == "POST" and request.url.path == "/v1/runs":
            return httpx.Response(200, json=run)
        if request.method == "GET" and request.url.path == "/v1/runs/run-123":
            return httpx.Response(200, json=run)
        if request.method == "GET" and request.url.path == "/v1/runs/run-123/events":
            return httpx.Response(200, json=events)
        if request.method == "GET" and request.url.path == "/v1/approvals":
            return httpx.Response(200, json=[run])
        if request.method == "POST" and request.url.path == "/v1/runs/run-123/resume":
            resumed = {**run, "status": "succeeded", "payload": {"final_output": {"approved": True}}}
            return httpx.Response(200, json=resumed)
        return httpx.Response(500, json={"detail": "unexpected path"})

    client = mock_client(handler)
    stdout, stderr = io.StringIO(), io.StringIO()
    sample_root = Path(__file__).resolve().parent / "sample_platform"
    assert main(["--project-root", str(sample_root), "workflows", "register", str(workflow_path)], client=client, stdout=stdout, stderr=stderr) == 0
    assert main(["runs", "start", "--workflow", "code_review", "--input", str(input_path)], client=client, stdout=stdout, stderr=stderr) == 0
    assert "secret" not in stdout.getvalue()
    stdout.seek(0); stdout.truncate(0)
    assert main(["runs", "show", "run-123"], client=client, stdout=stdout, stderr=stderr) == 0
    stdout.seek(0); stdout.truncate(0)
    assert main(["runs", "events", "run-123"], client=client, stdout=stdout, stderr=stderr) == 0
    assert "api_token" not in stdout.getvalue()
    stdout.seek(0); stdout.truncate(0)
    assert main(["approvals", "list"], client=client, stdout=stdout, stderr=stderr) == 0
    stdout.seek(0); stdout.truncate(0)
    assert main(["approvals", "resume", "run-123", "--decision", "approve"], client=client, stdout=stdout, stderr=stderr) == 0
    assert any(request.url.path == "/v1/runs/run-123/resume" for request in requests)


def test_cli_workflows_show_displays_registered_workflow():
    workflow_data = {
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
                },
            },
        ],
        "edges": [
            {
                "from": "external_text_analysis",
                "to": "external_text_analysis_quality_checker",
                "condition": None,
            }
        ],
        "max_steps": 100,
    }

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/v1/workflows/text_analysis_validation":
            return httpx.Response(200, json=workflow_data)
        return httpx.Response(404, json={"detail": "workflow not found"})

    client = mock_client(handler)
    stdout, stderr = io.StringIO(), io.StringIO()
    exit_code = main(["workflows", "show", "text_analysis_validation"], client=client, stdout=stdout, stderr=stderr)
    assert exit_code == 0
    assert not stderr.getvalue()
    output = json.loads(stdout.getvalue())
    assert output["id"] == "text_analysis_validation"
    assert output["version"] == "1.0.0"
    assert len(output["nodes"]) == 2
    assert output["nodes"][0]["id"] == "external_text_analysis"
    assert output["nodes"][0]["input_mappings"] == {"text": {"path": "workflow_input.text"}}
    assert output["nodes"][1]["id"] == "external_text_analysis_quality_checker"
    assert output["nodes"][1]["input_mappings"]["original_text"] == {"path": "workflow_input.text"}
    assert output["nodes"][1]["input_mappings"]["summary"] == {"path": "node_outputs.external_text_analysis.summary"}
    assert output["edges"] == [{"from": "external_text_analysis", "to": "external_text_analysis_quality_checker", "condition": None}]


def test_cli_workflows_show_handles_errors_and_custom_options():
    def not_found_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "workflow not found"})

    stdout, stderr = io.StringIO(), io.StringIO()
    exit_code = main(["workflows", "show", "nonexistent_flow"], client=mock_client(not_found_handler), stdout=stdout, stderr=stderr)
    assert exit_code == 2
    assert "404" in stderr.getvalue()
    assert "workflow not found" in stderr.getvalue()

    def auth_fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "missing or invalid authorization header"})

    stdout, stderr = io.StringIO(), io.StringIO()
    exit_code = main(["workflows", "show", "text_analysis_validation"], client=mock_client(auth_fail_handler), stdout=stdout, stderr=stderr)
    assert exit_code == 2
    assert "401" in stderr.getvalue()
    assert "authorization" in stderr.getvalue()

    def offline_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    stdout, stderr = io.StringIO(), io.StringIO()
    exit_code = main(["workflows", "show", "text_analysis_validation"], client=mock_client(offline_handler), stdout=stdout, stderr=stderr)
    assert exit_code == 2
    assert "could not connect" in stderr.getvalue()

    recorded_requests = []

    def custom_handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(200, json={"id": "custom_flow", "version": "2.0.0", "nodes": [], "edges": []})

    stdout, stderr = io.StringIO(), io.StringIO()
    custom_client = mock_client(custom_handler)
    exit_code = main(
        ["--base-url", "http://custom-host:9999", "--token", "custom-secret-token", "workflows", "show", "custom_flow"],
        client=custom_client,
        stdout=stdout,
        stderr=stderr,
    )
    assert exit_code == 0
    assert len(recorded_requests) == 1
    assert recorded_requests[0].url.path == "/v1/workflows/custom_flow"
    assert recorded_requests[0].headers.get("authorization") == "Bearer custom-secret-token"
    res = json.loads(stdout.getvalue())
    assert res["id"] == "custom_flow"


def test_cli_runs_summary_includes_agent_outputs_and_final_output():
    run_record = {
        "run_id": "run-test-outputs",
        "workflow_id": "test_workflow",
        "workflow_version": "1.0.0",
        "thread_id": "run-test-outputs",
        "status": "succeeded",
        "payload": {
            "node_outputs": {
                "agent_one": {"message": "hello"},
                "agent_two": {"valid": True},
            },
            "agent_outputs": {
                "agent_one": {"message": "hello"},
                "agent_two": {"valid": True},
            },
            "final_output": {"valid": True},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/runs/run-test-outputs":
            return httpx.Response(200, json=run_record)
        return httpx.Response(404, json={"detail": "not found"})

    stdout, stderr = io.StringIO(), io.StringIO()
    code = main(["runs", "show", "run-test-outputs"], client=mock_client(handler), stdout=stdout, stderr=stderr)
    assert code == 0
    result = json.loads(stdout.getvalue())
    assert result["run_id"] == "run-test-outputs"
    assert result["status"] == "succeeded"
    assert result["agent_outputs"] == {
        "agent_one": {"message": "hello"},
        "agent_two": {"valid": True},
    }
    assert result["final_output"] == {"valid": True}


