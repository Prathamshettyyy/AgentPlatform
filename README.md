# Agent Platform

A small, provider-independent agent framework built with Python, Pydantic, FastAPI, and LangGraph. The workspace is self-contained; no external project is required.

## Setup (Windows PowerShell)

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONPATH = "."
.\.venv\Scripts\python.exe -m pytest -q
```

For an explicitly local-only development server, set the development bypass in the same PowerShell session:

```powershell
$env:AGENT_PLATFORM_AUTH_MODE = "development"
$env:AGENT_PLATFORM_DEV_MODE = "1"
\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The default is fail-closed bearer-token authentication. For a protected local/deployed instance, configure `$env:AGENT_PLATFORM_API_TOKEN` and leave development mode unset.

## Developer CLI

Start the API in one PowerShell terminal, then use the CLI from the project root in another:

```powershell
\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
$env:PYTHONPATH = "."
\.venv\Scripts\python.exe -m app.cli --token $env:AGENT_PLATFORM_API_TOKEN agents list
\.venv\Scripts\python.exe -m app.cli tools list
```

The CLI defaults to `http://127.0.0.1:8000` and reads `AGENT_PLATFORM_API_TOKEN` automatically. Use `--token` or `--base-url` before the command to target another instance, for example `\.venv\Scripts\python.exe -m app.cli --base-url http://localhost:9000 --token $env:AGENT_PLATFORM_API_TOKEN agents list`.

## Web Developer Dashboard

The platform includes a real-time developer dashboard built with React, Vite, TypeScript, Tailwind CSS, and Lucide icons.

### 1. Start Backend API

In a PowerShell terminal:

```powershell
# Development mode (token bypass):
$env:AGENT_PLATFORM_AUTH_MODE = "development"
$env:AGENT_PLATFORM_DEV_MODE = "1"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

# Or Protected mode (bearer token):
$env:AGENT_PLATFORM_API_TOKEN = "local-dev-token-2026"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### 2. Start Frontend Dev Server

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

If running with protected authentication, navigate to **Settings** in the dashboard and enter your bearer token (e.g. `local-dev-token-2026`).

### 3. Build Frontend for Production

```powershell
cd frontend
npm run build
```

This verifies TypeScript compilation and outputs the optimized bundle to `frontend/dist/`.

### Dashboard Features

- **Overview**: System health indicator, real-time counters (connected agents, registered & draft workflows, runs by state), and recent execution activity table.
- **Agents**: Browse registered agents, search and filter by capability/type, inspect detailed manifests (input/output schemas, allowed tools, permissions), and trigger direct single-agent runs.
- **Workflows**: Visual interactive DAG graph visualizing nodes, directed dependencies, and input mappings. Inspect definitions, launch workflow runs with JSON payload inputs, create draft workflows, and perform workflow deletions with a full impact preview.
- **Runs**: Searchable and filterable execution history (by status and workflow). Detail view provides inputs, outputs, error logs, and execution step timeline.
- **Logs & Events**: Comprehensive platform telemetry stream. Filter events by run ID and event type, with searchable payload inspection.
- **Approvals**: Real-time pending approvals management with a persistent sidebar badge count. Review pause context, inputs, and issue approve/reject decisions.
- **Tools**: Catalog of registered tools, parameter definitions, and permission requirements.
- **Settings**: Real-time backend connectivity check, latency ping, API base URL override, and in-memory token manager.

> **Security Note:** In compliance with security standards, the web dashboard stores API credentials strictly in-memory for the active session. Tokens are never written to `localStorage` or `sessionStorage`, and build secrets are never embedded in frontend assets. External agents must still be verified and connected via the CLI before they appear in the dashboard.


Every `/v1` route requires authentication unless the explicit development-only mode is enabled. Run inspection, events, approvals, and resume are owner-scoped; tokens may also be assigned permissions through `AGENT_PLATFORM_AUTH_TOKENS` JSON records.

Validate and register the included code-review workflow, then start it with a JSON input file:

```powershell
\.venv\Scripts\python.exe -m app.cli workflows validate workflow_definitions/code_review.yaml
\.venv\Scripts\python.exe -m app.cli workflows register workflow_definitions/code_review.yaml
\.venv\Scripts\python.exe -m app.cli workflows show code_review
\.venv\Scripts\python.exe -m app.cli runs start --workflow code_review --input examples/code_review_input.json
\.venv\Scripts\python.exe -m app.cli runs show RUN_ID
\.venv\Scripts\python.exe -m app.cli runs events RUN_ID
\.venv\Scripts\python.exe -m app.cli approvals list
\.venv\Scripts\python.exe -m app.cli approvals resume RUN_ID --decision approve
```

`agents validate PATH` and `tools validate PATH` validate manifest structure without contacting the API. Workflow validation safely parses YAML and uses the same local registry and workflow builder checks as the service. `workflows show WORKFLOW_ID` retrieves and displays the workflow definition as formatted JSON along with its registration status (`registered` or `disconnected`). `workflows disconnect WORKFLOW_ID` (with interactive confirmation or `--yes`) unregisters the workflow from the active API registry (`POST /v1/workflows/{workflow_id}/disconnect`) while preserving its local YAML definition, mappings, referenced agents, and execution history. `workflows delete WORKFLOW_ID` (with interactive confirmation or `--yes`) permanently removes the workflow from the server-side registry (`DELETE /v1/workflows/{workflow_id}`) and deletes its local YAML definition in `workflow_definitions/<workflow_id>.yaml` while preserving historical run and event records. Run output is summarized and sensitive fields are redacted; use `runs events RUN_ID --include-payload` only when sanitized event payloads are needed.

Run one registered agent directly when you do not need a multi-node workflow:

```powershell
\.venv\Scripts\python.exe -m app.cli --token "local-dev-token-2026" agents run external_text_analysis --interactive
\.venv\Scripts\python.exe -m app.cli --token $env:AGENT_PLATFORM_API_TOKEN agents run external_text_analysis --input-file input.json
\.venv\Scripts\python.exe -m app.cli runs show RUN_ID
\.venv\Scripts\python.exe -m app.cli runs events RUN_ID
```

Interactive prompts are generated from the registered input schema. If the schema is missing or ambiguous, the CLI asks for a JSON object rather than assuming a text field. Direct runs use the authenticated `POST /v1/agents/{agent_id}/runs` API route, the existing `AgentRunner`, owner-scoped SQLite run history, redacted execution events, and the same `runs show/events` inspection commands. Restart/reload the API after updating the platform or connecting a new manifest, then use the CLI; it never starts another server. Tokens need `agent.execute`; interactive mode also reads the agent metadata (`metadata.read`). Configure the shown token in the API's `AGENT_PLATFORM_API_TOKEN` environment setting before startup.

For the file example, `input.json` contains `{"text":"A sentence to analyze."}`.

Scaffold compatible plugins offline:

```powershell
\.venv\Scripts\python.exe -m app.cli agents scaffold sentiment_analyzer --name "Sentiment Analyzer" --description "Classifies text sentiment"
\.venv\Scripts\python.exe -m app.cli agents validate plugins/manifests/sentiment_analyzer.yaml
\.venv\Scripts\python.exe -m app.cli tools scaffold text_normalizer --name "Text Normalizer" --description "Normalizes text"
\.venv\Scripts\python.exe -m app.cli tools validate plugins/tool_manifests/text_normalizer.yaml
```

Agent scaffolding creates `plugins/examples/sentiment_analyzer/agent.py`, its package initializer, deterministic example input, and `plugins/manifests/sentiment_analyzer.yaml`. Tool scaffolding creates the implementation, `plugins/tool_manifests/text_normalizer.yaml`, and a local authorization example under `plugins/tools/`. Add the generated ID to a workflow and register it with `workflows register`; restart the API afterward because manifest discovery occurs at application startup. Scaffolding refuses invalid/path-traversal IDs and never overwrites existing targets.

### Connect an existing Python agent

`agents connect` can register a separate Python project that exposes one top-level `run(input_dict)` function or one no-argument class with a `run(input_dict)` method. It uses AST inspection to find candidates without importing them. If the choice is unambiguous, the entry point and default ID/name are inferred; otherwise, specify `--entry-point`, `--id`, or `--name`.

```powershell
\.venv\Scripts\python.exe -m app.cli agents connect --path "C:\Users\PrathamRShetty\Documents\external_agent_demo"
```

The command displays the selected entry point and dependency inspection, then requires you to type `TRUST` before it imports or invokes external code. For an explicit non-interactive approval, add `--trust`. A custom JSON/YAML test input can be supplied with `--test-input path\to\input.json`. The connector creates a thin adapter under `plugins/examples/connected_<id>/` plus a regular manifest under `plugins/manifests/`; it does not copy or edit the external source. The adapter calls the external function/class with the mapped input dictionary and returns its dictionary output unchanged.

For the standalone `TextAnalysisAgent`, the default ID is `external_text_analysis`:

```powershell
\.venv\Scripts\python.exe -m app.cli agents validate external_text_analysis
\.venv\Scripts\python.exe -m app.cli agents list
\.venv\Scripts\python.exe -m app.cli agents show external_text_analysis
# Safe default: normal disconnect (removes registration and generated adapter, retains history, catalog entry, and workflows)
\.venv\Scripts\python.exe -m app.cli agents disconnect external_text_analysis
# Permanent agent deletion: removes registration, adapter, connection catalog entry, direct runs, events, checkpoints, and updates referencing workflows
\.venv\Scripts\python.exe -m app.cli agents delete external_text_analysis
\.venv\Scripts\python.exe -m app.cli agents disconnect external_text_analysis --purge
```

`agents validate <ID>` checks the local manifest through the trusted loader; `agents list` and `show` query the API and therefore require a running API. Restart/reload the API after connection because manifests are read at startup. `disconnect` removes only the generated adapter and manifest, preserving run history and workflow definitions (emitting warnings if saved workflows reference the disconnected agent). Use `--purge` (with optional `--yes`) to permanently delete platform-managed records, history, and checkpoints after interactive confirmation, safely updating workflows only if their definitions remain valid. Neither mode ever deletes or modifies the external agent's source project. Repeating an unchanged connection is idempotent and does not repeat its test invocation. Python source files are fingerprinted; if they change, execution fails closed until you review and reconnect. Declared/imported dependencies are reported but never installed automatically. Connected Python code executes in-process with the platform's permissions—it is not sandboxed; use a separate-process isolation design for untrusted code or conflicting environments.

### Simplified three-command workflow

```powershell
# 1. Connect: entry point, ID, name and verification input are inferred. You are asked to type TRUST.
python -m app.cli agents connect --path "C:\Projects\my_agent"
# (restart the API so it discovers the new manifest)

# 2. Add the agent to an existing workflow: node, edge and input mappings are inferred, the whole
#    workflow is validated, workflow_definitions/<id>.yaml is updated (patch version bump) and the
#    workflow is registered through the authenticated API.
python -m app.cli workflows add-agent text_analysis_validation external_text_analysis_quality_checker --after external_text_analysis
python -m app.cli workflows show text_analysis_validation

# 3. Run it, typing the initial input in the terminal (no JSON file; `--input file.json` still works).
python -m app.cli runs start --workflow text_analysis_validation --interactive
```

`agents connect` options are all optional overrides: `--entry-point`, `--id`, `--name`, `--test-input`, and `--trust` (non-interactive approval). The verification input is, in order: `--test-input`; a detected example file (`example_input`, `sample_input`, `test_input`, `input`, `example`, `sample` with `.json/.yaml/.yml`, in the project root or an `examples/`/`samples/` folder); an interactively entered JSON object; a built-in text sample. Several unnamed `*input*` files are never guessed between—choose with `--test-input`. The observed output of the verification call is recorded as the manifest's `output_schema` so later workflow tooling knows the agent's output fields.

`workflows add-agent` maps each input field of the new agent from the original workflow input or the preceding node's output. A source is chosen only when it is the single best match (identical name, or one name is a whole-word suffix of the other, e.g. `analysis_status` ← `status`, `original_text` ← `workflow_input.text`) and its JSON type is compatible. Output fields come from the preceding agent's `output_schema` plus fields existing workflows already consume from that agent. Ambiguous or unmatched fields are asked interactively, or pass `--map FIELD=PATH` / `--literal FIELD=JSON`; in non-interactive use the command stops with the list and changes nothing. Repeating the command never duplicates nodes or edges (the report shows `changed: false`) and re-attempts registration. If registration fails the YAML is already saved and validated; repeat the command after fixing the cause (for example restarting the API so it knows the agent). Other options: `--node-id`, `--version`. A node that already has a successor is not branched automatically. Comments inside the YAML body are not preserved (leading header comments are).

`runs start --interactive` reads the registered workflow and agent input schemas through the API, prompts per field (or for a JSON object when fields cannot be inferred safely, e.g. nested `workflow_input` paths), and posts the result to the same authenticated `/v1/runs` endpoint. It never starts a server. The run ID and final result (or approval/failure information) are printed; use `approvals resume` as before.

Scaffold a workflow from already discovered agents:

```powershell
\.venv\Scripts\python.exe -m app.cli workflows scaffold code_analysis --agents source_inspector,code_reviewer
\.venv\Scripts\python.exe -m app.cli workflows validate workflow_definitions/code_analysis.yaml
```

The generated YAML contains one sequential node per selected agent, valid empty `input_mappings`, manifest-derived TODO comments for required fields, and commented examples for optional approval or conditional routing. Complete mappings with real `workflow_input.*` or `node_outputs.*` paths, validate again, register, and execute. The command verifies agent IDs and never overwrites an existing workflow file.

## Architecture

```text
Agent SDK -> Trusted Registry -> AgentRunner -> WorkflowBuilder -> LangGraph
                                      |                         |
                              SQLite execution history     checkpoint/interrupt
                                      |
                                   FastAPI
```

The registry and runner are independent of example plugins. Workflow nodes resolve registered IDs at runtime, while LangGraph owns graph execution and interrupt semantics. SQLite is authoritative for platform run history; LangGraph checkpoints preserve resumable graph state.

## Included MVP

- Typed SDK contracts, trusted registry, manifest-based local plugin discovery, callable and compiled-graph adapter interfaces.
- Generic async runner with standardized errors and execution metadata.
- Validated workflow models, safe mappings, conditional routing, cycle rejection, and dynamic LangGraph construction.
- In-memory interrupt/checkpoint support for deterministic tests.
- SQLite run history, FastAPI agent/workflow/run/events/approval endpoints, and a scheduler wrapper.
- Mock email summarizer, reply drafter, human approval, and sender workflow configuration as ordinary example plugins.
- Deterministic code-review workflow with source inspection, structured findings, schema validation, and reusable human approval.
- Optional local Ollama text/email summarizer plugin and mapped summary-to-reply workflow.
- Reusable tool contracts, permission-aware registry/runner, and deterministic mock email search/read/send tools.

Detailed extension instructions are in `AGENT_DEVELOPER_GUIDE.md` and `WORKFLOW_AUTHOR_GUIDE.md`. Trusted agent manifests live under `plugins/manifests/`, tool manifests live under `plugins/tool_manifests/`, and both are loaded during application startup.

Tools are discovered from validated trusted manifests and exposed to agents through `AgentContext.call_tool`. Agent manifests declare `execution.allowed_tools` and `execution.permissions`; the generic `ToolRunner` enforces both. The mock email workflow uses search/read before approval and the non-idempotent mock send tool only after approval. Tool loading trusts local `plugins.*` code; it is not sandboxing and does not install arbitrary third-party code.

## Domain-independent workflow example

[`code_review.yaml`](./workflow_definitions/code_review.yaml) demonstrates the same framework with no email concepts: a source-inspection agent parses a Python snippet with `ast` only, a review agent produces structured findings, a validator checks that contract, and a generic human-approval node pauses the run. The workflow is submitted to `POST /v1/workflows` and executed through `POST /v1/runs`, like the email example. The code is inspected, never executed, and no generated code is run.

## Optional Ollama example

The `ollama_text_summarizer` plugin calls a local Ollama HTTP service only when a workflow executes. It does not contact Ollama during application startup and does not require a paid provider.

Configure it in PowerShell:

```powershell
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "llama3.2"
$env:OLLAMA_TIMEOUT_SECONDS = "60"
```

Install and start Ollama separately, make the selected model available, then start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The example workflow is [ollama_summary_reply.yaml](./workflow_definitions/ollama_summary_reply.yaml). Submit its definition to `POST /v1/workflows`, then start it with `POST /v1/runs` and an input such as `{"text":"Quarterly review is next Tuesday."}`. If Ollama is unavailable, the API still starts and the run is recorded as `failed` with an `OllamaUnavailableError` and execution duration.

Core tests mock the model and never require Ollama. Set `RUN_OLLAMA_TESTS=1` only when a local Ollama service is intentionally available to run the optional integration test.

## Limitations

Workflow definitions, run metadata, and LangGraph checkpoints are persisted in separate SQLite databases. Workflow definitions have immutable `(workflow_id, version)` records, and paused runs can be rebuilt and resumed after a new application instance using the run's recorded version and thread ID. Bearer authentication, owner-scoped run access, permission checks, redaction, retention, SQLite WAL/busy-timeout settings, and an atomic resume claim are implemented. Multi-worker checkpoint coordination, cancellation, recovery leases, and scheduler persistence are not implemented. Parallel execution, remote adapters, advanced transformations, and production-grade LLM tool use remain out of scope. Trusted plugins still execute in-process and are not sandboxed.

