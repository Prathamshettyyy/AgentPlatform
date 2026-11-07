# Final Architecture and Reliability Review

Audit date: 2026-10-27  
Scope: the existing `agent_platform` workspace only. No files from the former `langgraph-learning` project were inspected or used.

## Executive assessment

The project has a coherent, domain-independent MVP architecture. Agent and tool implementations are discovered from trusted local manifests, workflow nodes are built from configuration, and the same runner/builder path executes the deterministic email, code-review, scaffolded-plugin, and Ollama examples. The final live regression run passed **64 tests** with the local `llama3.2:3b` model.

The platform is not production-ready. Hardening now provides fail-closed bearer authentication, permission checks, owner-scoped runs, redaction at API/storage/checkpoint boundaries, configurable repository retention, and an atomic resume claim. The remaining principal risks are that trusted plugins execute as ordinary Python in the API process, token authentication lacks rotation/tenant identity, encrypted storage is absent, and SQLite/checkpoint coordination is not a fully coordinated multi-worker deployment. These are security and operational boundaries, not failures of the deterministic test suite.

## Architecture and responsibilities

| Layer | Responsibility | Review result |
|---|---|---|
| SDK | Pydantic request/result/metadata contracts and `AgentContext` | Generic; no email assumptions found. |
| Agent registry and loader | Validate manifests, enforce the trusted `plugins.*` namespace, import implementations, reject duplicates and disabled/invalid entries | Separate from execution and workflow construction. |
| Agent runner and adapters | Resolve an agent ID, invoke the declared adapter, normalize errors, add execution ID and duration | Generic; callable and compiled-graph adapter interfaces are separated. |
| Tool contracts, registry, loader, runner | Validate schemas, discover trusted tools, enforce allowlists/permissions, run with timeout/retry rules, redact logged inputs, and record tool events | Generic; agents access tools through `AgentContext`, not provider-specific code. |
| Workflow models/validator/mappings | Validate IDs, node/edge references, mappings, approval options, reachability, cycles, and safe dictionary traversal | Declarative and expression-free. Converging DAG validation was corrected during this audit. |
| LangGraph builder | Translate a validated definition into nodes, edges, conditional routes, and interrupt/resume behavior | No individual email, code-review, or Ollama branches. |
| Storage | SQLite run history, events, current workflow pointers, immutable workflow versions, workflow/thread/version fields | Separate from LangGraph checkpoint storage. |
| API | Startup discovery, workflow registration, run start/status/events, approvals, resume, and OpenAPI | Thin service layer over the framework; no second execution engine. |
| CLI/scaffolding | Safe YAML/JSON parsing, HTTP client operations, and offline plugin/workflow file generation | Does not own runner, graph, monitoring, or checkpoint logic. |
| Plugins/examples | Ordinary trusted implementations and manifests for email, code review, Ollama, tools, and scaffolds | Domain examples remain outside the framework packages. |

Static inspection found no email/outlook/exchange/smtp assumptions in `app/sdk`, registry, runtime, tools, workflows, storage, or API. Email-specific code is under `plugins/`, workflow definitions, tests, and documentation. No circular-import defect was found; the SDK uses local/type-only imports where the tool context crosses package boundaries.

## Confirmed strengths

- A new compatible agent can be added through a trusted implementation and manifest. The generic runner and graph builder do not require edits.
- A new trusted tool can be added through its implementation and manifest, then authorized through the agent manifest's `allowed_tools` and `permissions` metadata.
- Workflow node IDs, agent IDs, edges, mappings, conditional paths, and approval nodes are configuration-driven.
- Mappings use dictionary/list traversal only. No `eval`, imports, shell commands, or LLM-generated code paths are accepted.
- Tool input/output JSON Schema validation, disabled/unknown checks, permission checks, timeouts, idempotent retry restrictions, and event recording are implemented and tested.
- Approval is implemented as a generic LangGraph interrupt. The rejection path does not reach the protected successor, and approval options are now routed by the explicit `approve` option rather than by list position.
- Workflow definitions are stored by immutable `(workflow_id, version)` key. A resumed run loads its recorded definition version and uses its recorded thread ID after an application restart.
- The same architecture executes both the email and code-review workflows. The code-review example parses source with `ast` and does not execute supplied code.
- Scaffolding validates identifiers, rejects traversal, refuses overwrites, writes only to trusted directories, and works offline.

## Verified acceptance criteria

| Scenario | Evidence | Result |
|---|---|---|
| Add an unrelated agent without core edits | `tests/test_sdk_registry_runner.py`, `tests/test_manifest_loader.py`, `tests/test_api.py` | Passed. |
| Discover metadata through the API and execute the agent | `test_manifest_discovered_agent_runs_through_api_without_bootstrap_registration` | Passed. |
| Add and authorize a tool through a manifest | `tests/test_tool_loader.py`, `tests/test_tools.py` | Passed. |
| Deny unknown, disabled, unallowed, or under-permissioned tools | Tool registry/runner security tests | Passed. |
| Pass mapped output between agents | `test_configured_mapping_flows_between_agents`, code-review tests | Passed. |
| Reject malformed mappings, unknown nodes, cycles, and downstream references | `tests/test_workflows.py` | Passed. |
| Accept a converging DAG | `test_converging_dag_is_valid_but_cycles_are_not` | Passed after validator correction. |
| Scaffold, validate, register, and run a workflow | `tests/test_cli_workflow_scaffold.py` | Passed. |
| Connect agents from separate domains | `tests/test_code_review_workflow.py` and email/Ollama tests | Passed. |
| Pause, restart, and resume approval | `test_paused_run_resumes_after_new_app_instance` | Passed. |
| Resume the recorded workflow version after a newer version is registered | `test_resume_uses_the_persisted_workflow_version_after_restart` | Passed. |
| Reject approval and prevent protected action | `test_rejection_option_cannot_authorize_sender_when_not_first` and email tool approval tests | Passed. |
| Preserve failure status and run context | API failure/event tests plus runner failure tests | Passed; explicit failed results now retain duration and execution ID. |
| Run the real Ollama example | `tests/test_ollama_plugin.py`, `RUN_OLLAMA_TESTS=1` | Passed with `llama3.2:3b` installed locally. |
| Reject missing/invalid credentials and unauthorized permissions | `tests/test_security_hardening.py` | Passed; default startup is fail-closed and development bypass is explicit. |
| Prevent cross-user run inspection/resume | `test_runs_are_owner_scoped_and_approval_requires_permission` | Passed; cross-owner access returns not-found and insufficient approval permission returns forbidden. |
| Redact credentials from API results, logs, SQLite, checkpoints, and errors | `test_redaction_applies_to_api_payloads_database_and_agent_errors` | Passed for credential-like keys/patterns. Semantic sensitive content and encryption remain deployment concerns. |
| Keep concurrent runs distinct and prevent repeated approval resume | `test_concurrent_runs_have_distinct_owner_and_thread_state`, `test_repeated_resume_has_one_winner` | Passed in the shared-process/shared-repository test boundary. Distributed recovery remains limited. |

These results are test evidence. Documentation alone was not counted as proof.

## Reliability and persistence review

The platform deliberately has two persistence responsibilities:

1. `ExecutionRepository` stores workflow definitions, immutable versions, run status, run ID, workflow ID/version, thread ID, payload, and execution events.
2. LangGraph's `AsyncSqliteSaver` stores resumable graph state in the companion checkpoint database.

The audit found and corrected four reliability defects:

- Existing workflow serialization included an unset `literal: null`, which failed Pydantic validation after restart. The mapping validator now treats `path` plus a null legacy literal as a path mapping, while repository writes remove only that redundant field inside `input_mappings` and preserve an explicit literal-only null.
- The validator treated a converging DAG as a cycle because it rejected a node seen from two parents. It now uses incoming-edge accounting and still rejects real cycles/unreachable nodes.
- Resume previously used the latest workflow definition. It now loads the run's recorded workflow version and uses the persisted thread ID.

The in-memory repository now uses an in-memory checkpoint connection instead of deriving a filesystem name from `:memory:`; this is covered by an API regression test.

A startup regression test inserts the legacy serialized `path` plus `literal: null` representation directly into a temporary SQLite database and verifies that a new API instance loads it without rewriting or discarding the record.

Remaining reliability limitations:

- SQLite writes have local WAL/busy-timeout protection and repeated resume uses an atomic claim in a shared repository, but checkpoint access is not coordinated for multiple API workers or distributed deployments.
- There is no cancellation protocol, lease, distributed idempotency lock, or recovery coordinator. A process crash after claiming a resume can leave a run in `resuming` until operational recovery is applied.
- Scheduler registration is runtime-only; schedules are not persisted and reconciled at startup.
- Concurrent resume requests are protected by a conditional database claim; cross-process recovery after a crash remains a limitation.
- API approval is scoped to a run/thread and the graph's pending state, but there is no authenticated approver identity or authorization policy binding a human to a particular business action.
- The API has no version-specific workflow route; version selection is internal to persisted runs.

Retries are restricted by the tool metadata's `idempotent` flag. Non-idempotent tools do not retry automatically. This is a local process guard, not a distributed exactly-once guarantee.

## Security review

### Implemented local safeguards

- Agent and tool imports are restricted to explicitly trusted `plugins.*` namespaces and validated entry-point syntax.
- Manifest schemas reject malformed IDs, unsupported adapters, missing implementations, disabled entries, duplicate IDs, and invalid JSON Schemas.
- Scaffolding rejects invalid identifiers/path traversal, refuses overwrite, and writes under fixed trusted directories.
- YAML workflow loading is safe parsing plus Pydantic validation. Workflow mappings are data traversal, not executable expressions.
- Tool access requires both an agent allowlist and required permissions. Unknown and disabled tools are rejected.
- Tool inputs and recorded tool payload inputs are redacted by sensitive-key name. No real Outlook integration or real email send exists.
- `/v1` routes fail closed unless explicit development mode is enabled with both `AGENT_PLATFORM_AUTH_MODE=development` and `AGENT_PLATFORM_DEV_MODE=1`.
- Bearer tokens map to principals and permissions; run records carry an owner ID, and cross-owner inspection/events/approval access returns not-found.
- Resume uses a conditional database claim, so repeated requests against the same shared repository produce one winner and a conflict for the other request.
- Credential-like keys and `key=value`/Bearer patterns are redacted from agent/tool errors, logs, API persistence, event records, and API-created checkpoint state.
- SQLite uses WAL/busy-timeout settings, and checkpoint initialization is serialized to prevent simultaneous first-run schema setup races.
- `AGENT_PLATFORM_RETENTION_DAYS` purges old run/event records at repository startup, and authorized run deletion removes repository history.

### Production security requirements not implemented

- Plugins are ordinary Python imported and invoked in the API process. They can use the application's OS permissions. This is trusted local code loading, not sandboxing, isolation, signature verification, or safe execution of arbitrary third-party code.
- Authentication is a local static bearer-token boundary, not a complete identity system: token rotation, revocation, external identity providers, tenant isolation, and approval-principal audit policy are not implemented.
- Persisted workflow inputs, outputs, and exception messages are redacted for credential-like data, but storage is not encrypted and semantic sensitive content is not automatically classified. Avoid regulated data in this development database.
- There is no manifest signing, plugin provenance policy, upload control, dependency isolation, or supply-chain scanner.
- Agent input/output JSON Schemas are declared in metadata but are not enforced by `AgentRunner` as strictly as tool schemas are.
- Logging and event payload redaction is stronger for tool inputs than for all agent outputs and workflow payloads.

## Warning audit

The final default run was:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -W default
```

Result: **63 passed, 1 skipped, 33 warnings**.

The final live run was:

```powershell
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:OLLAMA_MODEL = "llama3.2:3b"
$env:RUN_OLLAMA_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest -q -W default
```

Result: **64 passed, 33 warnings**. `ollama list` confirmed `llama3.2:3b` was installed.

Warning classification:

| Source/location | Warning | Classification | Action |
|---|---|---|---|
| `.venv/Lib/site-packages/starlette/testclient.py:51` | AnyIO `BlockingPortal` alias deprecation | Third-party/Python-framework deprecation | Not application-owned. Track Starlette/AnyIO compatibility; do not suppress globally. |
| `.venv/Lib/site-packages/langgraph/checkpoint/base/__init__.py:18` | LangChain pending deprecation for `allowed_objects` default | Third-party dependency | Track LangGraph/LangChain compatible release; current checkpoint API is pinned to the working `aiosqlite` interface. |
| `.venv/Lib/site-packages/langgraph/_internal/_runnable.py:485` | `asyncio.iscoroutinefunction` deprecated for Python 3.16 | Third-party/Python-framework deprecation | Track LangGraph release that switches to `inspect.iscoroutinefunction`. |
| `.venv/Lib/site-packages/langgraph/_internal/_runnable.py:487` | Same deprecation in callable-object detection | Third-party/Python-framework deprecation | Same compatibility plan. |

No application-owned or test-owned warning was found. The new hardening module passed **7 tests**. The warning count increased only because the new security/concurrency tests exercise existing LangGraph code paths; no new warning category was introduced.

## Findings ranked by severity

### High

1. **Trusted plugin execution is not sandboxed.** A compromised or unsafe manifest entry point runs with API-process and OS privileges. This is acceptable only for a controlled local development trust boundary.
2. **Authentication is not a production identity system.** Static bearer tokens and configured permissions now protect routes and owner-scope runs, but production still needs rotation/revocation, an external identity boundary, tenant policy, and an auditable approval principal/action binding.

### Medium

3. **Sensitive data persistence is only best-effort redaction.** Credential-like keys and patterns are redacted and retention/deletion are available, but encryption, semantic content classification, and complete checkpoint lifecycle deletion are not implemented.
4. **Single-process persistence/concurrency model.** Local concurrent runs and atomic repeated resume are tested, but SQLite checkpoint access lacks distributed locking, run leases, cancellation, and recovery coordination.
5. **Agent contract schemas are descriptive at runtime.** Manifest input/output schemas are validated as manifest data but are not enforced around every agent invocation.
6. **Scheduler is not durable.** Runtime schedule registration does not survive restart or provide reliable distributed dispatch.

### Low

7. **Dependency deprecations.** They are external and do not currently fail tests, but the pinned compatibility set should be revisited before a Python/LangGraph upgrade.
8. **Observability is local only.** SQLite events include useful status and timing data, but there is no provider-independent distributed tracing or token metrics.

## Fixes made during this audit

- Corrected workflow mapping persistence round-trips, including legacy `path` plus `literal: null` records, without discarding existing workflow rows.
- Corrected converging-DAG validation.
- Rejected mappings that reference downstream or independent nodes before graph compilation.
- Made approval routing honor the explicit `approve` option regardless of option order.
- Added immutable workflow-version storage and exact-version resume after restart.
- Preserved the run's thread ID on resume.
- Corrected the in-memory checkpoint path.
- Ensured all normalized agent failures, including explicit failed `AgentResult` values, retain execution ID and duration metadata.
- Added regression tests for each correction.

Security/reliability hardening added after this audit:

- Added fail-closed bearer authentication, explicit development-only bypass, principal permissions, and owner-scoped run inspection/events/approvals/resume.
- Added redaction for credential-like keys/patterns across agent/tool errors, logs, API persistence, event records, and API-created checkpoint state.
- Added configurable repository retention and authorized run deletion.
- Added SQLite WAL/busy-timeout configuration and serialized checkpoint initialization.
- Added an atomic resume claim and deterministic concurrent-run/repeated-resume tests.
- Added CLI bearer-token forwarding and security documentation.

No new product feature, external integration, frontend, distributed infrastructure, or plugin sandbox was introduced.

## Recommended next work

Essential before production use:

1. Replace local static tokens with a managed identity/authentication boundary, token rotation/revocation, tenant isolation, and approval-principal/action binding.
2. Move untrusted or semi-trusted plugins behind a real isolation boundary and define signed/provenanced plugin distribution.
3. Define data classification, encryption, and complete redaction/retention rules for run payloads, events, and checkpoints.
4. Add distributed idempotency keys, cancellation, recovery leases, and a deployment-supported database/checkpoint topology.
5. Enforce agent input/output schemas consistently and add contract-version compatibility checks.

Optional future work:

- Replace local event inspection with OpenTelemetry/provider-independent tracing.
- Persist and reconcile schedules.
- Add richer workflow version routes and explicit migration policy.
- Upgrade dependency versions only after validating LangGraph checkpoint compatibility and removing the recorded deprecations.

## Production-readiness decision

**Not production-ready; suitable as a well-tested local development/MVP framework.** The core extensibility, workflow configuration, tool permissions, monitoring, approval interrupt, restart recovery, authentication boundary, redaction, concurrency checks, CLI, scaffolding, and optional Ollama paths are implemented and regression-tested. The decision remains driven by ordinary in-process plugin execution, static local authentication, unencrypted storage, and single-process checkpoint coordination—not by an unverified claim that the framework is complete.

## Addendum: direct single-agent execution (2026-10-27)

The CLI now supports `agents run ID --interactive` and `agents run ID --input-file PATH`. It calls the authenticated `POST /v1/agents/{agent_id}/runs` route, which invokes the existing `AgentRunner` directly—without synthesizing or persisting a workflow definition. The API validates the registered input JSON Schema, preserves tool permissions, redacts stored inputs/outputs, assigns a run/thread ID and owner, and records the agent result as a normal run event. Existing owner-scoped `runs show` and `runs events` commands inspect these executions. The CLI requires an already-running API and does not launch another process.

The `external_text_analysis` manifest now declares its verified `text` string input. New connections infer observed field types from the connection test input but do not infer requiredness from a sample; unsupported or missing schemas cause interactive mode to request a JSON object. The connected external agent was exercised through the actual CLI/API code using an in-process authenticated FastAPI test client and an in-memory repository; no Uvicorn server was started and no persistent run database was changed.

Regression results after this addition: **82 passed, 1 skipped, 34 third-party warnings** in the deterministic suite; **83 passed, 34 warnings** with live Ollama enabled. The optional Ollama integration accounts for the deterministic skip. Warnings remain from Starlette/AnyIO and LangGraph/Python deprecations; no application-owned warning was introduced.
