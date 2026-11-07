from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.sdk.context import AgentContext
from app.sdk.contracts import AgentMetadata, AgentRequest


metadata = AgentMetadata(
    id="ollama_text_summarizer",
    name="Ollama Text Summarizer",
    description="Summarizes supplied text or email content using a local Ollama model.",
    capabilities=["llm", "text_summarization", "email_summarization"],
)


class OllamaError(RuntimeError):
    """Base error for local Ollama invocation failures."""


class OllamaUnavailableError(OllamaError):
    pass


class OllamaResponseError(OllamaError):
    pass


class TextGenerator(Protocol):
    async def generate(self, prompt: str) -> str: ...


@dataclass(frozen=True)
class OllamaSettings:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "llama3.2"
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "OllamaSettings":
        timeout = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", str(cls.timeout_seconds)))
        return cls(
            base_url=os.getenv("OLLAMA_BASE_URL", cls.base_url).rstrip("/"),
            model=os.getenv("OLLAMA_MODEL", cls.model),
            timeout_seconds=timeout,
        )


class OllamaClient:
    def __init__(self, settings: OllamaSettings | None = None):
        self.settings = settings or OllamaSettings.from_env()

    async def generate(self, prompt: str) -> str:
        try:
            async with httpx.AsyncClient(base_url=self.settings.base_url, timeout=self.settings.timeout_seconds) as client:
                response = await client.post(
                    "/api/generate",
                    json={"model": self.settings.model, "prompt": prompt, "stream": False},
                )
                response.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise OllamaUnavailableError(
                f"Ollama is unavailable at {self.settings.base_url}. "
                "Start Ollama and ensure the configured model is available."
            ) from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ollama request failed at {self.settings.base_url}: {exc}") from exc
        try:
            payload = response.json()
            generated = payload["response"]
        except (ValueError, KeyError, TypeError) as exc:
            raise OllamaResponseError("Ollama returned an invalid response without a text 'response' field") from exc
        if not isinstance(generated, str) or not generated.strip():
            raise OllamaResponseError("Ollama returned an empty summary")
        return generated.strip()


def _content_from_inputs(inputs: dict[str, Any]) -> str:
    for key in ("text", "content"):
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    emails = inputs.get("emails")
    if isinstance(emails, list) and emails:
        lines: list[str] = []
        for index, email in enumerate(emails, start=1):
            if not isinstance(email, dict):
                raise ValueError(f"emails[{index - 1}] must be an object")
            subject = str(email.get("subject", ""))
            body = str(email.get("body", email.get("content", "")))
            lines.append(f"Email {index}\nSubject: {subject}\nBody: {body}")
        return "\n\n".join(lines)
    raise ValueError("ollama_text_summarizer requires non-empty inputs.text, inputs.content, or inputs.emails")


def _prompt(content: str) -> str:
    return "Summarize the following text clearly and concisely. Preserve important facts, actions, and dates.\n\n" + content


async def run(request: AgentRequest, context: AgentContext) -> dict[str, Any]:
    content = _content_from_inputs(request.inputs)
    settings = OllamaSettings.from_env()
    summary = await OllamaClient(settings).generate(_prompt(content))
    return {"summary": summary, "model": settings.model, "source_length": len(content)}

