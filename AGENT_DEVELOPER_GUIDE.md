# Agent developer guide

Implement a callable accepting `AgentRequest` and `AgentContext`, returning a dictionary (or `AgentResult`). Place the implementation under the trusted `plugins.*` package namespace, then add a YAML or JSON manifest under `plugins/manifests/`:

```yaml
id: my_agent
name: My Agent
version: "1.0.0"
description: Deterministic example agent.
capabilities: [example]
adapter_type: python_callable
entrypoint: plugins.examples.my_agent:run
enabled: true
input_schema: {type: object}
output_schema: {type: object}
```

On the next application startup, `AgentLoader` validates the manifest, checks the trusted namespace, imports the declared callable, and registers it. No edit to the runner, registry, graph builder, or application bootstrap is required. Disabled manifests are skipped during discovery and rejected if loaded directly. This loader trusts local code; it is not a sandbox and does not install or safely execute arbitrary third-party plugins.

Agents own their provider integrations. The core runner supplies IDs, timing, normalized errors, and a safe context; it does not require an LLM.

## API security and data handling

The API fails closed with bearer-token authentication by default. Configure `AGENT_PLATFORM_API_TOKEN` for a protected instance, or `AGENT_PLATFORM_AUTH_TOKENS` with a JSON object of user records containing `token` and optional `permissions`. The development bypass requires both `AGENT_PLATFORM_AUTH_MODE=development` and `AGENT_PLATFORM_DEV_MODE=1`; never set those values in a deployed environment.

Run records have an owner identity. Run inspection, events, approvals, and resume are denied across users, and approval resume uses an atomic database claim. Workflow inputs, outputs, event payloads, and agent/tool error text are redacted for credential-like keys and patterns before persistence or logging. `AGENT_PLATFORM_RETENTION_DAYS` enables startup cleanup of older run/event records; `DELETE /v1/runs/{run_id}` removes an authorized run's repository history. Checkpoint cleanup and encrypted storage are still deployment responsibilities.

Trusted manifest loading is not sandboxing. Plugin Python runs inside the application process with its OS permissions. Do not accept uploaded or third-party plugin code into the trusted namespace; use a separately isolated worker/process boundary before introducing untrusted plugins.

## Local Ollama plugin

An LLM-backed plugin should keep provider-specific HTTP/client code inside its plugin package. The included [ollama_text_summarizer](./plugins/examples/ollama_text_summarizer/agent.py) reads `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_TIMEOUT_SECONDS` when it executes. Its manifest is [ollama_text_summarizer.yaml](./plugins/manifests/ollama_text_summarizer.yaml), and the mapped example workflow is [ollama_summary_reply.yaml](./workflow_definitions/ollama_summary_reply.yaml).

The plugin must not contact Ollama during import or manifest discovery. Connection failures should become clear agent execution failures so the API can start and record the failed run. Use a fake client in core tests; only enable the optional live integration test when a local Ollama service is deliberately available. Local plugin loading is trusted code loading, not a sandbox.

## Reusable tools

Tools are independent callables discovered from `plugins/tool_manifests/`; they are not branches in the generic runner or LangGraph builder. Add the implementation under the trusted `plugins.*` namespace and add a manifest such as:

```python
# plugins/tools/weather.py
def lookup(request, context):
    return {"temperature": 21}
```

```yaml
# plugins/tool_manifests/weather_lookup.yaml
id: weather_lookup
name: Weather Lookup
version: "1.0.0"
description: Returns deterministic weather data.
adapter_type: python_callable
entrypoint: plugins.tools.weather:lookup
enabled: true
input_schema:
  type: object
  required: [city]
  properties: {city: {type: string}}
output_schema:
  type: object
  required: [temperature]
  properties: {temperature: {type: number}}
required_permissions: [weather.read]
```

Restart the API to discover the manifest. No application bootstrap, `ToolRunner`, registry, or graph-builder change is required. The loader rejects disabled, malformed, duplicate, missing, unsupported, and untrusted entries.

An agent receives only the tools named in its manifest execution configuration and only when it has the required permissions:

```yaml
execution:
  allowed_tools: [weather_lookup]
  permissions: [weather.read]
```

Inside an agent, call `await context.call_tool("weather_lookup", {"city": "Bengaluru"})`. The `ToolRunner` validates inputs and outputs, enforces permissions, applies timeouts/retries, records duration/status through the platform event recorder, and redacts sensitive input fields from logs. Non-idempotent tools should set `idempotent: false`; mock email sending uses this rule and is placed after human approval in the example workflow. Tool access is trusted local code execution, not sandboxing or arbitrary shell/Python execution.

## Domain-independent workflow example

Email is only one demonstration domain. The [code-review workflow](./workflow_definitions/code_review.yaml) uses three ordinary manifest-discovered agents: `source_inspector`, `code_reviewer`, and `review_validator`. The first parses a supplied Python snippet with the standard-library AST and never executes it. The second receives the first agent's output through `node_outputs.inspect`, and the validator receives the review through `node_outputs.review`. A normal `human_approval` node then pauses the workflow.

To add another domain, create compatible agent implementations and manifests under the trusted `plugins.*` namespace, then connect their IDs with the existing workflow schema. No domain-specific branch is needed in the SDK, registry, runner, tool runner, API, shared state, or graph builder. The framework records each agent/tool event and handles failures through the same generic execution path.

## CLI scaffolding

The CLI can create a deterministic starter agent without an API or LLM:

```powershell
\.venv\Scripts\python.exe -m app.cli agents scaffold sentiment_analyzer --name "Sentiment Analyzer" --description "Classifies text sentiment"
\.venv\Scripts\python.exe -m app.cli agents validate plugins/manifests/sentiment_analyzer.yaml
```

This creates a package at `plugins/examples/sentiment_analyzer/`, an `agent.py` using `AgentRequest` and `AgentContext`, an `__init__.py`, a deterministic `example_input.json`, and a trusted manifest. Add `sentiment_analyzer` to an ordinary workflow node, then use `workflows validate`, `workflows register`, and `runs start` from the CLI. The generated implementation contains comments showing where domain logic belongs.

For a quick single-agent check, run the registered agent directly without creating a workflow definition:

```powershell
\.venv\Scripts\python.exe -m app.cli --token "local-dev-token-2026" agents run external_text_analysis --interactive
\.venv\Scripts\python.exe -m app.cli --token $env:AGENT_PLATFORM_API_TOKEN agents run external_text_analysis --input-file input.json
\.venv\Scripts\python.exe -m app.cli runs show <RUN_ID>
\.venv\Scripts\python.exe -m app.cli runs events <RUN_ID>
```

Restart/reload the API after updating the platform or connecting a new manifest, then run this command; the CLI never starts a server. Interactive mode reads the manifest's `input_schema` and asks for typed fields (a string property named `text` prompts for the text to analyze). If a schema is absent or ambiguous, it asks for a JSON object instead of guessing. The direct endpoint invokes the same `AgentRunner` used by workflows, applies the agent's tool allowlist/permissions, validates declared input JSON Schema, redacts persisted values, and stores owner-scoped run status and events. The API token needs `agent.execute`; interactive mode also needs `metadata.read` to retrieve the schema. `runs show/events` work exactly as they do for workflow runs.

For the file example, `input.json` contains `{"text":"A sentence to analyze."}`.

When connecting an external Python agent, the provided connection-test input is used to infer observed input field types in the generated manifest. A sample alone does not establish requiredness, so inferred fields are not marked required; edit the manifest to reflect the verified contract. The connected Text Analysis Agent's `text` field is marked required because its implementation explicitly checks for that key.

Create an authorized tool in the same way:

```powershell
\.venv\Scripts\python.exe -m app.cli tools scaffold text_normalizer --name "Text Normalizer" --description "Normalizes text"
\.venv\Scripts\python.exe -m app.cli tools validate plugins/tool_manifests/text_normalizer.yaml
```

The generated tool uses `ToolRequest` and `ToolExecutionContext`, declares a required permission such as `text_normalizer.use`, and includes a Markdown authorization example. An agent must declare both `allowed_tools: [text_normalizer]` and `permissions: [text_normalizer.use]` before `await context.call_tool("text_normalizer", {"text": "..."})` can succeed.

Scaffolding validates lowercase Python-style identifiers, rejects path traversal, uses the existing Pydantic manifest models and safe YAML serialization, and refuses to overwrite any existing target. It writes only to the trusted plugin directories. Newly generated manifests are discovered on API startup, so restart or reload the API before using a newly scaffolded plugin; dynamic reload is not implemented.

## Connect an existing Python project

The CLI can connect a separate project that offers either a module-level `run(input_dict)` function or a no-argument class with a `run(input_dict)` method. Discovery reads Python AST and dependency metadata without importing the project. If exactly one compatible entry point is found, IDs and display names are inferred; otherwise, provide `--entry-point relative_file.py:Symbol` and optionally `--id` / `--name`.

```powershell
\.venv\Scripts\python.exe -m app.cli agents connect --path "C:\Users\PrathamRShetty\Documents\external_agent_demo"
```

Before any import or test invocation, the CLI explains that this is ordinary in-process Python execution and asks you to type `TRUST`. Use `--trust` only when explicitly approving the same execution in a non-interactive terminal. Supply a JSON/YAML object file to the connection test with `--test-input path\to\input.json`. For the standalone Text Analysis Agent, the inferred ID is `external_text_analysis` and the adapter delegates by calling `TextAnalysisAgent().run(request.inputs)`, preserving its returned dictionary.

The command validates a normal `AgentManifest`, loads the generated entry point with `AgentLoader`, then performs one test call through `AgentRunner`. The generated adapter and manifest are in `plugins/examples/connected_<id>/` and `plugins/manifests/`; the source project remains where it is. Python-source hashes are checked before subsequent invocations. An unchanged repeated connection is idempotent and skips another invocation. If source changes, disconnect the registration, review the changed code, and connect again with new approval.

```powershell
\.venv\Scripts\python.exe -m app.cli agents validate external_text_analysis
\.venv\Scripts\python.exe -m app.cli agents list
\.venv\Scripts\python.exe -m app.cli agents show external_text_analysis
# Safe default: normal disconnect
\.venv\Scripts\python.exe -m app.cli agents disconnect external_text_analysis
# Permanent removal: purge platform-managed data, direct runs, events, checkpoints
\.venv\Scripts\python.exe -m app.cli agents disconnect external_text_analysis --purge
```

Validation and disconnect are local/offline. Listing and showing use the API. Restart/reload the API after connection; it currently discovers manifests only during startup. `disconnect` is safe by default: it removes only generated adapter and manifest artifacts, retaining execution history and workflow definitions without modification (and displaying warnings if saved workflows reference the agent). Adding `--purge` (with optional `-y`/`--yes`) displays a preview, requires explicit confirmation, permanently removes agent-specific database records and checkpoints, and safely updates referencing workflows only when their definitions remain valid without the purged agent. Neither mode touches the external agent's source project.

## Simplified connect, compose and run

```powershell
python -m app.cli agents connect --path "C:\Projects\my_agent"
python -m app.cli workflows add-agent text_analysis_validation external_text_analysis_quality_checker --after external_text_analysis
python -m app.cli workflows show text_analysis_validation
python -m app.cli runs start --workflow text_analysis_validation --interactive
```

**Connect.** Only `--path` is required. The CLI statically discovers the entry point (an ambiguous result requires `--entry-point`), derives a deterministic `external_<name>` ID and display name, and picks a verification input: `--test-input`, then a detected example file (`example_input`, `sample_input`, `test_input`, `input`, `example`, `sample`; JSON/YAML; project root or `examples/`/`samples/`), then an interactive JSON sample, then the built-in text sample. Multiple unnamed `*input*` files are an error unless you choose one. Before importing anything it prints the inferred values and requires `TRUST` (or `--trust`); this is ordinary in-process execution and is not sandboxed. The observed verification output becomes the manifest `output_schema` (a sample, not a guarantee). Overrides: `--id`, `--name`, `--entry-point`, `--test-input`.

**Add to a workflow.** `workflows add-agent <workflow-id-or-yaml> <agent-id> [--after NODE]` loads `workflow_definitions/<id>.yaml`, compares the agent's `input_schema` with the workflow input and the preceding node's output, and creates the node, edge and `input_mappings`. A field is mapped only when exactly one best, type-compatible source exists. For the quality checker, `original_text` → `workflow_input.text`; `summary`, `word_count`, `character_count`, `most_frequent_words` → same-named `external_text_analysis` outputs; `analysis_status` → `...external_text_analysis.status`. Nothing is hardcoded to these agents. The whole workflow is validated with `WorkflowBuilder`, the YAML is rewritten atomically (version patch bump when changed), and the definition is registered via `POST /v1/workflows` using `--token`/`AGENT_PLATFORM_API_TOKEN`. Ambiguity, an unmatched required field, or a type mismatch is asked interactively; otherwise it stops without changes and tells you to use `--map FIELD=PATH` or `--literal FIELD=JSON`. An explicit `--map` whose type is known to be incompatible is rejected. The output JSON lists each mapping with its origin (`inferred`, `override`, `answered`, `existing`), type-check status and any skipped optional fields. Repeating the command is safe (`changed: false`). If registration fails, the saved YAML is valid; fix the cause (e.g. restart the API so it loads the new agent) and repeat.

**Run interactively.** `runs start --workflow W --interactive` fetches the workflow and agent schemas through the API, prompts for each initial input field (a JSON object prompt when fields cannot be inferred safely), and runs through the normal authenticated `/v1/runs` path, so run ownership, history, node events, error handling and approval/resume are unchanged. `--input file.json` remains supported and is mutually exclusive with `--interactive`. The CLI never starts an API server.

## Workflow scaffolding walkthrough

After creating and implementing an agent, confirm its trusted manifest and generate a sequential workflow template from registered IDs:

```powershell
\.venv\Scripts\python.exe -m app.cli agents scaffold source_inspector --name "Source Inspector" --description "Inspects source text"
\.venv\Scripts\python.exe -m app.cli agents validate plugins/manifests/source_inspector.yaml
\.venv\Scripts\python.exe -m app.cli workflows scaffold code_analysis --agents source_inspector,code_reviewer
```

The workflow scaffold checks the local trusted registry, writes `workflow_definitions/code_analysis.yaml`, and derives TODO comments from the selected agents' declared input schemas. It does not invent mappings. Edit the generated `input_mappings` with paths such as:

```yaml
input_mappings:
  source_code: {path: workflow_input.source_code}
```

For a downstream node, map from an earlier output:

```yaml
input_mappings:
  inspection: {path: node_outputs.source_inspector}
```

Use the existing approval format when needed:

```yaml
- id: approve
  type: human_approval
  approval_payload_path: node_outputs.code_reviewer
  approval_options: [approve, reject]
```

Connect the node with a normal edge, then validate, register, run, and inspect it through the same CLI:

```powershell
\.venv\Scripts\python.exe -m app.cli workflows validate workflow_definitions/code_analysis.yaml
\.venv\Scripts\python.exe -m app.cli workflows register workflow_definitions/code_analysis.yaml
\.venv\Scripts\python.exe -m app.cli workflows show code_analysis
\.venv\Scripts\python.exe -m app.cli runs start --workflow code_analysis --input examples/code_review_input.json
\.venv\Scripts\python.exe -m app.cli runs show <RUN_ID>
\.venv\Scripts\python.exe -m app.cli runs events <RUN_ID>
\.venv\Scripts\python.exe -m app.cli approvals list
\.venv\Scripts\python.exe -m app.cli approvals resume <RUN_ID> --decision approve
```

Workflow scaffolding is offline and safe YAML only. Newly created agent manifests still require an API restart or reload before the service discovers them; dynamic plugin reload is not implemented.

