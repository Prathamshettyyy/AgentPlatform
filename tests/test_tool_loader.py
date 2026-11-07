from pathlib import Path

import pytest
import yaml

from app.tools import (
    DisabledToolManifestError,
    ToolLoader,
    ToolManifestError,
    ToolRegistry,
    UntrustedToolEntrypointError,
)


def manifest(**overrides):
    value = {
        "id": "loader_tool",
        "name": "Loader Tool",
        "version": "1.0.0",
        "description": "A deterministic test tool.",
        "adapter_type": "python_callable",
        "entrypoint": "plugins.tools.echo_tool:run",
        "enabled": True,
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        "output_schema": {
            "type": "object",
            "properties": {"result": {"type": "string"}},
            "required": ["result"],
        },
        "required_permissions": [],
    }
    value.update(overrides)
    return value


def write_manifest(folder: Path, name: str, **overrides) -> Path:
    path = folder / name
    path.write_text(yaml.safe_dump(manifest(**overrides)), encoding="utf-8")
    return path


def test_loader_discovers_and_registers_trusted_tool(tmp_path):
    write_manifest(tmp_path, "loader.yaml")
    registry = ToolRegistry()

    loaded = ToolLoader(registry, tmp_path).load_all()

    assert loaded == ["loader_tool"]
    assert registry.get("loader_tool").metadata.name == "Loader Tool"


@pytest.mark.parametrize(
    ("filename", "overrides", "error_type"),
    [
        ("bad.yaml", {"input_schema": {"type": "not-a-schema"}}, ToolManifestError),
        ("unknown.yaml", {"adapter_type": "shell"}, ToolManifestError),
        ("untrusted.yaml", {"entrypoint": "os:path"}, UntrustedToolEntrypointError),
        ("missing.yaml", {"entrypoint": "plugins.tools.echo_tool:missing"}, ToolManifestError),
    ],
)
def test_loader_rejects_invalid_manifest_variants(tmp_path, filename, overrides, error_type):
    write_manifest(tmp_path, filename, **overrides)

    with pytest.raises(error_type):
        ToolLoader(ToolRegistry(), tmp_path).load_all()


def test_loader_rejects_malformed_yaml_and_duplicate_ids(tmp_path):
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("id: [", encoding="utf-8")
    with pytest.raises(ToolManifestError, match="invalid tool manifest"):
        ToolLoader(ToolRegistry(), tmp_path).load_all()

    malformed.unlink()
    write_manifest(tmp_path, "a.yaml")
    write_manifest(tmp_path, "b.yaml")
    with pytest.raises(ToolManifestError, match="already registered"):
        ToolLoader(ToolRegistry(), tmp_path).load_all()


def test_loader_skips_disabled_manifests_and_direct_load_rejects_them(tmp_path):
    path = write_manifest(tmp_path, "disabled.yaml", id="disabled_tool", enabled=False)
    loader = ToolLoader(ToolRegistry(), tmp_path)

    assert loader.load_all() == []
    with pytest.raises(DisabledToolManifestError):
        loader.load_manifest(path)
