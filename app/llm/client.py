from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator, TypeVar, Union
from pydantic import BaseModel

from .contracts import (
    ModelCapabilities,
    ModelConfiguration,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    LLMUnavailableError,
    LLMTimeoutError,
    LLMAuthenticationError,
    LLMCapabilityError,
    LLMInvalidRequestError,
    LLMError,
)

if TYPE_CHECKING:
    from .registry import LLMProviderRegistry

logger = logging.getLogger("agent_platform.llm.client")
T = TypeVar("T", bound=BaseModel)


class LLMClient:
    """Agent-facing LLM interface.

    Agents interact with this client using logical profiles (e.g. 'document_analysis')
    without needing to know whether the backing model is Ollama, Gemini, OpenAI, etc.
    """

    def __init__(self, config: ModelConfiguration, registry: "LLMProviderRegistry"):
        self.config = config
        self.registry = registry

    def _normalize_messages(
        self, prompt: str | list[LLMMessage], system: str | None = None
    ) -> list[LLMMessage]:
        messages: list[LLMMessage] = []
        if system:
            messages.append(LLMMessage.system(system))

        if isinstance(prompt, str):
            messages.append(LLMMessage.user(prompt))
        elif isinstance(prompt, list):
            messages.extend(prompt)
        else:
            messages.append(LLMMessage.user(str(prompt)))

        return messages

    def _validate_request_capabilities(
        self, config: ModelConfiguration, request: LLMRequest
    ) -> None:
        """Validate that the target model supports all features requested by the agent."""
        provider = self.registry.get_provider(config.provider)
        caps = config.capabilities or provider.get_capabilities(config.model)

        if request.response_format:
            caps.validate_capability("structured_output", f"{config.provider}/{config.model}")

        if request.tools:
            caps.validate_capability("tool_calling", f"{config.provider}/{config.model}")

        # Check for image content in messages
        has_images = any(
            isinstance(m.content, list)
            and any(isinstance(p, dict) and (p.get("type") == "image_url" or "image" in p) for p in m.content)
            for m in request.messages
        )
        if has_images:
            caps.validate_capability("image", f"{config.provider}/{config.model}")

    async def generate(
        self,
        prompt: str | list[LLMMessage],
        system: str | None = None,
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        top_p: float | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response using the configured model profile and automatic fallbacks."""
        messages = self._normalize_messages(prompt, system)
        request = LLMRequest(
            messages=messages,
            response_format=response_format,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stream=False,
        )

        models_to_try = [self.config] + list(self.config.fallback_models)
        attempt_logs: list[dict[str, Any]] = []

        last_error: Exception | None = None

        for idx, model_cfg in enumerate(models_to_try):
            is_fallback = idx > 0
            model_tag = f"{model_cfg.provider}/{model_cfg.model}"

            # Skip candidate fallback if it requires an unconfigured environment key
            if model_cfg.api_key_env and not os.getenv(model_cfg.api_key_env):
                logger.debug("Skipping model %s because %s is not set", model_tag, model_cfg.api_key_env)
                continue

            try:
                # Pre-flight capability validation
                self._validate_request_capabilities(model_cfg, request)

                provider = self.registry.get_provider(model_cfg.provider)
                response = await provider.generate(model_cfg, request)

                # Annotate response with the actual executing model and fallback status
                response.provider = model_cfg.provider
                response.model = model_cfg.model
                response.fallback_used = is_fallback
                if is_fallback and attempt_logs:
                    response.metadata["fallback_attempts"] = attempt_logs

                return response

            except (LLMUnavailableError, LLMTimeoutError) as transient_err:
                # Transient errors trigger fallback to the next model
                logger.warning(
                    "Model %s failed with transient error: %s. %s",
                    model_tag,
                    transient_err,
                    "Attempting fallback..." if idx < len(models_to_try) - 1 else "No more fallbacks available.",
                )
                attempt_logs.append({
                    "model": model_tag,
                    "error_type": type(transient_err).__name__,
                    "message": str(transient_err),
                })
                last_error = transient_err
                continue

            except (LLMAuthenticationError, LLMInvalidRequestError, LLMCapabilityError) as non_transient_err:
                # Non-transient errors fail immediately unless a fallback explicitly supports it
                logger.error("Model %s failed with non-transient error: %s", model_tag, non_transient_err)
                raise non_transient_err

            except Exception as unexpected:
                logger.warning("Model %s encountered unexpected failure: %s", model_tag, unexpected)
                attempt_logs.append({
                    "model": model_tag,
                    "error_type": type(unexpected).__name__,
                    "message": str(unexpected),
                })
                last_error = unexpected
                continue

        # If all candidate models in the fallback chain failed
        raise LLMUnavailableError(
            f"All configured models failed for profile. Primary: {self.config.provider}/{self.config.model}. "
            f"Attempts: {attempt_logs}. Last error: {last_error}"
        ) from last_error

    async def stream(
        self,
        prompt: str | list[LLMMessage],
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream response chunks from the primary model."""
        messages = self._normalize_messages(prompt, system)
        request = LLMRequest(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        self._validate_request_capabilities(self.config, request)
        provider = self.registry.get_provider(self.config.provider)
        async for chunk in provider.stream(self.config, request):
            yield chunk

    async def generate_structured(
        self,
        schema: type[T] | dict[str, Any],
        prompt: str | list[LLMMessage],
        system: str | None = None,
        **kwargs: Any,
    ) -> Union[T, dict[str, Any]]:
        """Generate guaranteed structured output parsed into a Pydantic model or dict."""
        json_schema: dict[str, Any]
        is_pydantic = isinstance(schema, type) and issubclass(schema, BaseModel)

        if is_pydantic:
            json_schema = schema.model_json_schema()
            response_format = {"type": "json_object", "schema": json_schema}
        elif isinstance(schema, dict):
            json_schema = schema
            response_format = {"type": "json_object", "schema": json_schema}
        else:
            raise ValueError("schema must be a Pydantic BaseModel class or a JSON schema dict")

        format_instruction = (
            f"\n\nYou MUST respond with valid JSON matching this schema:\n{json.dumps(json_schema, indent=2)}"
        )
        sys_prompt = f"{system or ''}{format_instruction}".strip()

        response = await self.generate(
            prompt=prompt,
            system=sys_prompt,
            response_format=response_format,
            **kwargs,
        )

        if response.structured_output is not None:
            parsed_data = response.structured_output
        else:
            # Fallback parsing from content
            clean = response.content.strip()
            if clean.startswith("```json"):
                clean = clean[7:]
            elif clean.startswith("```"):
                clean = clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            parsed_data = json.loads(clean.strip())

        if is_pydantic:
            return schema.model_validate(parsed_data)
        return parsed_data

