from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import yaml
from pydantic import ValidationError

from app.sdk.contracts import AgentMetadata
from .manifests import AgentManifest
from .registry import AgentRegistry


class ManifestError(ValueError):
    """A manifest could not be safely discovered or loaded."""


class DisabledManifestError(ManifestError):
    pass


class UntrustedEntrypointError(ManifestError):
    pass


class AgentLoader:
    """Discover trusted local manifests and register their implementations."""

    def __init__(self, registry: AgentRegistry, manifests_dir: str | Path, trusted_namespaces: tuple[str, ...] | None = None):
        self.registry = registry
        self.manifests_dir = Path(manifests_dir).resolve()
        self.trusted_namespaces = trusted_namespaces or registry.trusted_namespaces

    def discover(self) -> list[Path]:
        if not self.manifests_dir.exists():
            raise ManifestError(f"trusted manifest directory does not exist: {self.manifests_dir}")
        return sorted(
            path
            for pattern in ("*.yaml", "*.yml", "*.json")
            for path in self.manifests_dir.glob(pattern)
            if not path.name.endswith("catalog.json")
        )

    def load_all(self) -> list[AgentMetadata]:
        loaded: list[AgentMetadata] = []
        for path in self.discover():
            manifest = self.read_manifest(path)
            if not manifest.enabled:
                continue
            loaded.append(self.register_manifest(manifest, path))
        return loaded

    def read_manifest(self, path: str | Path) -> AgentManifest:
        manifest_path = Path(path).resolve()
        if manifest_path.parent != self.manifests_dir:
            raise ManifestError("manifest must be directly inside the trusted manifest directory")
        try:
            with manifest_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle) if manifest_path.suffix == ".json" else yaml.safe_load(handle)
            return AgentManifest.model_validate(raw)
        except (OSError, ValidationError, yaml.YAMLError, json.JSONDecodeError, TypeError) as exc:
            raise ManifestError(f"invalid manifest {manifest_path.name}: {exc}") from exc

    def load_manifest(self, path: str | Path) -> AgentMetadata:
        manifest = self.read_manifest(path)
        if not manifest.enabled:
            raise DisabledManifestError(f"manifest is disabled: {manifest.id}")
        return self.register_manifest(manifest, Path(path))

    def register_manifest(self, manifest: AgentManifest, source: Path | None = None) -> AgentMetadata:
        if not any(manifest.entrypoint.startswith(prefix) for prefix in self.trusted_namespaces):
            raise UntrustedEntrypointError(f"untrusted entrypoint for {manifest.id}: {manifest.entrypoint}")
        try:
            metadata = manifest.to_metadata()
            self.registry.register_entrypoint(metadata, manifest.entrypoint)
            return metadata
        except (ImportError, AttributeError, TypeError, ValueError) as exc:
            location = f" in {source.name}" if source else ""
            raise ManifestError(f"could not load manifest {manifest.id}{location}: {exc}") from exc

