import pytest
from pydantic import ValidationError

from app.registry import AgentLoader, AgentManifest, AgentRegistry, DisabledManifestError, ManifestError, UntrustedEntrypointError


def write_manifest(folder, name, content):
    path = folder / name
    path.write_text(content, encoding="utf-8")
    return path


def valid_manifest(agent_id="temp_agent", entrypoint="plugins.examples.manifest_echo:run"):
    return f"""id: {agent_id}
name: Temporary Agent
version: '1.0.0'
description: test manifest
capabilities: [testing]
adapter_type: python_callable
entrypoint: {entrypoint}
enabled: true
input_schema:
  type: object
output_schema:
  type: object
"""


def test_loader_discovers_and_registers_trusted_manifest(tmp_path):
    write_manifest(tmp_path, "agent.yaml", valid_manifest())
    registry = AgentRegistry()
    loaded = AgentLoader(registry, tmp_path).load_all()
    assert [item.id for item in loaded] == ["temp_agent"]
    assert registry.get("temp_agent").entrypoint == "plugins.examples.manifest_echo:run"


def test_loader_rejects_disabled_unknown_adapter_invalid_contract_and_untrusted_entrypoint(tmp_path):
    registry = AgentRegistry()
    disabled = write_manifest(tmp_path, "disabled.yaml", valid_manifest("disabled_agent").replace("enabled: true", "enabled: false"))
    with pytest.raises(DisabledManifestError): AgentLoader(registry, tmp_path).load_manifest(disabled)

    untrusted = write_manifest(tmp_path, "untrusted.yaml", valid_manifest("untrusted_agent", "os:path"))
    with pytest.raises(UntrustedEntrypointError): AgentLoader(registry, tmp_path).load_manifest(untrusted)

    unknown = write_manifest(tmp_path, "unknown.yaml", valid_manifest("unknown_adapter").replace("python_callable", "shell_command"))
    with pytest.raises(ManifestError): AgentLoader(registry, tmp_path).load_manifest(unknown)

    invalid_contract = write_manifest(tmp_path, "invalid_contract.yaml", valid_manifest("invalid_contract").replace("type: object", "type: unsupported", 1))
    with pytest.raises(ManifestError): AgentLoader(registry, tmp_path).load_manifest(invalid_contract)

    missing = write_manifest(tmp_path, "missing.yaml", valid_manifest("missing_agent", "plugins.examples.manifest_echo:nope"))
    with pytest.raises(ManifestError): AgentLoader(registry, tmp_path).load_manifest(missing)


def test_loader_rejects_duplicate_ids(tmp_path):
    write_manifest(tmp_path, "one.yaml", valid_manifest("same_agent"))
    write_manifest(tmp_path, "two.yaml", valid_manifest("same_agent"))
    with pytest.raises(ManifestError): AgentLoader(AgentRegistry(), tmp_path).load_all()

