from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator

from app.security import redact_sensitive, redact_text
from app.sdk.contracts import ErrorInfo
from .contracts import ToolExecutionContext, ToolRequest, ToolResult
from .registry import ToolRegistry


class ToolPermissionError(PermissionError):
    pass


class ToolValidationError(ValueError):
    pass


class ToolRunner:
    def __init__(self, registry: ToolRegistry, logger: logging.Logger | None = None,
                 execution_recorder: Callable[[str, str, str, dict[str, Any]], None] | None = None):
        self.registry = registry
        self.logger = logger or logging.getLogger("agent_platform.tools")
        self.execution_recorder = execution_recorder

    async def run(self, request: ToolRequest, allowed_tools: set[str] | None = None,
                  permissions: set[str] | None = None) -> ToolResult:
        started = time.perf_counter()
        execution_id = str(uuid.uuid4())
        permissions = permissions or set()
        try:
            if allowed_tools is None or request.tool_id not in allowed_tools:
                raise ToolPermissionError(f"agent {request.execution_context.agent_id} is not permitted to use tool {request.tool_id}")
            registered = self.registry.get(request.tool_id)
            missing = set(registered.metadata.required_permissions) - permissions
            if missing:
                raise ToolPermissionError(f"missing permissions for {request.tool_id}: {sorted(missing)}")
            self._validate(request.inputs, registered.metadata.input_schema, "input")
            attempts = 0
            value: Any = None
            while True:
                attempts += 1
                try:
                    value = await asyncio.wait_for(self._invoke(registered.implementation, request), registered.metadata.timeout_seconds)
                    break
                except Exception:
                    if attempts > registered.metadata.max_retries or not registered.metadata.idempotent:
                        raise
            if not isinstance(value, dict):
                raise ToolValidationError("tool output must be a dictionary")
            self._validate(value, registered.metadata.output_schema, "output")
            metadata = {"execution_id": execution_id, "duration_ms": round((time.perf_counter() - started) * 1000, 3), "attempts": attempts}
            result = ToolResult(status="succeeded", output=value, metadata=metadata)
        except Exception as exc:
            metadata = {"execution_id": execution_id, "duration_ms": round((time.perf_counter() - started) * 1000, 3)}
            result = ToolResult(status="failed", error=ErrorInfo(code=type(exc).__name__, message=redact_text(str(exc))), metadata=metadata)
        safe_inputs = redact_sensitive(request.inputs)
        self.logger.info("tool execution", extra={"tool_id": request.tool_id, "run_id": request.execution_context.run_id, "inputs": safe_inputs, "status": result.status})
        if self.execution_recorder:
            payload = {"output": redact_sensitive(result.output), "error": redact_sensitive(result.error.model_dump()) if result.error else None, "metadata": result.metadata, "inputs": safe_inputs}
            self.execution_recorder(request.execution_context.run_id, f"tool:{request.tool_id}", result.status, payload)
        return result

    @staticmethod
    async def _invoke(implementation: Any, request: ToolRequest) -> Any:
        context = request.execution_context
        if inspect.iscoroutinefunction(implementation):
            return await implementation(request, context)
        value = await asyncio.to_thread(implementation, request, context)
        return await value if inspect.isawaitable(value) else value

    @staticmethod
    def _validate(value: Any, schema: dict[str, Any], label: str) -> None:
        if schema:
            errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
            if errors:
                raise ToolValidationError(f"invalid tool {label}: {errors[0].message}")

