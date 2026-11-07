from __future__ import annotations

import inspect
from typing import Any, Protocol

from app.sdk.context import AgentContext
from app.sdk.contracts import AgentRequest, AgentResult


class Adapter(Protocol):
    def invoke(self, implementation: Any, request: AgentRequest, context: AgentContext) -> Any: ...


class PythonCallableAdapter:
    def invoke(self, implementation: Any, request: AgentRequest, context: AgentContext) -> Any:
        value = implementation(request, context)
        return value if not inspect.isawaitable(value) else value


class CompiledLangGraphAdapter:
    def invoke(self, implementation: Any, request: AgentRequest, context: AgentContext) -> Any:
        config = {"configurable": {"thread_id": request.run_id}}
        value = implementation.invoke({"request": request.model_dump()}, config)
        if isinstance(value, AgentResult):
            return value
        return {"output": value}

