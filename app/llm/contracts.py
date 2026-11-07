from __future__ import annotations

import os
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# 1. Standard LLM Exceptions
# ============================================================================

class LLMError(RuntimeError):
    """Base exception for all LLM provider and invocation errors."""
    pass


class LLMUnavailableError(LLMError):
    """The model or provider service is unavailable (e.g. connection refused, 503).
    Eligible for automatic model fallback.
    """
    pass


class LLMTimeoutError(LLMUnavailableError):
    """The request to the model or provider timed out.
    Eligible for automatic model fallback.
    """
    pass


class LLMAuthenticationError(LLMError):
    """Authentication or authorization failed (e.g. invalid API key).
    Not eligible for retry with the same credentials.
    """
    pass


class LLMCapabilityError(LLMError):
    """The model does not support a requested capability (e.g. vision, structured output)."""
    pass


class LLMInvalidRequestError(LLMError):
    """The request is invalid (e.g. context window exceeded, malformed prompt)."""
    pass


class LLMResponseError(LLMError):
    """The model returned an unexpected, empty, or malformed response."""
    pass


# ============================================================================
# 2. Model Capabilities
# ============================================================================

class ModelCapabilities(BaseModel):
    """Declares capabilities natively supported by a model and provider."""
    model_config = ConfigDict(extra="ignore")

    text: bool = True
    image: bool = False
    pdf: bool = False
    structured_output: bool = False
    tool_calling: bool = False
    streaming: bool = True

    def validate_capability(self, capability: str, model_id: str = "") -> None:
        """Validates that a requested capability is supported.
        Raises LLMCapabilityError if unavailable.
        """
        if not getattr(self, capability, False):
            target = f"Model '{model_id}'" if model_id else "Selected model"
            raise LLMCapabilityError(
                f"{target} does not support requested capability '{capability}'. "
                f"Supported capabilities: {[k for k, v in self.model_dump().items() if v]}"
            )


# ============================================================================
# 3. Model Configuration
# ============================================================================

class ModelConfiguration(BaseModel):
    """Configuration for a specific LLM model instance or logical profile."""
    model_config = ConfigDict(extra="ignore")

    provider: str  # e.g. "ollama", "gemini", "openai", "anthropic"
    model: str  # e.g. "qwen3.5:4b", "llama3.2", "gemini-1.5-flash"
    api_base: Optional[str] = None
    api_key_env: Optional[str] = None  # Name of environment variable holding the secret key
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout_seconds: float = 60.0
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    capabilities: Optional[ModelCapabilities] = None
    fallback_models: list[ModelConfiguration] = Field(default_factory=list)

    def get_api_key(self) -> Optional[str]:
        """Safely resolve API key from environment variable without exposing it in serialized config."""
        if self.api_key_env:
            return os.getenv(self.api_key_env)
        return None

    def safe_repr(self) -> dict[str, Any]:
        """Safe dictionary representation without leaking sensitive environment variable values."""
        data = self.model_dump(exclude={"fallback_models"})
        if self.api_key_env:
            data["api_key_configured"] = bool(self.get_api_key())
        return data


# ============================================================================
# 4. Request & Response Contracts
# ============================================================================

class LLMMessage(BaseModel):
    """Represents a single message in an LLM conversation."""
    model_config = ConfigDict(extra="ignore")

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]]
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None

    @classmethod
    def system(cls, content: str) -> "LLMMessage":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str | list[dict[str, Any]]) -> "LLMMessage":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str) -> "LLMMessage":
        return cls(role="assistant", content=content)


class LLMRequest(BaseModel):
    """A standardized request passed to an LLM provider."""
    model_config = ConfigDict(extra="ignore")

    messages: list[LLMMessage]
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    max_tokens: Optional[int] = None
    response_format: Optional[dict[str, Any]] = None  # e.g. {"type": "json_object", "schema": ...}
    tools: Optional[list[dict[str, Any]]] = None
    stream: bool = False


class LLMUsage(BaseModel):
    """Token accounting metadata."""
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """Standardized result returned by all LLM providers."""
    model_config = ConfigDict(extra="ignore")

    content: str
    structured_output: Optional[dict[str, Any]] = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    usage: LLMUsage = Field(default_factory=LLMUsage)
    provider: str = ""
    model: str = ""
    fallback_used: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMStreamChunk(BaseModel):
    """A single streamed token or delta."""
    model_config = ConfigDict(extra="ignore")

    delta: str
    done: bool = False
    usage: Optional[LLMUsage] = None

