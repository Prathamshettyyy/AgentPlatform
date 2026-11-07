from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Iterable

import yaml
from pydantic import ValidationError

from app.tools.registry import ToolRegistry

from .manifests import ToolManifest


class ToolManifestError(ValueError):
    """Raised when a trusted tool manifest cannot be loaded safely."""


class DisabledToolManifestError(ToolManifestError):
    pass


class UntrustedToolEntrypointError(ToolManifestError):
    pass


class ToolLoader:
    """Discover and register tools from a local, trusted manifest directory."""

    SUPPORTED_SUFFIXES = {".yaml", ".yml", ".json"}

    def __init__(
        self,
        registry: ToolRegistry,
        manifests_dir: str | Path,
        trusted_namespaces: Iterable[str] = ("plugins.",),
    ) -> None:
        self.registry = registry
        self.manifests_dir = Path(manifests_dir).resolve()
        self.trusted_namespaces = tuple(trusted_namespaces)

    def discover(self) -> list[Path]:
        if not self.manifests_dir.is_dir():
            raise ToolManifestError(f"tool manifest directory does not exist: {self.manifests_dir}")
        return sorted(
            path
            for path in self.manifests_dir.iterdir()
            if path.is_file() and path.suffix.lower() in self.SUPPORTED_SUFFIXES
        )

    def load_all(self) -> list[str]:
        loaded: list[str] = []
        for path in self.discover():
            manifest = self.read_manifest(path)
            if not manifest.enabled:
                continue
            self.register_manifest(manifest)
            loaded.append(manifest.id)
        return loaded

    def load_manifest(self, path: str | Path) -> ToolManifest:
        manifest = self.read_manifest(Path(path))
        if not manifest.enabled:
            raise DisabledToolManifestError(f"tool manifest is disabled: {manifest.id}")
        self.register_manifest(manifest)
        return manifest

    def read_manifest(self, path: Path) -> ToolManifest:
        path = path.resolve()
        try:
            path.relative_to(self.manifests_dir)
        except ValueError as exc:
            raise ToolManifestError(f"manifest is outside the trusted directory: {path}") from exc
        if not path.is_file() or path.suffix.lower() not in self.SUPPORTED_SUFFIXES:
            raise ToolManifestError(f"unsupported tool manifest file: {path}")
        try:
            contents = path.read_text(encoding="utf-8")
            raw = json.loads(contents) if path.suffix.lower() == ".json" else yaml.safe_load(contents)
            if not isinstance(raw, dict):
                raise TypeError("manifest root must be an object")
            return ToolManifest.model_validate(raw)
        except (OSError, ValueError, TypeError, yaml.YAMLError, ValidationError) as exc:
            raise ToolManifestError(f"invalid tool manifest {path.name}: {exc}") from exc

    def register_manifest(self, manifest: ToolManifest) -> None:
        module_name, attribute_name = manifest.entrypoint.split(":", 1)
        if not any(module_name.startswith(prefix) for prefix in self.trusted_namespaces):
            raise UntrustedToolEntrypointError(
                f"untrusted tool entry point: {manifest.entrypoint}; "
                f"allowed namespaces: {self.trusted_namespaces}"
            )
        try:
            implementation = getattr(importlib.import_module(module_name), attribute_name)
        except (ImportError, AttributeError) as exc:
            raise ToolManifestError(
                f"tool implementation not found for {manifest.id}: {manifest.entrypoint}"
            ) from exc
        if not callable(implementation):
            raise ToolManifestError(f"tool implementation is not callable: {manifest.entrypoint}")
        try:
            self.registry.register(manifest.to_metadata(), implementation)
        except (TypeError, ValueError) as exc:
            raise ToolManifestError(f"could not register tool {manifest.id}: {exc}") from exc
