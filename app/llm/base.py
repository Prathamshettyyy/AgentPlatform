from __future__ import annotations

from typing import AsyncIterator, Protocol
from .contracts import (
    ModelCapabilities,
    ModelConfiguration,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
)


class LLMProvider(Protocol):
    """Common abstraction that every LLM provider plugin must implement."""

    provider_name: str

    def get_capabilities(self, model: str) -> ModelCapabilities:
        """Return the declared capabilities for a given model under this provider."""
        ...

    async def generate(self, config: ModelConfiguration, request: LLMRequest) -> LLMResponse:
        """Execute a text generation / chat completion request."""
        ...

    async def stream(
        self, config: ModelConfiguration, request: LLMRequest
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream chunks for a text generation request."""
        ...

