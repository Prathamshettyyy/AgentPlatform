from __future__ import annotations

import inspect
import logging
import time
import uuid
from typing import Any

from app.registry import AgentRegistry
from app.security import redact_sensitive, redact_text
from app.sdk.context import AgentContext
from app.sdk.contracts import AgentRequest, AgentResult, ErrorInfo
from .adapters import CompiledLangGraphAdapter, PythonCallableAdapter


class AgentRunner:
    def __init__(self, registry: AgentRegistry, logger: logging.Logger | None = None, tool_runner: Any = None, llm_registry: Any = None):
        self.registry = registry
        self.logger = logger or logging.getLogger("agent_platform.runner")
        self.tool_runner = tool_runner
        self.llm_registry = llm_registry
        self.adapters = {"python_callable": PythonCallableAdapter(), "compiled_langgraph": CompiledLangGraphAdapter()}

    async def run(self, agent_id: str, request: AgentRequest, configuration: dict[str, Any] | None = None) -> AgentResult:
        started = time.perf_counter()
        execution_id = str(uuid.uuid4())
        try:
            registered = self.registry.get(agent_id)
            configured_tools = set(registered.metadata.execution.get("allowed_tools", []))
            if configuration and "allowed_tools" in configuration:
                configured_tools &= set(configuration["allowed_tools"])
            permissions = set(registered.metadata.execution.get("permissions", []))
            context = AgentContext(
                request.run_id,
                request.workflow_id,
                request.node_id,
                self.logger,
                configuration,
                registered.metadata.id,
                self.tool_runner,
                configured_tools,
                permissions,
                llm_registry=self.llm_registry,
            )
            adapter = self.adapters[registered.metadata.adapter_type]
            value = adapter.invoke(registered.implementation, request, context)
            if inspect.isawaitable(value):
                value = await value
            result = value if isinstance(value, AgentResult) else AgentResult(status="succeeded", output=value if isinstance(value, dict) else {"value": value})
            if result.error:
                result = result.model_copy(update={"error": result.error.model_copy(update={"message": redact_text(result.error.message), "details": redact_sensitive(result.error.details)})})
            return result.model_copy(update={"metadata": {**result.metadata, "execution_id": execution_id, "duration_ms": round((time.perf_counter() - started) * 1000, 3)}})
        except Exception as exc:
            self.logger.error("agent execution failed", extra={"agent_id": agent_id, "run_id": request.run_id, "error": redact_text(str(exc))})
            return AgentResult(status="failed", error=ErrorInfo(code=type(exc).__name__, message=redact_text(str(exc))), metadata={"execution_id": execution_id, "duration_ms": round((time.perf_counter() - started) * 1000, 3)})

