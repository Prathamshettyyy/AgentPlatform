# Workflow author guide

Workflow definitions use YAML/JSON models. Agent node mappings may read `workflow_input.field` or `node_outputs.node_id.field`; literal values are also supported. Edges are declarative and may use `equals`, `not_equals`, `exists`, or `truthy` conditions. Human approval nodes use `approval_payload_path` and resume with `approve` or `reject`.

Mappings are resolved as dictionary/list traversal only. No expressions, imports, shell commands, or `eval` are accepted.

## CLI workflow walkthrough

The developer CLI is a thin client over the existing API. For local-only work, set the explicit development bypass before starting the service:

```powershell
$env:AGENT_PLATFORM_AUTH_MODE = "development"
$env:AGENT_PLATFORM_DEV_MODE = "1"
\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

For a protected server, omit those development variables, set `AGENT_PLATFORM_API_TOKEN`, and add `--token $env:AGENT_PLATFORM_API_TOKEN` to CLI commands. Run records are visible and resumable only by their owner.

From another terminal, validate and register a workflow. Validation uses safe YAML parsing and the same agent registry and `WorkflowBuilder` checks used by the API:

```powershell
$env:PYTHONPATH = "."
\.venv\Scripts\python.exe -m app.cli --token $env:AGENT_PLATFORM_API_TOKEN agents list
\.venv\Scripts\python.exe -m app.cli --token $env:AGENT_PLATFORM_API_TOKEN tools list
\.venv\Scripts\python.exe -m app.cli --token $env:AGENT_PLATFORM_API_TOKEN workflows validate workflow_definitions/code_review.yaml
\.venv\Scripts\python.exe -m app.cli --token $env:AGENT_PLATFORM_API_TOKEN workflows register workflow_definitions/code_review.yaml
```

Start a run with a JSON object input file, then inspect the sanitized summary and node events:

```powershell
\.venv\Scripts\python.exe -m app.cli runs start --workflow code_review --input examples/code_review_input.json
\.venv\Scripts\python.exe -m app.cli runs show <RUN_ID>
\.venv\Scripts\python.exe -m app.cli runs events <RUN_ID>
```

If a workflow pauses for human approval, list pending runs and resume one with an allowed decision from its approval payload:

```powershell
\.venv\Scripts\python.exe -m app.cli approvals list
\.venv\Scripts\python.exe -m app.cli approvals resume <RUN_ID> --decision approve
```

Use `runs events <RUN_ID> --include-payload` only when sanitized payload details are required. The CLI does not print workflow input by default and redacts keys containing common secret markers. A server or invalid workflow produces a concise non-zero-error response instead of a traceback.

To temporarily unregister/disable a workflow from the active API registry while preserving its local YAML definition, mappings, agents, and execution history:

```powershell
\.venv\Scripts\python.exe -m app.cli workflows disconnect <WORKFLOW_ID>
\.venv\Scripts\python.exe -m app.cli workflows disconnect <WORKFLOW_ID> --yes
```

To permanently remove a workflow definition from both the server-side registry and `workflow_definitions/<workflow_id>.yaml` while preserving historical execution records:

```powershell
\.venv\Scripts\python.exe -m app.cli workflows delete <WORKFLOW_ID>
\.venv\Scripts\python.exe -m app.cli workflows delete <WORKFLOW_ID> --yes
```

