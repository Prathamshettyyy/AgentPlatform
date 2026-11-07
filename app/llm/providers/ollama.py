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
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    LLMUsage,
    LLMUnavailableError,
    LLMTimeoutError,
    LLMResponseError,
    LLMError,
)

logger = logging.getLogger("agent_platform.llm.ollama")


class OllamaProvider(LLMProvider):
    """LLM Provider plugin for local Ollama instances."""

    provider_name: str = "ollama"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def get_capabilities(self, model: str) -> ModelCapabilities:
        model_lower = model.lower()
        is_vision = any(v in model_lower for v in ("vl", "vision", "llava", "bakllava", "minicpm-v"))
        return ModelCapabilities(
            text=True,
            image=is_vision,
            pdf=False,
            structured_output=True,
            tool_calling=True,
            streaming=True,
        )

    def _resolve_base_url(self, config: ModelConfiguration) -> str:
        base = config.api_base or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        return base.rstrip("/")

    def _build_payload(self, config: ModelConfiguration, request: LLMRequest, stream: bool = False) -> dict[str, Any]:
        messages_data: list[dict[str, Any]] = []
        for msg in request.messages:
            entry: dict[str, Any] = {"role": msg.role}
            if isinstance(msg.content, str):
                entry["content"] = msg.content
            elif isinstance(msg.content, list):
                # Multimodal or part-based content
                text_parts = []
                images = []
                for part in msg.content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                        elif part.get("type") == "image_url" or "image" in part:
                            # base64 encoded image or url
                            img_data = part.get("image_url", {}).get("url") or part.get("image")
                            if img_data:
                                if img_data.startswith("data:image"):
                                    img_data = img_data.split(",", 1)[-1]
                                images.append(img_data)
                entry["content"] = "\n".join(text_parts)
                if images:
                    entry["images"] = images
            else:
                entry["content"] = str(msg.content)
            messages_data.append(entry)

        payload: dict[str, Any] = {
            "model": config.model,
            "messages": messages_data,
            "stream": stream,
        }

        # Sampling options
        options: dict[str, Any] = {}
        temp = request.temperature if request.temperature is not None else config.temperature
        if temp is not None:
            options["temperature"] = temp
        top_p = request.top_p if request.top_p is not None else config.top_p
        if top_p is not None:
            options["top_p"] = top_p
        max_tok = request.max_tokens if request.max_tokens is not None else config.max_tokens
        if max_tok is not None:
            options["num_predict"] = max_tok

        if options:
            payload["options"] = options

        # Structured output format
        if request.response_format:
            fmt = request.response_format
            if isinstance(fmt, dict) and "schema" in fmt:
                payload["format"] = fmt["schema"]
            elif isinstance(fmt, dict) and fmt.get("type") == "json_object":
                payload["format"] = "json"
            else:
                payload["format"] = "json"

        # Tools
        if request.tools:
            payload["tools"] = request.tools

        return payload

    async def generate(self, config: ModelConfiguration, request: LLMRequest) -> LLMResponse:
        base_url = self._resolve_base_url(config)
        endpoint = f"{base_url}/api/chat"
        payload = self._build_payload(config, request, stream=False)

        timeout = httpx.Timeout(
            timeout=config.timeout_seconds,
            connect=min(3.0, config.timeout_seconds),
        )
        try:
            if self._client is not None:
                res = await self._client.post(endpoint, json=payload, timeout=timeout)
            else:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    res = await client.post(endpoint, json=payload)
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(
                f"Ollama is unavailable at {base_url}. Start Ollama and ensure model '{config.model}' is pulled."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"Ollama request to '{config.model}' at {base_url} timed out after {config.timeout_seconds}s"
            ) from exc
        except Exception as exc:
            raise LLMError(f"Ollama invocation error for model '{config.model}': {exc}") from exc

        if res.status_code >= 400:
            if res.status_code == 404:
                raise LLMUnavailableError(f"Ollama model '{config.model}' was not found at {base_url} (HTTP 404).")
            raise LLMResponseError(f"Ollama returned HTTP {res.status_code}: {res.text}")

        try:
            data = res.json()
        except Exception as exc:
            raise LLMResponseError(f"Failed to decode Ollama JSON response: {exc}") from exc

        msg = data.get("message") or {}
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls") or []

        prompt_tokens = data.get("prompt_eval_count", 0)
        completion_tokens = data.get("eval_count", 0)
        usage = LLMUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

        structured: dict[str, Any] | None = None
        if request.response_format and content:
            try:
                structured = json.loads(content)
            except Exception as parse_err:
                logger.debug("Failed to parse structured JSON from Ollama response: %s", parse_err)

        return LLMResponse(
            content=content,
            structured_output=structured,
            tool_calls=tool_calls,
            usage=usage,
            provider=self.provider_name,
            model=config.model,
            metadata={
                "total_duration": data.get("total_duration"),
                "load_duration": data.get("load_duration"),
            },
        )

    async def stream(
        self, config: ModelConfiguration, request: LLMRequest
    ) -> AsyncIterator[LLMStreamChunk]:
        base_url = self._resolve_base_url(config)
        endpoint = f"{base_url}/api/chat"
        payload = self._build_payload(config, request, stream=True)

        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                async with client.stream("POST", endpoint, json=payload) as response:
                    if response.status_code >= 400:
                        raise LLMResponseError(f"Ollama stream failed with HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        chunk_data = json.loads(line)
                        msg = chunk_data.get("message") or {}
                        delta = msg.get("content", "")
                        done = chunk_data.get("done", False)
                        usage = None
                        if done:
                            p_tok = chunk_data.get("prompt_eval_count", 0)
                            c_tok = chunk_data.get("eval_count", 0)
                            usage = LLMUsage(prompt_tokens=p_tok, completion_tokens=c_tok, total_tokens=p_tok + c_tok)
                        yield LLMStreamChunk(delta=delta, done=done, usage=usage)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise LLMUnavailableError(f"Ollama stream failed to connect at {base_url}") from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Ollama stream timed out after {config.timeout_seconds}s") from exc

