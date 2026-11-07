"""Tests for generic, configuration-driven plugin and workflow discovery in Agent Platform.

Phase 1.1 verification:
1. Loading manifests from multiple configured directories.
2. Loading workflows from multiple configured directories.
3. Loading an external application plugin without hardcoding its package name.
4. Invalid entrypoint rejection.
5. Duplicate agent ID handling.
6. Missing manifest directory handling.
7. Agent Platform startup without importing GeoStrata.
8. Existing GeoStrata agent registration when configured.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import pytest
import yaml

from app.api.app import create_app
from app.registry import AgentLoader, AgentRegistry, UntrustedEntrypointError, ManifestError
from app.storage.repository import ExecutionRepository


def _make_manifest(agent_id: str, entrypoint: str, name: str = "Test Agent") -> str:
    return f"""id: {agent_id}
name: {name}
version: '1.0.0'
description: Generic discovery test agent
capabilities: [testing]
adapter_type: python_callable
entrypoint: {entrypoint}
enabled: true
input_schema:
  type: object
output_schema:
  type: object
"""


def _make_workflow(workflow_id: str, agent_id: str) -> str:
    return f"""id: {workflow_id}
name: Test Workflow {workflow_id}
version: '1.0.0'
description: Generic discovery test workflow
nodes:
  - id: step_1
    name: Step 1
    type: agent
    agent_id: {agent_id}
edges: []
"""


# ----------------------------------------------------------------------------
# 1. Loading manifests from multiple configured directories
# ----------------------------------------------------------------------------
def test_loading_manifests_from_multiple_configured_directories(tmp_path, monkeypatch):
    dir_a = tmp_path / "app_a_manifests"
    dir_b = tmp_path / "app_b_manifests"
    dir_a.mkdir()
    dir_b.mkdir()

    (dir_a / "agent_a.yaml").write_text(_make_manifest("agent_a", "plugins.examples.manifest_echo:run"), encoding="utf-8")
    (dir_b / "agent_b.yaml").write_text(_make_manifest("agent_b", "app_b.plugins.adapter:run"), encoding="utf-8")

    # Mock app_b module so importlib succeeds
    import types
    app_b_mod = types.ModuleType("app_b.plugins.adapter")
    app_b_mod.run = lambda req, ctx: {"status": "ok"}
    monkeypatch.setitem(sys.modules, "app_b", types.ModuleType("app_b"))
    monkeypatch.setitem(sys.modules, "app_b.plugins", types.ModuleType("app_b.plugins"))
    monkeypatch.setitem(sys.modules, "app_b.plugins.adapter", app_b_mod)

    monkeypatch.setenv("AGENT_PLATFORM_PLUGIN_DIRS", f"{dir_a};{dir_b}")
    monkeypatch.setenv("AGENT_PLATFORM_TRUSTED_NAMESPACES", "plugins.,app_b.plugins.")

    repo = ExecutionRepository(":memory:")
    app = create_app(repo)

    registry = app.state.registry
    assert "agent_a" in registry
    assert "agent_b" in registry
    assert registry.get("agent_a").entrypoint == "plugins.examples.manifest_echo:run"
    assert registry.get("agent_b").entrypoint == "app_b.plugins.adapter:run"


# ----------------------------------------------------------------------------
# 2. Loading workflows from multiple configured directories
# ----------------------------------------------------------------------------
def test_loading_workflows_from_multiple_configured_directories(tmp_path, monkeypatch):
    wf_dir_1 = tmp_path / "wf_dir_1"
    wf_dir_2 = tmp_path / "wf_dir_2"
    wf_dir_1.mkdir()
    wf_dir_2.mkdir()

    (wf_dir_1 / "workflow_one.yaml").write_text(_make_workflow("wf_one", "echo_agent"), encoding="utf-8")
    (wf_dir_2 / "workflow_two.yaml").write_text(_make_workflow("wf_two", "echo_agent"), encoding="utf-8")

    monkeypatch.setenv("AGENT_PLATFORM_WORKFLOW_DIRS", f"{wf_dir_1};{wf_dir_2}")

    repo = ExecutionRepository(":memory:")
    app = create_app(repo)

    workflows = app.state.workflows
    assert "wf_one" in workflows
    assert "wf_two" in workflows


# ----------------------------------------------------------------------------
# 3. Loading external application plugin without hardcoding its package name
# ----------------------------------------------------------------------------
def test_external_application_plugin_without_hardcoded_package(tmp_path, monkeypatch):
    """Verify an entirely new application (e.g. legal_ai) can register via configuration alone."""
    legal_manifests = tmp_path / "legal_manifests"
    legal_manifests.mkdir()

    (legal_manifests / "contract_analyzer.yaml").write_text(
        _make_manifest("contract_analyzer", "legal_ai.plugins.analyzer:run", "Contract Analyzer"),
        encoding="utf-8",
    )

    import types
    legal_mod = types.ModuleType("legal_ai.plugins.analyzer")
    legal_mod.run = lambda req, ctx: {"risk": "low"}
    monkeypatch.setitem(sys.modules, "legal_ai", types.ModuleType("legal_ai"))
    monkeypatch.setitem(sys.modules, "legal_ai.plugins", types.ModuleType("legal_ai.plugins"))
    monkeypatch.setitem(sys.modules, "legal_ai.plugins.analyzer", legal_mod)

    # Configure external application via environment variables
    monkeypatch.setenv("AGENT_PLATFORM_PLUGIN_DIRS", str(legal_manifests))
    monkeypatch.setenv("AGENT_PLATFORM_TRUSTED_NAMESPACES", "plugins.,legal_ai.plugins.")

    reg = AgentRegistry()
    assert "legal_ai.plugins." in reg.trusted_namespaces

    loader = AgentLoader(reg, legal_manifests)
    loaded = loader.load_all()

    assert len(loaded) == 1
    assert loaded[0].id == "contract_analyzer"
    assert reg.get("contract_analyzer").entrypoint == "legal_ai.plugins.analyzer:run"


# ----------------------------------------------------------------------------
# 4. Invalid entrypoint rejection
# ----------------------------------------------------------------------------
def test_invalid_entrypoint_rejection(tmp_path):
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()

    bad_manifest = manifests_dir / "malicious.yaml"
    bad_manifest.write_text(_make_manifest("bad_agent", "os:system"), encoding="utf-8")

    registry = AgentRegistry(trusted_namespaces=("plugins.",))
    loader = AgentLoader(registry, manifests_dir)

    with pytest.raises(UntrustedEntrypointError):
        loader.load_manifest(bad_manifest)


# ----------------------------------------------------------------------------
# 5. Duplicate agent ID handling
# ----------------------------------------------------------------------------
def test_duplicate_agent_id_handling_within_directory(tmp_path):
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir()

    (manifests_dir / "agent1.yaml").write_text(_make_manifest("duplicate_agent", "plugins.examples.manifest_echo:run"), encoding="utf-8")
    (manifests_dir / "agent2.yaml").write_text(_make_manifest("duplicate_agent", "plugins.examples.manifest_echo:run"), encoding="utf-8")

    registry = AgentRegistry()
    loader = AgentLoader(registry, manifests_dir)

    # load_all() raises ManifestError on duplicate in single directory load
    with pytest.raises(ManifestError):
        loader.load_all()


def test_duplicate_agent_id_handling_across_directories(tmp_path, monkeypatch):
    """When two configured directories define the same agent ID, create_app keeps first and skips duplicate."""
    dir_1 = tmp_path / "dir_1"
    dir_2 = tmp_path / "dir_2"
    dir_1.mkdir()
    dir_2.mkdir()

    (dir_1 / "agent.yaml").write_text(_make_manifest("shared_agent", "plugins.examples.manifest_echo:run", "First Definition"), encoding="utf-8")
    (dir_2 / "agent.yaml").write_text(_make_manifest("shared_agent", "plugins.examples.manifest_echo:run", "Second Definition"), encoding="utf-8")

    monkeypatch.setenv("AGENT_PLATFORM_PLUGIN_DIRS", f"{dir_1};{dir_2}")
    repo = ExecutionRepository(":memory:")
    import app.api.app as api_module
    create_fn = getattr(api_module, "create_app_unpatched", create_app)
    app = create_fn(repo)

    registry = app.state.registry
    assert "shared_agent" in registry
    assert registry.get("shared_agent").metadata.name == "First Definition"


# ----------------------------------------------------------------------------
# 6. Missing manifest directory handling
# ----------------------------------------------------------------------------
def test_missing_manifest_directory_handling(tmp_path, monkeypatch):
    non_existent = tmp_path / "non_existent_manifests_dir"
    valid_dir = tmp_path / "valid_manifests"
    valid_dir.mkdir()
    (valid_dir / "good_agent.yaml").write_text(_make_manifest("good_agent", "plugins.examples.manifest_echo:run"), encoding="utf-8")

    monkeypatch.setenv("AGENT_PLATFORM_PLUGIN_DIRS", f"{non_existent};{valid_dir}")

    repo = ExecutionRepository(":memory:")
    import app.api.app as api_module
    create_fn = getattr(api_module, "create_app_unpatched", create_app)
    app = create_fn(repo)

    registry = app.state.registry
    assert "good_agent" in registry


# ----------------------------------------------------------------------------
# 7. Agent Platform startup without importing GeoStrata
# ----------------------------------------------------------------------------
def test_agent_platform_startup_without_importing_geostrata():
    """Verify clean Agent Platform initialization does not import geostrata domain modules in a fresh process."""
    import subprocess
    clean_env = dict(os.environ)
    clean_env.pop("AGENT_PLATFORM_PLUGIN_DIRS", None)
    clean_env.pop("AGENT_PLATFORM_WORKFLOW_DIRS", None)
    clean_env.pop("AGENT_PLATFORM_MANIFEST_DIRS", None)
    clean_env.pop("AGENT_PLATFORM_TRUSTED_NAMESPACES", None)
    clean_env["AGENT_PLATFORM_API_TOKEN"] = clean_env.get("AGENT_PLATFORM_API_TOKEN", "test-token")
    cmd = [
        sys.executable,
        "-c",
        (
            "import sys, os; "
            "from app.api.app import create_app; "
            "from app.storage.repository import ExecutionRepository; "
            "app = create_app(ExecutionRepository(':memory:')); "
            "leaked = [m for m in sys.modules if m.startswith('geostrata.backend')]; "
            "assert len(leaked) == 0, f'GeoStrata modules leaked into Agent Platform: {leaked}'; "
            "print('CLEAN_STARTUP')"
        ),
    ]
    res = subprocess.run(cmd, env=clean_env, capture_output=True, text=True)
    assert res.returncode == 0, f"Clean startup failed:\nstdout: {res.stdout}\nstderr: {res.stderr}"
    assert "CLEAN_STARTUP" in res.stdout


# ----------------------------------------------------------------------------
# 8. Existing GeoStrata agent registration when configured
# ----------------------------------------------------------------------------
def test_geostrata_agents_and_workflows_registered_when_configured(monkeypatch):
    """When configured with GeoStrata paths, all 4 GeoStrata agents and workflow register cleanly."""
    workspace_root = Path(__file__).resolve().parents[1]
    geostrata_manifests = workspace_root / "geostrata" / "plugins" / "manifests"
    geostrata_workflows = workspace_root / "geostrata" / "workflow_definitions"

    assert geostrata_manifests.is_dir(), f"Manifests dir not found: {geostrata_manifests}"
    assert geostrata_workflows.is_dir(), f"Workflows dir not found: {geostrata_workflows}"

    monkeypatch.setenv("AGENT_PLATFORM_PLUGIN_DIRS", str(geostrata_manifests))
    monkeypatch.setenv("AGENT_PLATFORM_WORKFLOW_DIRS", str(geostrata_workflows))
    monkeypatch.setenv("AGENT_PLATFORM_TRUSTED_NAMESPACES", "plugins.,geostrata.plugins.")

    repo = ExecutionRepository(":memory:")
    app = create_app(repo)

    registry = app.state.registry
    expected_agents = [
        "geotechnical_analysis",
        "foundation_research",
        "requirement_agent",
        "project_document_validator",
    ]
    for agent_id in expected_agents:
        assert agent_id in registry, f"Expected agent '{agent_id}' to be registered"
        reg_agent = registry.get(agent_id)
        assert reg_agent.entrypoint.startswith("geostrata.plugins."), f"Expected geostrata entrypoint, got: {reg_agent.entrypoint}"

    workflows = app.state.workflows
    assert "geotechnical_foundation_investigation" in workflows
