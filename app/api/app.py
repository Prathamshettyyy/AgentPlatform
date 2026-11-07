from __future__ import annotations
import asyncio, json, logging, os, threading, uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger("agent_platform.api")
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langgraph.types import Command
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, Field
from app.registry import AgentLoader, AgentRegistry
from app.runtime.errors import AgentDisabledError, AgentNotFoundError
from app.runtime.runner import AgentRunner
from app.security import AuthConfig, AuthenticationError, AuthorizationError, Principal, redact_sensitive
from app.sdk.contracts import AgentRequest
from app.storage.repository import ExecutionRepository
from app.tools import ToolLoader, ToolRegistry, ToolRunner
from app.workflows.builder import WorkflowBuilder
from app.workflows.models import WorkflowDefinition
from app.workflows.validator import WorkflowValidationError
from typing import Literal, Any
from app.temporal import (
    TemporalConfig,
    get_temporal_client,
    DynamicLangGraphWorkflow,
    BatchLangGraphWorkflow,
    create_temporal_schedule,
    get_temporal_schedule,
    list_temporal_schedules,
    pause_temporal_schedule,
    unpause_temporal_schedule,
    trigger_temporal_schedule,
    delete_temporal_schedule,
)

class RunRequest(BaseModel):
    workflow_id: str
    inputs: dict = {}
    allow_partial: bool = True
    strict: bool = False
    execution_backend: Literal["direct", "temporal"] | None = None
    wait: bool | None = None

class BatchRunRequest(BaseModel):
    workflow_id: str
    items: list[dict[str, Any]]
    concurrency: int = 5
    execution_backend: Literal["direct", "temporal"] | None = None
    allow_partial: bool = True

class ScheduleCreateRequest(BaseModel):
    schedule_id: str
    workflow_id: str
    workflow_version: str = "1.0.0"
    cron_or_interval: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    paused: bool = False

class ResumeRequest(BaseModel): decision: str
class AgentRunRequest(BaseModel):
    inputs: dict = Field(default_factory=dict)
    task: str = "direct agent execution"

def create_app(
    repository: ExecutionRepository | None = None,
    manifests_dir: str | Path | None = None,
    tool_manifests_dir: str | Path | None = None,
    auth_mode: str | None = None,
    auth_tokens: dict[str, str | dict] | None = None,
    additional_routers: list[Any] | None = None,
    app_state_initializer: Any | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            if app.state.checkpointer is not None:
                await app.state.checkpointer.conn.close()
            app.state.repository.close()

    auth = AuthConfig.from_values(auth_mode, auth_tokens)
    app = FastAPI(title="Agent Platform", lifespan=lifespan)
    app.state.auth = auth

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def authenticate_requests(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path.startswith("/v1/") and request.url.path not in {"/v1/health"}:
            try:
                request.state.principal = auth.authenticate(request.headers.get("authorization"))
            except AuthenticationError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
        elif not hasattr(request.state, "principal"):
            request.state.principal = Principal("anonymous", frozenset())
        return await call_next(request)

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        if isinstance(exc, HTTPException):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "*",
                    "Access-Control-Allow-Headers": "*",
                },
            )
        return JSONResponse(
            status_code=500,
            content={"detail": str(exc)},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )

    @app.get("/v1/health")
    def health():
        return {
            "status": "healthy",
            "service": "agent-platform",
            "auth_mode": auth.mode,
            "version": "1.0.0",
        }

    def principal(request: Request) -> Principal:
        return request.state.principal

    def require(request: Request, permission: str) -> Principal:
        current = principal(request)
        try:
            auth.require(current, permission)
        except AuthorizationError as exc:
            raise HTTPException(403, str(exc)) from exc
        return current

    def owned_run(request: Request, run_id: str) -> tuple[Principal, dict]:
        current = require(request, "runs.read")
        record = repo.get_run(run_id)
        if not record or record.get("owner_id") != current.user_id:
            raise HTTPException(404, "run not found")
        return current, record

    registry = AgentRegistry()
    workspace_root = Path(__file__).resolve().parents[2]
    trusted_manifests = Path(manifests_dir) if manifests_dir else workspace_root / "plugins" / "manifests"

    def _parse_configured_dirs(env_vars: list[str]) -> list[Path]:
        """Parse semicolon or comma separated directories from environment variables."""
        results: list[Path] = []
        for env_name in env_vars:
            val = os.getenv(env_name)
            if not val:
                continue
            delims = [";", ","]
            raw_items = [val]
            for d in delims:
                raw_items = [part for item in raw_items for part in item.split(d)]
            for raw in raw_items:
                cleaned = raw.strip()
                if not cleaned:
                    continue
                p = Path(cleaned)
                if not p.is_absolute():
                    p = (workspace_root / p).resolve()
                if p.is_dir():
                    if p not in results:
                        results.append(p)
                else:
                    logger.warning("Configured directory not found for %s: %s", env_name, cleaned)
        return results

    def _get_manifest_dirs() -> list[Path]:
        dirs: list[Path] = []
        if trusted_manifests.is_dir() and trusted_manifests not in dirs:
            dirs.append(trusted_manifests)
        configured = _parse_configured_dirs(["AGENT_PLATFORM_PLUGIN_DIRS", "AGENT_PLATFORM_MANIFEST_DIRS"])
        for c_dir in configured:
            if c_dir not in dirs:
                dirs.append(c_dir)
        return dirs

    def _get_workflow_dirs() -> list[Path]:
        dirs: list[Path] = []
        std_wf = trusted_manifests.parent.parent / "workflow_definitions"
        if std_wf.is_dir() and std_wf not in dirs:
            dirs.append(std_wf)
        configured = _parse_configured_dirs(["AGENT_PLATFORM_WORKFLOW_DIRS"])
        for c_dir in configured:
            if c_dir not in dirs:
                dirs.append(c_dir)
        return dirs

    for m_dir in _get_manifest_dirs():
        try:
            loader = AgentLoader(registry, m_dir)
            for path in loader.discover():
                try:
                    manifest = loader.read_manifest(path)
                    if not manifest.enabled:
                        continue
                    if manifest.id in registry:
                        logger.warning("Agent '%s' is already registered; skipping duplicate from %s", manifest.id, path)
                        continue
                    loader.register_manifest(manifest, path)
                except Exception as exc:
                    logger.warning("Failed to load agent manifest from %s: %s", path, exc)
        except Exception as exc:
            logger.warning("Failed to discover manifests in %s: %s", m_dir, exc)
    repo = repository or ExecutionRepository()
    tool_registry = ToolRegistry()
    trusted_tool_manifests = (
        Path(tool_manifests_dir)
        if tool_manifests_dir
        else Path(__file__).resolve().parents[2] / "plugins" / "tool_manifests"
    )
    ToolLoader(tool_registry, trusted_tool_manifests).load_all()
    tool_runner = ToolRunner(tool_registry, execution_recorder=lambda run_id, node_id, status, payload: repo.add_event(run_id, node_id, status, payload))
    agent_runner = AgentRunner(registry, tool_runner=tool_runner)
    workflows = {item["id"]: WorkflowDefinition.model_validate(item) for item in repo.list_workflows()}
    def _sync_workflows():
        persisted = repo.list_workflows()
        persisted_ids = {item["id"] for item in persisted if isinstance(item, dict) and "id" in item}
        for stale_id in list(workflows.keys()):
            if stale_id not in persisted_ids:
                workflows.pop(stale_id, None)
        for item in persisted:
            try:
                workflows[item["id"]] = WorkflowDefinition.model_validate(item)
            except Exception:
                pass
        for wf_dir in _get_workflow_dirs():
            if wf_dir.is_dir():
                import yaml
                for path in sorted(wf_dir.glob("*.y*ml")):
                    try:
                        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                        if isinstance(raw, dict) and raw.get("id"):
                            disk_wf = WorkflowDefinition.model_validate(raw)
                            if disk_wf.id not in workflows or (
                                disk_wf.version != workflows[disk_wf.id].version
                                or [n.id for n in disk_wf.nodes] != [n.id for n in workflows[disk_wf.id].nodes]
                                or [n.status for n in disk_wf.nodes] != [n.status for n in workflows[disk_wf.id].nodes]
                            ):
                                workflows[disk_wf.id] = disk_wf
                                repo.delete_workflow(disk_wf.id)
                                repo.save_workflow(disk_wf.model_dump(by_alias=True, exclude_unset=True))
                    except Exception as exc:
                        logger.warning("Failed to load workflow definition from %s: %s", path, exc)
    _sync_workflows()
    if str(repo.path) == ":memory:":
        checkpoint_path = ":memory:"
    else:
        repository_path = Path(repo.path)
        checkpoint_path = str(repository_path.with_name(repository_path.stem + "_checkpoints" + (repository_path.suffix or ".db")))
    app.state.registry, app.state.tool_registry, app.state.tool_runner, app.state.agent_runner, app.state.workflows, app.state.repository, app.state.graphs, app.state.checkpointer = registry, tool_registry, tool_runner, agent_runner, workflows, repo, {}, None
    app.state.resume_locks: dict[str, threading.Lock] = {}
    app.state.checkpointer_lock = threading.Lock()
    async def get_checkpointer():
        while not app.state.checkpointer_lock.acquire(blocking=False):
            await asyncio.sleep(0)
        try:
            current_loop = asyncio.get_running_loop()
            checkpointer = app.state.checkpointer
            if checkpointer is not None:
                try:
                    lock_loop = checkpointer.lock._get_loop()
                    if lock_loop != current_loop:
                        checkpointer = None
                        app.state.checkpointer = None
                except Exception:
                    checkpointer = None
                    app.state.checkpointer = None
            if app.state.checkpointer is None:
                connection = await aiosqlite.connect(checkpoint_path)
                await connection.execute("PRAGMA busy_timeout = 5000")
                if checkpoint_path != ":memory:":
                    await connection.execute("PRAGMA journal_mode = WAL")
                await connection.commit()
                app.state.checkpointer = AsyncSqliteSaver(connection)
                await app.state.checkpointer.setup()
        finally:
            app.state.checkpointer_lock.release()
        return app.state.checkpointer
    def _sync_agents():
        for aid in list(registry._agents.keys()):
            entry = registry._agents[aid].entrypoint or ""
            if entry.startswith("plugins.examples.") and not any((m_dir / f"{aid}.yaml").is_file() or (m_dir / f"{aid}.yml").is_file() for m_dir in _get_manifest_dirs()):
                registry._agents.pop(aid, None)
        for m_dir in _get_manifest_dirs():
            if m_dir.is_dir():
                try:
                    loader = AgentLoader(registry, m_dir)
                    for path in loader.discover():
                        manifest = loader.read_manifest(path)
                        if manifest.enabled and manifest.id not in registry._agents:
                            loader.register_manifest(manifest, path)
                except Exception:
                    pass

    @app.get("/v1/agents")
    def agents(request: Request):
        require(request, "metadata.read")
        _sync_agents()
        return registry.list_enabled()

    @app.get("/v1/agents/{agent_id}")
    def agent(agent_id: str, request: Request):
        require(request, "metadata.read")
        _sync_agents()
        try: return registry.get(agent_id).metadata
        except Exception as exc: raise HTTPException(404, str(exc))

    @app.get("/v1/agents/{agent_id}/preview-delete")
    def preview_delete_agent(agent_id: str, request: Request):
        require(request, "metadata.read")
        _sync_agents()
        existed_in_registry = agent_id in registry._agents
        inspection = repo.inspect_agent_records(agent_id)
        plugins_dir = trusted_manifests.parent
        manifest_path = None
        for suffix in (".yaml", ".yml"):
            p = trusted_manifests / f"{agent_id}{suffix}"
            if p.is_file():
                manifest_path = p
                break
        adapter_dir = plugins_dir / "examples" / f"connected_{agent_id}"
        if not adapter_dir.is_dir():
            alt_dir = plugins_dir / "examples" / agent_id
            if alt_dir.is_dir():
                adapter_dir = alt_dir
            else:
                adapter_dir = None
        catalog_entry = False
        for cat_name in ("connection_catalog.json", "agents_catalog.json"):
            for candidate in (trusted_manifests / cat_name, plugins_dir / cat_name):
                if candidate.is_file():
                    try:
                        catalog = json.loads(candidate.read_text(encoding="utf-8"))
                        if isinstance(catalog, dict) and agent_id in catalog:
                            catalog_entry = True
                    except Exception:
                        pass
        has_db_records = bool(inspection["direct_run_count"] or inspection["event_count"] or inspection["workflows_referencing"])
        exists_on_disk = manifest_path is not None or adapter_dir is not None
        if not existed_in_registry and not has_db_records and not exists_on_disk:
            raise HTTPException(404, "agent not found")
        return {
            "agent_id": agent_id,
            "direct_run_count": inspection["direct_run_count"],
            "event_count": inspection["event_count"],
            "checkpoint_count": inspection["checkpoint_count"],
            "workflows_referencing": [wf["id"] for wf in inspection["workflows_referencing"]],
            "has_manifest": manifest_path is not None,
            "has_adapter": adapter_dir is not None,
            "has_catalog_entry": catalog_entry,
        }

    @app.delete("/v1/agents/{agent_id}")
    def delete_agent(agent_id: str, request: Request):
        current = principal(request)
        if not (current.can("agent.write") or current.can("agent.delete") or current.can("workflow.write")):
            require(request, "workflow.write")
        _sync_agents()
        existed_in_registry = registry._agents.pop(agent_id, None) is not None
        inspection = repo.inspect_agent_records(agent_id)
        plugins_dir = trusted_manifests.parent
        manifest_path = None
        for suffix in (".yaml", ".yml"):
            p = trusted_manifests / f"{agent_id}{suffix}"
            if p.is_file():
                manifest_path = p
                break
        adapter_dir = plugins_dir / "examples" / f"connected_{agent_id}"
        if not adapter_dir.is_dir():
            alt_dir = plugins_dir / "examples" / agent_id
            if alt_dir.is_dir():
                adapter_dir = alt_dir
            else:
                adapter_dir = None

        has_db_records = bool(inspection["direct_run_count"] or inspection["event_count"] or inspection["workflows_referencing"])
        exists_on_disk = manifest_path is not None or adapter_dir is not None
        if not existed_in_registry and not has_db_records and not exists_on_disk:
            raise HTTPException(404, "agent not found")

        # 1. Purge database records (direct runs, events, checkpoints)
        purged = repo.purge_agent_records(agent_id)

        # 2. Delete local manifest file
        removed_files = []
        if manifest_path and manifest_path.is_file():
            try:
                manifest_path.unlink()
                removed_files.append(str(manifest_path))
            except Exception:
                pass

        # 3. Delete generated adapter package directory
        if adapter_dir and adapter_dir.is_dir():
            try:
                for child in sorted(adapter_dir.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink(missing_ok=True)
                        removed_files.append(str(child))
                    elif child.is_dir():
                        child.rmdir()
                adapter_dir.rmdir()
                removed_files.append(str(adapter_dir))
            except Exception:
                pass

        # 4. Remove from connection_catalog.json if present
        for cat_name in ("connection_catalog.json", "agents_catalog.json"):
            for candidate in (trusted_manifests / cat_name, plugins_dir / cat_name):
                if candidate.is_file():
                    try:
                        catalog = json.loads(candidate.read_text(encoding="utf-8"))
                        if isinstance(catalog, dict) and agent_id in catalog:
                            catalog.pop(agent_id, None)
                            candidate.write_text(json.dumps(catalog, indent=2), encoding="utf-8")
                    except Exception:
                        pass

        # 5. Clean up referencing workflows: update or unregister them
        wf_dir = trusted_manifests.parent.parent / "workflow_definitions"
        _sync_workflows()
        for wf_id, wf in list(workflows.items()):
            if any(n.type == "agent" and n.agent_id == agent_id for n in wf.nodes):
                remaining_nodes = [n for n in wf.nodes if not (n.type == "agent" and n.agent_id == agent_id)]
                if not remaining_nodes:
                    workflows.pop(wf_id, None)
                    repo.unregister_workflow(wf_id)
                else:
                    removed_node_ids = {n.id for n in wf.nodes if n.type == "agent" and n.agent_id == agent_id}
                    remaining_edges = [e for e in wf.edges if e.from_node not in removed_node_ids and e.to not in removed_node_ids]
                    new_nodes = []
                    for n in remaining_nodes:
                        n_copy = n.model_copy(deep=True)
                        n_copy.input_mappings = {
                            f: m for f, m in n_copy.input_mappings.items()
                            if not (m.path and m.path.startswith("node_outputs.") and m.path.split(".")[1] in removed_node_ids)
                        }
                        new_nodes.append(n_copy)
                    try:
                        updated_wf = WorkflowDefinition(
                            id=wf.id,
                            version=wf.version,
                            nodes=new_nodes,
                            edges=remaining_edges,
                            max_steps=wf.max_steps,
                        )
                        WorkflowBuilder(registry).build(updated_wf)
                        workflows[wf_id] = updated_wf
                        repo.save_workflow(updated_wf.model_dump(by_alias=True))
                    except Exception:
                        workflows.pop(wf_id, None)
                        repo.unregister_workflow(wf_id)

        # Also update workflow definition YAML files on disk if they reference this agent
        if wf_dir.is_dir():
            import yaml
            for p in sorted(wf_dir.glob("*.y*ml")):
                try:
                    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
                    if isinstance(raw, dict) and any(n.get("type") == "agent" and n.get("agent_id") == agent_id for n in raw.get("nodes", [])):
                        nodes = [n for n in raw.get("nodes", []) if not (n.get("type") == "agent" and n.get("agent_id") == agent_id)]
                        removed_ids = {n.get("id") for n in raw.get("nodes", []) if n.get("type") == "agent" and n.get("agent_id") == agent_id}
                        edges = [e for e in raw.get("edges", []) if e.get("from") not in removed_ids and e.get("to") not in removed_ids]
                        raw["nodes"] = nodes
                        raw["edges"] = edges
                        p.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
                except Exception:
                    pass

        return {"deleted": True, "agent_id": agent_id, "purged_records": purged, "removed_files": removed_files}

    @app.post("/v1/agents/{agent_id}/runs")
    async def run_agent(agent_id: str, request: AgentRunRequest, http_request: Request):
        current = require(http_request, "agent.execute")
        _sync_agents()
        try:
            registered = registry.get(agent_id)
        except (AgentNotFoundError, AgentDisabledError) as exc:
            raise HTTPException(404, "agent not found or disabled") from exc
        schema = registered.metadata.input_schema
        if schema:
            try:
                validator = Draft202012Validator(schema)
                validator.check_schema(schema)
            except SchemaError as exc:
                raise HTTPException(500, "agent input schema is invalid") from exc
            failures = sorted(validator.iter_errors(request.inputs), key=lambda error: list(error.absolute_path))
            if failures:
                raise HTTPException(
                    422,
                    detail={
                        "message": "agent input does not match its declared schema",
                        "path": list(failures[0].absolute_path),
                    },
                )

        run_id = str(uuid.uuid4())
        safe_inputs = redact_sensitive(request.inputs)
        repo.start_run(run_id, None, safe_inputs, None, run_id, current.user_id)
        result = await agent_runner.run(
            agent_id,
            AgentRequest(
                task=request.task,
                inputs=safe_inputs,
                run_id=run_id,
                node_id=agent_id,
            ),
        )
        safe_output = redact_sensitive(result.output)
        execution = redact_sensitive(result.metadata)
        payload: dict = {"agent_id": agent_id, "execution": execution}
        event_payload: dict = {"agent_id": agent_id, "metadata": execution}
        if result.status == "succeeded":
            payload["final_output"] = safe_output
            event_payload["output"] = safe_output
        else:
            safe_error = redact_sensitive(result.error.model_dump(mode="json")) if result.error else {"message": "agent execution failed"}
            payload["error"] = safe_error
            event_payload["error"] = safe_error
        repo.update_run(run_id, result.status, payload)
        repo.add_event(run_id, agent_id, result.status, event_payload)
        return repo.get_run(run_id)
    @app.get("/v1/tools")
    def tools(request: Request):
        require(request, "metadata.read")
        return tool_registry.list_enabled()
    @app.get("/v1/workflows")
    def list_workflows(request: Request, include_drafts: bool = False):
        require(request, "workflow.read")
        _sync_workflows()
        result = []
        for wf in workflows.values():
            entry = wf.model_dump(by_alias=True, exclude_unset=True)
            entry["registered"] = True
            entry["registration_status"] = "registered"
            result.append(entry)
        if not include_drafts:
            return result
        registered_ids = set(workflows.keys())
        for wf_dir in _get_workflow_dirs():
            if wf_dir.is_dir():
                import yaml
                for path in sorted(wf_dir.glob("*.y*ml")):
                    try:
                        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                        if isinstance(raw, dict) and raw.get("id") and str(raw["id"]) not in registered_ids:
                            draft_wf = WorkflowDefinition.model_validate(raw)
                            draft_entry = draft_wf.model_dump(by_alias=True, exclude_unset=True)
                            draft_entry["registered"] = False
                            draft_entry["registration_status"] = "disconnected"
                            draft_entry["workflow_file"] = str(path)
                            result.append(draft_entry)
                            registered_ids.add(str(raw["id"]))
                    except Exception:
                        pass
        return result

    @app.post("/v1/workflows/draft")
    def save_workflow_draft(payload: dict, request: Request):
        require(request, "workflow.write")
        wf_id = payload.get("id")
        if not wf_id or not isinstance(wf_id, str):
            raise HTTPException(422, "id is required")
        import re, yaml
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", wf_id):
            raise HTTPException(422, "invalid workflow id")
        wf_dir = trusted_manifests.parent.parent / "workflow_definitions"
        wf_dir.mkdir(parents=True, exist_ok=True)
        wf_path = wf_dir / f"{wf_id}.yaml"
        content = {
            "id": wf_id,
            "version": payload.get("version", "1.0.0"),
            "nodes": payload.get("nodes", []),
            "edges": payload.get("edges", []),
        }
        wf_path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
        return {"id": wf_id, "status": "draft", "saved": True, "workflow_file": str(wf_path)}

    @app.get("/v1/workflows/{workflow_id}/preview-delete")
    def preview_delete_workflow(workflow_id: str, request: Request):
        require(request, "workflow.read")
        _sync_workflows()
        inspection = repo.inspect_workflow_records(workflow_id)
        existed_in_mem = workflow_id in workflows
        wf_dir = trusted_manifests.parent.parent / "workflow_definitions"
        local_path = None
        if wf_dir.is_dir():
            for suffix in (".yaml", ".yml"):
                p = wf_dir / f"{workflow_id}{suffix}"
                if p.is_file():
                    local_path = str(p)
                    break
        if not existed_in_mem and not inspection["registered"] and inspection["version_count"] == 0 and local_path is None:
            raise HTTPException(404, "workflow not found")
        return {
            "workflow_id": workflow_id,
            "registered": existed_in_mem or bool(inspection["registered"]),
            "has_local_file": local_path is not None,
            "local_file": local_path,
            "versions": inspection["versions"],
            "run_count": inspection["run_count"],
            "event_count": inspection["event_count"],
            "checkpoint_count": inspection["checkpoint_count"],
        }

    @app.post("/v1/workflows")
    def create_workflow(workflow: WorkflowDefinition, request: Request):
        require(request, "workflow.write")
        _sync_agents()
        try: WorkflowBuilder(registry).build(workflow)
        except Exception as exc: raise HTTPException(422, str(exc))
        try:
            repo.save_workflow(workflow.model_dump(by_alias=True))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        workflows[workflow.id] = workflow
        res = workflow.model_dump(by_alias=True, exclude_unset=True)
        res["registered"] = True
        res["registration_status"] = "registered"
        return res

    @app.get("/v1/workflows/{workflow_id}")
    def get_workflow(workflow_id: str, request: Request):
        require(request, "workflow.read")
        _sync_workflows()
        if workflow_id not in workflows: raise HTTPException(404, "workflow not found")
        res = workflows[workflow_id].model_dump(by_alias=True, exclude_unset=True)
        res["registered"] = True
        res["registration_status"] = "registered"
        return res

    @app.put("/v1/workflows/{workflow_id}")
    def update_workflow(workflow_id: str, payload: dict, request: Request):
        require(request, "workflow.write")
        _sync_workflows()
        wf_dir = trusted_manifests.parent.parent / "workflow_definitions"
        wf_dir.mkdir(parents=True, exist_ok=True)
        wf_path = wf_dir / f"{workflow_id}.yaml"
        for suffix in (".yaml", ".yml"):
            p = wf_dir / f"{workflow_id}{suffix}"
            if p.is_file():
                wf_path = p
                break

        clean = dict(payload)
        for k in ("registered", "registration_status", "workflow_file", "validation_error"):
            clean.pop(k, None)
        clean["id"] = workflow_id
        if "version" not in clean:
            clean["version"] = "1.0.0"

        try:
            wf_obj = WorkflowDefinition.model_validate(clean)
        except Exception as exc:
            raise HTTPException(422, detail=f"Invalid workflow definition: {exc}")

        import yaml
        content = wf_obj.model_dump(by_alias=True, exclude_unset=True)
        for k in ("registered", "registration_status", "workflow_file", "validation_error"):
            content.pop(k, None)
        wf_path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")

        is_registered = workflow_id in workflows
        had_versions = bool(repo.inspect_workflow_records(workflow_id).get("versions"))
        validation_error = None
        if (is_registered or had_versions) and len(wf_obj.nodes) > 0:
            _sync_agents()
            try:
                WorkflowBuilder(registry).build(wf_obj)
                try:
                    repo.save_workflow(wf_obj.model_dump(by_alias=True))
                except ValueError as exc:
                    if "workflow version already exists with a different definition" in str(exc):
                        current_ver = wf_obj.version or "1.0.0"
                        parts = current_ver.split(".")
                        while len(parts) < 3:
                            parts.append("0")
                        try:
                            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
                        except ValueError:
                            major, minor, patch = 1, 0, 0
                        while True:
                            patch += 1
                            next_ver = f"{major}.{minor}.{patch}"
                            if not repo.get_workflow(wf_obj.id, next_ver):
                                break
                        wf_obj.version = next_ver
                        content["version"] = next_ver
                        wf_path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
                        repo.save_workflow(wf_obj.model_dump(by_alias=True))
                workflows[workflow_id] = wf_obj
            except Exception as exc:
                validation_error = str(exc)
                repo.unregister_workflow(workflow_id)
                workflows.pop(workflow_id, None)
        elif len(wf_obj.nodes) == 0 and is_registered:
            repo.unregister_workflow(workflow_id)
            workflows.pop(workflow_id, None)

        res = wf_obj.model_dump(by_alias=True, exclude_unset=True)
        res["registered"] = workflow_id in workflows
        res["registration_status"] = "registered" if workflow_id in workflows else ("draft" if len(wf_obj.nodes) == 0 else "disconnected")
        res["workflow_file"] = str(wf_path)
        if validation_error:
            res["validation_error"] = validation_error
        return res

    @app.post("/v1/workflows/{workflow_id}/add-agent")
    def add_agent_to_workflow(workflow_id: str, payload: dict, request: Request):
        require(request, "workflow.write")
        _sync_agents()
        agent_id = payload.get("agent_id")
        if not agent_id or not isinstance(agent_id, str):
            raise HTTPException(422, "agent_id is required")

        if agent_id not in registry._agents:
            raise HTTPException(404, f"agent '{agent_id}' not found in registry")

        agent_meta = registry.get(agent_id).metadata

        wf_dir = trusted_manifests.parent.parent / "workflow_definitions"
        wf_path = wf_dir / f"{workflow_id}.yaml"
        for suffix in (".yaml", ".yml"):
            p = wf_dir / f"{workflow_id}{suffix}"
            if p.is_file():
                wf_path = p
                break

        raw = {}
        if wf_path.is_file():
            import yaml
            try:
                raw = yaml.safe_load(wf_path.read_text(encoding="utf-8")) or {}
            except Exception:
                raw = {}
        elif workflow_id in workflows:
            raw = workflows[workflow_id].model_dump(by_alias=True)

        existing_nodes = list(raw.get("nodes", []))
        existing_edges = list(raw.get("edges", []))

        node_id = payload.get("node_id") or agent_id
        existing_node_ids = {n.get("id") for n in existing_nodes if isinstance(n, dict)}
        if node_id in existing_node_ids:
            counter = 2
            while f"{node_id}_{counter}" in existing_node_ids:
                counter += 1
            node_id = f"{node_id}_{counter}"

        after = payload.get("after")
        before = payload.get("before")
        # If caller explicitly provided after="" or after="__start__", do not force after
        if "after" not in payload and not after and not before and existing_nodes:
            outgoing_sources = {e.get("from") for e in existing_edges if isinstance(e, dict)}
            candidates = [n.get("id") for n in existing_nodes if n.get("id") not in outgoing_sources]
            after = candidates[0] if candidates else existing_nodes[-1].get("id")
        elif after == "__start__":
            after = None

        input_mappings = payload.get("input_mappings")
        if not input_mappings or not isinstance(input_mappings, dict):
            input_mappings = {}
            schema_props = {}
            if isinstance(agent_meta.input_schema, dict) and "properties" in agent_meta.input_schema:
                schema_props = agent_meta.input_schema["properties"]

            prev_output_props = set()
            if after:
                prev_node = next((n for n in existing_nodes if n.get("id") == after), None)
                if prev_node and prev_node.get("agent_id") in registry._agents:
                    prev_meta = registry.get(prev_node["agent_id"]).metadata
                    if isinstance(prev_meta.output_schema, dict) and "properties" in prev_meta.output_schema:
                        prev_output_props = set(prev_meta.output_schema["properties"].keys())

            # Collect all workflow-level input fields from the first node's input_mappings
            # so we know what real workflow_input.* keys exist.
            workflow_input_keys: set[str] = set()
            for n in existing_nodes:
                for mapping in (n.get("input_mappings") or {}).values():
                    if isinstance(mapping, dict):
                        p = mapping.get("path", "")
                        if p.startswith("workflow_input."):
                            workflow_input_keys.add(p[len("workflow_input."):])

            def _best_workflow_input(field: str) -> str:
                """Return the best workflow_input.<key> path for an unmapped field.

                Priority:
                  1. Exact match on a known workflow input key.
                  2. Fuzzy: a known key whose name is contained in field or vice-versa.
                  3. Fallback: workflow_input.<field> (original behaviour).
                """
                if field in workflow_input_keys:
                    return f"workflow_input.{field}"
                for wk in workflow_input_keys:
                    if wk in field or field in wk:
                        return f"workflow_input.{wk}"
                return f"workflow_input.{field}"

            for field_name in schema_props.keys():
                if after and field_name in prev_output_props:
                    input_mappings[field_name] = {"path": f"node_outputs.{after}.{field_name}"}
                else:
                    # Check whether any previous node output field is a good match
                    # (handles cases like "analysis_status" matching output field "status").
                    matched_output = None
                    if after and prev_output_props:
                        # Exact match on a suffix or prefix of the field name
                        for op in prev_output_props:
                            if field_name == op or field_name.endswith(f"_{op}") or op.endswith(f"_{field_name}"):
                                matched_output = op
                                break
                    if matched_output:
                        input_mappings[field_name] = {"path": f"node_outputs.{after}.{matched_output}"}
                    else:
                        input_mappings[field_name] = {"path": _best_workflow_input(field_name)}

            if not input_mappings:
                input_mappings["text"] = {"path": "workflow_input.text"}

        new_node = {
            "id": node_id,
            "type": "agent",
            "agent_id": agent_id,
            "input_mappings": input_mappings,
        }
        existing_nodes.append(new_node)

        if after and after != node_id:
            if not any(e.get("from") == after and e.get("to") == node_id for e in existing_edges):
                existing_edges.append({"from": after, "to": node_id})

        if before and before != node_id:
            if not any(e.get("from") == node_id and e.get("to") == before for e in existing_edges):
                existing_edges.append({"from": node_id, "to": before})

        import yaml
        content = {
            "id": workflow_id,
            "version": raw.get("version", "1.0.0"),
            "nodes": existing_nodes,
            "edges": existing_edges,
        }
        if raw.get("max_steps"):
            content["max_steps"] = raw["max_steps"]
        wf_path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")

        try:
            wf_obj = WorkflowDefinition.model_validate(content)
        except Exception as exc:
            raise HTTPException(422, detail=f"Invalid workflow definition: {exc}")
        _sync_workflows()
        had_versions = bool(repo.inspect_workflow_records(workflow_id).get("versions"))
        validation_error = None
        if workflow_id in workflows or had_versions:
            try:
                WorkflowBuilder(registry).build(wf_obj)
                try:
                    repo.save_workflow(wf_obj.model_dump(by_alias=True))
                except ValueError as exc:
                    if "workflow version already exists with a different definition" in str(exc):
                        current_ver = wf_obj.version or "1.0.0"
                        parts = current_ver.split(".")
                        while len(parts) < 3:
                            parts.append("0")
                        try:
                            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
                        except ValueError:
                            major, minor, patch = 1, 0, 0
                        while True:
                            patch += 1
                            next_ver = f"{major}.{minor}.{patch}"
                            if not repo.get_workflow(wf_obj.id, next_ver):
                                break
                        wf_obj.version = next_ver
                        content["version"] = next_ver
                        wf_path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
                        repo.save_workflow(wf_obj.model_dump(by_alias=True))
                workflows[workflow_id] = wf_obj
            except Exception as exc:
                validation_error = str(exc)
                repo.unregister_workflow(workflow_id)
                workflows.pop(workflow_id, None)

        res = wf_obj.model_dump(by_alias=True, exclude_unset=True)
        res["registered"] = workflow_id in workflows
        res["registration_status"] = "registered" if workflow_id in workflows else "disconnected"
        if validation_error:
            res["validation_error"] = validation_error
        res["workflow_file"] = str(wf_path)
        return res

    @app.delete("/v1/workflows/{workflow_id}/nodes/{node_id}")
    def remove_node_from_workflow(workflow_id: str, node_id: str, request: Request):
        require(request, "workflow.write")
        _sync_workflows()
        wf_dir = trusted_manifests.parent.parent / "workflow_definitions"
        wf_path = wf_dir / f"{workflow_id}.yaml"
        for suffix in (".yaml", ".yml"):
            p = wf_dir / f"{workflow_id}{suffix}"
            if p.is_file():
                wf_path = p
                break

        raw = {}
        if wf_path.is_file():
            import yaml
            try:
                raw = yaml.safe_load(wf_path.read_text(encoding="utf-8")) or {}
            except Exception:
                raw = {}
        elif workflow_id in workflows:
            raw = workflows[workflow_id].model_dump(by_alias=True)

        existing_nodes = [n for n in raw.get("nodes", []) if n.get("id") != node_id]
        existing_edges = [
            e for e in raw.get("edges", [])
            if e.get("from") != node_id and e.get("to") != node_id
        ]

        import yaml
        content = {
            "id": workflow_id,
            "version": raw.get("version", "1.0.0"),
            "nodes": existing_nodes,
            "edges": existing_edges,
        }
        if raw.get("max_steps"):
            content["max_steps"] = raw["max_steps"]
        wf_path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")

        try:
            wf_obj = WorkflowDefinition.model_validate(content)
        except Exception as exc:
            raise HTTPException(422, detail=f"Invalid workflow definition: {exc}")
        had_versions = bool(repo.inspect_workflow_records(workflow_id).get("versions"))
        validation_error = None
        if len(existing_nodes) == 0 and (workflow_id in workflows or had_versions):
            repo.unregister_workflow(workflow_id)
            workflows.pop(workflow_id, None)
        elif workflow_id in workflows or had_versions:
            _sync_agents()
            try:
                WorkflowBuilder(registry).build(wf_obj)
                try:
                    repo.save_workflow(wf_obj.model_dump(by_alias=True))
                except ValueError as exc:
                    if "workflow version already exists with a different definition" in str(exc):
                        current_ver = wf_obj.version or "1.0.0"
                        parts = current_ver.split(".")
                        while len(parts) < 3:
                            parts.append("0")
                        try:
                            major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
                        except ValueError:
                            major, minor, patch = 1, 0, 0
                        while True:
                            patch += 1
                            next_ver = f"{major}.{minor}.{patch}"
                            if not repo.get_workflow(wf_obj.id, next_ver):
                                break
                        wf_obj.version = next_ver
                        content["version"] = next_ver
                        wf_path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")
                        repo.save_workflow(wf_obj.model_dump(by_alias=True))
                workflows[workflow_id] = wf_obj
            except Exception as exc:
                validation_error = str(exc)
                repo.unregister_workflow(workflow_id)
                workflows.pop(workflow_id, None)

        res = wf_obj.model_dump(by_alias=True, exclude_unset=True)
        res["registered"] = workflow_id in workflows
        res["registration_status"] = "registered" if workflow_id in workflows else ("draft" if len(existing_nodes) == 0 else "disconnected")
        if validation_error:
            res["validation_error"] = validation_error
        res["workflow_file"] = str(wf_path)
        return res

    @app.post("/v1/workflows/{workflow_id}/register")
    def register_workflow_by_id(workflow_id: str, request: Request):
        require(request, "workflow.write")
        _sync_agents()
        wf_dir = trusted_manifests.parent.parent / "workflow_definitions"
        raw_def = None
        if wf_dir.is_dir():
            import yaml
            for suffix in (".yaml", ".yml"):
                p = wf_dir / f"{workflow_id}{suffix}"
                if p.is_file():
                    try:
                        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
                        if isinstance(raw, dict) and raw.get("id"):
                            raw_def = raw
                            break
                    except Exception:
                        pass
        if not raw_def:
            if workflow_id in workflows:
                raw_def = workflows[workflow_id].model_dump(by_alias=True)
            else:
                inspection = repo.inspect_workflow_records(workflow_id)
                if inspection.get("versions"):
                    raw_def = repo.get_workflow(workflow_id, inspection["versions"][-1])
        if not raw_def:
            raise HTTPException(404, f"workflow definition '{workflow_id}' not found")

        for k in ("registered", "registration_status", "workflow_file"):
            raw_def.pop(k, None)

        workflow = WorkflowDefinition.model_validate(raw_def)
        try:
            WorkflowBuilder(registry).build(workflow)
        except Exception as exc:
            raise HTTPException(422, str(exc))
        try:
            repo.save_workflow(workflow.model_dump(by_alias=True))
        except ValueError as exc:
            if "workflow version already exists with a different definition" in str(exc):
                import re
                current_ver = workflow.version or "1.0.0"
                match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", current_ver)
                if match:
                    major, minor, patch = map(int, match.groups())
                    next_ver = current_ver
                    while True:
                        patch += 1
                        next_ver = f"{major}.{minor}.{patch}"
                        if not repo.get_workflow(workflow.id, next_ver):
                            break
                    workflow.version = next_ver
                    raw_def["version"] = next_ver
                    if p and p.is_file():
                        p.write_text(yaml.safe_dump(raw_def, sort_keys=False), encoding="utf-8")
                    repo.save_workflow(workflow.model_dump(by_alias=True))
                else:
                    raise HTTPException(409, str(exc))
            else:
                raise HTTPException(409, str(exc))
        workflows[workflow.id] = workflow
        res = workflow.model_dump(by_alias=True, exclude_unset=True)
        res["registered"] = True
        res["registration_status"] = "registered"
        return res

    @app.post("/v1/workflows/{workflow_id}/disconnect")
    def disconnect_workflow(workflow_id: str, request: Request):
        current = principal(request)
        if not (current.can("workflow.write") or current.can("workflow.delete")):
            require(request, "workflow.write")
        _sync_workflows()
        existed_in_mem = workflow_id in workflows
        unregistered_in_db = repo.unregister_workflow(workflow_id)
        workflows.pop(workflow_id, None)
        if not existed_in_mem and not unregistered_in_db:
            raise HTTPException(404, "workflow not found")
        return {
            "disconnected": True,
            "workflow_id": workflow_id,
            "registered": False,
            "registration_status": "disconnected",
        }

    @app.delete("/v1/workflows/{workflow_id}")
    def delete_workflow(workflow_id: str, request: Request):
        current = principal(request)
        if not (current.can("workflow.write") or current.can("workflow.delete")):
            require(request, "workflow.write")
        _sync_workflows()
        existed_in_mem = workflow_id in workflows
        inspection = repo.inspect_workflow_records(workflow_id)
        wf_dir = trusted_manifests.parent.parent / "workflow_definitions"
        local_path = None
        if wf_dir.is_dir():
            for suffix in (".yaml", ".yml"):
                p = wf_dir / f"{workflow_id}{suffix}"
                if p.is_file():
                    local_path = p
                    break
        # 404 if the workflow doesn't exist anywhere
        if not existed_in_mem and not inspection["registered"] and inspection["version_count"] == 0 and inspection["run_count"] == 0 and local_path is None:
            raise HTTPException(404, "workflow not found")
        purge_result = repo.delete_workflow_records(workflow_id)
        workflows.pop(workflow_id, None)
        # Clear graph cache for this workflow's runs
        for run_id in inspection.get("run_ids", []):
            app.state.graphs.pop(run_id, None)
        deleted_local_file = None
        if local_path and local_path.is_file():
            try:
                local_path.unlink()
                deleted_local_file = str(local_path)
            except Exception:
                pass
        return {
            "deleted": True,
            "workflow_id": workflow_id,
            "deleted_versions": purge_result["deleted_versions"],
            "deleted_runs": purge_result["deleted_runs"],
            "deleted_events": purge_result["deleted_events"],
            "deleted_checkpoints": purge_result["deleted_checkpoints"],
            "deleted_local_file": deleted_local_file,
        }
    @app.post("/v1/runs")
    async def start_run(request: RunRequest, http_request: Request):
        current = require(http_request, "workflow.execute")
        _sync_workflows()
        if request.workflow_id not in workflows: raise HTTPException(404, "workflow not found")
        run_id = str(uuid.uuid4())
        workflow = workflows[request.workflow_id]
        for aid in list(registry._agents.keys()):
            entry = registry._agents[aid].entrypoint or ""
            if entry.startswith("plugins.examples.connected_") and not (trusted_manifests / f"{aid}.yaml").is_file():
                registry._agents.pop(aid, None)
        if any(n.type == "agent" and n.status == "available" and n.agent_id and n.agent_id not in registry._agents for n in workflow.nodes):
            for m_dir in _get_manifest_dirs():
                try:
                    loader = AgentLoader(registry, m_dir)
                    for path in loader.discover():
                        manifest = loader.read_manifest(path)
                        if manifest.enabled and manifest.id not in registry._agents:
                            loader.register_manifest(manifest, path)
                except Exception:
                    pass
        checkpointer = await get_checkpointer()
        allow_partial = bool(request.allow_partial and not request.strict)
        try:
            graph = WorkflowBuilder(registry, runner=agent_runner, checkpointer=checkpointer).build(
                workflow, allow_partial=allow_partial
            )
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc
        app.state.graphs[run_id] = graph
        safe_inputs = redact_sensitive(request.inputs)

        # Optional pre-run input validation hook (if registered on app.state)
        pre_run_validator = getattr(app.state, "pre_run_validator", None)
        if callable(pre_run_validator):
            val_err = pre_run_validator(safe_inputs, app.state)
            if val_err:
                raise HTTPException(
                    status_code=400,
                    detail=str(val_err),
                )

        temporal_cfg = TemporalConfig.from_env()
        effective_backend = request.execution_backend or temporal_cfg.execution_backend

        if effective_backend == "temporal":
            try:
                t_client = await get_temporal_client(temporal_cfg)
            except Exception as exc:
                raise HTTPException(503, f"Temporal service unavailable: {exc}")

            temporal_wf_id = f"wf-{run_id}"
            try:
                handle = await t_client.start_workflow(
                    DynamicLangGraphWorkflow.run,
                    {
                        "workflow_id": request.workflow_id,
                        "workflow_version": workflow.version,
                        "run_id": run_id,
                        "workflow_input": safe_inputs,
                        "max_steps": workflow.max_steps,
                    },
                    id=temporal_wf_id,
                    task_queue=temporal_cfg.task_queue,
                )
                temporal_run_id = handle.result_run_id
                repo.start_run(
                    run_id,
                    request.workflow_id,
                    safe_inputs,
                    workflow.version,
                    run_id,
                    current.user_id,
                    execution_backend="temporal",
                    temporal_workflow_id=temporal_wf_id,
                    temporal_run_id=temporal_run_id,
                )
                repo.add_event(
                    run_id,
                    "workflow",
                    "started",
                    {
                        "execution_backend": "temporal",
                        "temporal_workflow_id": temporal_wf_id,
                        "temporal_run_id": temporal_run_id,
                    },
                )
            except Exception as exc:
                raise HTTPException(503, f"Failed to dispatch Temporal workflow: {exc}")

            if request.wait:
                try:
                    for _ in range(20):
                        desc = await handle.describe()
                        if desc.status.name == "COMPLETED":
                            result = await handle.result()
                            status = result.get("status", "succeeded") if isinstance(result, dict) else "succeeded"
                            repo.update_run(
                                run_id,
                                status,
                                result,
                                temporal_workflow_id=temporal_wf_id,
                                temporal_run_id=temporal_run_id,
                            )
                            if isinstance(result, dict):
                                for node_id, output in result.get("node_outputs", {}).items():
                                    repo.add_event(run_id, node_id, "succeeded", output)
                            break
                        elif desc.status.name in ("FAILED", "TERMINATED", "TIMED_OUT"):
                            await handle.result()
                            break
                        elif desc.status.name == "RUNNING":
                            try:
                                wf_status = await handle.query(DynamicLangGraphWorkflow.get_status)
                                if isinstance(wf_status, dict) and wf_status.get("status") == "waiting_for_approval":
                                    latest_output = wf_status.get("latest_output") or {}
                                    pending_approval = wf_status.get("pending_approval")
                                    repo.update_run(
                                        run_id,
                                        "waiting_for_approval",
                                        latest_output,
                                        temporal_workflow_id=temporal_wf_id,
                                        temporal_run_id=temporal_run_id,
                                    )
                                    if pending_approval:
                                        repo.add_event(run_id, "approval", "waiting_for_approval", pending_approval)
                                    for node_id, output in latest_output.get("node_outputs", {}).items():
                                        repo.add_event(run_id, node_id, "succeeded", output)
                                    break
                            except Exception:
                                pass
                        await asyncio.sleep(0.5)
                except Exception as exc:
                    repo.update_run(
                        run_id,
                        "failed",
                        {"error": str(exc)},
                        temporal_workflow_id=temporal_wf_id,
                        temporal_run_id=temporal_run_id,
                    )
                    repo.add_event(run_id, "workflow", "failed", {"error": str(exc)})

            return repo.get_run(run_id)

        # Direct execution path
        repo.start_run(
            run_id,
            request.workflow_id,
            safe_inputs,
            workflow.version,
            run_id,
            current.user_id,
            execution_backend="direct",
        )
        repo.add_event(run_id, "workflow", "started", {"execution_backend": "direct"})

        initial_state = {
            "run_id": run_id,
            "workflow_id": request.workflow_id,
            "workflow_version": workflow.version,
            "workflow_input": safe_inputs,
            "node_outputs": {},
            "agent_outputs": {},
        }

        if request.wait is False:
            target_ids = {e.to for e in workflow.edges}
            entry_nodes = [n.id for n in workflow.nodes if n.id not in target_ids]
            for en_id in entry_nodes:
                repo.add_event(run_id, en_id, "running", {"node_id": en_id, "status": "running"})

            bg_graph = WorkflowBuilder(registry, runner=agent_runner, checkpointer=None).build(
                workflow, allow_partial=allow_partial
            )

            async def _run_direct_background():
                accumulated: dict[str, Any] = dict(initial_state)
                accumulated["node_outputs"] = {}
                accumulated["agent_outputs"] = {}
                try:
                    async for chunk in bg_graph.astream(
                        initial_state,
                        {"configurable": {"thread_id": run_id}},
                        stream_mode="updates",
                    ):
                        if not isinstance(chunk, dict):
                            continue
                        for node_id, state_update in chunk.items():
                            if node_id == "__interrupt__":
                                accumulated["__interrupt__"] = state_update
                                continue
                            if isinstance(state_update, dict):
                                for k, v in state_update.items():
                                    if k in ("node_outputs", "agent_outputs") and isinstance(v, dict):
                                        accumulated.setdefault(k, {}).update(v)
                                    else:
                                        accumulated[k] = v
                                node_out = (state_update.get("node_outputs") or {}).get(node_id, state_update)
                                repo.add_event(run_id, node_id, "succeeded", node_out)
                                repo.update_run(run_id, "running", accumulated)
                                for edge in workflow.edges:
                                    if edge.from_node == node_id:
                                        repo.add_event(
                                            run_id,
                                            edge.to,
                                            "running",
                                            {"node_id": edge.to, "status": "running"},
                                        )
                    if accumulated.get("__interrupt__"):
                        final_status = "waiting_for_approval"
                    elif accumulated.get("partial_execution"):
                        final_status = "partially_succeeded" if accumulated.get("node_outputs") else "failed"
                    else:
                        final_status = "succeeded"
                    repo.update_run(run_id, final_status, accumulated)
                    for skipped in accumulated.get("skipped_nodes", []):
                        if isinstance(skipped, dict) and skipped.get("node_id"):
                            repo.add_event(run_id, str(skipped["node_id"]), str(skipped.get("status", "skipped")), skipped)
                    if final_status == "waiting_for_approval":
                        repo.add_event(run_id, "approval", final_status, accumulated.get("__interrupt__", {}))
                    else:
                        repo.add_event(run_id, "workflow", final_status, {"status": final_status})
                except Exception as exc:
                    import traceback
                    tb = traceback.format_exc()
                    repo.update_run(run_id, "failed", {"error": str(exc), "traceback": tb, **accumulated})
                    repo.add_event(run_id, "workflow", "failed", {"error": str(exc), "traceback": tb})

            threading.Thread(target=lambda: asyncio.run(_run_direct_background()), daemon=True).start()
            return repo.get_run(run_id)

        try:
            result = await graph.ainvoke(
                initial_state,
                {"configurable": {"thread_id": run_id}},
            )
            if result.get("__interrupt__"):
                status = "waiting_for_approval"
            elif result.get("partial_execution"):
                status = "partially_succeeded" if result.get("node_outputs") else "failed"
            else:
                status = "succeeded"
            repo.update_run(run_id, status, result)
            for node_id, output in result.get("node_outputs", {}).items():
                repo.add_event(run_id, node_id, "succeeded", output)
            for skipped in result.get("skipped_nodes", []):
                if isinstance(skipped, dict) and skipped.get("node_id"):
                    repo.add_event(run_id, str(skipped["node_id"]), str(skipped.get("status", "skipped")), skipped)
            if status == "waiting_for_approval":
                repo.add_event(run_id, "approval", status, result.get("__interrupt__", {}))
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            repo.update_run(run_id, "failed", {"error": str(exc), "traceback": tb})
            repo.add_event(run_id, "workflow", "failed", {"error": str(exc), "traceback": tb})
        return repo.get_run(run_id)

    @app.post("/v1/workflows/{workflow_id}/run")
    async def run_workflow_by_id(workflow_id: str, request: RunRequest, http_request: Request):
        request.workflow_id = workflow_id
        return await start_run(request, http_request)

    @app.post("/v1/webhooks/{workflow_id}")
    async def trigger_webhook(workflow_id: str, http_request: Request):
        """Universal incoming webhook receiver that triggers a workflow run.

        External services (SendGrid, GitHub, Stripe, Custom Webhooks, Mailgun, etc.)
        can POST JSON payloads to this endpoint.
        If the workflow has a trigger node configured with a secret_token,
        it validates the 'X-Webhook-Token' header or '?token=' query parameter.
        """
        _sync_workflows()
        if workflow_id not in workflows:
            raise HTTPException(404, f"workflow '{workflow_id}' not found")
        workflow = workflows[workflow_id]

        # Check for trigger node & validate token if configured
        trigger_nodes = [n for n in workflow.nodes if getattr(n, "type", "") == "trigger"]
        for t_node in trigger_nodes:
            t_cfg = getattr(t_node, "trigger_config", {}) or {}
            secret = t_cfg.get("secret_token")
            if secret:
                token_header = http_request.headers.get("x-webhook-token") or http_request.query_params.get("token")
                if token_header != secret:
                    raise HTTPException(401, "invalid webhook secret token")

        # Parse payload
        try:
            body = await http_request.json()
            if not isinstance(body, dict):
                body = {"data": body}
        except Exception:
            body = dict(http_request.query_params)

        inputs = dict(body)
        inputs["_webhook_received_at"] = datetime.now(timezone.utc).isoformat()

        run_id = str(uuid.uuid4())
        safe_inputs = redact_sensitive(inputs)

        temporal_cfg = TemporalConfig.from_env()
        effective_backend = temporal_cfg.execution_backend

        if effective_backend == "temporal":
            try:
                t_client = await get_temporal_client(temporal_cfg)
                temporal_wf_id = f"wf-{run_id}"
                handle = await t_client.start_workflow(
                    DynamicLangGraphWorkflow.run,
                    {
                        "workflow_id": workflow_id,
                        "workflow_version": workflow.version,
                        "run_id": run_id,
                        "workflow_input": safe_inputs,
                        "max_steps": workflow.max_steps,
                    },
                    id=temporal_wf_id,
                    task_queue=temporal_cfg.task_queue,
                )
                temporal_run_id = handle.result_run_id
                repo.start_run(
                    run_id,
                    workflow_id,
                    safe_inputs,
                    workflow.version,
                    run_id,
                    "webhook",
                    execution_backend="temporal",
                    temporal_workflow_id=temporal_wf_id,
                    temporal_run_id=temporal_run_id,
                )
                repo.add_event(
                    run_id,
                    "workflow",
                    "started",
                    {
                        "execution_backend": "temporal",
                        "triggered_by": "webhook",
                        "temporal_workflow_id": temporal_wf_id,
                        "temporal_run_id": temporal_run_id,
                    },
                )
                return {
                    "status": "triggered",
                    "run_id": run_id,
                    "workflow_id": workflow_id,
                    "execution_backend": "temporal",
                    "temporal_workflow_id": temporal_wf_id,
                }
            except Exception as exc:
                pass

        # Direct execution fallback
        checkpointer = await get_checkpointer()
        graph = WorkflowBuilder(registry, runner=agent_runner, checkpointer=checkpointer).build(workflow)
        app.state.graphs[run_id] = graph
        repo.start_run(run_id, workflow_id, safe_inputs, workflow.version, run_id, "webhook", execution_backend="direct")
        repo.add_event(run_id, "workflow", "started", {"execution_backend": "direct", "triggered_by": "webhook"})

        async def _run_direct():
            try:
                result = await graph.ainvoke({"workflow_input": safe_inputs, "run_id": run_id, "workflow_id": workflow_id, "workflow_version": workflow.version}, {"configurable": {"thread_id": run_id}})
                status = "waiting_for_approval" if result.get("__interrupt__") else "succeeded"
                repo.update_run(run_id, status, result)
                repo.add_event(run_id, "workflow", status, result)
            except Exception as e:
                repo.update_run(run_id, "failed", {"error": str(e)})
                repo.add_event(run_id, "workflow", "failed", {"error": str(e)})

        asyncio.create_task(_run_direct())
        return {
            "status": "triggered",
            "run_id": run_id,
            "workflow_id": workflow_id,
            "execution_backend": "direct",
        }

    @app.post("/v1/batch-runs")
    async def start_batch_run(request: BatchRunRequest, http_request: Request):
        current = require(http_request, "workflow.execute")
        _sync_workflows()
        if request.workflow_id not in workflows:
            raise HTTPException(404, "workflow not found")
        workflow = workflows[request.workflow_id]
        batch_id = f"batch-{uuid.uuid4()}"

        temporal_cfg = TemporalConfig.from_env()
        effective_backend = request.execution_backend or temporal_cfg.execution_backend

        if effective_backend == "temporal":
            try:
                t_client = await get_temporal_client(temporal_cfg)
            except Exception as exc:
                raise HTTPException(503, f"Temporal service unavailable: {exc}")

            try:
                handle = await t_client.start_workflow(
                    BatchLangGraphWorkflow.run,
                    {
                        "batch_id": batch_id,
                        "workflow_id": request.workflow_id,
                        "workflow_version": workflow.version,
                        "items": request.items,
                        "concurrency": request.concurrency,
                        "max_steps": workflow.max_steps,
                    },
                    id=batch_id,
                    task_queue=temporal_cfg.task_queue,
                )
            except Exception as exc:
                raise HTTPException(503, f"Failed to dispatch Temporal batch workflow: {exc}")
            repo.start_run(
                batch_id,
                request.workflow_id,
                {"total_items": len(request.items), "concurrency": request.concurrency},
                workflow.version,
                batch_id,
                current.user_id,
                execution_backend="temporal",
                temporal_workflow_id=batch_id,
                temporal_run_id=handle.result_run_id,
            )
            return repo.get_run(batch_id)
        else:
            sem = asyncio.Semaphore(request.concurrency)
            checkpointer = await get_checkpointer()
            graph = WorkflowBuilder(registry, runner=agent_runner, checkpointer=checkpointer).build(
                workflow, allow_partial=request.allow_partial
            )

            async def run_one(item_idx: int, item_data: dict[str, Any]):
                item_id = item_data.get("item_id", f"item-{item_idx}")
                async with sem:
                    try:
                        res = await graph.ainvoke(
                            {
                                "run_id": f"{batch_id}-{item_id}",
                                "workflow_id": request.workflow_id,
                                "workflow_version": workflow.version,
                                "workflow_input": item_data.get("input", item_data),
                                "node_outputs": {},
                                "agent_outputs": {},
                            },
                            {"configurable": {"thread_id": f"{batch_id}-{item_id}"}},
                        )
                        return {"item_id": item_id, "status": "succeeded", "output": res}
                    except Exception as err:
                        return {"item_id": item_id, "status": "failed", "error": str(err)}

            tasks = [run_one(i, it) for i, it in enumerate(request.items)]
            results = await asyncio.gather(*tasks)
            succeeded_cnt = sum(1 for r in results if r["status"] == "succeeded")
            batch_result = {
                "batch_id": batch_id,
                "workflow_id": request.workflow_id,
                "total_items": len(request.items),
                "succeeded_count": succeeded_cnt,
                "failed_count": len(request.items) - succeeded_cnt,
                "items": results,
                "status": "succeeded" if succeeded_cnt == len(request.items) else "partial",
            }
            repo.start_run(
                batch_id,
                request.workflow_id,
                {"total_items": len(request.items)},
                workflow.version,
                batch_id,
                current.user_id,
                execution_backend="direct",
            )
            repo.update_run(batch_id, batch_result["status"], batch_result)
            return repo.get_run(batch_id)
    @app.get("/v1/runs")
    def list_runs(request: Request, status: str | None = None, workflow_id: str | None = None):
        current = require(request, "runs.read")
        owner_id = current.user_id if not current.can("*") else None
        records = repo.list_runs(status=status, owner_id=owner_id)
        if workflow_id:
            records = [r for r in records if r.get("workflow_id") == workflow_id]
        return records

    @app.get("/v1/events")
    def list_events(request: Request, run_id: str | None = None, limit: int = 100, offset: int = 0):
        current = require(request, "runs.read")
        owner_id = current.user_id if not current.can("*") else None
        return repo.list_events(run_id=run_id, limit=limit, offset=offset, owner_id=owner_id)

    @app.get("/v1/overview")
    def overview_stats(request: Request):
        require(request, "metadata.read")
        _sync_agents()
        _sync_workflows()
        current = principal(request)
        owner_id = current.user_id if not current.can("*") else None
        all_runs = repo.list_runs(owner_id=owner_id)
        approvals_list = [r for r in all_runs if r.get("status") == "waiting_for_approval"]
        succeeded_runs = [r for r in all_runs if r.get("status") == "succeeded"]
        failed_runs = [r for r in all_runs if r.get("status") == "failed"]
        running_runs = [r for r in all_runs if r.get("status") in {"running", "resuming"}]
        
        wf_dir = trusted_manifests.parent.parent / "workflow_definitions"
        local_draft_count = 0
        if wf_dir.is_dir():
            for p in wf_dir.glob("*.y*ml"):
                if p.stem not in workflows:
                    local_draft_count += 1

        return {
            "agents_count": len(registry.list_enabled()),
            "workflows_total": len(workflows) + local_draft_count,
            "workflows_registered": len(workflows),
            "workflows_drafts": local_draft_count,
            "runs_total": len(all_runs),
            "runs_running": len(running_runs),
            "runs_succeeded": len(succeeded_runs),
            "runs_failed": len(failed_runs),
            "pending_approvals": len(approvals_list),
            "tools_count": len(tool_registry.list_enabled()),
        }

    @app.get("/v1/runs/{run_id}")
    async def get_run(run_id: str, request: Request):
        _, value = owned_run(request, run_id)
        if value.get("status") in ("running", "resuming", "waiting_for_approval") and value.get("execution_backend") == "temporal":
            try:
                temporal_cfg = TemporalConfig.from_env()
                t_client = await get_temporal_client(temporal_cfg)
                twf_id = value.get("temporal_workflow_id") or f"wf-{run_id}"
                handle = t_client.get_workflow_handle(twf_id)
                desc = await handle.describe()
                if desc.status.name == "COMPLETED":
                    result = await handle.result()
                    status = result.get("status", "succeeded") if isinstance(result, dict) else "succeeded"
                    repo.update_run(run_id, status, result)
                    if isinstance(result, dict):
                        for node_id, output in result.get("node_outputs", {}).items():
                            repo.add_event(run_id, node_id, "succeeded", output)
                    value = repo.get_run(run_id) or value
                elif desc.status.name in ("FAILED", "TERMINATED", "TIMED_OUT"):
                    err_msg = f"Temporal execution {desc.status.name.lower()}"
                    try:
                        await handle.result()
                    except Exception as wf_exc:
                        curr = wf_exc
                        while getattr(curr, "cause", None):
                            curr = curr.cause
                            if hasattr(curr, "message") and curr.message:
                                err_msg = str(curr.message)
                            elif str(curr):
                                err_msg = str(curr)
                        if err_msg == f"Temporal execution {desc.status.name.lower()}":
                            err_msg = str(wf_exc)
                    repo.update_run(run_id, "failed", {"error": err_msg})
                    repo.add_event(run_id, "workflow", "failed", {"error": err_msg})
                    value = repo.get_run(run_id) or value
                elif desc.status.name == "RUNNING":
                    try:
                        wf_status = await handle.query(DynamicLangGraphWorkflow.get_status)
                        if isinstance(wf_status, dict):
                            curr_status = wf_status.get("status")
                            latest_output = wf_status.get("latest_output") or {}
                            pending_approval = wf_status.get("pending_approval")
                            if curr_status == "waiting_for_approval":
                                if value.get("status") != "waiting_for_approval":
                                    repo.update_run(run_id, "waiting_for_approval", latest_output)
                                    if pending_approval:
                                        repo.add_event(run_id, "approval", "waiting_for_approval", pending_approval)
                                    for node_id, output in latest_output.get("node_outputs", {}).items():
                                        repo.add_event(run_id, node_id, "succeeded", output)
                                    value = repo.get_run(run_id) or value
                            elif curr_status == "running" and value.get("status") == "waiting_for_approval":
                                repo.update_run(run_id, "running", latest_output)
                                value = repo.get_run(run_id) or value
                    except Exception:
                        pass
            except Exception:
                pass
        return value
    @app.get("/v1/runs/{run_id}/events")
    def events(run_id: str, request: Request):
        owned_run(request, run_id)
        return repo.events(run_id)
    @app.get("/v1/approvals")
    def approvals(request: Request):
        current = require(request, "approval.read")
        return repo.list_runs("waiting_for_approval", current.user_id)
    @app.post("/v1/runs/{run_id}/resume")
    async def resume(run_id: str, request: ResumeRequest, http_request: Request):
        current = require(http_request, "approval.execute")
        record = repo.get_run(run_id)
        if not record or record.get("owner_id") != current.user_id: raise HTTPException(404, "run not found")
        if record["status"] != "waiting_for_approval": raise HTTPException(409, "run is not awaiting approval")

        workflow_payload = repo.get_workflow(record["workflow_id"], record.get("workflow_version"))
        allowed_decisions = {option for node in (workflow_payload or {}).get("nodes", []) if node.get("type") == "human_approval" for option in node.get("approval_options", ["approve", "reject"])}
        if request.decision not in allowed_decisions:
            raise HTTPException(422, "invalid approval decision")
        if not repo.claim_resume(run_id, current.user_id):
            raise HTTPException(409, "run is already being resumed or is no longer awaiting approval")

        if record.get("execution_backend") == "temporal":
            try:
                temporal_cfg = TemporalConfig.from_env()
                t_client = await get_temporal_client(temporal_cfg)
                twf_id = record.get("temporal_workflow_id") or f"wf-{run_id}"
                handle = t_client.get_workflow_handle(twf_id)
                await handle.signal(DynamicLangGraphWorkflow.resume_approval, request.decision)
                result = await handle.result()
                if isinstance(result, dict) and result.get("__interrupt__"):
                    status = "waiting_for_approval"
                elif isinstance(result, dict) and result.get("partial_execution"):
                    status = "partially_succeeded" if result.get("node_outputs") else "failed"
                else:
                    status = "succeeded"
                repo.update_run(run_id, status, result)
                if isinstance(result, dict):
                    for node_id, output in result.get("node_outputs", {}).items():
                        repo.add_event(run_id, node_id, "succeeded", output)
                if status == "waiting_for_approval":
                    repo.add_event(run_id, "approval", status, result.get("__interrupt__", {}))
                return repo.get_run(run_id)
            except Exception as exc:
                safe_error = redact_sensitive({"error": str(exc)})
                repo.update_run(run_id, "failed", safe_error)
                repo.add_event(run_id, "workflow", "failed", safe_error)
                raise HTTPException(422, safe_error["error"])
                safe_error = redact_sensitive({"error": str(exc)})
                repo.update_run(run_id, "failed", safe_error)
                repo.add_event(run_id, "workflow", "failed", safe_error)
                raise HTTPException(422, safe_error["error"])

        graph = app.state.graphs.get(run_id)
        if not graph:
            if not workflow_payload: raise HTTPException(404, "workflow definition not found")
            checkpointer = await get_checkpointer()
            graph = WorkflowBuilder(registry, runner=agent_runner, checkpointer=checkpointer).build(WorkflowDefinition.model_validate(workflow_payload)); app.state.graphs[run_id] = graph

        try:
            result = await graph.ainvoke(Command(resume=request.decision), {"configurable":{"thread_id":record.get("thread_id") or run_id}})
        except Exception as exc:
            safe_error = redact_sensitive({"error": str(exc)})
            repo.update_run(run_id, "failed", safe_error)
            repo.add_event(run_id, "workflow", "failed", safe_error)
            raise HTTPException(422, safe_error["error"])
        status = "waiting_for_approval" if result.get("__interrupt__") else "succeeded"; repo.update_run(run_id, status, result)
        for node_id, output in result.get("node_outputs", {}).items(): repo.add_event(run_id, node_id, "succeeded", output)
        return repo.get_run(run_id)

    @app.post("/v1/runs/{run_id}/retry")
    async def retry_run(run_id: str, http_request: Request):
        current = require(http_request, "workflow.execute")
        record = repo.get_run(run_id)
        if not record or record.get("owner_id") != current.user_id:
            raise HTTPException(404, "run not found")
        _sync_workflows()
        wf_id = record["workflow_id"]
        if wf_id not in workflows:
            raise HTTPException(404, "workflow not found")
        workflow = workflows[wf_id]
        raw_prev = record.get("payload") or record.get("output")
        prev_output = raw_prev if isinstance(raw_prev, dict) else {}
        safe_inputs = prev_output.get("workflow_input") or record.get("inputs") or {}
        retry_count = int(prev_output.get("retry_count", 0)) + 1

        checkpointer = await get_checkpointer()
        graph = WorkflowBuilder(registry, runner=agent_runner, checkpointer=checkpointer).build(
            workflow, allow_partial=True
        )
        app.state.graphs[run_id] = graph

        repo.add_event(
            run_id,
            "workflow",
            "retried",
            {"retry_count": retry_count, "previous_status": record.get("status")},
        )
        repo.update_run(run_id, "running", {"workflow_input": safe_inputs, "retry_count": retry_count, "node_outputs": {}})

        thread_id = f"{run_id}-retry-{retry_count}"
        try:
            result = await graph.ainvoke(
                {
                    "run_id": run_id,
                    "workflow_id": wf_id,
                    "workflow_version": workflow.version,
                    "workflow_input": safe_inputs,
                    "node_outputs": {},
                    "agent_outputs": {},
                },
                {"configurable": {"thread_id": thread_id}},
            )
            result["retry_count"] = retry_count
            if result.get("__interrupt__"):
                status = "waiting_for_approval"
            elif result.get("partial_execution"):
                status = "partially_succeeded" if result.get("node_outputs") else "failed"
            else:
                status = "succeeded"
            repo.update_run(run_id, status, result)
            for node_id, output in result.get("node_outputs", {}).items():
                repo.add_event(run_id, node_id, "succeeded", output)
        except Exception as exc:
            import traceback
            tb = traceback.format_exc()
            repo.update_run(run_id, "failed", {"error": str(exc), "traceback": tb, "retry_count": retry_count, "workflow_input": safe_inputs})
            repo.add_event(run_id, "workflow", "failed", {"error": str(exc), "retry_count": retry_count})
        return repo.get_run(run_id)

    @app.delete("/v1/runs/{run_id}")
    def delete_run(run_id: str, request: Request):
        current, _ = owned_run(request, run_id)
        require(request, "runs.delete")
        if not repo.delete_run(run_id):
            raise HTTPException(404, "run not found")
        app.state.graphs.pop(run_id, None)
        return {"deleted": True, "run_id": run_id}

    # Temporal Schedule Endpoints
    @app.post("/v1/schedules")
    async def create_schedule_endpoint(request: ScheduleCreateRequest, http_request: Request):
        require(http_request, "workflow.execute")
        _sync_workflows()
        if request.workflow_id not in workflows:
            raise HTTPException(404, "workflow not found")
        temporal_cfg = TemporalConfig.from_env()
        try:
            t_client = await get_temporal_client(temporal_cfg)
            await create_temporal_schedule(
                client=t_client,
                schedule_id=request.schedule_id,
                workflow_id=request.workflow_id,
                workflow_version=request.workflow_version,
                cron_or_interval=request.cron_or_interval,
                input_payload=request.input_payload,
                task_queue=temporal_cfg.task_queue,
                paused=request.paused,
            )
        except Exception as exc:
            raise HTTPException(502, f"Failed to create schedule in Temporal: {exc}")

        repo.save_schedule(
            request.schedule_id,
            request.workflow_id,
            request.workflow_version,
            request.cron_or_interval,
            request.input_payload,
            paused=request.paused,
        )
        return repo.get_schedule(request.schedule_id)

    @app.get("/v1/schedules")
    async def list_schedules_endpoint(http_request: Request):
        require(http_request, "runs.read")
        local_schedules = repo.list_schedules()
        try:
            temporal_cfg = TemporalConfig.from_env()
            t_client = await get_temporal_client(temporal_cfg)
            t_list = await list_temporal_schedules(t_client)
            t_map = {item["id"]: item for item in t_list}
            for s in local_schedules:
                if s["schedule_id"] in t_map:
                    s["paused"] = t_map[s["schedule_id"]]["paused"]
        except Exception:
            pass
        return local_schedules

    @app.get("/v1/schedules/{schedule_id}")
    async def get_schedule_endpoint(schedule_id: str, http_request: Request):
        require(http_request, "runs.read")
        local_record = repo.get_schedule(schedule_id)
        if not local_record:
            raise HTTPException(404, "schedule not found")
        try:
            temporal_cfg = TemporalConfig.from_env()
            t_client = await get_temporal_client(temporal_cfg)
            t_desc = await get_temporal_schedule(t_client, schedule_id)
            local_record.update({
                "next_run_times": t_desc.get("next_run_times", []),
                "recent_actions": t_desc.get("recent_actions", []),
                "total_actions": t_desc.get("total_actions", 0),
                "paused": t_desc.get("paused", local_record["paused"]),
            })
        except Exception:
            pass
        return local_record

    @app.post("/v1/schedules/{schedule_id}/pause")
    async def pause_schedule_endpoint(schedule_id: str, http_request: Request):
        require(http_request, "workflow.execute")
        local_record = repo.get_schedule(schedule_id)
        if not local_record:
            raise HTTPException(404, "schedule not found")
        try:
            temporal_cfg = TemporalConfig.from_env()
            t_client = await get_temporal_client(temporal_cfg)
            await pause_temporal_schedule(t_client, schedule_id)
        except Exception as exc:
            raise HTTPException(502, f"Failed to pause schedule in Temporal: {exc}")
        repo.update_schedule_status(schedule_id, paused=True)
        return {"status": "paused", "schedule_id": schedule_id}

    @app.post("/v1/schedules/{schedule_id}/unpause")
    async def unpause_schedule_endpoint(schedule_id: str, http_request: Request):
        require(http_request, "workflow.execute")
        local_record = repo.get_schedule(schedule_id)
        if not local_record:
            raise HTTPException(404, "schedule not found")
        try:
            temporal_cfg = TemporalConfig.from_env()
            t_client = await get_temporal_client(temporal_cfg)
            await unpause_temporal_schedule(t_client, schedule_id)
        except Exception as exc:
            raise HTTPException(502, f"Failed to unpause schedule in Temporal: {exc}")
        repo.update_schedule_status(schedule_id, paused=False)
        return {"status": "unpaused", "schedule_id": schedule_id}

    @app.post("/v1/schedules/{schedule_id}/trigger")
    async def trigger_schedule_endpoint(schedule_id: str, http_request: Request):
        require(http_request, "workflow.execute")
        local_record = repo.get_schedule(schedule_id)
        if not local_record:
            raise HTTPException(404, "schedule not found")
        try:
            temporal_cfg = TemporalConfig.from_env()
            t_client = await get_temporal_client(temporal_cfg)
            await trigger_temporal_schedule(t_client, schedule_id)
        except Exception as exc:
            raise HTTPException(502, f"Failed to trigger schedule in Temporal: {exc}")
        return {"status": "triggered", "schedule_id": schedule_id}

    @app.delete("/v1/schedules/{schedule_id}")
    async def delete_schedule_endpoint(schedule_id: str, http_request: Request):
        require(http_request, "workflow.execute")
        local_record = repo.get_schedule(schedule_id)
        if not local_record:
            raise HTTPException(404, "schedule not found")
        try:
            temporal_cfg = TemporalConfig.from_env()
            t_client = await get_temporal_client(temporal_cfg)
            await delete_temporal_schedule(t_client, schedule_id)
        except Exception:
            pass
        repo.delete_schedule(schedule_id)
        return {"status": "deleted", "schedule_id": schedule_id}

    # Mount any extension routers (if provided)
    if additional_routers:
        for extra_router in additional_routers:
            app.include_router(extra_router)

    # Invoke any extension state initializers (if provided)
    if callable(app_state_initializer):
        app_state_initializer(app)

    return app


def __getattr__(name: str):
    if name == "app":
        import os
        if not os.getenv("AGENT_PLATFORM_AUTH_MODE") and not os.getenv("AGENT_PLATFORM_API_TOKEN") and not os.getenv("AGENT_PLATFORM_AUTH_TOKENS"):
            os.environ["AGENT_PLATFORM_AUTH_MODE"] = "development"
            os.environ["AGENT_PLATFORM_DEV_MODE"] = "1"
        return create_app()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


