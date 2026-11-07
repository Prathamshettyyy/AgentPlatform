from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.runtime.errors import AgentDisabledError, AgentNotFoundError
from .contracts import ToolMetadata


@dataclass(frozen=True)
class RegisteredTool:
    metadata: ToolMetadata
    implementation: Any


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, metadata: ToolMetadata, implementation: Any) -> None:
        if metadata.id in self._tools:
            raise ValueError(f"tool already registered: {metadata.id}")
        if metadata.adapter_type != "python_callable":
            raise ValueError(f"unsupported tool adapter type: {metadata.adapter_type}")
        if not callable(implementation):
            raise TypeError(f"tool implementation is not callable: {metadata.id}")
        self._tools[metadata.id] = RegisteredTool(metadata, implementation)

    def get(self, tool_id: str, require_enabled: bool = True) -> RegisteredTool:
        try:
            tool = self._tools[tool_id]
        except KeyError as exc:
            raise AgentNotFoundError(f"unknown tool: {tool_id}") from exc
        if require_enabled and not tool.metadata.enabled:
            raise AgentDisabledError(f"tool is disabled: {tool_id}")
        return tool

    def list_enabled(self) -> list[ToolMetadata]:
        return [tool.metadata for tool in self._tools.values() if tool.metadata.enabled]

    def list_all(self) -> list[ToolMetadata]:
        return [tool.metadata for tool in self._tools.values()]

    def disable(self, tool_id: str) -> None:
        self.get(tool_id, require_enabled=False).metadata.enabled = False

