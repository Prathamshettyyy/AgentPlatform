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

logger = logging.getLogger("agent_platform.llm.anthropic")


class AnthropicProvider(LLMProvider):
    """LLM Provider plugin for Anthropic Claude Messages API."""

    provider_name: str = "anthropic"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def get_capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            text=True,
            image=True,
            pdf=False,
            structured_output=True,
            tool_calling=True,
            streaming=True,
        )

    def _get_api_key(self, config: ModelConfiguration) -> str:
        key = config.get_api_key() or os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise LLMAuthenticationError(
                f"Anthropic API key missing for model '{config.model}'. "
                "Set ANTHROPIC_API_KEY or configure api_key_env."
            )
        return key

    async def generate(self, config: ModelConfiguration, request: LLMRequest) -> LLMResponse:
        api_key = self._get_api_key(config)
        base = (config.api_base or "https://api.anthropic.com").rstrip("/")
        url = f"{base}/v1/messages"

        system_prompt = ""
        anthropic_messages = []
        for msg in request.messages:
            if msg.role == "system":
                system_prompt = msg.content if isinstance(msg.content, str) else str(msg.content)
            else:
                anthropic_messages.append({"role": msg.role, "content": msg.content})

        payload: dict[str, Any] = {
            "model": config.model,
            "messages": anthropic_messages,
            "max_tokens": request.max_tokens or config.max_tokens or 2048,
        }
        if system_prompt:
            payload["system"] = system_prompt
        if config.temperature is not None or request.temperature is not None:
            payload["temperature"] = request.temperature if request.temperature is not None else config.temperature

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        try:
            if self._client is not None:
                res = await self._client.post(url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                    res = await client.post(url, json=payload, headers=headers)
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(f"Anthropic connection error: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Anthropic request timed out: {exc}") from exc
        except Exception as exc:
            raise LLMError(f"Anthropic unexpected error: {exc}") from exc

        if res.status_code in (401, 403):
            raise LLMAuthenticationError(f"Anthropic authentication failed: {res.text}")
        if res.status_code == 429:
            raise LLMUnavailableError(f"Anthropic rate limit exceeded: {res.text}")
        if res.status_code >= 500:
            raise LLMUnavailableError(f"Anthropic server error: {res.text}")
        if res.status_code >= 400:
            raise LLMResponseError(f"Anthropic returned HTTP {res.status_code}: {res.text}")

        data = res.json()
        content_blocks = data.get("content") or []
        content = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")

        raw_usage = data.get("usage") or {}
        p_tok = raw_usage.get("input_tokens", 0)
        c_tok = raw_usage.get("output_tokens", 0)
        usage = LLMUsage(prompt_tokens=p_tok, completion_tokens=c_tok, total_tokens=p_tok + c_tok)

        structured = None
        if request.response_format and content:
            try:
                structured = json.loads(content)
            except Exception:
                pass

        return LLMResponse(
            content=content,
            structured_output=structured,
            usage=usage,
            provider=self.provider_name,
            model=config.model,
            metadata={"stop_reason": data.get("stop_reason")},
        )

    async def stream(
        self, config: ModelConfiguration, request: LLMRequest
    ) -> AsyncIterator[LLMStreamChunk]:
        api_key = self._get_api_key(config)
        base = (config.api_base or "https://api.anthropic.com").rstrip("/")
        url = f"{base}/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": config.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages if m.role != "system"],
            "max_tokens": request.max_tokens or config.max_tokens or 2048,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        raise LLMResponseError(f"Anthropic stream returned HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = json.loads(line[6:])
                        if data.get("type") == "content_block_delta":
                            delta = data.get("delta", {}).get("text", "")
                            yield LLMStreamChunk(delta=delta, done=False)
                        elif data.get("type") == "message_stop":
                            yield LLMStreamChunk(delta="", done=True)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Anthropic stream timed out: {exc}") from exc
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(f"Anthropic stream connection failed: {exc}") from exc

