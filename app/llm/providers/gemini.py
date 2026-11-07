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
    LLMAuthenticationError,
    LLMUnavailableError,
    LLMTimeoutError,
    LLMResponseError,
    LLMError,
)

logger = logging.getLogger("agent_platform.llm.gemini")


class GeminiProvider(LLMProvider):
    """LLM Provider plugin for Google Gemini API."""

    provider_name: str = "gemini"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def get_capabilities(self, model: str) -> ModelCapabilities:
        return ModelCapabilities(
            text=True,
            image=True,
            pdf=True,
            structured_output=True,
            tool_calling=True,
            streaming=True,
        )

    def _get_api_key(self, config: ModelConfiguration) -> str:
        key = config.get_api_key() or os.getenv("GEMINI_API_KEY")
        if not key:
            env_var = config.api_key_env or "GEMINI_API_KEY"
            raise LLMAuthenticationError(
                f"Gemini API key is missing. No API key found in environment variable '{env_var}' "
                f"for model '{config.model}'."
            )
        return key

    def _build_payload(self, config: ModelConfiguration, request: LLMRequest) -> dict[str, Any]:
        system_instructions: list[dict[str, str]] = []
        contents: list[dict[str, Any]] = []

        for msg in request.messages:
            if msg.role == "system":
                if isinstance(msg.content, str):
                    system_instructions.append({"text": msg.content})
            else:
                role = "model" if msg.role == "assistant" else "user"
                parts = []
                if isinstance(msg.content, str):
                    parts.append({"text": msg.content})
                elif isinstance(msg.content, list):
                    for p in msg.content:
                        if isinstance(p, dict):
                            if p.get("type") == "text":
                                parts.append({"text": p.get("text", "")})
                            elif p.get("type") == "image_url" or "image" in p:
                                img_data = p.get("image_url", {}).get("url") or p.get("image")
                                mime_type = "image/jpeg"
                                if img_data and img_data.startswith("data:"):
                                    header, b64 = img_data.split(",", 1)
                                    mime_type = header.split(";")[0].replace("data:", "")
                                    img_data = b64
                                parts.append({"inlineData": {"mimeType": mime_type, "data": img_data}})
                contents.append({"role": role, "parts": parts})

        payload: dict[str, Any] = {"contents": contents}
        if system_instructions:
            payload["systemInstruction"] = {"parts": system_instructions}

        # Generation config
        gen_config: dict[str, Any] = {}
        temp = request.temperature if request.temperature is not None else config.temperature
        if temp is not None:
            gen_config["temperature"] = temp
        top_p = request.top_p if request.top_p is not None else config.top_p
        if top_p is not None:
            gen_config["topP"] = top_p
        max_tok = request.max_tokens if request.max_tokens is not None else config.max_tokens
        if max_tok is not None:
            gen_config["maxOutputTokens"] = max_tok

        # Structured output
        if request.response_format:
            gen_config["responseMimeType"] = "application/json"
            if isinstance(request.response_format, dict) and "schema" in request.response_format:
                gen_config["responseSchema"] = request.response_format["schema"]

        if gen_config:
            payload["generationConfig"] = gen_config

        return payload

    async def generate(self, config: ModelConfiguration, request: LLMRequest) -> LLMResponse:
        api_key = self._get_api_key(config)
        base = (config.api_base or "https://generativelanguage.googleapis.com").rstrip("/")
        model = config.model
        url = f"{base}/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": api_key}
        payload = self._build_payload(config, request)

        try:
            if self._client is not None:
                res = await self._client.post(url, headers=headers, json=payload)
            else:
                async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                    res = await client.post(url, headers=headers, json=payload)
        except httpx.ConnectError as exc:
            raise LLMUnavailableError(f"Gemini API connection error for model '{model}': {exc}") from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Gemini API request timed out after {config.timeout_seconds}s") from exc
        except Exception as exc:
            raise LLMError(f"Gemini API unexpected error: {exc}") from exc

        if res.status_code in (401, 403):
            raise LLMAuthenticationError(f"Gemini API authentication failed (HTTP {res.status_code}): {res.text}")
        if res.status_code == 429:
            raise LLMUnavailableError(f"Gemini API rate limit exceeded (HTTP 429): {res.text}")
        if res.status_code >= 500:
            raise LLMUnavailableError(f"Gemini API server error (HTTP {res.status_code}): {res.text}")
        if res.status_code >= 400:
            raise LLMResponseError(f"Gemini API returned HTTP {res.status_code}: {res.text}")

        data = res.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMResponseError("Gemini returned no candidates in response.")

        parts = candidates[0].get("content", {}).get("parts", [])
        content = "".join(p.get("text", "") for p in parts)

        usage_meta = data.get("usageMetadata") or {}
        p_tok = usage_meta.get("promptTokenCount", 0)
        c_tok = usage_meta.get("candidatesTokenCount", 0)
        t_tok = usage_meta.get("totalTokenCount", p_tok + c_tok)

        structured: dict[str, Any] | None = None
        if request.response_format and content:
            try:
                structured = json.loads(content)
            except Exception as parse_err:
                logger.debug("Failed to parse structured output from Gemini: %s", parse_err)

        return LLMResponse(
            content=content,
            structured_output=structured,
            usage=LLMUsage(prompt_tokens=p_tok, completion_tokens=c_tok, total_tokens=t_tok),
            provider=self.provider_name,
            model=model,
            metadata={"finish_reason": candidates[0].get("finishReason")},
        )

    async def stream(
        self, config: ModelConfiguration, request: LLMRequest
    ) -> AsyncIterator[LLMStreamChunk]:
        api_key = self._get_api_key(config)
        base = (config.api_base or "https://generativelanguage.googleapis.com").rstrip("/")
        model = config.model
        url = f"{base}/v1beta/models/{model}:streamGenerateContent?alt=sse&key={api_key}"
        payload = self._build_payload(config, request)

        try:
            async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
                async with client.stream("POST", url, json=payload) as response:
                    if response.status_code in (401, 403):
                        raise LLMAuthenticationError(f"Gemini authentication failed: {response.status_code}")
                    if response.status_code >= 400:
                        raise LLMResponseError(f"Gemini stream returned HTTP {response.status_code}")
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        chunk_json = line[6:].strip()
                        if not chunk_json:
                            continue
                        chunk_data = json.loads(chunk_json)
                        candidates = chunk_data.get("candidates") or []
                        delta = ""
                        done = False
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            delta = "".join(p.get("text", "") for p in parts)
                            if candidates[0].get("finishReason"):
                                done = True
                        yield LLMStreamChunk(delta=delta, done=done)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Gemini stream timed out: {exc}") from exc
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise LLMUnavailableError(f"Gemini stream connection failed: {exc}") from exc

