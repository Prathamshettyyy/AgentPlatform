from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator
import httpx

from ..base import LLMProvider
from ..contracts import (
    ModelCapabilities,
    ModelConfiguration,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
    LLMAuthenticationError,
    LLMUnavailableError,
    LLMTimeoutError,
    LLMResponseError,
    LLMError,
)

logger = logging.getLogger("agent_platform.llm.openai")


class OpenAIProvider(LLMProvider):
    """LLM Provider plugin for OpenAI and compatible APIs (e.g. vLLM, DeepSeek)."""

    provider_name: str = "openai"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def get_capabilities(self, model: str) -> ModelCapabilities:
        model_lower = model.lower()
        is_vision = "vision" in model_lower or "4o" in model_lower
        return ModelCapabilities(
            text=True,
            image=is_vision,
            pdf=False,
            structured_output=True,
            tool_calling=True,
            streaming=True,
        )

    def _get_api_key(self, config: ModelConfiguration) -> str:
        key = config.get_api_key() or os.getenv("OPENAI_API_KEY")
        if not key:
            raise LLMAuthenticationError(
                f"OpenAI API key missing for model '{config.model}'. "
                "Set OPENAI_API_KEY or configure api_key_env."
            )
        return key

    def _build_payload(self, config: ModelConfiguration, request: LLMRequest, stream: bool = False) -> dict[str, Any]:
        messages_data = [msg.model_dump(exclude_none=True) for msg in request.messages]
        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages_data,
            "stream": stream,
        }

        temp = request.temperature if request.temperature is not None else config.temperature
        if temp is not None:
            payload["temperature"] = temp
        top_p = request.top_p if request.top_p is not None else config.top_p
        if top_p is not None:
            payload["top_p"] = top_p
        max_tok = request.max_tokens if request.max_tokens is not None else config.max_tokens
        if max_tok is not None:
            payload["max_tokens"] = max_tok

        if request.response_format:
            payload["response_format"] = request.response_format
        if request.tools:
            payload["tools"] = request.tools

        return payload

    async def generate(self, config: ModelConfiguration, request: LLMRequest) -> LLMResponse:
        api_key = self._get_api_key(config)
        base = (config.api_base or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/chat/completions"
        payload = self._build_payload(config, request, stream=False)
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            if self._client is not None:
                res = await self._client.post(url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                    res = await client.post(url, json=payload, headers=headers)
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(f"OpenAI connection error: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"OpenAI request timed out: {exc}") from exc
        except Exception as exc:
            raise LLMError(f"OpenAI unexpected error: {exc}") from exc

        if res.status_code in (401, 403):
            raise LLMAuthenticationError(f"OpenAI authentication failed: {res.text}")
        if res.status_code == 429:
            raise LLMUnavailableError(f"OpenAI rate limit exceeded: {res.text}")
        if res.status_code >= 500:
            raise LLMUnavailableError(f"OpenAI server error: {res.text}")
        if res.status_code >= 400:
            raise LLMResponseError(f"OpenAI returned HTTP {res.status_code}: {res.text}")

        data = res.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMResponseError("OpenAI returned no choices in response.")

        msg = choices[0].get("message") or {}
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls") or []

        raw_usage = data.get("usage") or {}
        usage = LLMUsage(
            prompt_tokens=raw_usage.get("prompt_tokens", 0),
            completion_tokens=raw_usage.get("completion_tokens", 0),
            total_tokens=raw_usage.get("total_tokens", 0),
        )

        structured: dict[str, Any] | None = None
        if request.response_format and content:
            try:
                structured = json.loads(content)
            except Exception as parse_err:
                logger.debug("Failed to parse structured JSON: %s", parse_err)

        return LLMResponse(
            content=content,
            structured_output=structured,
            tool_calls=tool_calls,
            usage=usage,
            provider=self.provider_name,
            model=config.model,
            metadata={"finish_reason": choices[0].get("finish_reason")},
        )

    async def stream(
        self, config: ModelConfiguration, request: LLMRequest
    ) -> AsyncIterator[LLMStreamChunk]:
        api_key = self._get_api_key(config)
        base = (config.api_base or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/chat/completions"
        payload = self._build_payload(config, request, stream=True)
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code in (401, 403):
                        raise LLMAuthenticationError("OpenAI authentication failed")
                    if response.status_code >= 400:
                        raise LLMResponseError(f"OpenAI stream returned HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            yield LLMStreamChunk(delta="", done=True)
                            break
                        chunk_data = json.loads(data_str)
                        choices = chunk_data.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta", {}).get("content", "")
                            yield LLMStreamChunk(delta=delta, done=False)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"OpenAI stream timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(f"OpenAI stream connection failed: {exc}") from exc

