from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
from pathlib import Path
from typing import Any, Optional
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.langgraph import LangGraphPlugin

from app.registry import AgentRegistry
from app.registry.loader import AgentLoader
from app.tools.registry import ToolRegistry
from app.tools.loader import ToolLoader
from app.tools.runner import ToolRunner
from app.runtime.runner import AgentRunner
from app.storage.repository import ExecutionRepository
from app.workflows.builder import WorkflowBuilder
from app.workflows.models import WorkflowDefinition
from .config import TemporalConfig
from .client import get_temporal_client
from .workflows import DynamicLangGraphWorkflow, BatchLangGraphWorkflow

logger = logging.getLogger(__name__)


def get_worker_identity(instance_id: Optional[str] = None) -> dict[str, Any]:
    """Retrieve unique Worker instance identity details for logging and observability."""
    inst = instance_id or os.getenv("WORKER_INSTANCE", os.getenv("WORKER_ID", "1"))
    host = socket.gethostname()
    pid = os.getpid()
    return {
        "instance_id": str(inst),
        "hostname": host,
        "pid": pid,
        "formatted": f"worker-{inst}@{host}:{pid}",
    }


def configure_worker_logging(identity_str: str) -> None:
    """Set up log formatting containing the unique worker identity."""
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        f"%(asctime)s [%(levelname)s] [{identity_str}] %(name)s: %(message)s"
    )
    handler.setFormatter(formatter)
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    else:
        for h in root.handlers:
            h.setFormatter(formatter)


def build_registered_graphs(
    registry: AgentRegistry,
    repository: ExecutionRepository,
    runner: Optional[AgentRunner] = None,
    extra_graphs: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build LangGraph StateGraphs for all registered workflows in repository and definitions."""
    builder = WorkflowBuilder(registry, runner=runner)
    graphs: dict[str, Any] = {}

    # 1. From repository (latest for each workflow)
    for item in repository.list_workflows():
        try:
            wf_def = WorkflowDefinition.model_validate(item)
            graph = builder.build_state_graph(wf_def, allow_partial=True)
            graphs[wf_def.id] = graph
            logger.debug("Loaded graph for workflow '%s' (v%s)", wf_def.id, wf_def.version)
        except Exception as exc:
            logger.warning("Failed to build graph for workflow '%s': %s", item.get("id"), exc)

    # 2. Add extra or mock graphs
    if extra_graphs:
        graphs.update(extra_graphs)

    return graphs


def create_temporal_worker(
    client: Client,
    registry: AgentRegistry,
    repository: ExecutionRepository,
    runner: Optional[AgentRunner] = None,
    config: Optional[TemporalConfig] = None,
    extra_graphs: Optional[dict[str, Any]] = None,
    identity: Optional[str] = None,
    build_id: Optional[str] = None,
) -> Worker:
    """Create a configured Temporal Worker with LangGraphPlugin."""
    cfg = config or TemporalConfig.from_env()
    graphs = build_registered_graphs(registry, repository, runner=runner, extra_graphs=extra_graphs)
    plugin = LangGraphPlugin(graphs=graphs)

    worker_identity = identity or get_worker_identity()["formatted"]
    worker_build_id = build_id or worker_identity

    worker = Worker(
        client,
        task_queue=cfg.task_queue,
        workflows=[DynamicLangGraphWorkflow, BatchLangGraphWorkflow],
        plugins=[plugin],
        max_concurrent_activities=cfg.worker_concurrency,
        identity=worker_identity,
        build_id=worker_build_id,
    )
    worker._graphs = graphs  # type: ignore[attr-defined]
    return worker


async def run_worker(
    client: Optional[Client] = None,
    config: Optional[TemporalConfig] = None,
    repository_path: Optional[str] = None,
    instance_id: Optional[str] = None,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Start and run the Temporal Worker with graceful shutdown and unique identity."""
    identity = get_worker_identity(instance_id)
    configure_worker_logging(identity["formatted"])

    cfg = config or TemporalConfig.from_env()
    db_path = repository_path or os.getenv("AGENT_PLATFORM_DB_PATH", "agent_platform.db")
    repo = ExecutionRepository(db_path)
    logger.info("Worker database initialized at: %s", repo.path)

    c = client or await get_temporal_client(cfg)

    # Setup registries and runner
    registry = AgentRegistry()
    manifests_dir = Path(__file__).resolve().parents[2] / "plugins" / "manifests"
    if manifests_dir.exists():
        AgentLoader(registry, manifests_dir).load_all()

    tool_registry = ToolRegistry()
    tool_manifests_dir = Path(__file__).resolve().parents[2] / "plugins" / "tool_manifests"
    if tool_manifests_dir.exists():
        ToolLoader(tool_registry, tool_manifests_dir).load_all()

    tool_runner = ToolRunner(
        tool_registry,
        execution_recorder=lambda run_id, node_id, status, payload: repo.add_event(run_id, node_id, status, payload),
    )
    runner = AgentRunner(registry, tool_runner=tool_runner)

    worker = create_temporal_worker(
        client=c,
        registry=registry,
        repository=repo,
        runner=runner,
        config=cfg,
        identity=identity["formatted"],
    )

    logger.info(
        "Starting Temporal Worker [%s] on queue '%s' (concurrency: %d, shutdown_timeout: %.1fs)...",
        identity["formatted"],
        cfg.task_queue,
        cfg.worker_concurrency,
        cfg.worker_shutdown_timeout_seconds,
    )

    shutdown_event = stop_event or asyncio.Event()

    def _on_signal(sig: signal.Signals):
        logger.info(
            "Worker [%s] received signal %s (%d). Initiating graceful shutdown...",
            identity["formatted"],
            sig.name,
            sig.value,
        )
        shutdown_event.set()

    cleanup_signal_handlers = []
    if sys.platform != "win32":
        try:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, _on_signal, sig)
                cleanup_signal_handlers.append(sig)
        except (NotImplementedError, RuntimeError):
            pass

    worker_task = asyncio.create_task(worker.run())
    stop_wait_task = asyncio.create_task(shutdown_event.wait())

    worker_graphs = getattr(worker, "_graphs", None)

    async def _periodic_graph_refresh():
        if worker_graphs is None:
            return
        while not shutdown_event.is_set():
            try:
                refreshed = build_registered_graphs(registry, repo, runner=runner)
                worker_graphs.update(refreshed)
            except Exception as e:
                logger.debug("Failed periodic graph refresh: %s", e)
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    refresh_task = asyncio.create_task(_periodic_graph_refresh())

    try:
        done, pending = await asyncio.wait(
            [worker_task, stop_wait_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if shutdown_event.is_set():
            logger.info(
                "Worker [%s] stopping task polling and draining in-flight work (graceful timeout: %.1fs)...",
                identity["formatted"],
                cfg.worker_shutdown_timeout_seconds,
            )
            try:
                await asyncio.wait_for(
                    worker.shutdown(),
                    timeout=cfg.worker_shutdown_timeout_seconds,
                )
                logger.info("Worker [%s] successfully completed graceful shutdown.", identity["formatted"])
            except asyncio.TimeoutError:
                logger.warning(
                    "Worker [%s] graceful shutdown timed out after %.1fs. Forcing cancellation.",
                    identity["formatted"],
                    cfg.worker_shutdown_timeout_seconds,
                )
                worker_task.cancel()
            except Exception as exc:
                logger.error("Worker [%s] error during worker.shutdown(): %s", identity["formatted"], exc)
                worker_task.cancel()

        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Worker [%s] interrupted. Initiating immediate shutdown...", identity["formatted"])
        try:
            await asyncio.wait_for(worker.shutdown(), timeout=5.0)
        except Exception:
            pass
    finally:
        refresh_task.cancel()
        if sys.platform != "win32":
            try:
                loop = asyncio.get_running_loop()
                for sig in cleanup_signal_handlers:
                    loop.remove_signal_handler(sig)
            except Exception:
                pass
        stop_wait_task.cancel()
        logger.info("Worker [%s] process stopped.", identity["formatted"])


if __name__ == "__main__":
    asyncio.run(run_worker())

