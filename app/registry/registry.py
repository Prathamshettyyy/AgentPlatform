from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from typing import Any

from app.sdk.contracts import AgentMetadata
from app.runtime.errors import AgentDisabledError, AgentNotFoundError


DEFAULT_TRUSTED_NAMESPACES: tuple[str, ...] = ("plugins.",)


@dataclass(frozen=True)
class RegisteredAgent:
    metadata: AgentMetadata
    implementation: Any
    entrypoint: str | None = None


class AgentRegistry:
    DEFAULT_TRUSTED_NAMESPACES: tuple[str, ...] = DEFAULT_TRUSTED_NAMESPACES

    def __init__(self, trusted_namespaces: tuple[str, ...] | None = None):
        self._agents: dict[str, RegisteredAgent] = {}
        if trusted_namespaces is not None:
            self.trusted_namespaces = tuple(
                ns if ns.endswith(".") else f"{ns}." for ns in trusted_namespaces
            )
        else:
            env_ns = os.getenv("AGENT_PLATFORM_TRUSTED_NAMESPACES")
            if env_ns:
                delims = [",", ";"]
                raw_list = [env_ns]
                for d in delims:
                    raw_list = [item for part in raw_list for item in part.split(d)]
                parsed: list[str] = []
                for ns in raw_list:
                    cleaned = ns.strip()
                    if cleaned:
                        if not cleaned.endswith("."):
                            cleaned += "."
                        if cleaned not in parsed:
                            parsed.append(cleaned)
                for def_ns in self.DEFAULT_TRUSTED_NAMESPACES:
                    if def_ns not in parsed:
                        parsed.append(def_ns)
                self.trusted_namespaces = tuple(parsed)
            else:
                self.trusted_namespaces = self.DEFAULT_TRUSTED_NAMESPACES

    def add_trusted_namespace(self, prefix: str) -> None:
        cleaned = prefix.strip()
        if cleaned and not cleaned.endswith("."):
            cleaned += "."
        if cleaned and cleaned not in self.trusted_namespaces:
            self.trusted_namespaces = self.trusted_namespaces + (cleaned,)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def register(self, metadata: AgentMetadata, implementation: Any, entrypoint: str | None = None) -> None:
        if metadata.id in self._agents:
            raise ValueError(f"agent already registered: {metadata.id}")
        if not callable(implementation) and metadata.adapter_type == "python_callable":
            raise TypeError("python_callable agents must be callable")
        self._agents[metadata.id] = RegisteredAgent(metadata, implementation, entrypoint)

    def register_entrypoint(self, metadata: AgentMetadata, entrypoint: str) -> None:
        if not any(entrypoint.startswith(prefix) for prefix in self.trusted_namespaces):
            raise ValueError("entrypoint is outside trusted plugin namespaces")
        module_name, separator, attribute = entrypoint.partition(":")
        if not separator or not module_name or not attribute:
            raise ValueError("entrypoint must use module:attribute syntax")
        implementation = getattr(importlib.import_module(module_name), attribute, None)
        if implementation is None:
            raise ValueError(f"entrypoint not found: {entrypoint}")
        self.register(metadata, implementation, entrypoint)

    def get(self, agent_id: str, require_enabled: bool = True) -> RegisteredAgent:
        try:
            registered = self._agents[agent_id]
        except KeyError as exc:
            raise AgentNotFoundError(f"unknown agent: {agent_id}") from exc
        if require_enabled and not registered.metadata.enabled:
            raise AgentDisabledError(f"agent is disabled: {agent_id}")
        return registered

    def list_enabled(self) -> list[AgentMetadata]:
        return [a.metadata for a in self._agents.values() if a.metadata.enabled]

    def list_all(self) -> list[AgentMetadata]:
        return [a.metadata for a in self._agents.values()]

    def disable(self, agent_id: str) -> None:
        registered = self.get(agent_id, require_enabled=False)
        registered.metadata.enabled = False

