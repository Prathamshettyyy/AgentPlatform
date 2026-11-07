from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
import yaml

from .base import LLMProvider
from .client import LLMClient
from .contracts import ModelCapabilities, ModelConfiguration, LLMError
from .providers.ollama import OllamaProvider
from .providers.gemini import GeminiProvider
from .providers.openai import OpenAIProvider
from .providers.anthropic import AnthropicProvider

logger = logging.getLogger("agent_platform.llm.registry")

_DEFAULT_REGISTRY: LLMProviderRegistry | None = None


class LLMProviderRegistry:
    """Central registry for LLM providers and logical model profiles."""

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._profiles: dict[str, ModelConfiguration] = {}

    # ------------------------------------------------------------------------
    # Provider Registration
    # ------------------------------------------------------------------------

    def register_provider(self, name: str, provider: LLMProvider) -> None:
        """Register a provider plugin (e.g. 'ollama', 'gemini', 'openai')."""
        self._providers[name.lower()] = provider
        logger.debug("Registered LLM provider: %s", name)

    def get_provider(self, name: str) -> LLMProvider:
        """Retrieve a registered provider by name."""
        provider = self._providers.get(name.lower())
        if not provider:
            raise LLMError(
                f"Unknown LLM provider '{name}'. Available providers: {list(self._providers.keys())}"
            )
        return provider

    def list_providers(self) -> list[str]:
        return list(self._providers.keys())

    # ------------------------------------------------------------------------
    # Profile Registration & Configuration
    # ------------------------------------------------------------------------

    def register_profile(self, name: str, config: ModelConfiguration) -> None:
        """Register a logical model profile (e.g. 'document_analysis')."""
        self._profiles[name] = config
        logger.debug("Registered model profile '%s' -> %s/%s", name, config.provider, config.model)

    def get_profile(self, name: str = "default") -> ModelConfiguration:
        """Retrieve configuration for a logical profile, falling back to 'default' if not found."""
        if name in self._profiles:
            return self._profiles[name]
        if "default" in self._profiles:
            logger.warning("Profile '%s' not found; falling back to 'default' profile.", name)
            return self._profiles["default"]
        raise LLMError(f"Model profile '{name}' not found and no 'default' profile is configured.")

    def list_profiles(self) -> dict[str, dict[str, Any]]:
        """Return safe representation of all registered profiles without secrets."""
        return {name: cfg.safe_repr() for name, cfg in self._profiles.items()}

    def get(self, name: str = "default") -> LLMClient:
        """Get an LLMClient configured for the specified logical model profile."""
        profile = self.get_profile(name)
        return LLMClient(config=profile, registry=self)

    # ------------------------------------------------------------------------
    # Loading Configuration from YAML / Dict
    # ------------------------------------------------------------------------

    def load_profiles_from_dict(self, data: dict[str, Any]) -> None:
        """Load profile definitions from a dictionary."""
        profiles_section = data.get("llm_profiles") or data
        for name, entry in profiles_section.items():
            if not isinstance(entry, dict) or "provider" not in entry or "model" not in entry:
                continue

            # Parse optional capabilities
            caps: ModelCapabilities | None = None
            if "capabilities" in entry and isinstance(entry["capabilities"], dict):
                caps = ModelCapabilities(**entry["capabilities"])

            # Parse optional fallback models
            fallbacks: list[ModelConfiguration] = []
            fallback_sec = entry.get("fallback")
            if isinstance(fallback_sec, dict) and fallback_sec.get("enabled", True):
                for fb_item in fallback_sec.get("models", []):
                    fb_caps = ModelCapabilities(**fb_item["capabilities"]) if "capabilities" in fb_item else None
                    fallbacks.append(
                        ModelConfiguration(
                            provider=fb_item["provider"],
                            model=fb_item["model"],
                            api_base=fb_item.get("api_base"),
                            api_key_env=fb_item.get("api_key_env"),
                            temperature=fb_item.get("temperature"),
                            timeout_seconds=fb_item.get("timeout_seconds", 60.0),
                            capabilities=fb_caps,
                        )
                    )

            cfg = ModelConfiguration(
                provider=entry["provider"],
                model=entry["model"],
                api_base=entry.get("api_base"),
                api_key_env=entry.get("api_key_env"),
                temperature=entry.get("temperature"),
                top_p=entry.get("top_p"),
                max_tokens=entry.get("max_tokens"),
                timeout_seconds=float(entry.get("timeout_seconds", 60.0)),
                max_retries=int(entry.get("max_retries", 2)),
                retry_backoff_seconds=float(entry.get("retry_backoff_seconds", 1.0)),
                capabilities=caps,
                fallback_models=fallbacks,
            )
            self.register_profile(name, cfg)

    def load_profiles_from_file(self, file_path: str | Path) -> bool:
        """Load model profiles from a YAML or JSON file."""
        p = Path(file_path).resolve()
        if not p.is_file():
            return False
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                self.load_profiles_from_dict(data)
                logger.info("Loaded %d LLM profiles from %s", len(self._profiles), p)
                return True
        except Exception as exc:
            logger.error("Failed to load LLM profiles from %s: %s", p, exc)
        return False


def create_default_registry() -> LLMProviderRegistry:
    """Create and initialize an LLMProviderRegistry with default providers and profiles."""
    reg = LLMProviderRegistry()

    # 1. Register Built-in Providers
    reg.register_provider("ollama", OllamaProvider())
    reg.register_provider("gemini", GeminiProvider())
    reg.register_provider("openai", OpenAIProvider())
    reg.register_provider("anthropic", AnthropicProvider())

    # 2. Check for external configuration file
    config_file = os.getenv("LLM_PROFILES_FILE")
    loaded = False
    if config_file:
        loaded = reg.load_profiles_from_file(config_file)
    if not loaded:
        # Check standard config directory
        standard_path = Path("config/llm_profiles.yaml")
        if standard_path.is_file():
            loaded = reg.load_profiles_from_file(standard_path)

    # 3. Default fallback profiles if no config file present
    if not loaded or "default" not in reg._profiles:
        default_ollama_model = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")
        default_ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

        base_ollama = ModelConfiguration(
            provider="ollama",
            model=default_ollama_model,
            api_base=default_ollama_url,
            timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60.0")),
            capabilities=ModelCapabilities(
                text=True,
                structured_output=True,
                streaming=True,
                tool_calling=True,
            ),
            fallback_models=[
                ModelConfiguration(
                    provider="ollama",
                    model="llama3.2",
                    api_base=default_ollama_url,
                    timeout_seconds=60.0,
                )
            ],
        )

        reg.register_profile("default", base_ollama)
        reg.register_profile("fast", base_ollama)
        reg.register_profile("reasoning", base_ollama)
        reg.register_profile("vision", base_ollama)

    return reg


def get_default_llm_registry() -> LLMProviderRegistry:
    """Retrieve or initialize the global singleton LLMProviderRegistry."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = create_default_registry()
    return _DEFAULT_REGISTRY


def get_llm(profile_name: str = "default") -> LLMClient:
    """Convenience accessor to get an LLMClient for a logical profile."""
    return get_default_llm_registry().get(profile_name)

