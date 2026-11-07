from __future__ import annotations

from typing import Protocol

from .context import AgentContext
from .contracts import AgentRequest, AgentResult


class AgentProtocol(Protocol):
    metadata: object

    def __call__(self, request: AgentRequest, context: AgentContext) -> AgentResult | dict: ...

