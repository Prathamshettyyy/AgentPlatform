from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.tools.contracts import ToolResult


class AgentContext:
    def __init__(self, run_id: str, workflow_id: str | None, node_id: str | None,
                 logger: logging.Logger | None = None, configuration: dict[str, Any] | None = None,
                 agent_id: str | None = None, tool_runner: Any = None,
                 allowed_tools: set[str] | None = None, permissions: set[str] | None = None,
                 llm_registry: Any = None):
        self.run_id = run_id
        self.workflow_id = workflow_id
        self.node_id = node_id
        self.agent_id = agent_id or "unknown-agent"
        self.logger = logger or logging.getLogger("agent_platform.agent")
        self._configuration = dict(configuration or {})
        self._tool_runner = tool_runner
        self._allowed_tools = allowed_tools
        self._permissions = permissions or set()
        self._llm_registry = llm_registry

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._configuration.get(key, default)

    def get_llm(self, profile: str = "default") -> Any:
        """Retrieve a model-agnostic LLMClient for a logical profile.

        Example:
            llm = context.get_llm("document_analysis")
            response = await llm.generate("Please analyze this document...")
        """
        if self._llm_registry is None:
            from app.llm import get_default_llm_registry
            self._llm_registry = get_default_llm_registry()
        return self._llm_registry.get(profile)

    async def call_tool(self, tool_id: str, inputs: dict[str, Any]) -> ToolResult:
        if self._tool_runner is None:
            raise RuntimeError("no tool runner is configured for this agent execution")
        from app.tools.contracts import ToolRequest

        request = ToolRequest(
            tool_id=tool_id,
            inputs=inputs,
            execution_context={
                "run_id": self.run_id,
                "workflow_id": self.workflow_id,
                "node_id": self.node_id,
                "agent_id": self.agent_id,
                "permissions": sorted(self._permissions),
            },
        )
        return await self._tool_runner.run(request, allowed_tools=self._allowed_tools, permissions=self._permissions)

