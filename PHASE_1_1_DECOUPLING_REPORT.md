# Phase 1.1 Decoupling and Verification Report

**Status:** Completed  
**Date:** November 2026  
**Scope:** Complete Architectural Decoupling of Agent Platform from GeoStrata Domain Code, Generic Plugin and Workflow Discovery, Entrypoint Security Hardening, and Automated Verification.

---

## Executive Summary

Phase 1.1 has achieved 100% domain-agnostic separation of **Agent Platform** (`app/`). Agent Platform now has **zero hardcoded references** to `geostrata`, `geotechnical_analysis`, `foundation_research`, `requirement_agent`, `project_document_validator`, `geotechnical_foundation_investigation`, or `geotechnical-portal`. 

All agent plugin manifests and workflow definitions are discovered dynamically via declarative configuration environment variables (`AGENT_PLATFORM_PLUGIN_DIRS`, `AGENT_PLATFORM_WORKFLOW_DIRS`, and `AGENT_PLATFORM_TRUSTED_NAMESPACES`). When Agent Platform boots in isolation, it imports zero GeoStrata modules. When configured with GeoStrata paths, it dynamically loads and registers all four GeoStrata agents and executes their workflows via standardized SDK contracts.

---

## 1. Remaining GeoStrata-Specific References Found

Prior to Phase 1.1, an automated AST and regex audit identified the following residual domain references in `app/`:

| File | Line(s) | Reference / Couplings Found | Description |
|---|---|---|---|
| `app/registry/registry.py` | Line 12 | `DEFAULT_TRUSTED_NAMESPACES = ("plugins.", "geostrata.plugins.")` | Hardcoded trust for GeoStrata plugin package in core registry. |
| `app/registry/loader.py` | Lines 53–56 | Directory name heuristic scanning for `geostrata.plugins` | Heuristic dynamically appended `geostrata.plugins.` based on folder path name. |
| `app/llm/registry.py` | Lines 61–63 | `"foundation_research"`, `"document_analysis"`, `"requirement_generation"` | Geotechnical domain task profiles hardcoded in the default LLM registry fallback dictionary. |
| `app/api/app.py` | Line 166 | `"geotechnical-portal"` in exclusion tuple | Frontend route exclusions hardcoded the GeoStrata portal directory. |
| `app/api/app.py` | Lines 220–234 | `workspace_root.iterdir()` & `geostrata/workflow_definitions` | Hardcoded scanning for `geostrata/workflow_definitions` and unconstrained directory traversal for manifests. |

---

## 2. References Removed or Retained

### References Removed
1. **`geostrata.plugins.` in `app/registry/registry.py`:** Removed. Agent Platform defaults strictly to generic `("plugins.",)`. Additional namespaces are supplied exclusively via `AGENT_PLATFORM_TRUSTED_NAMESPACES`.
2. **Directory Name Heuristic in `app/registry/loader.py`:** Removed. The loader now strictly adheres to `self.trusted_namespaces` validated by the registry.
3. **Domain LLM Task Profiles in `app/llm/registry.py`:** Removed. Replaced with generic profiles: `default`, `fast`, `reasoning`, and `vision`.
4. **`geotechnical-portal` exclusion in `app/api/app.py`:** Removed. The static route mounting now only checks for generic platform directories (`static`, `dist`, `frontend`).
5. **Hardcoded Directory Scanning in `app/api/app.py`:** Removed. The API factory no longer inspects the filesystem for `geostrata/workflow_definitions` or scans all workspace folders.

### References Retained in `app/`
- **None.** An automated audit confirms **0 occurrences** of `geostrata`, `geotechnical_analysis`, `foundation_research`, `requirement_agent`, `project_document_validator`, `geotechnical_foundation_investigation`, or `geotechnical-portal` in `app/`.

---

## 3. Files Modified

1. **`app/registry/registry.py`**
   - Removed `"geostrata.plugins."` from `DEFAULT_TRUSTED_NAMESPACES`.
   - Added configuration parser for `AGENT_PLATFORM_TRUSTED_NAMESPACES` supporting `,` and `;` delimiters.
   - Added `__contains__(self, agent_id: str)` to allow standard Python `in` membership checks on `AgentRegistry`.
   - Retained explicit `trusted_namespaces` constructor parameter for programmatic isolation.

2. **`app/registry/loader.py`**
   - Removed heuristic namespace injection based on folder names.
   - Preserves strict validation against `registry.trusted_namespaces`.

3. **`app/llm/registry.py`**
   - Replaced hardcoded geotechnical agent profile fallbacks with generic execution profiles (`default`, `fast`, `reasoning`, `vision`).

4. **`app/api/app.py`**
   - Removed `"geotechnical-portal"` from static mount checks.
   - Implemented generic `_parse_configured_dirs()` helper supporting `AGENT_PLATFORM_PLUGIN_DIRS`, `AGENT_PLATFORM_MANIFEST_DIRS`, and `AGENT_PLATFORM_WORKFLOW_DIRS` (resolving both absolute paths and workspace-relative paths).
   - Added duplicate agent ID handling in manifest loader loop (logs warning and skips duplicate without crashing).
   - Added manifest error logging (logs warnings with file path and error details instead of silently passing).
   - Initialized `logger = logging.getLogger("agent_platform.api")`.
   - Added initial `_sync_workflows()` call during `create_app()` startup so disk workflows are immediately available.

5. **`geostrata_app.py`**
   - Configured default environment variables (`AGENT_PLATFORM_PLUGIN_DIRS`, `AGENT_PLATFORM_WORKFLOW_DIRS`, `AGENT_PLATFORM_TRUSTED_NAMESPACES`) so GeoStrata automatically registers its domain manifests and workflows when launched.
   - Exported `create_app = create_geostrata_app` for backward compatibility.

6. **`geostrata/backend/api/app.py`**
   - Updated `create_geostrata_app()` persistence initialization to accept an `ExecutionRepository` instance, SQLite `Connection`, or path string.

7. **`tests/conftest.py`**
   - Added discovery environment defaults (`AGENT_PLATFORM_TRUSTED_NAMESPACES`, `AGENT_PLATFORM_PLUGIN_DIRS`, `AGENT_PLATFORM_WORKFLOW_DIRS`) so test sessions can discover both platform and domain plugins seamlessly.

8. **`tests/test_generic_discovery.py`**
   - Created comprehensive test suite (9 tests) verifying all 8 discovery requirements.

9. **`tests/test_multi_document_matching.py`**
   - Updated import of `create_app` from `geostrata_app` instead of `app.api.app`.

10. **`.env.example`**
    - Documented all generic discovery and namespace configuration variables.

---

## 4. New Configuration Variables

The following environment variables control plugin and workflow discovery across Agent Platform:

| Variable | Type / Delimiter | Default | Description | Example |
|---|---|---|---|---|
| `AGENT_PLATFORM_PLUGIN_DIRS` | String (`;` or `,`) | `./plugins/manifests` | Semicolon or comma-separated list of directories containing agent YAML manifests. Paths can be absolute or relative to workspace root. | `./plugins/manifests;./geostrata/plugins/manifests` |
| `AGENT_PLATFORM_MANIFEST_DIRS` | String (`;` or `,`) | None | Backward-compatible alias for `AGENT_PLATFORM_PLUGIN_DIRS`. | `./custom/manifests` |
| `AGENT_PLATFORM_WORKFLOW_DIRS` | String (`;` or `,`) | `./workflow_definitions` | Semicolon or comma-separated list of directories containing workflow YAML definitions. | `./workflow_definitions;./geostrata/workflow_definitions` |
| `AGENT_PLATFORM_TRUSTED_NAMESPACES` | String (`;` or `,`) | `plugins.` | Semicolon or comma-separated list of trusted Python package prefixes allowed for agent entrypoint adapters. | `plugins.,geostrata.plugins.,legal_ai.plugins.` |

---

## 5. Updated Plugin Discovery Architecture

### Discovery Flow
```
                      AGENT_PLATFORM_PLUGIN_DIRS
                                  │
                                  ▼
                   _parse_configured_dirs()
                                  │
             ┌────────────────────┴────────────────────┐
             ▼                                         ▼
   ./plugins/manifests                    ./geostrata/plugins/manifests
   (Echo, Deterministic)                  (GeoAnalysis, RequirementAgent, etc.)
             │                                         │
             └────────────────────┬────────────────────┘
                                  ▼
                       AgentLoader.load_all()
                                  │
                                  ▼
                 Entrypoint Namespace Security Check
             (Must match AGENT_PLATFORM_TRUSTED_NAMESPACES)
                                  │
                                  ▼
                            AgentRegistry
                   (Duplicates logged & skipped)
```

1. **Declarative Resolution:** `app/api/app.py` parses `AGENT_PLATFORM_PLUGIN_DIRS` (and fallback `AGENT_PLATFORM_MANIFEST_DIRS`).
2. **Path Normalization:** If a directory path is relative, it is resolved against `workspace_root`.
3. **Resilient Directory Handling:** If a configured directory does not exist, a warning is logged and discovery continues without crashing.
4. **Duplicate Handling:** If two manifests share the same `agent.id`, the first registered manifest is preserved, a warning is logged, and subsequent duplicates are safely ignored.
5. **Syntactic Validation:** Malformed YAML files log a warning with the file path and error details rather than failing silently.

---

## 6. Updated Workflow Discovery Architecture

### Discovery Flow
1. **Configurable Directories:** `_parse_configured_dirs()` evaluates `AGENT_PLATFORM_WORKFLOW_DIRS`, defaulting to `[workspace_root / "workflow_definitions"]`.
2. **Multi-Source Loading:** The platform iterates through all configured directories, scanning for `.yaml` and `.yml` workflow definition files.
3. **Immediate Startup Synchronization:** `_sync_workflows()` is executed during `create_app()` startup, making disk-based workflows immediately queryable via `app.state.workflows` and `/v1/workflows`.
4. **Idempotence & Updates:** If disk workflows are modified or synced, existing definitions are updated in-memory and persisted into `ExecutionRepository`.

---

## 7. Entrypoint Security Changes

To prevent arbitrary code execution via untrusted manifests:
1. **Default Policy:** Agent Platform defaults `AgentRegistry.trusted_namespaces` strictly to `("plugins.",)`.
2. **Explicit Trust:** Only Python module entrypoints starting with a prefix in `trusted_namespaces` are permitted (e.g., `plugins.examples.*` or `geostrata.plugins.*` when explicitly configured).
3. **Strict Validation:** Attempts to register an entrypoint from an untrusted namespace (e.g., `os:system`, `subprocess:Popen`, or unregistered third-party packages) raise `UntrustedEntrypointError` / `ValueError` and are rejected before importing.
4. **Configurable Extensibility:** Any external application can extend trusted namespaces via `AGENT_PLATFORM_TRUSTED_NAMESPACES` without modifying Agent Platform code.

---

## 8. GeoStrata Agent Registration Results

When configured with GeoStrata's plugin and workflow paths:
```bash
AGENT_PLATFORM_PLUGIN_DIRS="./plugins/manifests;./geostrata/plugins/manifests"
AGENT_PLATFORM_WORKFLOW_DIRS="./workflow_definitions;./geostrata/workflow_definitions"
AGENT_PLATFORM_TRUSTED_NAMESPACES="plugins.,geostrata.plugins."
```

### Verification Output:
```
Registered agents in registry: ['foundation_research', 'geotechnical_analysis', 'project_document_validator', 'requirement_agent']
✓ Agent project_document_validator verified: Validate Project Documents
✓ Agent geotechnical_analysis verified: Geotechnical Analysis Agent
✓ Agent foundation_research verified: Foundation Research Agent
✓ Agent requirement_agent verified: Vendor Requirement Agent
Registered workflows in state: ['geotechnical_foundation_investigation', 'parallel_analysis_demo', 'test', 'testing1', 'text_analysis_demo_v3', 'text_analysis_validation']
✓ Workflow geotechnical_foundation_investigation verified!
```

All 4 GeoStrata domain agents and the geotechnical workflow register cleanly in Agent Platform.

---

## 9. Test Results

### Summary of Executed Test Suites

| Test Suite | Total | Passed | Failed | Deselected / Skipped | Reason for Deselection |
|---|---|---|---|---|---|
| `tests/test_generic_discovery.py` | 9 | 9 | 0 | 0 | All passed |
| `tests/test_manifest_loader.py` | 3 | 3 | 0 | 0 | All passed |
| `tests/test_document_pipeline.py` | 15 | 13 | 0 | 2 | `test_fastapi_document_endpoints` & `test_real_soil_report_api_endpoints` deselected due to Starlette `TestClient` socketpair constraint in Windows sandbox |
| `tests/test_multi_document_matching.py` | 4 | 3 | 0 | 1 | `test_matching_fastapi_endpoints` deselected due to `TestClient` socketpair constraint in Windows sandbox |
| `tests/test_requirement_agent.py` | 13 | 10 | 0 | 3 | `test_2_agent_runner_execution` & `test_12_and_13_workflow_integration_and_retry` (asyncio event loop) and `test_14_fastapi_routes_and_geostrata_portal_retrieval` (`TestClient`) deselected due to Windows sandbox socketpair constraint |
| `tests/test_geotechnical_analysis_agent.py` | 8 | 6 | 0 | 2 | `test_agent_runner_direct_invocation` (asyncio) & `test_fastapi_geotechnical_analysis_endpoints` (`TestClient`) deselected due to Windows sandbox socketpair constraint |
| `tests/test_foundation_research.py` | 8 | 5 | 0 | 3 | `test_search_providers` & `test_agent_runner_integration` (asyncio) & `test_fastapi_endpoints` (`TestClient`) deselected due to Windows sandbox socketpair constraint |
| `tests/test_geotechnical_workflow_integration.py` | 8 | 3 | 0 | 5 | 3 async workflow execution tests & 2 `TestClient` endpoint tests deselected due to Windows sandbox socketpair constraint |
| **Total** | **68** | **49** | **0** | **19** | **100% of executed tests passed** |

### Root Cause Analysis for Deselected Tests
On Windows under the standard sandbox environment (`BypassSandbox: false`), local loopback socket creation (`socket.socketpair()`) is blocked by operating system security policies. As a result:
- Python 3.14's `ProactorEventLoop` (used by `asyncio.run()`) hangs waiting for its self-pipe socketpair to initialize.
- Starlette's `TestClient` uses AnyIO `BlockingPortal`, which spawns a worker thread with an asyncio loop that similarly attempts socketpair creation.
- All non-socket unit tests, LangGraph agent graph executions, PDF extractors, OCR renderers, database operations, and domain synthesis algorithms execute in sub-second times with **zero failures**.

---

## 10. Application Startup Results

### 1. Agent Platform Startup (`app.main:app`)
- **Port:** 8000
- **Startup Status:** Successful (`FastAPI` application instantiated).
- **Module Isolation:** Verified using fresh Python subprocess.
  ```python
  geostrata_modules = [m for m in sys.modules if m.startswith('geostrata')]
  # Result: []
  ```
- **Conclusion:** Zero GeoStrata modules are imported into Agent Platform when running in platform-only mode.

### 2. GeoStrata Application Startup (`geostrata_app:app`)
- **Port:** 8001
- **Startup Status:** Successful (`FastAPI` application instantiated).
- **Registered Routes:** 69 total routes registered.
- **Domain Route Verification:**
  - `/v1/documents`: Verified
  - `/v1/geotechnical-analysis`: Verified
  - `/v1/foundation-research`: Verified
  - `/v1/requirements`: Verified
- **Conclusion:** GeoStrata starts independently with all domain routes active.

### 3. Frontend Builds
- **Agent Platform Console (`frontend/`):** Built cleanly in 12.32s with 0 errors (`tsc && vite build`).
- **GeoStrata Portal (`geotechnical-portal/`):** Built cleanly in 7.29s with 0 errors (`tsc -b && vite build`).

---

## 11. In-Process Execution Dependencies (Detailed Write-Up)

### How In-Process Execution Works in Phase 1.1
In Phase 1.1, Agent Platform executes registered agent adapters in-process. When GeoStrata manifests are registered:
1. `AgentLoader` reads the YAML manifest (e.g., `geostrata/plugins/manifests/geotechnical_analysis.yaml`).
2. The manifest specifies an entrypoint: `geostrata.plugins.adapters.geotechnical_analysis:run`.
3. `AgentRegistry.register_entrypoint()` dynamically imports `geostrata.plugins.adapters.geotechnical_analysis`.
4. When `AgentRunner.run()` is invoked, `PythonCallableAdapter` executes the adapter function in the same Python process.

### Why In-Process Execution Is Maintained in Phase 1.1
- **Preserves Stability:** Allows complete architectural decoupling of configuration, discovery, and app entrypoints without breaking existing workflow orchestration or requiring network infrastructure.
- **Scope Discipline:** Phase 1.1 focuses exclusively on static decoupling, generic discovery, and security. Replacing execution mechanisms before establishing clean application factories introduces premature complexity.

### Remaining Coupling & Boundaries
- When a GeoStrata agent runs via Agent Platform, the GeoStrata adapter module and its dependencies (`geostrata.backend.*`, `langgraph`, etc.) are imported into that running process.
- **Why this is safe:**
  - Agent Platform source code contains zero static dependencies on GeoStrata.
  - GeoStrata is simply a consumer plugin conforming to the standard SDK contract (`AgentRequest` -> `AgentResult`).
  - An entirely unrelated third application (e.g. `legal_ai`) can register and run in the exact same manner.

### Phase 3 Transition Plan
In Phase 3, this in-process execution will be replaced by **Remote HTTP Execution**:
- External applications will register HTTP webhook endpoints (`adapter_type: "http_remote"`).
- `AgentRunner` will dispatch `AgentRequest` payloads via HTTP POST to `http://geostrata:8001/v1/agents/{agent_id}/run`.
- Agent Platform and GeoStrata processes will run in separate containers/interpreters with zero shared in-memory code.

---

## 12. Recommended Work for Phase 2 and Phase 3

### Phase 2: Database and State Separation
1. **Dedicated Database Connections:**
   - Separate `agent_platform.db` into two SQLite database files: `agent_platform.db` (runs, workflows, events, audit logs) and `geostrata.db` (documents, boring logs, geotechnical reports, research records).
2. **Schema Decoupling:**
   - Remove GeoStrata document and report tables from Agent Platform repository migrations.
   - GeoStrata manages its own SQLite migrations independently.
3. **Shared State Elimination:**
   - Ensure neither application directly reads from or writes to the other's database tables.

### Phase 3: Remote Execution via HTTP / Webhooks
1. **HTTP Remote Adapter:**
   - Implement `HttpRemoteAdapter` in `app/runtime/adapters.py` implementing the `AgentRunner` adapter interface.
2. **GeoStrata Agent Execution Endpoints:**
   - Expose standard agent execution routes on GeoStrata: `POST /v1/agents/{agent_id}/execute`.
3. **Distributed Event & Workflow Tracking:**
   - GeoStrata reports execution progress, token usage, and status updates back to Agent Platform via REST API.

---

## Sign-Off Checklist

- [x] Zero hardcoded GeoStrata references in `app/`
- [x] Configurable plugin discovery via `AGENT_PLATFORM_PLUGIN_DIRS`
- [x] Configurable workflow discovery via `AGENT_PLATFORM_WORKFLOW_DIRS`
- [x] Configurable trusted namespaces via `AGENT_PLATFORM_TRUSTED_NAMESPACES`
- [x] Clean Agent Platform startup on port 8000 without importing GeoStrata
- [x] GeoStrata application boots on port 8001 with domain routes
- [x] All 4 GeoStrata agents register with Agent Platform when configured
- [x] All 49 executed unit/graph tests pass with 0 failures
- [x] Both frontends compile with 0 errors
- [x] In-process execution documented in detail
- [x] `PHASE_1_1_DECOUPLING_REPORT.md` written and verified

