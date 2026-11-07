from __future__ import annotations

import argparse
import ast
import asyncio
import copy
import json
import keyword
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import quote

import httpx
import yaml
from pydantic import ValidationError

from app.registry import AgentLoader, AgentManifest, AgentRegistry
from app.registry.external_connector import (
    default_agent_id,
    default_agent_name,
    discover_python_entrypoints,
    evict_external_agent_cache,
    infer_json_schema,
    inspect_dependencies,
    project_plugin_namespace,
    render_adapter_source,
    resolve_python_entrypoint,
    source_fingerprint,
)
from app.runtime.runner import AgentRunner
from app.sdk.contracts import AgentRequest
from app.storage.repository import ExecutionRepository
from app.tools import ToolManifest
from app.tools.runner import redact_sensitive
from app.workflows.builder import WorkflowBuilder
from app.workflows.composer import Decision, MappingError, plan_agent_mappings
from app.workflows.models import WorkflowDefinition
from app.workflows.validator import WorkflowValidationError, validate_workflow


class CliError(RuntimeError):
    pass


_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _bump_patch(version: str) -> str:
    match = _SEMVER.fullmatch(version)
    if not match:
        raise CliError(f"cannot increment non-semantic workflow version {version!r}; pass --version explicitly")
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


_SCAFFOLD_ID = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_WORKFLOW_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_CONNECTED_AGENT_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


def _scaffold_id(value: str) -> str:
    if not _SCAFFOLD_ID.fullmatch(value) or keyword.iskeyword(value):
        raise CliError("scaffold ID must be a lowercase Python identifier (letters, digits, underscores only)")
    return value


def _scaffold_text(value: str, label: str) -> str:
    if not value.strip() or len(value) > 200 or any(ord(char) < 32 and char not in "\t" for char in value):
        raise CliError(f"{label} must be non-empty, at most 200 characters, and contain no control characters")
    return value.strip()


def _connected_agent_id(value: str) -> str:
    if not _CONNECTED_AGENT_ID.fullmatch(value) or keyword.iskeyword(value):
        raise CliError("agent ID must start with a lowercase letter and contain only lowercase letters, digits, hyphens, or underscores")
    return value


def _connected_package_name(agent_id: str) -> str:
    return "connected_" + agent_id.replace("-", "_")


def _connected_manifest_path(root: Path, agent_id: str) -> Path:
    return root / "plugins" / "manifests" / f"{agent_id}.yaml"


def _connected_adapter_dir(root: Path, agent_id: str) -> Path:
    return root / "plugins" / "examples" / _connected_package_name(agent_id)


def _write_connected_files(root: Path, files: dict[Path, str]) -> list[Path]:
    resolved_root = root.resolve()
    resolved = [path.resolve() for path in files]
    if any(resolved_root not in path.parents for path in resolved):
        raise CliError("connected-agent output escaped the project root")
    existing = [path for path in resolved if path.exists()]
    if existing:
        raise CliError("connection target already exists: " + ", ".join(str(path) for path in existing))
    created_files: list[Path] = []
    created_dirs: list[Path] = []
    try:
        for path in resolved:
            missing: list[Path] = []
            parent = path.parent
            while not parent.exists() and resolved_root in parent.parents:
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                created_dirs.append(directory)
        for path, content in zip(resolved, files.values()):
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            created_files.append(path)
    except OSError as exc:
        for path in reversed(created_files):
            path.unlink(missing_ok=True)
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise CliError(f"could not create connected-agent files: {exc}") from exc
    return created_files


def _remove_adapter_dir(adapter_dir: Path) -> None:
    """Remove only the bytecode cache Python generated, then the directory if empty."""
    cache_dir = adapter_dir / "__pycache__"
    if cache_dir.is_dir():
        for pyc in cache_dir.glob("*.pyc"):
            pyc.unlink(missing_ok=True)
        try:
            cache_dir.rmdir()
        except OSError:
            pass
    try:
        adapter_dir.rmdir()
    except OSError:
        pass


def _remove_connected_files(root: Path, agent_id: str) -> list[str]:
    manifest_path = _connected_manifest_path(root, agent_id)
    adapter_dir = _connected_adapter_dir(root, agent_id)
    adapter_path = adapter_dir / "adapter.py"
    init_path = adapter_dir / "__init__.py"
    if not manifest_path.is_file():
        raise CliError(f"connected agent is not registered: {agent_id}")
    try:
        manifest = AgentManifest.model_validate(_read_document(manifest_path))
    except (ValidationError, CliError) as exc:
        raise CliError(f"refusing to disconnect an invalid or unrelated manifest: {manifest_path}") from exc
    expected_entrypoint = f"plugins.examples.{_connected_package_name(agent_id)}.adapter:run"
    if manifest.id != agent_id or manifest.entrypoint != expected_entrypoint or not adapter_path.is_file():
        raise CliError(f"refusing to remove registration not created by agents connect: {agent_id}")
    source = adapter_path.read_text(encoding="utf-8")
    if not source.startswith("# Generated by agent_platform agents connect. Do not edit by hand.\n"):
        raise CliError(f"refusing to remove adapter without the connector marker: {adapter_path}")
    removed: list[str] = []
    manifest_path.unlink()
    removed.append(str(manifest_path))
    adapter_path.unlink()
    removed.append(str(adapter_path))
    if init_path.is_file() and init_path.read_text(encoding="utf-8").startswith("# Generated by agent_platform agents connect. Do not edit by hand."):
        init_path.unlink()
        removed.append(str(init_path))
    _remove_adapter_dir(adapter_dir)
    return removed


def _validate_agent_id(project_root: str | Path, agent_id: str) -> dict[str, Any]:
    valid_id = _connected_agent_id(agent_id)
    root = Path(project_root).expanduser().resolve()
    manifest_path = _connected_manifest_path(root, valid_id)
    if not manifest_path.is_file():
        raise CliError(f"agent manifest not found for ID: {valid_id}")
    try:
        with project_plugin_namespace(root):
            registry = AgentRegistry()
            metadata = AgentLoader(registry, root / "plugins" / "manifests").load_manifest(manifest_path)
        return metadata.model_dump(mode="json")
    except (ValueError, OSError, ImportError) as exc:
        raise CliError(f"agent registration is invalid: {exc}") from exc


def _same_connection(root: Path, agent_id: str, adapter_text: str, init_text: str) -> bool:
    manifest_path = _connected_manifest_path(root, agent_id)
    adapter_dir = _connected_adapter_dir(root, agent_id)
    adapter_path = adapter_dir / "adapter.py"
    init_path = adapter_dir / "__init__.py"
    if not (manifest_path.is_file() and adapter_path.is_file() and init_path.is_file()):
        return False
    try:
        existing_manifest = AgentManifest.model_validate(_read_document(manifest_path))
    except (CliError, ValidationError):
        return False
    expected_entrypoint = f"plugins.examples.{_connected_package_name(agent_id)}.adapter:run"
    return (
        existing_manifest.id == agent_id
        and existing_manifest.entrypoint == expected_entrypoint
        and existing_manifest.enabled
        and adapter_path.read_text(encoding="utf-8") == adapter_text
        and init_path.read_text(encoding="utf-8") == init_text
    )


_EXAMPLE_NAMES = ("example_input", "sample_input", "test_input", "input", "example", "sample")
_EXAMPLE_SUFFIXES = (".json", ".yaml", ".yml")
_EXAMPLE_DIRS = ("", "examples", "example", "samples", "sample")
_MAX_EXAMPLE_BYTES = 1_000_000
_DEFAULT_VERIFICATION_INPUT = {
    "text": "Agent platform connection test. This sentence is supplied to verify delegated text analysis.",
}


def _usable_example(external_root: Path, path: Path) -> dict[str, Any] | None:
    """Read an example file only if it is a small regular file inside the project."""
    try:
        resolved = path.resolve(strict=True)
        if path.is_symlink() or external_root not in resolved.parents or not resolved.is_file():
            return None
        if resolved.stat().st_size > _MAX_EXAMPLE_BYTES:
            return None
        return _read_document(resolved)
    except (OSError, CliError):
        return None


def _detect_example_inputs(external_root: Path) -> tuple[list[Path], list[Path]]:
    """Return (named examples in priority order, other ``*input*`` files).

    Only JSON/YAML files are considered and nothing is imported or executed.
    """
    named: list[Path] = []
    for directory in _EXAMPLE_DIRS:
        base = external_root / directory if directory else external_root
        for stem in _EXAMPLE_NAMES:
            for suffix in _EXAMPLE_SUFFIXES:
                candidate = base / f"{stem}{suffix}"
                if candidate.is_file() and _usable_example(external_root, candidate) is not None:
                    named.append(candidate)
    others: list[Path] = []
    for directory in _EXAMPLE_DIRS:
        base = external_root / directory if directory else external_root
        if not base.is_dir():
            continue
        for candidate in sorted(base.iterdir(), key=lambda item: item.name.casefold()):
            stem = candidate.stem.lower()
            if (
                candidate.suffix.lower() in _EXAMPLE_SUFFIXES
                and ("input" in stem or stem.endswith(("_example", "_sample")))
                and candidate not in named
                and _usable_example(external_root, candidate) is not None
            ):
                others.append(candidate)
    return named, others


def _resolve_verification_input(
    external_root: Path,
    test_input_path: str | Path | None,
    input_fn,
    is_interactive: bool,
    error_output: TextIO | None,
) -> tuple[dict[str, Any], str]:
    """Choose the sample payload used to verify a connection.

    Priority: explicit --test-input, a detected example file, an interactively
    entered sample, then the built-in text sample (non-interactive default).
    """
    if test_input_path:
        value = _read_document(test_input_path)
        return value, f"file {Path(test_input_path).resolve()}"
    named, others = _detect_example_inputs(external_root)
    if named:
        chosen = named[0]
        return _read_document(chosen), f"detected example file {chosen}"
    if len(others) == 1:
        return _read_document(others[0]), f"detected example file {others[0]}"
    can_ask = is_interactive and input_fn is not None
    if len(others) > 1:
        listing = ", ".join(str(item.relative_to(external_root)) for item in others)
        if not can_ask:
            raise CliError(f"multiple example input files were found ({listing}); choose one with --test-input")
        print("Multiple example input files were found:", file=error_output or sys.stderr)
        for index, item in enumerate(others, 1):
            print(f"  {index}. {item.relative_to(external_root)}", file=error_output or sys.stderr)
        answer = input_fn("Number of the file to use for verification: ").strip()
        if not answer.isdigit() or not 1 <= int(answer) <= len(others):
            raise CliError("invalid example input selection; choose one with --test-input")
        chosen = others[int(answer) - 1]
        return _read_document(chosen), f"selected example file {chosen}"
    if can_ask:
        raw = input_fn(
            "No example input file was found. Enter sample input as a JSON object "
            "(press Enter to use a default {\"text\": ...} sample): "
        ).strip()
        if raw:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise CliError("sample input must be a JSON object") from exc
            if not isinstance(value, dict):
                raise CliError("sample input must be a JSON object")
            return value, "interactive sample"
    return dict(_DEFAULT_VERIFICATION_INPUT), "built-in default text sample"


def _connection_catalog_path(root: Path) -> Path:
    return root / "plugins" / "connection_catalog.json"


def _extract_adapter_connection(adapter_path: Path) -> dict[str, Any] | None:
    if not adapter_path.is_file():
        return None
    try:
        source = adapter_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(adapter_path))
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_CONNECTION":
                        value = ast.literal_eval(node.value)
                        if isinstance(value, dict):
                            return value
    except Exception:
        pass
    try:
        source = adapter_path.read_text(encoding="utf-8")
        proj_match = re.search(r"['\"]project_path['\"]\s*:\s*['\"]([^'\"]+)['\"]", source)
        rel_match = re.search(r"['\"]relative_file['\"]\s*:\s*['\"]([^'\"]+)['\"]", source)
        sym_match = re.search(r"['\"]symbol['\"]\s*:\s*['\"]([^'\"]+)['\"]", source)
        if proj_match:
            return {
                "project_path": proj_match.group(1),
                "relative_file": rel_match.group(1) if rel_match else "",
                "symbol": sym_match.group(1) if sym_match else "",
            }
    except Exception:
        pass
    return None


def _extract_project_path(adapter_path: Path) -> str | None:
    conn = _extract_adapter_connection(adapter_path)
    if conn and isinstance(conn.get("project_path"), str):
        return conn["project_path"]
    return None


def _read_catalog_file(root: Path) -> dict[str, dict[str, Any]]:
    path = _connection_catalog_path(root)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        catalog: dict[str, dict[str, Any]] = {}
        for key, item in raw.items():
            if not isinstance(item, dict):
                continue
            aid = str(item.get("id") or key).strip()
            proj = str(item.get("project_path") or "").strip()
            ep = str(item.get("entry_point") or "").strip()
            disp = str(item.get("name") or aid).strip()
            if aid and proj:
                entry: dict[str, Any] = {
                    "id": aid,
                    "name": disp,
                    "project_path": proj,
                    "entry_point": ep,
                }
                if item.get("test_input"):
                    entry["test_input"] = str(item["test_input"])
                catalog[aid] = entry
        return catalog
    except Exception:
        return {}


def _write_catalog_file(root: Path, catalog: dict[str, dict[str, Any]]) -> None:
    path = _connection_catalog_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)


def _save_catalog_entry(
    root: Path,
    *,
    agent_id: str,
    name: str,
    project_path: str,
    entry_point: str,
    test_input: str | None = None,
) -> dict[str, Any]:
    catalog = _read_catalog_file(root)
    existing = catalog.get(agent_id, {})
    resolved_test_input = test_input
    if resolved_test_input is None and existing.get("project_path") == str(project_path):
        resolved_test_input = existing.get("test_input")
    entry: dict[str, Any] = {
        "id": agent_id,
        "name": name,
        "project_path": str(project_path),
        "entry_point": entry_point,
    }
    if resolved_test_input:
        entry["test_input"] = str(resolved_test_input)
    catalog[agent_id] = entry
    _write_catalog_file(root, catalog)
    return entry


def _remove_catalog_entry(root: Path, agent_id: str) -> dict[str, Any] | None:
    catalog = _read_catalog_file(root)
    removed = catalog.pop(agent_id, None)
    if removed is not None:
        _write_catalog_file(root, catalog)
    return removed


def _is_agent_registered(root: Path, agent_id: str) -> AgentManifest | None:
    manifests_dir = root / "plugins" / "manifests"
    if not manifests_dir.is_dir():
        return None
    for suffix in (".yaml", ".yml", ".json"):
        candidate = manifests_dir / f"{agent_id}{suffix}"
        if candidate.is_file():
            try:
                manifest = AgentManifest.model_validate(_read_document(candidate))
                if manifest.id == agent_id and manifest.enabled:
                    return manifest
            except Exception:
                continue
    return None


def _discover_active_connected_agents(root: Path) -> dict[str, dict[str, Any]]:
    discovered: dict[str, dict[str, Any]] = {}
    manifests_dir = root / "plugins" / "manifests"
    if not manifests_dir.is_dir():
        return discovered
    for path in (
        sorted(manifests_dir.glob("*.yaml"))
        + sorted(manifests_dir.glob("*.yml"))
        + sorted(manifests_dir.glob("*.json"))
    ):
        try:
            manifest = AgentManifest.model_validate(_read_document(path))
        except Exception:
            continue
        if not manifest.enabled or manifest.id != path.stem:
            continue
        adapter_path = _connected_adapter_dir(root, manifest.id) / "adapter.py"
        conn = _extract_adapter_connection(adapter_path)
        if not conn:
            continue
        proj = str(conn.get("project_path") or "").strip()
        rel = str(conn.get("relative_file") or "").strip()
        sym = str(conn.get("symbol") or "").strip()
        ep = f"{rel}:{sym}" if (rel and sym) else ""
        if proj:
            discovered[manifest.id] = {
                "id": manifest.id,
                "name": manifest.name,
                "project_path": proj,
                "entry_point": ep,
            }
    return discovered


def _load_connection_catalog(root: Path) -> dict[str, dict[str, Any]]:
    catalog = _read_catalog_file(root)
    for aid, active_entry in _discover_active_connected_agents(root).items():
        if aid in catalog:
            catalog[aid] = {**catalog[aid], **active_entry}
        else:
            catalog[aid] = active_entry
    return catalog


def _list_disconnected_agents(root: Path) -> list[dict[str, Any]]:
    catalog = _load_connection_catalog(root)
    return [
        entry
        for aid, entry in sorted(catalog.items())
        if _is_agent_registered(root, aid) is None
    ]


def _find_catalog_or_registered_agent(
    root: Path, query: str
) -> tuple[dict[str, Any] | None, AgentManifest | None]:
    q = query.strip()
    if not q:
        return None, None
    q_fold = q.casefold()
    q_slug = re.sub(r"[^a-z0-9]+", "_", q_fold).strip("_")
    catalog = _load_connection_catalog(root)

    if q in catalog:
        return catalog[q], _is_agent_registered(root, q)

    matches: list[dict[str, Any]] = []
    for aid, entry in sorted(catalog.items()):
        name_fold = str(entry.get("name") or "").strip().casefold()
        name_no_suffix = name_fold[:-len(" agent")].strip() if name_fold.endswith(" agent") else name_fold
        if (
            aid.casefold() == q_fold
            or name_fold == q_fold
            or (name_no_suffix and name_no_suffix == q_fold)
            or f"external_{q_slug}" == aid.casefold()
        ):
            matches.append(entry)
    if len(matches) == 1:
        matched = matches[0]
        return matched, _is_agent_registered(root, matched["id"])

    manifests_dir = root / "plugins" / "manifests"
    if manifests_dir.is_dir():
        for path in (
            sorted(manifests_dir.glob("*.yaml"))
            + sorted(manifests_dir.glob("*.yml"))
            + sorted(manifests_dir.glob("*.json"))
        ):
            try:
                manifest = AgentManifest.model_validate(_read_document(path))
            except Exception:
                continue
            if not manifest.enabled or manifest.id != path.stem:
                continue
            if manifest.id.casefold() == q_fold or manifest.name.strip().casefold() == q_fold:
                return catalog.get(manifest.id), manifest

    return None, None


def _looks_like_filesystem_path(value: str) -> bool:
    return (
        any(sep in value for sep in ("/", "\\"))
        or value.startswith((".", "~"))
        or (len(value) >= 2 and value[1] == ":")
    )


def _connect_agent(
    project_root: str | Path,
    external_path: str | Path | None = None,
    agent_id: str | None = None,
    name: str | None = None,
    entry_point: str | None = None,
    test_input_path: str | Path | None = None,
    *,
    trust_approved: bool = False,
    db_path: str | Path | None = None,
    explicit_path: bool = False,
    input_fn=None,
    is_interactive: bool = False,
    error_output: TextIO | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise CliError(f"agent_platform project root is not a directory: {root}")

    stream = error_output or sys.stderr
    selected_catalog_entry: dict[str, Any] | None = None

    if external_path is None or str(external_path).strip() == "":
        if agent_id:
            cat_entry, active_manifest = _find_catalog_or_registered_agent(root, agent_id)
            if cat_entry is not None or active_manifest is not None:
                external_path = agent_id
                explicit_path = False
        if external_path is None or str(external_path).strip() == "":
            if not is_interactive or input_fn is None:
                raise CliError(
                    "missing target agent ID or project path. Pass 'agents connect AGENT_ID' to reconnect a "
                    "known agent, or 'agents connect --path <PROJECT_DIR>' to connect a new project."
                )
            disconnected = _list_disconnected_agents(root)
            if disconnected:
                print("Known disconnected agents available to connect:", file=stream)
                for idx, item in enumerate(disconnected, 1):
                    ep_label = f" [{item['entry_point']}]" if item.get("entry_point") else ""
                    print(
                        f"  {idx}. {item['id']} ({item['name']}) - {item['project_path']}{ep_label}",
                        file=stream,
                    )
                new_option_num = len(disconnected) + 1
                print(
                    f"  {new_option_num}. Connect a new external agent project (enter project path)",
                    file=stream,
                )
                choice = input_fn(
                    f"Select a disconnected agent by number (1-{len(disconnected)}) or ID, "
                    f"or choose {new_option_num} to connect a new project: "
                ).strip()
                if not choice:
                    raise CliError("no agent or project path was selected")
                if choice.isdigit():
                    num = int(choice)
                    if 1 <= num <= len(disconnected):
                        selected_catalog_entry = disconnected[num - 1]
                    elif num == new_option_num:
                        entered_path = input_fn("Path to the external Python agent directory: ").strip()
                        if not entered_path:
                            raise CliError("external project path is required")
                        external_path = entered_path
                        explicit_path = True
                    else:
                        raise CliError(
                            f"invalid selection {choice!r}; choose 1-{new_option_num} or enter an agent ID"
                        )
                elif choice.lower() in {"new", "path", "new project", "connect new"}:
                    entered_path = input_fn("Path to the external Python agent directory: ").strip()
                    if not entered_path:
                        raise CliError("external project path is required")
                    external_path = entered_path
                    explicit_path = True
                else:
                    external_path = choice
                    explicit_path = False
            else:
                print("No disconnected agents found.", file=stream)
                print("  1. Connect a new external agent project (enter project path)", file=stream)
                choice = input_fn(
                    "Select 1 or enter the path to the external Python agent directory: "
                ).strip()
                if choice.lower() in {"1", "new", "path", "new project", "connect new"}:
                    choice = input_fn("Path to the external Python agent directory: ").strip()
                if not choice:
                    raise CliError("external project path is required")
                external_path = choice
                explicit_path = False

    if selected_catalog_entry is None and external_path is not None and not explicit_path:
        target_str = str(external_path).strip()
        if not _looks_like_filesystem_path(target_str):
            cat_entry, active_manifest = _find_catalog_or_registered_agent(root, target_str)
            if active_manifest is not None:
                restored_workflows = _restore_reconnected_workflows(root, active_manifest.id, db_path=db_path)
                proj_path = cat_entry["project_path"] if cat_entry else None
                ep_spec = cat_entry.get("entry_point") if cat_entry else active_manifest.entrypoint
                msg = (
                    f"Agent '{active_manifest.id}' ({active_manifest.name}) is already connected"
                    + (f" to {proj_path} ({ep_spec})." if proj_path else ".")
                )
                print(msg, file=stream)
                adapter_dir = _connected_adapter_dir(root, active_manifest.id)
                manifest_path = _connected_manifest_path(root, active_manifest.id)
                return {
                    "id": active_manifest.id,
                    "name": active_manifest.name,
                    "status": "already_connected",
                    "entry_point": ep_spec,
                    "manifest_entrypoint": active_manifest.entrypoint,
                    "external_project": proj_path,
                    "generated_files": [
                        str(adapter_dir / "__init__.py"),
                        str(adapter_dir / "adapter.py"),
                        str(manifest_path),
                    ] if cat_entry else [str(manifest_path)],
                    "dependencies": (
                        inspect_dependencies(proj_path)
                        if (proj_path and Path(proj_path).is_dir())
                        else {}
                    ),
                    "already_connected": True,
                    "restored_workflows": restored_workflows,
                    "test_invocation": "not repeated; existing registration was previously verified",
                    "restart_required": False,
                    "message": msg,
                }
            if cat_entry is not None:
                selected_catalog_entry = cat_entry
            elif not Path(target_str).expanduser().exists():
                raise CliError(
                    f"unknown agent ID or name {target_str!r}: no saved connection metadata found and "
                    f"external project path does not exist. To connect a new external agent project, run: "
                    f"python -m app.cli agents connect --path <PROJECT_DIR>"
                )

    reconnected_from_catalog = selected_catalog_entry is not None
    if selected_catalog_entry is not None:
        saved_id = selected_catalog_entry["id"]
        agent_id = agent_id or saved_id
        name = name or selected_catalog_entry.get("name")
        entry_point = entry_point or selected_catalog_entry.get("entry_point") or None
        saved_path = selected_catalog_entry["project_path"]
        if test_input_path is None:
            saved_test_input = selected_catalog_entry.get("test_input")
            if saved_test_input and Path(saved_test_input).is_file():
                test_input_path = saved_test_input
        try:
            external_root = Path(saved_path).expanduser().resolve(strict=True)
        except OSError as exc:
            raise CliError(
                f"saved external project path for agent {saved_id!r} does not exist: {saved_path}. "
                f"To connect from a new location, run: python -m app.cli agents connect --path <PROJECT_DIR> --id {saved_id}"
            ) from exc
        if not external_root.is_dir():
            raise CliError(
                f"saved external project path for agent {saved_id!r} is not a directory: {external_root}. "
                f"To connect from a valid directory, run: python -m app.cli agents connect --path <PROJECT_DIR> --id {saved_id}"
            )
    else:
        try:
            external_root = Path(external_path).expanduser().resolve(strict=True)
        except OSError as exc:
            raise CliError(f"external project path does not exist: {external_path}") from exc
        if not external_root.is_dir():
            raise CliError(f"external project path is not a directory: {external_root}")

    if external_root == root or root in external_root.parents:
        raise CliError("external project must be separate from and outside the agent_platform project root")

    try:
        selected = resolve_python_entrypoint(external_root, entry_point)
        hashes = source_fingerprint(external_root)
        dependencies = inspect_dependencies(external_root)
    except (OSError, ValueError) as exc:
        raise CliError(str(exc)) from exc
    selected_id = _connected_agent_id(agent_id or default_agent_id(selected, external_root))
    selected_name = _scaffold_text(name or default_agent_name(selected, external_root), "agent name")

    if reconnected_from_catalog:
        print(
            f"Resolved saved connection metadata for agent {selected_id!r}:\n"
            f"  Agent ID:     {selected_id}\n"
            f"  Display name: {selected_name}\n"
            f"  Project path: {external_root}\n"
            f"  Entry point:  {selected.spec}",
            file=stream,
        )

    description = (
        f"Connected Python implementation from {external_root.name}; "
        "delegated unchanged through the trusted local Python adapter."
    )
    package_name = _connected_package_name(selected_id)
    entrypoint = f"plugins.examples.{package_name}.adapter:run"
    adapter_dir = _connected_adapter_dir(root, selected_id)
    manifest_path = _connected_manifest_path(root, selected_id)
    configuration = {
        "project_path": str(external_root),
        "relative_file": selected.relative_file,
        "symbol": selected.symbol,
        "kind": selected.kind,
        "source_hashes": hashes,
    }
    adapter_text = render_adapter_source(selected_id, configuration)
    init_text = (
        "# Generated by agent_platform agents connect. Do not edit by hand.\n"
        f'"""Trusted adapter for the external agent ID {selected_id}."""\n'
    )

    if _same_connection(root, selected_id, adapter_text, init_text):
        _save_catalog_entry(
            root,
            agent_id=selected_id,
            name=selected_name,
            project_path=str(external_root),
            entry_point=selected.spec,
            test_input=str(Path(test_input_path).resolve()) if test_input_path else None,
        )
        restored_workflows = _restore_reconnected_workflows(root, selected_id, db_path=db_path)
        msg = f"Agent '{selected_id}' ({selected_name}) is already connected to {external_root} ({selected.spec})."
        print(msg, file=stream)
        return {
            "id": selected_id,
            "name": selected_name,
            "status": "already_connected",
            "entry_point": selected.spec,
            "manifest_entrypoint": entrypoint,
            "external_project": str(external_root),
            "generated_files": [str(adapter_dir / "__init__.py"), str(adapter_dir / "adapter.py"), str(manifest_path)],
            "dependencies": dependencies,
            "already_connected": True,
            "restored_workflows": restored_workflows,
            "test_invocation": "not repeated; existing registration was previously verified",
            "restart_required": True,
            "message": msg,
        }

    if manifest_path.exists() or adapter_dir.exists():
        raise CliError(f"connection target already exists and does not match this registration: {selected_id}; disconnect it or choose another ID")

    verification_inputs, input_source = _resolve_verification_input(
        external_root, test_input_path, input_fn, is_interactive, error_output,
    )
    inferred_input_schema = infer_json_schema(verification_inputs)
    manifest = AgentManifest.model_validate({
        "id": selected_id,
        "name": selected_name,
        "version": "1.0.0",
        "description": description,
        "capabilities": ["external_python"],
        "adapter_type": "python_callable",
        "entrypoint": entrypoint,
        "enabled": True,
        "input_schema": inferred_input_schema,
        "output_schema": {"type": "object"},
    })
    manifest_text = yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False)
    files = {
        adapter_dir / "__init__.py": init_text,
        adapter_dir / "adapter.py": adapter_text,
        manifest_path: manifest_text,
    }

    if not trust_approved:
        if not is_interactive or input_fn is None:
            raise CliError(
                "external code has not been approved. Review the project, then rerun with --trust or confirm interactively; "
                "the agent will execute as ordinary in-process Python and is not sandboxed"
            )
        print(
            f"Discovered {selected.spec} in {external_root} (agent ID {selected_id!r}, name {selected_name!r}); "
            f"verification input: {input_source}.\n"
            f"About to import and invoke {selected.spec}. "
            "This executes ordinary Python code with this process's permissions; it is not sandboxed. "
            f"Detected dependencies: {dependencies}. Type TRUST to continue.",
            file=stream,
        )
        if input_fn("Trust and run this external code? ") != "TRUST":
            raise CliError("connection cancelled; no external code was imported or executed")

    created: list[Path] = []
    try:
        created = _write_connected_files(root, files)
        with project_plugin_namespace(root):
            registry = AgentRegistry()
            loaded = AgentLoader(registry, root / "plugins" / "manifests").load_manifest(manifest_path)
            if loaded.id != selected_id:
                raise CliError("generated manifest registered an unexpected agent ID")
            result = asyncio.run(AgentRunner(registry).run(
                selected_id,
                AgentRequest(task="connection verification", inputs=verification_inputs, run_id="agent-connect-verification"),
            ))
        if result.status != "succeeded":
            error = result.error.message if result.error else "agent returned a failed result"
            raise CliError(f"connection test invocation failed: {error}")
        if result.output:
            # Record the observed output shape so workflow tooling can map this agent's
            # outputs to downstream inputs. It is documentation of a sample, not a guarantee.
            observed = AgentManifest.model_validate({
                **manifest.model_dump(mode="json"), "output_schema": infer_json_schema(result.output),
            })
            manifest_path.write_text(yaml.safe_dump(observed.model_dump(mode="json"), sort_keys=False), encoding="utf-8", newline="\n")
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        _remove_adapter_dir(adapter_dir)
        raise

    _save_catalog_entry(
        root,
        agent_id=selected_id,
        name=selected_name,
        project_path=str(external_root),
        entry_point=selected.spec,
        test_input=str(Path(test_input_path).resolve()) if test_input_path else None,
    )
    restored_workflows = _restore_reconnected_workflows(root, selected_id, db_path=db_path)
    return {
        "id": selected_id,
        "name": selected_name,
        "entry_point": selected.spec,
        "manifest_entrypoint": entrypoint,
        "external_project": str(external_root),
        "generated_files": [str(path) for path in created],
        "dependencies": dependencies,
        "already_connected": False,
        "reconnected_from_catalog": reconnected_from_catalog,
        "restored_workflows": restored_workflows,
        "verification_input": input_source,
        "test_invocation": {"status": result.status, "output": result.output, "metadata": result.metadata},
        "restart_required": True,
    }


def _local_registry(project_root: str | Path | None = None, exclude_agent_id: str | None = None) -> AgentRegistry:
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parents[1]
    import plugins
    import plugins.examples

    p_dir = str(root / "plugins")
    if (root / "plugins").is_dir() and p_dir not in plugins.__path__:
        plugins.__path__.insert(0, p_dir)
    e_dir = str(root / "plugins" / "examples")
    if (root / "plugins" / "examples").is_dir() and e_dir not in plugins.examples.__path__:
        plugins.examples.__path__.insert(0, e_dir)

    registry = AgentRegistry()
    manifests_dir = root / "plugins" / "manifests"
    if manifests_dir.is_dir():
        for path in sorted(manifests_dir.glob("*.yaml")) + sorted(manifests_dir.glob("*.yml")):
            if exclude_agent_id and path.stem == exclude_agent_id:
                continue
            AgentLoader(registry, manifests_dir).load_manifest(path)
    return registry




def _saved_workflows(root: Path, repo: ExecutionRepository | None = None) -> dict[str, tuple[WorkflowDefinition, Path | None]]:
    workflows: dict[str, tuple[WorkflowDefinition, Path | None]] = {}
    wf_dir = root / "workflow_definitions"
    if wf_dir.is_dir():
        for path in sorted(wf_dir.glob("*.yaml")) + sorted(wf_dir.glob("*.yml")):
            try:
                data = _read_document(path)
                wf = WorkflowDefinition.model_validate(data)
                workflows[wf.id] = (wf, path.resolve())
            except Exception:
                continue

    if repo:
        try:
            for item in repo.list_workflows():
                try:
                    wf = WorkflowDefinition.model_validate(item)
                    if wf.id not in workflows:
                        workflows[wf.id] = (wf, None)
                except Exception:
                    continue
        except Exception:
            pass

    return workflows


def _analyze_workflow_agent_dependency(
    workflow: WorkflowDefinition,
    agent_id: str,
    remaining_registry: AgentRegistry,
) -> tuple[bool, WorkflowDefinition | None, str | None]:
    removed_nodes = [node for node in workflow.nodes if node.type == "agent" and node.agent_id == agent_id]
    if not removed_nodes:
        return True, None, None

    removed_node_ids = {node.id for node in removed_nodes}
    remaining_nodes = [node for node in workflow.nodes if node.id not in removed_node_ids]
    if not remaining_nodes:
        return (
            False,
            None,
            f"workflow '{workflow.id}' contains only agent '{agent_id}'; removing it would leave an empty workflow",
        )

    for node in remaining_nodes:
        for field, mapping in node.input_mappings.items():
            if mapping.path and mapping.path.startswith("node_outputs."):
                target_node = mapping.path.split(".")[1]
                if target_node in removed_node_ids:
                    return (
                        False,
                        None,
                        f"workflow '{workflow.id}' node '{node.id}' requires input '{field}' from removed node '{target_node}' ({mapping.path})",
                    )

    remaining_edges = [
        edge for edge in workflow.edges
        if edge.from_node not in removed_node_ids and edge.to not in removed_node_ids
    ]
    for edge in remaining_edges:
        if edge.condition and edge.condition.path.startswith("node_outputs."):
            target_node = edge.condition.path.split(".")[1]
            if target_node in removed_node_ids:
                return (
                    False,
                    None,
                    f"workflow '{workflow.id}' edge condition '{edge.from_node}->{edge.to}' references removed node '{target_node}'",
                )

    for node in remaining_nodes:
        if node.type == "human_approval" and node.approval_payload_path and node.approval_payload_path.startswith("node_outputs."):
            target_node = node.approval_payload_path.split(".")[1]
            if target_node in removed_node_ids:
                return (
                    False,
                    None,
                    f"workflow '{workflow.id}' approval node '{node.id}' payload references removed node '{target_node}'",
                )

    candidate_dict = workflow.model_dump(by_alias=True)
    candidate_dict["nodes"] = [node.model_dump(by_alias=True, exclude_unset=True) for node in remaining_nodes]
    candidate_dict["edges"] = [edge.model_dump(by_alias=True, exclude_unset=True) for edge in remaining_edges]
    try:
        candidate_dict["version"] = _bump_patch(workflow.version)
    except Exception:
        candidate_dict["version"] = workflow.version + ".1"

    try:
        candidate_workflow = WorkflowDefinition.model_validate(candidate_dict)
    except ValidationError as exc:
        return False, None, f"resulting workflow '{workflow.id}' definition is invalid: {exc}"

    try:
        validate_workflow(candidate_workflow, remaining_registry)
        WorkflowBuilder(remaining_registry).build(candidate_workflow)
    except (WorkflowValidationError, ValidationError, ValueError, KeyError, ImportError) as exc:
        return False, None, f"resulting workflow '{workflow.id}' failed validation: {exc}"
    except Exception as exc:
        return False, None, f"resulting workflow '{workflow.id}' is invalid: {exc}"

    return True, candidate_workflow, None


def _write_workflow_definition_file(path: Path, workflow: WorkflowDefinition) -> None:
    original_text = path.read_text(encoding="utf-8") if path.is_file() else ""
    header: list[str] = []
    for line in original_text.splitlines():
        if line.startswith("#") or (header and not line.strip()):
            header.append(line.rstrip("\r"))
        else:
            break
    while header and not header[-1].strip():
        header.pop()
    body = yaml.safe_dump(workflow.model_dump(by_alias=True, exclude_unset=True), sort_keys=False, allow_unicode=True)
    content = ("\n".join(header) + "\n" if header else "") + body
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise CliError(f"could not write {path}: {exc}") from exc


def _restore_reconnected_workflows(
    root: Path,
    agent_id: str,
    db_path: str | Path | None = None,
) -> dict[str, list[str]]:
    db_file: Path | None = None
    if db_path:
        db_file = Path(db_path).expanduser().resolve()
    elif (root / "agent_platform.db").is_file():
        db_file = (root / "agent_platform.db").resolve()

    repo: ExecutionRepository | None = None
    if db_file and db_file.is_file():
        try:
            repo = ExecutionRepository(str(db_file))
        except Exception:
            repo = None

    restored: dict[str, list[str]] = {}
    try:
        workflows_map = _saved_workflows(root, repo)
        for wf_id in sorted(workflows_map.keys()):
            wf, path = workflows_map[wf_id]
            disconnected_nodes = [
                node.id for node in wf.nodes
                if node.type == "agent" and node.agent_id == agent_id and node.status == "disconnected"
            ]
            if not disconnected_nodes:
                continue
            raw = _read_document(path) if (path and path.is_file()) else wf.model_dump(by_alias=True, exclude_unset=True)
            for node_dict in raw.get("nodes", []):
                if (
                    isinstance(node_dict, dict)
                    and node_dict.get("type", "agent") == "agent"
                    and node_dict.get("agent_id") == agent_id
                    and node_dict.get("status") == "disconnected"
                ):
                    node_dict["status"] = "available"
            updated_wf = WorkflowDefinition.model_validate(raw)
            if path and path.is_file():
                _write_workflow_definition_file(path, updated_wf)
            if repo and repo.get_workflow(wf_id) is not None:
                repo.save_workflow(updated_wf.model_dump(by_alias=True, exclude_unset=True))
            restored[wf_id] = disconnected_nodes
    finally:
        if repo:
            try:
                repo.close()
            except Exception:
                pass
    return restored


def _disconnect_agent(
    project_root: str | Path,
    agent_id: str,
    *,
    purge: bool = False,
    yes: bool = False,
    db_path: str | Path | None = None,
    input_fn=None,
    is_interactive: bool = False,
    error_output: TextIO | None = None,
) -> dict[str, Any]:
    selected_id = _connected_agent_id(agent_id)
    root = Path(project_root).expanduser().resolve()
    manifest_path = _connected_manifest_path(root, selected_id)
    adapter_dir = _connected_adapter_dir(root, selected_id)
    adapter_path = adapter_dir / "adapter.py"
    init_path = adapter_dir / "__init__.py"

    if not manifest_path.is_file():
        raise CliError(f"connected agent is not registered: {selected_id}")

    try:
        manifest = AgentManifest.model_validate(_read_document(manifest_path))
    except (ValidationError, CliError) as exc:
        raise CliError(f"refusing to disconnect an invalid or unrelated manifest: {manifest_path}") from exc

    expected_entrypoint = f"plugins.examples.{_connected_package_name(selected_id)}.adapter:run"
    if manifest.id != selected_id or manifest.entrypoint != expected_entrypoint or not adapter_path.is_file():
        raise CliError(f"refusing to remove registration not created by agents connect: {selected_id}")

    source = adapter_path.read_text(encoding="utf-8")
    if not source.startswith("# Generated by agent_platform agents connect. Do not edit by hand.\n"):
        raise CliError(f"refusing to remove adapter without the connector marker: {adapter_path}")

    adapter_connection = _extract_adapter_connection(adapter_path)
    external_project_path = adapter_connection.get("project_path") if adapter_connection else None
    rel_file = str(adapter_connection.get("relative_file") or "") if adapter_connection else ""
    sym_name = str(adapter_connection.get("symbol") or "") if adapter_connection else ""
    saved_entry_point = f"{rel_file}:{sym_name}" if (rel_file and sym_name) else ""

    db_file: Path | None = None
    if db_path:
        db_file = Path(db_path).expanduser().resolve()
    elif (root / "agent_platform.db").is_file():
        db_file = (root / "agent_platform.db").resolve()

    repo: ExecutionRepository | None = None
    if db_file and db_file.is_file():
        try:
            repo = ExecutionRepository(str(db_file))
        except Exception:
            repo = None

    try:
        workflows_map = _saved_workflows(root, repo)
        referencing_workflow_ids = sorted([
            wf_id for wf_id, (wf, _) in workflows_map.items()
            if any(node.type == "agent" and node.agent_id == selected_id for node in wf.nodes)
        ])

        if not purge:
            updated_workflows: dict[str, list[str]] = {}
            warnings: list[str] = []
            original_workflow_texts: dict[Path, str] = {}
            original_db_workflows: list[dict[str, Any]] = []
            original_catalog = _read_catalog_file(root)
            try:
                if external_project_path:
                    _save_catalog_entry(
                        root,
                        agent_id=selected_id,
                        name=manifest.name,
                        project_path=external_project_path,
                        entry_point=saved_entry_point,
                    )
                for wf_id in referencing_workflow_ids:
                    wf, path = workflows_map[wf_id]
                    raw = _read_document(path) if (path and path.is_file()) else wf.model_dump(by_alias=True, exclude_unset=True)
                    affected_nodes: list[str] = []
                    for node_dict in raw.get("nodes", []):
                        if isinstance(node_dict, dict) and node_dict.get("type", "agent") == "agent" and node_dict.get("agent_id") == selected_id:
                            node_dict["status"] = "disconnected"
                            affected_nodes.append(str(node_dict.get("id")))
                    updated_wf = WorkflowDefinition.model_validate(raw)
                    if path and path.is_file():
                        original_workflow_texts[path] = path.read_text(encoding="utf-8")
                        _write_workflow_definition_file(path, updated_wf)
                    if repo:
                        existing_db_wf = repo.get_workflow(wf_id)
                        if existing_db_wf is not None:
                            original_db_workflows.append(existing_db_wf)
                            repo.save_workflow(updated_wf.model_dump(by_alias=True, exclude_unset=True))
                    updated_workflows[wf_id] = affected_nodes
                    warnings.append(
                        f"workflow '{wf_id}' references disconnected agent '{selected_id}'; "
                        f"marked node(s) {', '.join(affected_nodes)} as disconnected while preserving configuration and history"
                    )
                removed_files = _remove_connected_files(root, selected_id)
            except Exception as exc:
                _write_catalog_file(root, original_catalog)
                for path, orig_text in original_workflow_texts.items():
                    try:
                        path.write_text(orig_text, encoding="utf-8")
                    except Exception:
                        pass
                if repo:
                    for orig_wf in original_db_workflows:
                        try:
                            repo.save_workflow(orig_wf)
                        except Exception:
                            pass
                raise CliError(f"disconnect failed and was rolled back: {exc}") from exc

            if error_output:
                for warning in warnings:
                    print(f"Warning: {warning}", file=error_output)

            return {
                "id": selected_id,
                "status": "disconnected",
                "removed_files": removed_files,
                "external_project": external_project_path,
                "external_project_modified": False,
                "workflows_updated": updated_workflows,
                "retained": {
                    "history": True,
                    "workflow_definitions": True,
                    "connection_catalog": bool(external_project_path),
                    "referenced_by_workflows": referencing_workflow_ids,
                },
                "warnings": warnings,
                "message": (
                    f"Agent '{selected_id}' was disconnected. "
                    "Its retained history and workflow definitions have not been deleted."
                ),
            }

        # Purge mode
        remaining_registry = _local_registry(root, exclude_agent_id=selected_id)
        safe_workflow_updates: list[tuple[str, WorkflowDefinition, Path | None]] = []
        for wf_id in referencing_workflow_ids:
            wf, path = workflows_map[wf_id]
            is_safe, candidate_wf, reason = _analyze_workflow_agent_dependency(wf, selected_id, remaining_registry)
            if not is_safe:
                raise CliError(
                    f"cannot safely purge agent '{selected_id}': {reason}. "
                    "Resolve workflow dependencies before purging."
                )
            if candidate_wf is not None:
                safe_workflow_updates.append((wf_id, candidate_wf, path))

        purged_node_ids = {
            node.id for wf_id in referencing_workflow_ids
            for node in workflows_map[wf_id][0].nodes
            if node.type == "agent" and node.agent_id == selected_id
        }

        if repo:
            inspection = repo.inspect_agent_records(selected_id, node_ids=purged_node_ids)
        else:
            inspection = {
                "direct_run_ids": [],
                "direct_thread_ids": [],
                "direct_run_count": 0,
                "event_ids": [],
                "event_count": 0,
                "checkpoint_count": 0,
                "workflows_referencing": [],
                "shared_runs_count": 0,
            }

        if not yes:
            if not is_interactive or input_fn is None:
                raise CliError(
                    "purge requires explicit confirmation. Rerun with --yes or confirm interactively; "
                    "this permanently deletes platform-managed registration and database records."
                )

            stream = error_output or sys.stderr
            print(f"Preview of platform-managed data to be permanently deleted for agent '{selected_id}':", file=stream)
            print(f"  - Registration manifest: {manifest_path}", file=stream)
            print(f"  - Generated adapter directory: {adapter_dir}", file=stream)
            print(f"  - Saved connection catalog entry: {selected_id}", file=stream)
            print(f"  - Direct run records: {inspection['direct_run_count']}", file=stream)
            print(f"  - Node/agent event records: {inspection['event_count']}", file=stream)
            print(f"  - Checkpoint records: {inspection['checkpoint_count']}", file=stream)
            if safe_workflow_updates:
                print(f"  - Workflows to update (safely remove agent node): {', '.join(wf_id for wf_id, _, _ in safe_workflow_updates)}", file=stream)
            else:
                print("  - Workflows to update: None", file=stream)
            if external_project_path:
                print(f"External project folder will be PRESERVED (unmodified): {external_project_path}", file=stream)
            print("Unrelated agents, shared workflow runs, and other records will be PRESERVED.", file=stream)

            confirm = input_fn(f"Permanently delete platform-managed records for '{selected_id}'? Type PURGE to continue: ")
            if confirm.strip() != "PURGE":
                raise CliError("purge cancelled; no files or database records were modified")

        original_workflow_texts: dict[Path, str] = {}
        original_catalog = _read_catalog_file(root)
        manifest_text = manifest_path.read_text(encoding="utf-8")
        adapter_text = adapter_path.read_text(encoding="utf-8")
        init_text = init_path.read_text(encoding="utf-8") if init_path.is_file() else ""

        try:
            for wf_id, candidate_wf, path in safe_workflow_updates:
                if path and path.is_file():
                    original_workflow_texts[path] = path.read_text(encoding="utf-8")
                    _write_workflow_definition_file(path, candidate_wf)

            if repo:
                db_updates = [candidate_wf.model_dump(by_alias=True) for _, candidate_wf, _ in safe_workflow_updates]
                purge_counts = repo.purge_agent_records(selected_id, node_ids=purged_node_ids, updated_workflows=db_updates)
            else:
                purge_counts = {"deleted_runs": 0, "deleted_events": 0, "deleted_checkpoints": 0, "workflows_updated": 0}

            removed_files = _remove_connected_files(root, selected_id)
            catalog_entry_removed = _remove_catalog_entry(root, selected_id) is not None
        except Exception as exc:
            _write_catalog_file(root, original_catalog)
            for path, orig_text in original_workflow_texts.items():
                try:
                    path.write_text(orig_text, encoding="utf-8")
                except Exception:
                    pass
            try:
                if not manifest_path.exists():
                    manifest_path.write_text(manifest_text, encoding="utf-8")
                adapter_dir.mkdir(parents=True, exist_ok=True)
                if not adapter_path.exists():
                    adapter_path.write_text(adapter_text, encoding="utf-8")
                if init_text and not init_path.exists():
                    init_path.write_text(init_text, encoding="utf-8")
            except Exception:
                pass
            raise CliError(f"purge failed and was rolled back: {exc}") from exc

        other_agents = [
            p.stem for p in (root / "plugins" / "manifests").glob("*.y*ml") if p.stem != selected_id
        ]
        retained_workflows = sorted(list(workflows_map.keys()))

        return {
            "id": selected_id,
            "status": "purged",
            "deleted": {
                "manifest": str(manifest_path),
                "adapter_files": removed_files,
                "adapter_directory": str(adapter_dir),
                "connection_catalog_entry": catalog_entry_removed,
                "direct_runs": purge_counts["deleted_runs"],
                "events": purge_counts["deleted_events"],
                "checkpoints": purge_counts["deleted_checkpoints"],
                "workflows_updated": [wf_id for wf_id, _, _ in safe_workflow_updates],
            },
            "retained": {
                "external_project": external_project_path,
                "unrelated_agents": sorted(other_agents),
                "workflows": retained_workflows,
                "shared_runs": inspection["shared_runs_count"],
            },
            "external_project_modified": False,
            "message": f"Agent '{selected_id}' and its platform-managed records were permanently purged.",
        }
    finally:
        if repo:
            try:
                repo.close()
            except Exception:
                pass


def _confirm_action(prompt: str, input_fn, *, cancel_message: str) -> None:
    try:
        answer = input_fn(prompt)
    except (KeyboardInterrupt, EOFError) as exc:
        raise CliError(cancel_message) from exc
    if not isinstance(answer, str) or answer.strip().lower() not in {"y", "yes"}:
        raise CliError(cancel_message)


def _plan_workflow_for_agent_deletion(
    workflow: WorkflowDefinition,
    path: Path | None,
    agent_id: str,
    remaining_registry: AgentRegistry,
) -> dict[str, Any]:
    removed_node_ids = [node.id for node in workflow.nodes if node.type == "agent" and node.agent_id == agent_id]
    removed_set = set(removed_node_ids)
    try:
        new_version = _bump_patch(workflow.version)
    except Exception:
        new_version = workflow.version + ".1"

    remaining_nodes_raw: list[dict[str, Any]] = []
    pruned_mappings: list[str] = []
    for node in workflow.nodes:
        if node.id in removed_set:
            continue
        node_dict = node.model_dump(by_alias=True, exclude_unset=True)
        cleaned_mappings: dict[str, Any] = {}
        for field, mapping in node.input_mappings.items():
            if mapping.path and mapping.path.startswith("node_outputs.") and mapping.path.split(".")[1] in removed_set:
                pruned_mappings.append(f"{node.id}.{field} ({mapping.path})")
            else:
                cleaned_mappings[field] = mapping.model_dump(by_alias=True, exclude_unset=True)
        node_dict["input_mappings"] = cleaned_mappings
        if (
            node.type == "human_approval"
            and node.approval_payload_path
            and node.approval_payload_path.startswith("node_outputs.")
            and node.approval_payload_path.split(".")[1] in removed_set
        ):
            node_dict.pop("approval_payload_path", None)
            pruned_mappings.append(f"{node.id}.approval_payload_path ({node.approval_payload_path})")
        remaining_nodes_raw.append(node_dict)

    if not remaining_nodes_raw:
        candidate_wf = WorkflowDefinition.model_validate({
            "id": workflow.id,
            "version": new_version,
            "nodes": [],
            "edges": [],
            "max_steps": workflow.max_steps,
        })
        return {
            "workflow_id": workflow.id,
            "path": path,
            "original_workflow": workflow,
            "candidate_wf": candidate_wf,
            "removed_nodes": removed_node_ids,
            "pruned_mappings": pruned_mappings,
            "can_keep_registered": False,
            "fate": "converted_to_empty_draft_and_unregistered",
            "description": (
                f"remove sole node(s) {', '.join(removed_node_ids)}, convert local YAML to empty draft "
                f"(version {workflow.version} -> {new_version}), and unregister from active server registry"
            ),
        }

    adj_removed: dict[str, list[str]] = {}
    for edge in workflow.edges:
        adj_removed.setdefault(edge.from_node, []).append(edge.to)

    kept_edges: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for edge in workflow.edges:
        if edge.from_node in removed_set or edge.to in removed_set:
            continue
        if edge.condition and edge.condition.path.startswith("node_outputs.") and edge.condition.path.split(".")[1] in removed_set:
            continue
        kept_edges.append(edge.model_dump(by_alias=True, exclude_unset=True))
        seen_pairs.add((edge.from_node, edge.to))

    remaining_id_set = {n["id"] for n in remaining_nodes_raw}
    for src in [n["id"] for n in remaining_nodes_raw]:
        visited: set[str] = set()
        stack = [nxt for nxt in adj_removed.get(src, []) if nxt in removed_set]
        while stack:
            curr = stack.pop()
            if curr in visited:
                continue
            visited.add(curr)
            for target in adj_removed.get(curr, []):
                if target in removed_set and target not in visited:
                    stack.append(target)
                elif target in remaining_id_set and target != src and (src, target) not in seen_pairs:
                    kept_edges.append({"from": src, "to": target})
                    seen_pairs.add((src, target))

    candidate_wf = WorkflowDefinition.model_validate({
        "id": workflow.id,
        "version": new_version,
        "nodes": remaining_nodes_raw,
        "edges": kept_edges,
        "max_steps": workflow.max_steps,
    })
    can_keep_registered = True
    try:
        validate_workflow(candidate_wf, remaining_registry, allow_partial=True)
        WorkflowBuilder(remaining_registry).build(candidate_wf, allow_partial=True)
    except Exception:
        can_keep_registered = False

    mapping_note = f", prune dependent mapping(s) [{', '.join(pruned_mappings)}]" if pruned_mappings else ""
    reg_note = "and update registered workflow" if can_keep_registered else "and unregister from active server registry"
    return {
        "workflow_id": workflow.id,
        "path": path,
        "original_workflow": workflow,
        "candidate_wf": candidate_wf,
        "removed_nodes": removed_node_ids,
        "pruned_mappings": pruned_mappings,
        "can_keep_registered": can_keep_registered,
        "fate": "updated_and_registered" if can_keep_registered else "updated_locally_and_unregistered",
        "description": (
            f"remove node(s) {', '.join(removed_node_ids)}{mapping_note}, bump version "
            f"{workflow.version} -> {new_version}, {reg_note}"
        ),
    }


def _delete_agent(
    project_root: str | Path,
    agent_id: str,
    api: "ApiClient | None" = None,
    *,
    yes: bool = False,
    db_path: str | Path | None = None,
    input_fn=None,
    is_interactive: bool = False,
    error_output: TextIO | None = None,
) -> dict[str, Any]:
    selected_id = _connected_agent_id(agent_id)
    root = Path(project_root).expanduser().resolve()
    manifest_path = _connected_manifest_path(root, selected_id)
    if not manifest_path.is_file():
        alt_manifest = root / "plugins" / "manifests" / f"{selected_id}.yml"
        if alt_manifest.is_file():
            manifest_path = alt_manifest

    connected_adapter_dir = _connected_adapter_dir(root, selected_id)
    scaffold_package_dir = root / "plugins" / "examples" / selected_id
    if connected_adapter_dir.is_dir():
        package_dir: Path | None = connected_adapter_dir
    elif scaffold_package_dir.is_dir():
        package_dir = scaffold_package_dir
    else:
        package_dir = None

    catalog = _read_catalog_file(root)
    catalog_entry = catalog.get(selected_id)

    external_project_path: str | None = None
    adapter_file = connected_adapter_dir / "adapter.py"
    if adapter_file.is_file():
        conn = _extract_adapter_connection(adapter_file)
        if conn and isinstance(conn.get("project_path"), str):
            external_project_path = conn["project_path"]
    if not external_project_path and isinstance(catalog_entry, dict):
        proj = catalog_entry.get("project_path")
        if isinstance(proj, str) and proj.strip():
            external_project_path = proj.strip()

    db_file: Path | None = None
    if db_path:
        db_file = Path(db_path).expanduser().resolve()
    elif (root / "agent_platform.db").is_file():
        db_file = (root / "agent_platform.db").resolve()

    repo: ExecutionRepository | None = None
    if db_file and db_file.is_file():
        try:
            repo = ExecutionRepository(str(db_file))
        except Exception:
            repo = None

    try:
        registered_on_server = False
        if api is not None:
            try:
                api.get(f"/v1/agents/{quote(selected_id, safe='')}")
                registered_on_server = True
            except CliError as exc:
                msg = str(exc)
                if "API 404:" in msg or "could not connect to" in msg:
                    registered_on_server = False
                else:
                    raise

        workflows_map = _saved_workflows(root, repo)
        if api is not None:
            try:
                remote_wfs = api.get("/v1/workflows")
                if isinstance(remote_wfs, list):
                    for item in remote_wfs:
                        if isinstance(item, dict) and item.get("id") and str(item["id"]) not in workflows_map:
                            try:
                                wf_obj = WorkflowDefinition.model_validate(item)
                                workflows_map[wf_obj.id] = (wf_obj, None)
                            except Exception:
                                pass
            except CliError as exc:
                if "could not connect to" not in str(exc) and "API 404:" not in str(exc):
                    raise

        referencing_workflow_ids = sorted([
            wf_id for wf_id, (wf, _) in workflows_map.items()
            if any(node.type == "agent" and node.agent_id == selected_id for node in wf.nodes)
        ])
        unrelated_workflow_ids = sorted([
            wf_id for wf_id in workflows_map.keys() if wf_id not in set(referencing_workflow_ids)
        ])

        purged_node_ids = {
            node.id for wf_id in referencing_workflow_ids
            for node in workflows_map[wf_id][0].nodes
            if node.type == "agent" and node.agent_id == selected_id
        }

        if repo:
            inspection = repo.inspect_agent_records(selected_id, node_ids=purged_node_ids)
        else:
            inspection = {
                "direct_run_ids": [],
                "direct_thread_ids": [],
                "direct_run_count": 0,
                "event_ids": [],
                "event_count": 0,
                "checkpoint_count": 0,
                "workflows_referencing": [],
                "shared_runs_count": 0,
            }

        exists_anywhere = bool(
            manifest_path.is_file()
            or (package_dir is not None and package_dir.exists())
            or catalog_entry is not None
            or registered_on_server
            or inspection["direct_run_count"] > 0
            or inspection["event_count"] > 0
            or referencing_workflow_ids
        )
        if not exists_anywhere:
            raise CliError(f"agent not found: {selected_id}")

        remaining_registry = _local_registry(root, exclude_agent_id=selected_id)
        workflow_plans = [
            _plan_workflow_for_agent_deletion(
                workflows_map[wf_id][0],
                workflows_map[wf_id][1],
                selected_id,
                remaining_registry,
            )
            for wf_id in referencing_workflow_ids
        ]

        other_agents = sorted([
            p.stem for p in (root / "plugins" / "manifests").glob("*.y*ml") if p.stem != selected_id
        ]) if (root / "plugins" / "manifests").is_dir() else []

        stream = error_output or sys.stderr
        print(
            f"WARNING: This permanently deletes the agent '{selected_id}' and the following associated resources:",
            file=stream,
        )
        print(
            f"  - Agent registration manifest: {manifest_path if manifest_path.is_file() else 'not present'}",
            file=stream,
        )
        print(
            f"  - Generated adapter / plugin package: {package_dir if (package_dir and package_dir.exists()) else 'not present'}",
            file=stream,
        )
        print(
            f"  - Saved connection catalog entry: {selected_id if catalog_entry else 'not present'}",
            file=stream,
        )
        print(
            f"  - Server-side agent registration: {'registered' if registered_on_server else 'not currently registered'}",
            file=stream,
        )
        print(f"  - Direct agent run records: {inspection['direct_run_count']}", file=stream)
        print(f"  - Agent execution event records: {inspection['event_count']}", file=stream)
        print(f"  - Agent-specific LangGraph checkpoints/writes: {inspection['checkpoint_count']}", file=stream)
        print(f"  - Agent module & bytecode caches: {selected_id}", file=stream)
        if workflow_plans:
            print(f"  - Referenced workflows to update ({len(workflow_plans)}):", file=stream)
            for plan in workflow_plans:
                print(f"    * {plan['workflow_id']}: {plan['description']}", file=stream)
        else:
            print("  - Referenced workflows to update: None", file=stream)
        print("Preserved resources (will NOT be deleted):", file=stream)
        if external_project_path:
            print(
                f"  - External project source files on disk (will remain untouched): {external_project_path}",
                file=stream,
            )
        else:
            print("  - External project source files on disk: none (local plugin only)", file=stream)
        print(f"  - Unrelated agents: {', '.join(other_agents) if other_agents else 'none'}", file=stream)
        print(f"  - Unrelated workflows: {', '.join(unrelated_workflow_ids) if unrelated_workflow_ids else 'none'}", file=stream)
        print(f"  - Shared workflow execution history: {inspection['shared_runs_count']} run(s)", file=stream)

        if not yes:
            if not is_interactive or input_fn is None:
                raise CliError(
                    "agent deletion requires explicit confirmation; rerun with --yes or confirm interactively"
                )
            _confirm_action(
                f"This action cannot be undone. Permanently delete agent '{selected_id}'? Continue? [y/N]: ",
                input_fn,
                cancel_message="agent deletion cancelled; no files or database records were modified",
            )

        original_workflow_texts: dict[Path, str] = {}
        original_catalog = _read_catalog_file(root)
        manifest_backup = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else None
        package_files_backup: dict[Path, bytes] = {}
        if package_dir and package_dir.is_dir():
            for file_path in package_dir.rglob("*"):
                if file_path.is_file() and "__pycache__" not in file_path.parts:
                    package_files_backup[file_path] = file_path.read_bytes()

        server_purged_counts = {"deleted_runs": 0, "deleted_events": 0, "deleted_checkpoints": 0}
        try:
            if api is not None:
                try:
                    del_resp = api.delete(f"/v1/agents/{quote(selected_id, safe='')}")
                    if isinstance(del_resp, dict) and isinstance(del_resp.get("purged_records"), dict):
                        server_purged_counts = del_resp["purged_records"]
                except CliError as exc:
                    msg = str(exc)
                    if "API 404:" not in msg and "could not connect to" not in msg:
                        raise

            for plan in workflow_plans:
                path = plan["path"]
                if path and path.is_file():
                    original_workflow_texts[path] = path.read_text(encoding="utf-8")
                    _write_workflow_definition_file(path, plan["candidate_wf"])
                if api is not None:
                    try:
                        if plan["can_keep_registered"]:
                            api.post("/v1/workflows", plan["candidate_wf"].model_dump(by_alias=True, exclude_unset=True))
                        else:
                            api.post(f"/v1/workflows/{quote(plan['workflow_id'], safe='')}/disconnect", {})
                    except CliError as exc:
                        msg = str(exc)
                        if "API 404:" not in msg and "could not connect to" not in msg and "API 422:" not in msg:
                            raise

            if repo is not None:
                db_updates = [
                    plan["candidate_wf"].model_dump(by_alias=True, exclude_unset=True)
                    for plan in workflow_plans
                    if plan["can_keep_registered"]
                ]
                purge_counts = repo.purge_agent_records(
                    selected_id,
                    node_ids=purged_node_ids,
                    updated_workflows=db_updates,
                )
                for plan in workflow_plans:
                    if not plan["can_keep_registered"]:
                        repo.unregister_workflow(plan["workflow_id"])
            else:
                purge_counts = {
                    "deleted_runs": server_purged_counts.get("deleted_runs", 0),
                    "deleted_events": server_purged_counts.get("deleted_events", 0),
                    "deleted_checkpoints": server_purged_counts.get("deleted_checkpoints", 0),
                    "workflows_updated": sum(1 for p in workflow_plans if p["can_keep_registered"]),
                }

            removed_files: list[str] = []
            if manifest_path.is_file():
                manifest_path.unlink()
                removed_files.append(str(manifest_path))
            if package_dir and package_dir.is_dir():
                for child in sorted(package_dir.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink(missing_ok=True)
                        if "__pycache__" not in child.parts:
                            removed_files.append(str(child))
                    elif child.is_dir():
                        try:
                            child.rmdir()
                        except OSError:
                            pass
                try:
                    package_dir.rmdir()
                except OSError:
                    pass

            catalog_removed = (_remove_catalog_entry(root, selected_id) is not None) or bool(catalog_entry)
            cache_entries_evicted = evict_external_agent_cache(
                external_project_path,
                package_dir.name if package_dir else selected_id,
            )
        except Exception as exc:
            _write_catalog_file(root, original_catalog)
            for path, orig_text in original_workflow_texts.items():
                try:
                    path.write_text(orig_text, encoding="utf-8")
                except Exception:
                    pass
            try:
                if manifest_backup is not None and not manifest_path.exists():
                    manifest_path.parent.mkdir(parents=True, exist_ok=True)
                    manifest_path.write_text(manifest_backup, encoding="utf-8")
                for file_path, content_bytes in package_files_backup.items():
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_bytes(content_bytes)
            except Exception:
                pass
            if isinstance(exc, CliError):
                raise
            raise CliError(f"agent deletion failed and was rolled back: {exc}") from exc

        return {
            "id": selected_id,
            "agent_id": selected_id,
            "status": "deleted",
            "deleted": {
                "manifest": str(manifest_path) if manifest_backup is not None else None,
                "package_directory": str(package_dir) if package_dir else None,
                "files": removed_files,
                "connection_catalog_entry": catalog_removed,
                "direct_runs": max(purge_counts["deleted_runs"], server_purged_counts.get("deleted_runs", 0)),
                "events": max(purge_counts["deleted_events"], server_purged_counts.get("deleted_events", 0)),
                "checkpoints": max(purge_counts["deleted_checkpoints"], server_purged_counts.get("deleted_checkpoints", 0)),
                "caches_evicted": cache_entries_evicted,
                "workflows_affected": {
                    plan["workflow_id"]: {
                        "fate": plan["fate"],
                        "removed_nodes": plan["removed_nodes"],
                        "pruned_mappings": plan["pruned_mappings"],
                        "new_version": plan["candidate_wf"].version,
                        "description": plan["description"],
                    }
                    for plan in workflow_plans
                },
            },
            "retained": {
                "external_project": external_project_path,
                "external_project_modified": False,
                "unrelated_agents": other_agents,
                "unrelated_workflows": unrelated_workflow_ids,
                "shared_runs": inspection["shared_runs_count"],
            },
            "external_project_modified": False,
            "message": (
                f"Agent '{selected_id}' and its platform-managed records were permanently deleted. "
                + (
                    f"External project files at {external_project_path} were preserved on disk."
                    if external_project_path
                    else "Unrelated agents, workflows, and execution history were preserved."
                )
            ),
        }
    finally:
        if repo:
            try:
                repo.close()
            except Exception:
                pass


def _workflow_id(value: str) -> str:
    if not _WORKFLOW_ID.fullmatch(value):
        raise CliError("workflow ID must start with a lowercase letter and contain only lowercase letters, digits, hyphens, or underscores")
    return value


def _write_new_files(files: dict[Path, str]) -> list[str]:
    paths = [path.resolve() for path in files]
    existing = [path for path in paths if path.exists()]
    if existing:
        raise CliError("scaffold target already exists: " + ", ".join(str(path) for path in existing))
    for path, contents in zip(paths, files.values()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8", newline="\n")
    return [str(path) for path in paths]


def _default_display_name(identifier: str) -> str:
    return identifier.replace("_", " ").replace("-", " ").strip().title()


def _scaffold_agent(
    project_root: str | Path,
    agent_id: str,
    name: str | None = None,
    description: str | None = None,
    *,
    input_fn=None,
    is_interactive: bool = False,
) -> dict[str, Any]:
    agent_id = _scaffold_id(agent_id)
    root = Path(project_root).resolve()
    package = root / "plugins" / "examples" / agent_id
    manifest_path = root / "plugins" / "manifests" / f"{agent_id}.yaml"
    input_path = package / "example_input.json"
    agent_path = package / "agent.py"
    init_path = package / "__init__.py"
    if package.exists() or manifest_path.exists():
        raise CliError(f"scaffold target already exists: {package if package.exists() else manifest_path}")

    default_name = _default_display_name(agent_id)
    if name is None:
        if is_interactive and input_fn is not None:
            entered_name = input_fn(f"Agent display name (press Enter for '{default_name}'): ").strip()
            name = entered_name or default_name
        else:
            name = default_name
    name = _scaffold_text(name, "agent name")

    default_description = f"Deterministic local agent plugin for {name}."
    if description is None:
        if is_interactive and input_fn is not None:
            entered_desc = input_fn(f"Agent description (press Enter for '{default_description}'): ").strip()
            description = entered_desc or default_description
        else:
            description = default_description
    description = _scaffold_text(description, "agent description")

    manifest = AgentManifest.model_validate({
        "id": agent_id,
        "name": name,
        "version": "1.0.0",
        "description": description,
        "capabilities": ["deterministic_example"],
        "adapter_type": "python_callable",
        "entrypoint": f"plugins.examples.{agent_id}.agent:run",
        "enabled": True,
        "input_schema": {
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
        "output_schema": {
            "type": "object",
            "required": ["result", "agent_id"],
            "properties": {"result": {"type": "string"}, "agent_id": {"type": "string"}},
        },
    })
    implementation = textwrap.dedent(f'''\
        from app.sdk.context import AgentContext
        from app.sdk.contracts import AgentRequest


        def run(request: AgentRequest, context: AgentContext) -> dict:
            """Deterministic starter implementation."""
            # Replace this example logic with the domain behavior for {agent_id}.
            text = request.inputs.get("text", "")
            return {{"result": text, "agent_id": "{agent_id}"}}
    ''')
    files = {
        init_path: f'"""Trusted plugin package for {name}."""\n',
        agent_path: implementation,
        input_path: json.dumps({"text": f"Example input for {name}."}, indent=2) + "\n",
        manifest_path: yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False),
    }
    return {"id": agent_id, "name": name, "description": description, "kind": "agent", "files": _write_new_files(files)}


def _scaffold_tool(
    project_root: str | Path,
    tool_id: str,
    name: str | None = None,
    description: str | None = None,
    *,
    input_fn=None,
    is_interactive: bool = False,
) -> dict[str, Any]:
    tool_id = _scaffold_id(tool_id)
    root = Path(project_root).resolve()
    implementation_path = root / "plugins" / "tools" / f"{tool_id}.py"
    manifest_path = root / "plugins" / "tool_manifests" / f"{tool_id}.yaml"
    docs_path = root / "plugins" / "tools" / f"{tool_id}.md"
    for existing_path in (implementation_path, manifest_path, docs_path):
        if existing_path.exists():
            raise CliError(f"scaffold target already exists: {existing_path}")

    default_name = _default_display_name(tool_id)
    if name is None:
        if is_interactive and input_fn is not None:
            entered_name = input_fn(f"Tool display name (press Enter for '{default_name}'): ").strip()
            name = entered_name or default_name
        else:
            name = default_name
    name = _scaffold_text(name, "tool name")

    default_description = f"Deterministic local tool capability for {name}."
    if description is None:
        if is_interactive and input_fn is not None:
            entered_desc = input_fn(f"Tool description (press Enter for '{default_description}'): ").strip()
            description = entered_desc or default_description
        else:
            description = default_description
    description = _scaffold_text(description, "tool description")

    permission = f"{tool_id}.use"
    manifest = ToolManifest.model_validate({
        "id": tool_id,
        "name": name,
        "version": "1.0.0",
        "description": description,
        "adapter_type": "python_callable",
        "entrypoint": f"plugins.tools.{tool_id}:run",
        "enabled": True,
        "input_schema": {
            "type": "object",
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
        "output_schema": {
            "type": "object",
            "required": ["result"],
            "properties": {"result": {"type": "string"}},
        },
        "required_permissions": [permission],
        "idempotent": True,
    })
    implementation = textwrap.dedent(f'''\
        from app.tools import ToolExecutionContext, ToolRequest


        def run(request: ToolRequest, context: ToolExecutionContext) -> dict[str, str]:
            """Deterministic starter implementation."""
            # Replace this example logic with the approved capability for {tool_id}.
            text = request.inputs["text"]
            return {{"result": text}}
    ''')
    documentation = textwrap.dedent(f'''\
        # {name}

        This trusted local tool requires the `{permission}` permission.

        An authorized agent declares:

        ```yaml
        execution:
          allowed_tools: [{tool_id}]
          permissions: [{permission}]
        ```

        and invokes it through the existing runtime:

        ```python
        result = await context.call_tool("{tool_id}", {{"text": "example"}})
        ```

        Keep implementation deterministic and validate any new input/output contract in the manifest.
    ''')
    files = {
        implementation_path: implementation,
        manifest_path: yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False),
        docs_path: documentation,
    }
    return {"id": tool_id, "name": name, "description": description, "kind": "tool", "files": _write_new_files(files)}


def _manifest_input_fields(metadata: Any) -> list[str]:
    schema = metadata.input_schema if isinstance(metadata.input_schema, dict) else {}
    required = schema.get("required")
    if isinstance(required, list) and all(isinstance(item, str) for item in required):
        return required
    properties = schema.get("properties")
    if isinstance(properties, dict):
        return [str(item) for item in properties]
    return []


def _default_workflow_version(root: Path, explicit_version: str | None = None) -> str:
    if explicit_version is not None:
        cleaned = explicit_version.strip()
        if not cleaned:
            raise CliError("workflow version must not be empty")
        return cleaned
    return "1.0.0"


def _create_workflow(
    project_root: str | Path,
    workflow_id: str,
    agent_list: str | list[str] | None = None,
    version: str | None = None,
    *,
    empty: bool = False,
    strict_mappings: bool = True,
    node_id: str | None = None,
    maps: list[str] | None = None,
    literals: list[str] | None = None,
    register: bool | None = None,
    no_register: bool = False,
    api: "ApiClient | None" = None,
    input_fn=None,
    is_interactive: bool = False,
    error_output: TextIO | None = None,
) -> dict[str, Any]:
    workflow_id = _workflow_id(workflow_id)
    root = Path(project_root).expanduser().resolve()
    workflow_path = root / "workflow_definitions" / f"{workflow_id}.yaml"
    if workflow_path.exists() or (root / "workflow_definitions" / f"{workflow_id}.yml").exists():
        raise CliError(f"scaffold target already exists: {workflow_path.resolve()}")

    path_overrides = _parse_assignments(maps, "--map")
    literal_overrides = _parse_assignments(literals, "--literal", literal=True)
    resolved_version = _default_workflow_version(root, version)
    registry = _local_registry(root)

    raw_items: list[str] = []
    if isinstance(agent_list, str):
        raw_items = [part.strip() for part in agent_list.split(",") if part.strip()]
    elif isinstance(agent_list, list):
        for entry in agent_list:
            if isinstance(entry, str):
                raw_items.extend(part.strip() for part in entry.split(","))

    if register is True and no_register:
        raise CliError("cannot combine --register and --no-register")
    if empty and raw_items:
        raise CliError("cannot combine --empty with agent IDs; choose either --empty or specify agents")
    if empty and (node_id is not None or path_overrides or literal_overrides):
        raise CliError("cannot combine --empty with --node-id, --map, or --literal; add agents later using 'workflows add-agent'")
    if empty and register is True:
        raise CliError("cannot register an empty workflow without valid nodes; add at least one agent first")

    stream = error_output or sys.stderr
    if not empty and not raw_items:
        if is_interactive and input_fn is not None:
            if strict_mappings:
                print("How would you like to create this workflow?", file=stream)
                print("1. Create with agents", file=stream)
                print("2. Create empty workflow and add agents later", file=stream)
                mode_choice: str | None = None
                for _ in range(3):
                    choice_raw = input_fn(
                        "How would you like to create this workflow? "
                        "(1: Create with agents, 2: Create empty workflow and add agents later): "
                    ).strip().lower()
                    if choice_raw in {"1", "1.", "create with agents", "with agents", "agents"}:
                        mode_choice = "agents"
                        break
                    if choice_raw in {
                        "2",
                        "2.",
                        "create empty workflow",
                        "create empty workflow and add agents later",
                        "empty",
                    }:
                        mode_choice = "empty"
                        break
                    print(
                        "Please enter 1 (Create with agents) or 2 (Create empty workflow and add agents later).",
                        file=stream,
                    )
                if mode_choice is None:
                    raise CliError(
                        "invalid workflow creation choice; expected 1 (Create with agents) or 2 (Create empty workflow)"
                    )
                if mode_choice == "empty":
                    empty = True
            if not empty:
                enabled_agents = registry.list_enabled()
                if not enabled_agents:
                    raise CliError(
                        "no registered agents were found in plugins/manifests. "
                        "Connect an agent with 'agents connect PATH' or create one with 'agents create AGENT_ID' first."
                    )
                print("Available registered agents:", file=stream)
                for idx, meta in enumerate(enabled_agents, 1):
                    print(f"  {idx}. {meta.id} ({meta.name})", file=stream)
                default_hint = f" [press Enter for {enabled_agents[0].id}]" if len(enabled_agents) == 1 else ""
                answer = input_fn(
                    f"Select agent(s) for workflow {workflow_id!r} (comma-separated IDs or numbers){default_hint}: "
                ).strip()
                if not answer and len(enabled_agents) == 1:
                    raw_items = [enabled_agents[0].id]
                elif answer:
                    for token in answer.split(","):
                        token = token.strip()
                        if token.isdigit() and 1 <= int(token) <= len(enabled_agents):
                            raw_items.append(enabled_agents[int(token) - 1].id)
                        else:
                            raw_items.append(token)
        else:
            available_ids = ", ".join(m.id for m in registry.list_enabled()) or "none"
            raise CliError(
                "workflow creation mode not specified in non-interactive mode. "
                "Pass agent IDs (e.g. 'workflows create WORKFLOW_ID AGENT_ID' or '--agents AGENT_ID,...') "
                "to create with agents, or pass '--empty' to create an empty workflow draft "
                f"(available agents: {available_ids})"
            )

    if empty:
        if register:
            raise CliError("cannot register an empty workflow without valid nodes; add at least one agent first")
        workflow = WorkflowDefinition.model_validate({
            "id": workflow_id,
            "version": resolved_version,
            "nodes": [],
            "edges": [],
        })
        comments = [
            "# Generated by agent_platform CLI (empty workflow draft).",
            f"# Add agents to this workflow with: python -m app.cli workflows add-agent {workflow_id} <AGENT_ID>",
        ]
        content = "\n".join(comments) + "\n" + yaml.safe_dump(
            workflow.model_dump(by_alias=True, exclude_unset=True), sort_keys=False
        )
        written = _write_new_files({workflow_path: content})
        return {
            "id": workflow_id,
            "version": resolved_version,
            "kind": "workflow",
            "status": "draft",
            "empty": True,
            "files": written,
            "nodes": [],
            "edges": [],
            "mappings": {},
            "registered": False,
            "registration_status": "disconnected",
            "message": (
                f"Empty workflow draft '{workflow_id}' (version {resolved_version}) created. "
                f"Add agents with: python -m app.cli workflows add-agent {workflow_id} <AGENT_ID>"
            ),
        }

    if not raw_items or any(not agent_id for agent_id in raw_items):
        available_ids = ", ".join(m.id for m in registry.list_enabled()) or "none"
        raise CliError(
            "--agents must contain one or more comma-separated agent IDs "
            f"(available agents: {available_ids})"
        )
    requested_agents = raw_items
    if len(requested_agents) != len(set(requested_agents)):
        raise CliError("--agents must not contain duplicate agent IDs")
    for agent_id in requested_agents:
        if not _WORKFLOW_ID.fullmatch(agent_id):
            raise CliError(f"invalid agent ID in --agents: {agent_id}")
    if node_id is not None and len(requested_agents) > 1:
        raise CliError("--node-id can only be used when creating a single-agent workflow")

    metadata_by_id: dict[str, Any] = {}
    for agent_id in requested_agents:
        try:
            registered = registry.get(agent_id)
        except Exception as exc:
            raise CliError(f"unknown or disabled agent: {agent_id}") from exc
        metadata_by_id[agent_id] = registered.metadata

    nodes_raw: list[dict[str, Any]] = []
    edges_raw: list[dict[str, Any]] = []
    mapping_reports: dict[str, list[dict[str, Any]]] = {}

    # First node: infer workflow_input.<field> for each declared input field when creating a workflow
    first_agent = requested_agents[0]
    first_node_id = _workflow_node_id(node_id or first_agent)
    first_fields = _manifest_input_fields(metadata_by_id[first_agent])
    first_mappings: dict[str, dict[str, Any]] = {}
    first_report: list[dict[str, Any]] = []
    if strict_mappings:
        if len(requested_agents) == 1:
            unknown_overrides = (set(path_overrides) | set(literal_overrides)) - set(first_fields)
            if unknown_overrides:
                raise CliError(f"not an input field of {first_agent}: {', '.join(sorted(unknown_overrides))}")
        for field in first_fields:
            if field in path_overrides and len(requested_agents) == 1:
                first_mappings[field] = {"path": path_overrides[field]}
                first_report.append({"field": field, "path": path_overrides[field], "origin": "override", "type_check": "verified"})
            elif field in literal_overrides and len(requested_agents) == 1:
                first_mappings[field] = {"literal": literal_overrides[field]}
                first_report.append({"field": field, "literal": literal_overrides[field], "origin": "override", "type_check": "verified"})
            else:
                first_mappings[field] = {"path": f"workflow_input.{field}"}
                first_report.append({"field": field, "path": f"workflow_input.{field}", "origin": "inferred", "type_check": "verified"})
    mapping_reports[first_node_id] = first_report
    nodes_raw.append({
        "id": first_node_id,
        "type": "agent",
        "agent_id": first_agent,
        "input_mappings": first_mappings,
    })

    other_wfs = _other_workflows(root, workflow_path)
    for index in range(1, len(requested_agents)):
        agent_id = requested_agents[index]
        prev_id = nodes_raw[index - 1]["id"]
        node_mappings: dict[str, dict[str, Any]] = {}
        node_report: list[dict[str, Any]] = []
        if strict_mappings:
            partial_wf = WorkflowDefinition.model_validate({
                "id": workflow_id,
                "version": resolved_version,
                "nodes": nodes_raw,
                "edges": edges_raw,
            })
            try:
                plan = plan_agent_mappings(
                    partial_wf, registry, agent_id, prev_id, other_wfs,
                    path_overrides if index == len(requested_agents) - 1 else None,
                    literal_overrides if index == len(requested_agents) - 1 else None,
                )
            except MappingError as exc:
                raise CliError(str(exc)) from exc
            decisions = list(plan.decisions)
            unresolved = []
            for question in plan.questions:
                if is_interactive and input_fn is not None:
                    answered = _ask_mapping(question, plan, input_fn, error_output)
                    if answered is not None:
                        decisions.append(answered)
                elif not question.required and question.reason == "schema_mismatch":
                    continue
                else:
                    unresolved.append(question)
            if unresolved:
                lines = "\n".join(f"  - {question.describe()}" for question in unresolved)
                raise CliError(
                    "developer input is required for these mappings; the workflow was not created:\n"
                    f"{lines}\nRun interactively, or pass --map FIELD=PATH or --literal FIELD=JSON."
                )
            order = {name: idx for idx, name in enumerate(plan.fields)}
            decisions.sort(key=lambda item: order[item.field])
            node_mappings = {item.field: item.mapping() for item in decisions}
            node_report = [item.describe() for item in decisions]
        nodes_raw.append({
            "id": agent_id,
            "type": "agent",
            "agent_id": agent_id,
            "input_mappings": node_mappings,
        })
        edges_raw.append({"from": prev_id, "to": agent_id})
        mapping_reports[agent_id] = node_report

    workflow = WorkflowDefinition.model_validate({
        "id": workflow_id,
        "version": resolved_version,
        "nodes": nodes_raw,
        "edges": edges_raw,
    })
    _check_workflow(workflow, registry, "workflow")

    comments = [
        "# Generated by agent_platform CLI.",
        "# Complete each node's input_mappings using workflow_input.* or node_outputs.* paths.",
        "# The examples below are comments only; replace them with real mappings from your workflow input.",
    ]
    for agent_id in requested_agents:
        fields = _manifest_input_fields(metadata_by_id[agent_id])
        if fields:
            comments.append(f"# {agent_id} input fields from its manifest: {', '.join(fields)}")
            for field in fields:
                comments.append(f"#   {field}: {{path: workflow_input.<field-for-{field}>}}")
        else:
            comments.append(f"# {agent_id} has no declared input fields; configure its mappings from the manifest contract.")
    comments.extend([
        "# Optional human approval extension:",
        "#   - id: approve",
        "#     type: human_approval",
        f"#     approval_payload_path: node_outputs.{requested_agents[-1]}",
        "#   Add an edge from the final agent to approve and choose approval_options if needed.",
        "# Optional conditional routing uses an edge condition with equals, not_equals, exists, or truthy.",
    ])
    content = "\n".join(comments) + "\n" + yaml.safe_dump(workflow.model_dump(by_alias=True, exclude_unset=True), sort_keys=False)
    written = _write_new_files({workflow_path: content})

    result: dict[str, Any] = {
        "id": workflow_id,
        "version": resolved_version,
        "kind": "workflow",
        "empty": False,
        "files": written,
        "nodes": [node.id for node in workflow.nodes],
        "edges": [{"from": edge.from_node, "to": edge.to} for edge in workflow.edges],
        "mappings": mapping_reports,
    }

    should_register = False
    if not empty and not no_register:
        if register is True or register is None:
            should_register = True

    if should_register and api is not None:
        try:
            registered = api.post("/v1/workflows", workflow.model_dump(by_alias=True, exclude_unset=True))
            result["registered"] = (
                {"id": registered.get("id", workflow.id), "version": registered.get("version", workflow.version)}
                if isinstance(registered, dict)
                else {"id": workflow.id, "version": workflow.version}
            )
            result["registration_status"] = "registered"
        except CliError as exc:
            if register is True:
                raise
            stream = error_output or sys.stderr
            msg = str(exc)
            if "could not connect to" in msg or "Connection refused" in msg or "ConnectError" in msg:
                print(
                    f"Note: API server is offline; workflow '{workflow_id}' was saved locally. "
                    f"Start the server and run 'python -m app.cli workflows register {workflow_id}' when ready.",
                    file=stream,
                )
            else:
                print(
                    f"Note: Workflow '{workflow_id}' saved locally; server registration skipped ({msg}).",
                    file=stream,
                )
            result["registered"] = False
            result["registration_status"] = "disconnected"
    elif should_register and api is None:
        if register is True:
            raise CliError("API client not configured; cannot register workflow")
        result["registered"] = False
        result["registration_status"] = "disconnected"
    else:
        result["registered"] = False
        result["registration_status"] = "disconnected"

    return result


def _scaffold_workflow(
    project_root: str | Path,
    workflow_id: str,
    agent_list: str | list[str] | None = None,
    version: str | None = "1.0.0",
    *,
    input_fn=None,
    is_interactive: bool = False,
    error_output: TextIO | None = None,
) -> dict[str, Any]:
    return _create_workflow(
        project_root,
        workflow_id,
        agent_list,
        version,
        strict_mappings=False,
        no_register=True,
        input_fn=input_fn,
        is_interactive=is_interactive,
        error_output=error_output,
    )


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 10.0, client: httpx.Client | None = None, token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        headers = {"Authorization": f"Bearer {token}"} if token else None
        self.client = client or httpx.Client(base_url=self.base_url, timeout=timeout, headers=headers)
        if client is not None and token:
            self.client.headers["Authorization"] = f"Bearer {token}"

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise CliError(f"could not connect to {self.base_url}: {exc}") from exc
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise CliError(f"API {response.status_code}: {detail}")
        try:
            return response.json()
        except ValueError as exc:
            raise CliError("API returned a non-JSON response") from exc

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, payload: Any) -> Any:
        return self.request("POST", path, json=payload)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)


def _read_document(path: str | Path) -> dict[str, Any]:
    document_path = Path(path)
    try:
        with document_path.open("r", encoding="utf-8") as handle:
            value = json.load(handle) if document_path.suffix.lower() == ".json" else yaml.safe_load(handle)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise CliError(f"could not read {document_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CliError(f"{document_path} must contain an object at its root")
    return value


def _print_json(value: Any, output: TextIO) -> None:
    print(json.dumps(redact_sensitive(value), indent=2, default=str), file=output)


def _run_summary(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload") or {}
    summary: dict[str, Any] = {
        "run_id": record.get("run_id"),
        "workflow_id": record.get("workflow_id"),
        "workflow_version": record.get("workflow_version"),
        "thread_id": record.get("thread_id"),
        "status": record.get("status"),
    }
    if payload.get("agent_id"):
        summary["agent_id"] = payload["agent_id"]
    agent_outputs = record.get("agent_outputs") or payload.get("agent_outputs")
    if agent_outputs is None and "node_outputs" in payload:
        agent_outputs = {
            k: v for k, v in payload["node_outputs"].items()
            if not (isinstance(v, dict) and "decision" in v and len(v) == 1)
        }
    if agent_outputs is not None:
        summary["agent_outputs"] = agent_outputs
    final_output = record.get("final_output") or payload.get("final_output")
    if record.get("status") in {"succeeded", "partially_succeeded"} and final_output is not None:
        summary["final_output"] = final_output
    for partial_key in ("blocked_by_node", "blocked_nodes", "skipped_nodes", "message"):
        val = record.get(partial_key) if partial_key in record else payload.get(partial_key)
        if val is not None:
            summary[partial_key] = val
    if record.get("status") == "failed":
        summary["error"] = payload.get("error", {"message": payload.get("message", "workflow failed")})
    if record.get("status") == "waiting_for_approval":
        summary["approval"] = payload.get("__interrupt__", payload.get("interrupt", "approval required"))
    return summary


def _interactive_agent_inputs(metadata: dict[str, Any], input_fn, output: TextIO) -> dict[str, Any]:
    schema = metadata.get("input_schema")
    properties = schema.get("properties") if isinstance(schema, dict) and schema.get("type", "object") == "object" else None
    required = schema.get("required", []) if isinstance(schema, dict) else []
    supported_types = {"string", "integer", "number", "boolean", "object", "array", "null"}
    if (
        not isinstance(properties, dict)
        or not properties
        or not isinstance(required, list)
        or any(not isinstance(key, str) or not isinstance(value, dict) or value.get("type") not in supported_types for key, value in properties.items())
        or any(key not in properties for key in required)
    ):
        raw = input_fn("Enter agent input as a JSON object: ")
        try:
            inputs = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CliError("agent input must be a JSON object because its input schema is missing or ambiguous") from exc
        if not isinstance(inputs, dict):
            raise CliError("agent input must be a JSON object")
        return inputs

    inputs: dict[str, Any] = {}
    required_fields = set(required)
    for field, field_schema in properties.items():
        field_type = field_schema["type"]
        if field == "text" and field_type == "string":
            prompt = "Enter the text you want to analyze: "
        elif field_schema.get("title"):
            prompt = f"{field_schema['title']}: "
        else:
            label = field.replace("_", " ")
            optional_note = " (optional; press Enter to skip)" if field not in required_fields else ""
            prompt = f"Enter {label}{optional_note}: "
        raw = input_fn(prompt)
        if raw == "" and field != "text":
            if "default" in field_schema:
                inputs[field] = field_schema["default"]
            elif field in required_fields:
                raise CliError(f"a value is required for {field}")
            continue
        if field_type == "string":
            value: Any = raw
        else:
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise CliError(f"{field} must be entered as a JSON {field_type} value") from exc
        inputs[field] = value
    return inputs



def _parse_assignments(items: list[str] | None, option: str, *, literal: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items or []:
        name, separator, value = item.partition("=")
        name, value = name.strip(), value.strip()
        if not separator or not name or not value:
            raise CliError(f"{option} must look like FIELD=VALUE: {item!r}")
        if name in result:
            raise CliError(f"{option} was given more than once for {name}")
        if literal:
            try:
                result[name] = json.loads(value)
            except json.JSONDecodeError as exc:
                raise CliError(f"{option} value for {name} must be valid JSON: {exc}") from exc
        else:
            result[name] = value
    return result


def _workflow_file(root: Path, reference: str) -> Path:
    candidate = Path(reference)
    if candidate.suffix.lower() in {".yaml", ".yml"} or candidate.is_file():
        for path in (candidate, root / candidate):
            if path.is_file():
                return path.resolve()
        raise CliError(f"workflow file not found: {reference}")
    workflow_id = _workflow_id(reference)
    for suffix in (".yaml", ".yml"):
        path = root / "workflow_definitions" / f"{workflow_id}{suffix}"
        if path.is_file():
            return path.resolve()
    raise CliError(f"workflow definition not found: {root / 'workflow_definitions' / (workflow_id + '.yaml')}")


def _other_workflows(root: Path, exclude: Path) -> list[WorkflowDefinition]:
    found: list[WorkflowDefinition] = []
    directory = root / "workflow_definitions"
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.y*ml")):
        if path.resolve() == exclude:
            continue
        try:
            found.append(WorkflowDefinition.model_validate(_read_document(path)))
        except (CliError, ValidationError):
            continue
    return found


def _check_workflow(definition: WorkflowDefinition, registry: AgentRegistry, label: str) -> None:
    try:
        WorkflowBuilder(registry).build(definition)
    except (ValidationError, ValueError, KeyError, ImportError) as exc:
        raise CliError(f"{label} is invalid: {exc}") from exc
    except Exception as exc:
        raise CliError(f"{label} is invalid: {exc}") from exc


def _ask_mapping(question, plan, input_fn, error_output: TextIO | None):
    stream = error_output or sys.stderr
    print(f"Mapping needed: {question.describe()}", file=stream)
    for index, candidate in enumerate(question.candidates, 1):
        print(f"  {index}. {candidate.label()}", file=stream)
    suffix = ", or press Enter to skip: " if not question.required else ": "
    prompt = f"Source for {question.field} (number, path, or literal:<json>){suffix}"
    for _ in range(3):
        answer = input_fn(prompt).strip()
        if not answer:
            if not question.required:
                return None
            print(f"{question.field} is required.", file=stream)
            continue
        try:
            if answer.isdigit() and 1 <= int(answer) <= len(question.candidates):
                return plan.decide_path(question.field, question.candidates[int(answer) - 1].path, "answered")
            if answer.startswith("literal:"):
                return plan.decide_literal(question.field, json.loads(answer[len("literal:"):]), "answered")
            return plan.decide_path(question.field, answer, "answered")
        except (MappingError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=stream)
    raise CliError(f"no valid mapping was provided for {question.field}; workflow unchanged")


def _add_agent_to_workflow(
    project_root: str | Path,
    workflow_ref: str,
    agent_id: str | None,
    api: "ApiClient",
    *,
    after: str | None = None,
    node_id: str | None = None,
    maps: list[str] | None = None,
    literals: list[str] | None = None,
    version: str | None = None,
    input_fn=None,
    is_interactive: bool = False,
    error_output: TextIO | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    path_overrides = _parse_assignments(maps, "--map")
    literal_overrides = _parse_assignments(literals, "--literal", literal=True)
    workflow_path = _workflow_file(root, workflow_ref)
    try:
        original_text = workflow_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(f"could not read {workflow_path}: {exc}") from exc
    raw = _read_document(workflow_path)
    try:
        current = WorkflowDefinition.model_validate(raw)
    except ValidationError as exc:
        raise CliError(f"invalid workflow {workflow_path}: {exc}") from exc

    with project_plugin_namespace(root):
        registry = _local_registry(root)
        if current.nodes:
            _check_workflow(current, registry, "existing workflow")
        elif current.edges:
            raise CliError("existing workflow is invalid: edge references unknown node")
        if not agent_id:
            if is_interactive and input_fn is not None:
                enabled_agents = registry.list_enabled()
                if not enabled_agents:
                    raise CliError(
                        "no registered agents were found in plugins/manifests. "
                        "Connect an agent with 'agents connect PATH' or create one with 'agents create AGENT_ID' first."
                    )
                stream = error_output or sys.stderr
                print("Available registered agents:", file=stream)
                for idx, meta in enumerate(enabled_agents, 1):
                    print(f"  {idx}. {meta.id} ({meta.name})", file=stream)
                answer = input_fn(f"Select agent to add to workflow {current.id!r} (ID or number): ").strip()
                if answer.isdigit() and 1 <= int(answer) <= len(enabled_agents):
                    agent_id = enabled_agents[int(answer) - 1].id
                else:
                    agent_id = answer
            if not agent_id:
                raise CliError("agent_id is required; pass 'workflows add-agent WORKFLOW_ID AGENT_ID'")

        agent_id = _connected_agent_id(agent_id)
        new_id = _workflow_node_id(node_id or agent_id)
        try:
            registered_agent = registry.get(agent_id)
        except Exception as exc:
            raise CliError(f"unknown or disabled agent: {agent_id}") from exc

        nodes = {node.id: node for node in current.nodes}
        existing_node = nodes.get(new_id)
        if existing_node is not None and (existing_node.type != "agent" or existing_node.agent_id != agent_id):
            raise CliError(f"workflow node {new_id!r} already exists and is not agent {agent_id}; choose another --node-id")

        decisions: list[Decision] = []
        skipped: list[str] = []

        if not current.nodes:
            if after is not None:
                raise CliError(f"--after node not found: {after}; workflow has no existing nodes")
            existing_edge = True
            first_fields = _manifest_input_fields(registered_agent.metadata)
            clash = sorted(set(path_overrides) & set(literal_overrides))
            if clash:
                raise CliError(f"field given both --map and --literal: {', '.join(clash)}")
            unknown_overrides = sorted((set(path_overrides) | set(literal_overrides)) - set(first_fields))
            if unknown_overrides:
                raise CliError(
                    f"{unknown_overrides[0]!r} is not an input field of the selected agent (fields: {', '.join(first_fields) or 'none'})"
                )
            for field in first_fields:
                if field in path_overrides:
                    path_val = path_overrides[field]
                    if not path_val.startswith("workflow_input."):
                        raise CliError(f"first workflow node cannot map from {path_val!r}; use workflow_input.<field>")
                    decisions.append(Decision(field, path=path_val, origin="override", type_check="verified"))
                elif field in literal_overrides:
                    decisions.append(
                        Decision(
                            field,
                            literal=literal_overrides[field],
                            is_literal=True,
                            origin="override",
                            type_check="not-applicable",
                        )
                    )
                else:
                    decisions.append(Decision(field, path=f"workflow_input.{field}", origin="inferred", type_check="verified"))
        else:
            if after is None:
                if existing_node is not None:
                    sources = sorted({edge.from_node for edge in current.edges if edge.to == new_id})
                    candidates = sources
                else:
                    candidates = [node.id for node in current.nodes if not any(edge.from_node == node.id for edge in current.edges)]
                if len(candidates) != 1:
                    raise CliError("--after is required; candidate preceding nodes: " + (", ".join(candidates) or "none"))
                after = candidates[0]
            if after not in nodes:
                raise CliError(f"--after node not found: {after}; workflow nodes: {', '.join(nodes)}")
            if after == new_id:
                raise CliError("a node cannot come after itself")
            existing_edge = any(edge.from_node == after and edge.to == new_id for edge in current.edges)
            if not existing_edge and any(edge.from_node == after and edge.to != new_id for edge in current.edges):
                raise CliError(
                    f"node {after!r} already has outgoing edges; refusing to branch or reroute the workflow automatically"
                )

            try:
                plan = plan_agent_mappings(
                    current, registry, agent_id, after, _other_workflows(root, workflow_path),
                    path_overrides, literal_overrides,
                )
            except MappingError as exc:
                raise CliError(str(exc)) from exc

            skipped = list(plan.skipped_optional)
            if existing_node is None:
                decisions = list(plan.decisions)
                unresolved = []
                for question in plan.questions:
                    if is_interactive and input_fn is not None:
                        answered = _ask_mapping(question, plan, input_fn, error_output)
                        if answered is None:
                            skipped.append(question.field)
                        else:
                            decisions.append(answered)
                    elif not question.required and question.reason == "schema_mismatch":
                        skipped.append(question.field)
                    else:
                        unresolved.append(question)
                if unresolved:
                    lines = "\n".join(f"  - {question.describe()}" for question in unresolved)
                    raise CliError(
                        "developer input is required for these mappings; the workflow was not changed:\n"
                        f"{lines}\nRun interactively, or pass --map FIELD=PATH (e.g. workflow_input.text, "
                        "node_outputs.<node>.<field>) or --literal FIELD=JSON."
                    )
                order = {name: index for index, name in enumerate(plan.fields)}
                decisions.sort(key=lambda item: order[item.field])
            else:
                decisions = [item for item in plan.decisions if item.origin == "override"]

        updated = copy.deepcopy(raw)
        node_added = existing_node is None
        edge_added = (after is not None) and (not existing_edge)
        if node_added:
            updated.setdefault("nodes", []).append({
                "id": new_id, "type": "agent", "agent_id": agent_id,
                "input_mappings": {item.field: item.mapping() for item in decisions},
            })
        elif decisions:
            node_raw = next(item for item in updated["nodes"] if item.get("id") == new_id)
            node_raw.setdefault("input_mappings", {}).update({item.field: item.mapping() for item in decisions})
        if edge_added:
            updated.setdefault("edges", []).append({"from": after, "to": new_id})
        changed = updated != raw
        previous_version = current.version
        if changed:
            updated["version"] = version or _bump_patch(previous_version)
        try:
            definition = WorkflowDefinition.model_validate(updated)
        except ValidationError as exc:
            raise CliError(f"updated workflow is invalid: {exc}") from exc
        _check_workflow(definition, registry, "updated workflow")

    if changed:
        header: list[str] = []
        for line in original_text.splitlines():
            if line.startswith("#") or (header and not line.strip()):
                header.append(line.rstrip("\r"))
            else:
                break
        while header and not header[-1].strip():
            header.pop()
        body = yaml.safe_dump(updated, sort_keys=False, allow_unicode=True)
        content = ("\n".join(header) + "\n" if header else "") + body
        temporary = workflow_path.with_name(workflow_path.name + ".tmp")
        try:
            temporary.write_text(content, encoding="utf-8", newline="\n")
            os.replace(temporary, workflow_path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise CliError(f"could not write {workflow_path}: {exc}") from exc

    try:
        registered = api.post("/v1/workflows", definition.model_dump(by_alias=True, exclude_unset=True))
    except CliError as exc:
        msg = str(exc)
        if "API 409:" in msg and "different definition" in msg:
            # Server already has this workflow at a different version — bump and retry once
            bumped_version = _bump_patch(definition.version)
            updated["version"] = bumped_version
            try:
                definition = WorkflowDefinition.model_validate(updated)
            except ValidationError as exc2:
                raise CliError(f"workflow is invalid after version bump: {exc2}") from exc2
            # Re-read existing file headers so we preserve comments
            try:
                existing_text = workflow_path.read_text(encoding="utf-8")
            except OSError:
                existing_text = ""
            existing_header: list[str] = []
            for line in existing_text.splitlines():
                if line.startswith("#") or (existing_header and not line.strip()):
                    existing_header.append(line.rstrip("\r"))
                else:
                    break
            while existing_header and not existing_header[-1].strip():
                existing_header.pop()
            bump_body = yaml.safe_dump(updated, sort_keys=False, allow_unicode=True)
            bump_content = ("\n".join(existing_header) + "\n" if existing_header else "") + bump_body
            tmp_path = workflow_path.with_name(workflow_path.name + ".tmp")
            try:
                tmp_path.write_text(bump_content, encoding="utf-8", newline="\n")
                os.replace(tmp_path, workflow_path)
            except OSError as exc2:
                tmp_path.unlink(missing_ok=True)
                raise CliError(f"could not write {workflow_path} after version bump: {exc2}") from exc2
            try:
                registered = api.post("/v1/workflows", definition.model_dump(by_alias=True, exclude_unset=True))
            except CliError as exc2:
                raise CliError(
                    f"workflow file was updated but registration failed after version bump: {exc2}. "
                    "Fix the cause and repeat the command; if the agent was connected after the API started, restart the API first."
                ) from exc2
        else:
            saved = "was updated" if changed else "is unchanged"
            raise CliError(
                f"workflow file {saved} but registration failed: {exc}. Fix the cause and repeat the command; "
                "if the agent was connected after the API started, restart the API first."
            ) from exc

    if existing_node is None:
        mapping_report = [item.describe() for item in decisions]
    else:
        mapping_report = [
            {**({"literal": value.literal} if value.path is None else {"path": value.path}), "field": key, "origin": "existing"}
            for key, value in next(node for node in definition.nodes if node.id == new_id).input_mappings.items()
        ]
    return {
        "workflow": definition.id,
        "workflow_file": str(workflow_path),
        "agent_id": agent_id,
        "node_id": new_id,
        "after": after,
        "node_added": node_added,
        "edge_added": edge_added,
        "changed": changed,
        "previous_version": previous_version,
        "version": definition.version,
        "mappings": mapping_report,
        "unmapped_optional_fields": skipped,
        "validated": True,
        "registered": {"id": registered.get("id", definition.id), "version": registered.get("version", definition.version)}
        if isinstance(registered, dict) else {"id": definition.id, "version": definition.version},
    }


def _workflow_node_id(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", value):
        raise CliError("node ID must start with a lowercase letter and contain only lowercase letters, digits, hyphens, or underscores")
    return value


def _check_local_empty_workflow(project_root: str | Path | None, workflow_id: str) -> None:
    root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[1]
    for suffix in (".yaml", ".yml"):
        candidate = root / "workflow_definitions" / f"{workflow_id}{suffix}"
        if candidate.is_file():
            try:
                raw = _read_document(candidate)
                if isinstance(raw, dict) and not raw.get("nodes"):
                    raise CliError(
                        f"workflow '{workflow_id}' has no valid nodes (empty workflow draft); "
                        f"add at least one agent with 'workflows add-agent {workflow_id} AGENT_ID'"
                    )
            except CliError as exc:
                if "has no valid nodes" in str(exc):
                    raise


def _interactive_workflow_inputs(
    api: "ApiClient",
    workflow_id: str,
    input_fn,
    error_output: TextIO | None,
    *,
    allow_partial: bool = True,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Prompt for a workflow's initial input using its registered definition and agent schemas."""
    stream = error_output or sys.stderr
    try:
        workflow = api.get(f"/v1/workflows/{quote(workflow_id, safe='')}")
    except CliError as exc:
        if "API 404:" in str(exc):
            _check_local_empty_workflow(project_root, workflow_id)
        raise
    nodes_list = [node for node in workflow.get("nodes", []) if isinstance(node, dict)]
    if not nodes_list:
        raise CliError(
            f"workflow '{workflow_id}' has no valid nodes; "
            f"add at least one agent with 'workflows add-agent {workflow_id} AGENT_ID'"
        )
    disconnected_ids = {
        str(node.get("id"))
        for node in nodes_list
        if node.get("type") == "agent" and node.get("status") == "disconnected"
    }
    disconnected_nodes = [
        f"{node.get('id')} (agent '{node.get('agent_id')}' is disconnected)"
        for node in nodes_list
        if node.get("type") == "agent" and node.get("status") == "disconnected"
    ]
    if disconnected_nodes and not allow_partial:
        raise CliError(
            f"workflow '{workflow_id}' cannot be executed because the following nodes are unavailable: "
            + ", ".join(disconnected_nodes)
        )
    eligible_node_ids: set[str] | None = None
    if allow_partial and disconnected_ids:
        incoming_sources: dict[str, list[str]] = {str(n.get("id")): [] for n in nodes_list if n.get("id")}
        for edge in workflow.get("edges", []):
            if isinstance(edge, dict):
                src = str(edge.get("from") or edge.get("from_node") or "")
                dst = str(edge.get("to") or "")
                if src and dst in incoming_sources and src not in incoming_sources[dst]:
                    incoming_sources[dst].append(src)
        eligible: set[str] = set()
        changed = True
        while changed:
            changed = False
            for node in nodes_list:
                nid = str(node.get("id") or "")
                if not nid or nid in eligible or nid in disconnected_ids:
                    continue
                if any(src not in eligible for src in incoming_sources.get(nid, [])):
                    continue
                mapping_blocked = False
                for mapping in (node.get("input_mappings") or {}).values():
                    path = mapping.get("path") if isinstance(mapping, dict) else None
                    if isinstance(path, str) and path.startswith("node_outputs."):
                        ref_node = path.split(".")[1]
                        if ref_node not in eligible:
                            mapping_blocked = True
                            break
                if mapping_blocked:
                    continue
                eligible.add(nid)
                changed = True
        if not eligible:
            raise CliError(
                f"workflow '{workflow_id}' cannot be executed because the following nodes are unavailable: "
                + ", ".join(disconnected_nodes)
            )
        eligible_node_ids = eligible
    properties: dict[str, dict[str, Any]] = {}
    required: set[str] = set()
    unsafe = False
    schemas: dict[str, dict[str, Any]] = {}

    def agent_schema(agent: str) -> dict[str, Any]:
        if agent not in schemas:
            try:
                metadata = api.get(f"/v1/agents/{quote(agent, safe='')}")
            except CliError:
                metadata = {}
            value = metadata.get("input_schema") if isinstance(metadata, dict) else None
            schemas[agent] = value if isinstance(value, dict) else {}
        return schemas[agent]

    for node in workflow.get("nodes", []):
        if node.get("type") != "agent":
            continue
        if allow_partial and (
            node.get("status") == "disconnected"
            or (eligible_node_ids is not None and str(node.get("id")) not in eligible_node_ids)
        ):
            continue
        schema = agent_schema(str(node.get("agent_id")))
        agent_properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        agent_required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key, mapping in (node.get("input_mappings") or {}).items():
            path = mapping.get("path") if isinstance(mapping, dict) else None
            if not isinstance(path, str) or not path.startswith("workflow_input."):
                continue
            parts = path.split(".")[1:]
            if len(parts) != 1:
                unsafe = True
                continue
            declared = agent_properties.get(key)
            field_schema = {"type": declared["type"]} if isinstance(declared, dict) and isinstance(declared.get("type"), str) else {}
            if parts[0] in properties:
                if allow_partial and not field_schema and properties[parts[0]]:
                    field_schema = properties[parts[0]]
                elif allow_partial and field_schema and not properties[parts[0]]:
                    pass
                elif properties[parts[0]] != field_schema:
                    field_schema = {}
            properties[parts[0]] = field_schema
            if key in agent_required:
                required.add(parts[0])
    for edge in workflow.get("edges", []):
        condition = edge.get("condition") if isinstance(edge, dict) else None
        if isinstance(condition, dict) and str(condition.get("path", "")).startswith("workflow_input"):
            parts = str(condition["path"]).split(".")[1:]
            if len(parts) == 1:
                properties.setdefault(parts[0], {})
            else:
                unsafe = True

    if not properties and not unsafe:
        print(f"Workflow {workflow_id} declares no initial input fields; starting with an empty input.", file=stream)
        return {}
    if unsafe or any(not value for value in properties.values()):
        raw = input_fn(f"Enter the initial input for workflow {workflow_id} as a JSON object: ")
        try:
            inputs = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CliError("workflow input must be a JSON object") from exc
        if not isinstance(inputs, dict):
            raise CliError("workflow input must be a JSON object")
        return inputs
    return _interactive_agent_inputs(
        {"input_schema": {"type": "object", "properties": properties, "required": sorted(required)}},
        input_fn, stream,
    )


def _event_summary(event: dict[str, Any], include_payload: bool) -> dict[str, Any]:
    value = {key: event.get(key) for key in ("run_id", "node_id", "status", "created_at")}
    payload = event.get("payload") or {}
    if event.get("status") == "failed":
        value["error"] = payload.get("error", payload)
    if event.get("status") in {"skipped", "blocked"} and isinstance(payload, dict) and "reason" in payload:
        value["reason"] = payload["reason"]
    if include_payload:
        value["payload"] = payload
    return value


def _validate_manifest(path: str, kind: str) -> dict[str, Any]:
    value = _read_document(path)
    try:
        manifest = AgentManifest.model_validate(value) if kind == "agent" else ToolManifest.model_validate(value)
    except ValidationError as exc:
        raise CliError(f"invalid {kind} manifest: {exc}") from exc
    if not manifest.entrypoint.startswith("plugins."):
        raise CliError(f"untrusted {kind} entrypoint: {manifest.entrypoint}")
    return manifest.model_dump()


def _validate_tool_id(project_root: str | Path, tool_id: str) -> dict[str, Any]:
    valid_id = _scaffold_id(tool_id)
    root = Path(project_root).expanduser().resolve()
    for suffix in (".yaml", ".yml"):
        manifest_path = root / "plugins" / "tool_manifests" / f"{valid_id}{suffix}"
        if manifest_path.is_file():
            return _validate_manifest(str(manifest_path), "tool")
    raise CliError(f"tool manifest not found for ID: {valid_id}")


def _resolve_workflow_target(target: str, project_root: str | Path | None = None) -> Path:
    candidate = Path(target)
    if candidate.exists() or candidate.suffix.lower() in {".yaml", ".yml", ".json"}:
        return candidate
    root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[1]
    return _workflow_file(root, target)


def _validate_workflow(target: str, project_root: str | Path | None = None) -> WorkflowDefinition:
    root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[1]
    resolved_path = _resolve_workflow_target(target, root)
    try:
        workflow = WorkflowDefinition.model_validate(_read_document(resolved_path))
        WorkflowBuilder(_local_registry(root)).build(workflow)
        return workflow
    except (ValidationError, ValueError, KeyError, ImportError) as exc:
        raise CliError(f"invalid workflow: {exc}") from exc


def _register_workflow(
    project_root: str | Path | None,
    target: str,
    api: "ApiClient",
    *,
    version: str | None = None,
) -> Any:
    root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[1]
    resolved_path = _resolve_workflow_target(target, root)
    workflow = _validate_workflow(str(resolved_path), root)
    if version is not None:
        resolved_ver = _default_workflow_version(root, version)
        if workflow.version != resolved_ver:
            workflow = workflow.model_copy(update={"version": resolved_ver})
            if resolved_path.is_file():
                _write_workflow_definition_file(resolved_path, workflow)
    payload = workflow.model_dump(by_alias=True, exclude_unset=True)
    try:
        return api.post("/v1/workflows", payload)
    except CliError as exc:
        if version is None and "API 409:" in str(exc) and "different definition" in str(exc):
            bumped_version = _bump_patch(workflow.version)
            workflow = workflow.model_copy(update={"version": bumped_version})
            if resolved_path.is_file():
                _write_workflow_definition_file(resolved_path, workflow)
            return api.post("/v1/workflows", workflow.model_dump(by_alias=True, exclude_unset=True))
        raise


def _list_workflows(project_root: str | Path | None, api: "ApiClient") -> list[dict[str, Any]]:
    root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[1]
    local_map = _saved_workflows(root)
    merged: dict[str, dict[str, Any]] = {}
    for wf_id, (wf, path) in sorted(local_map.items()):
        entry = wf.model_dump(by_alias=True, exclude_unset=True)
        if path is not None:
            entry["workflow_file"] = str(path)
        entry["registered"] = False
        entry["registration_status"] = "disconnected"
        merged[wf_id] = entry
    try:
        remote = api.get("/v1/workflows")
        if isinstance(remote, list):
            for item in remote:
                if isinstance(item, dict) and item.get("id"):
                    wf_id = str(item["id"])
                    if wf_id in merged and "workflow_file" in merged[wf_id]:
                        merged[wf_id] = {
                            **item,
                            "workflow_file": merged[wf_id]["workflow_file"],
                            "registered": True,
                            "registration_status": "registered",
                        }
                    else:
                        merged[wf_id] = {
                            **item,
                            "registered": True,
                            "registration_status": "registered",
                        }
    except CliError as exc:
        if "could not connect to" not in str(exc):
            raise
    return [merged[key] for key in sorted(merged)]


def _show_workflow(project_root: str | Path | None, workflow_id: str, api: "ApiClient") -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve() if project_root else None
    local_path: Path | None = None
    if root is not None:
        for suffix in (".yaml", ".yml"):
            candidate = root / "workflow_definitions" / f"{workflow_id}{suffix}"
            if candidate.is_file():
                local_path = candidate.resolve()
                break
    try:
        remote = api.get(f"/v1/workflows/{quote(workflow_id, safe='')}")
        if isinstance(remote, dict):
            result = {**remote, "registered": True, "registration_status": "registered"}
            if local_path is not None:
                result["workflow_file"] = str(local_path)
            return result
        return remote
    except CliError as exc:
        if "API 404:" in str(exc) and local_path is not None and local_path.is_file():
            raw = _read_document(local_path)
            wf = WorkflowDefinition.model_validate(raw)
            return {
                **wf.model_dump(by_alias=True, exclude_unset=True),
                "registered": False,
                "registration_status": "disconnected",
                "workflow_file": str(local_path),
            }
        raise


def _resolve_workflow_id_and_local_path(target: str, root: Path) -> tuple[str, Path | None]:
    candidate = Path(target)
    local_path: Path | None = None
    if candidate.suffix.lower() in {".yaml", ".yml"} or candidate.is_file() or (root / candidate).is_file():
        for path in (candidate, root / candidate):
            if path.is_file():
                local_path = path.resolve()
                break
        if local_path is not None:
            try:
                raw = _read_document(local_path)
                workflow_id = _workflow_id(str(raw.get("id") or local_path.stem))
            except CliError:
                workflow_id = _workflow_id(local_path.stem)
        else:
            workflow_id = _workflow_id(candidate.stem)
    else:
        workflow_id = _workflow_id(target)
        for suffix in (".yaml", ".yml"):
            path = root / "workflow_definitions" / f"{workflow_id}{suffix}"
            if path.is_file():
                local_path = path.resolve()
                break
    return workflow_id, local_path


def _disconnect_workflow(
    project_root: str | Path | None,
    target: str,
    api: "ApiClient",
    *,
    yes: bool = False,
    db_path: str | Path | None = None,
    input_fn=None,
    is_interactive: bool = False,
    error_output: TextIO | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[1]
    workflow_id, local_path = _resolve_workflow_id_and_local_path(target, root)

    db_file: Path | None = None
    if db_path:
        db_file = Path(db_path).expanduser().resolve()
    elif (root / "agent_platform.db").is_file():
        db_file = (root / "agent_platform.db").resolve()

    repo: ExecutionRepository | None = None
    if db_file and db_file.is_file():
        try:
            repo = ExecutionRepository(str(db_file))
        except Exception:
            repo = None

    try:
        db_inspection = repo.inspect_workflow_records(workflow_id) if repo else {
            "registered": False,
            "active_version": None,
            "versions": [],
            "version_count": 0,
            "run_ids": [],
            "run_count": 0,
            "event_count": 0,
            "checkpoint_count": 0,
        }
        registered_in_db = bool(db_inspection["registered"])
        registered_on_server = False
        remote_wf: dict[str, Any] | None = None
        try:
            fetched = api.get(f"/v1/workflows/{quote(workflow_id, safe='')}")
            registered_on_server = True
            if isinstance(fetched, dict):
                remote_wf = fetched
        except CliError as exc:
            msg = str(exc)
            if "API 404:" in msg or "could not connect to" in msg:
                registered_on_server = False
            else:
                raise

        if local_path is None and not registered_on_server and not registered_in_db and db_inspection["version_count"] == 0:
            raise CliError(f"workflow not found: {workflow_id}")

        referenced_agents: list[str] = []
        wf_source_dict: dict[str, Any] | None = None
        if local_path is not None and local_path.is_file():
            try:
                wf_source_dict = _read_document(local_path)
            except Exception:
                wf_source_dict = None
        if wf_source_dict is None and remote_wf is not None:
            wf_source_dict = remote_wf
        if wf_source_dict is not None:
            referenced_agents = sorted({
                str(n.get("agent_id"))
                for n in wf_source_dict.get("nodes", [])
                if isinstance(n, dict) and n.get("type", "agent") == "agent" and n.get("agent_id")
            })

        stream = error_output or sys.stderr
        if not registered_on_server and not registered_in_db:
            print(
                f"Workflow '{workflow_id}' is already disconnected (unregistered from the active API registry). "
                "Its local workflow definition and execution history remain preserved.",
                file=stream,
            )
            return {
                "id": workflow_id,
                "workflow_id": workflow_id,
                "status": "disconnected",
                "already_disconnected": True,
                "registered": False,
                "registration_status": "disconnected",
                "unregistered_from_server": False,
                "workflow_file": str(local_path) if local_path else None,
                "retained": {
                    "local_definition": str(local_path) if local_path else None,
                    "node_configuration": True,
                    "mappings": True,
                    "history": True,
                    "runs": db_inspection["run_count"],
                    "events": db_inspection["event_count"],
                    "agents": referenced_agents,
                },
                "message": (
                    f"Workflow '{workflow_id}' is already disconnected (unregistered). "
                    "The workflow definition and execution history are preserved."
                ),
            }

        print(f"Summary of workflow disconnection for '{workflow_id}':", file=stream)
        print(
            f"  - Action: Unregister workflow '{workflow_id}' from the active API workflow registry "
            "(new runs via the registered workflow API will be disabled)",
            file=stream,
        )
        print("  - Preserved resources (will NOT be deleted):", file=stream)
        print(
            f"    * Local YAML workflow definition, node configuration, and mappings: "
            f"{local_path if local_path else 'not present on disk'}",
            file=stream,
        )
        print(
            f"    * Referenced agents (remain untouched): {', '.join(referenced_agents) if referenced_agents else 'none'}",
            file=stream,
        )
        print(
            f"    * Historical workflow execution records: {db_inspection['run_count']} run(s), "
            f"{db_inspection['event_count']} event(s) (preserved)",
            file=stream,
        )

        if not yes:
            if not is_interactive or input_fn is None:
                raise CliError(
                    "workflow disconnection requires explicit confirmation; rerun with --yes or confirm interactively"
                )
            _confirm_action(
                f"Disconnect workflow '{workflow_id}'? The workflow definition and execution history will be preserved. "
                "Continue? [y/N]: ",
                input_fn,
                cancel_message="workflow disconnection cancelled; registration state was not modified",
            )

        unregistered_from_server = False
        if registered_on_server:
            api.post(f"/v1/workflows/{quote(workflow_id, safe='')}/disconnect", {})
            unregistered_from_server = True

        if repo is not None:
            if repo.unregister_workflow(workflow_id):
                unregistered_from_server = True

        return {
            "id": workflow_id,
            "workflow_id": workflow_id,
            "status": "disconnected",
            "already_disconnected": False,
            "registered": False,
            "registration_status": "disconnected",
            "unregistered_from_server": unregistered_from_server,
            "workflow_file": str(local_path) if local_path else None,
            "retained": {
                "local_definition": str(local_path) if local_path else None,
                "node_configuration": True,
                "mappings": True,
                "history": True,
                "runs": db_inspection["run_count"],
                "events": db_inspection["event_count"],
                "agents": referenced_agents,
            },
            "message": (
                f"Workflow '{workflow_id}' was disconnected from the active registry. "
                "The workflow definition and execution history have been preserved."
            ),
        }
    finally:
        if repo:
            try:
                repo.close()
            except Exception:
                pass


def _delete_workflow(
    project_root: str | Path | None,
    target: str,
    api: "ApiClient",
    *,
    yes: bool = False,
    db_path: str | Path | None = None,
    input_fn=None,
    is_interactive: bool = False,
    error_output: TextIO | None = None,
) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve() if project_root else Path(__file__).resolve().parents[1]
    workflow_id, local_path = _resolve_workflow_id_and_local_path(target, root)

    db_file: Path | None = None
    if db_path:
        db_file = Path(db_path).expanduser().resolve()
    elif (root / "agent_platform.db").is_file():
        db_file = (root / "agent_platform.db").resolve()

    repo: ExecutionRepository | None = None
    if db_file and db_file.is_file():
        try:
            repo = ExecutionRepository(str(db_file))
        except Exception:
            repo = None

    try:
        db_inspection = repo.inspect_workflow_records(workflow_id) if repo else {
            "registered": False,
            "active_version": None,
            "versions": [],
            "version_count": 0,
            "run_ids": [],
            "run_count": 0,
            "event_count": 0,
            "checkpoint_count": 0,
        }
        registered_in_db = bool(db_inspection["registered"])
        registered_on_server = False
        remote_wf: dict[str, Any] | None = None
        try:
            fetched = api.get(f"/v1/workflows/{quote(workflow_id, safe='')}")
            registered_on_server = True
            if isinstance(fetched, dict):
                remote_wf = fetched
        except CliError as exc:
            msg = str(exc)
            if "API 404:" in msg or "could not connect to" in msg:
                registered_on_server = False
            else:
                raise

        if local_path is None and not registered_on_server and not registered_in_db and db_inspection["version_count"] == 0:
            raise CliError(f"workflow not found: {workflow_id}")

        wf_source_dict: dict[str, Any] | None = None
        if local_path is not None and local_path.is_file():
            try:
                wf_source_dict = _read_document(local_path)
            except Exception:
                wf_source_dict = None
        if wf_source_dict is None and remote_wf is not None:
            wf_source_dict = remote_wf

        referenced_agents: list[str] = []
        if wf_source_dict is not None:
            referenced_agents = sorted({
                str(n.get("agent_id"))
                for n in wf_source_dict.get("nodes", [])
                if isinstance(n, dict) and n.get("type", "agent") == "agent" and n.get("agent_id")
            })

        other_workflows = sorted([
            wf_id for wf_id in _saved_workflows(root, repo).keys() if wf_id != workflow_id
        ])

        versions_list = list(db_inspection["versions"])
        if not versions_list and wf_source_dict and wf_source_dict.get("version"):
            versions_list = [str(wf_source_dict["version"])]

        stream = error_output or sys.stderr
        print(
            f"WARNING: This permanently deletes the workflow '{workflow_id}' and the following associated resources:",
            file=stream,
        )
        print(f"  - Workflow to delete: {workflow_id}", file=stream)
        print(
            f"  - Local workflow YAML definition: {local_path if local_path is not None else 'not present on disk'}",
            file=stream,
        )
        print(
            f"  - Registered API workflow entry: "
            f"{workflow_id if (registered_on_server or registered_in_db) else 'not currently registered'}",
            file=stream,
        )
        print(
            f"  - Persisted workflow version metadata: "
            f"{', '.join(versions_list) if (registered_on_server or registered_in_db or db_inspection['version_count'] > 0) else 'none'}",
            file=stream,
        )
        print(
            f"  - Workflow execution runs: {db_inspection['run_count']} run(s) (will be permanently deleted)",
            file=stream,
        )
        print(
            f"  - Execution events: {db_inspection['event_count']} event(s) (will be permanently deleted)",
            file=stream,
        )
        print(
            f"  - LangGraph checkpoints: {db_inspection['checkpoint_count']} record(s) (will be permanently deleted)",
            file=stream,
        )
        print("Preserved resources (will NOT be deleted):", file=stream)
        print(
            f"  - Referenced agents (remain untouched): {', '.join(referenced_agents) if referenced_agents else 'none'}",
            file=stream,
        )
        print(
            f"  - Unrelated workflows (remain untouched): {', '.join(other_workflows) if other_workflows else 'none'}",
            file=stream,
        )

        if not yes:
            if not is_interactive or input_fn is None:
                raise CliError(
                    "workflow deletion requires explicit confirmation; rerun with --yes or confirm interactively"
                )
            _confirm_action(
                f"This will permanently delete the workflow and its associated data. Continue? [y/N]: ",
                input_fn,
                cancel_message="workflow deletion cancelled; no files or registrations were removed",
            )

        deleted_from_server = False
        server_resp: dict[str, Any] = {}
        if registered_on_server:
            resp = api.delete(f"/v1/workflows/{quote(workflow_id, safe='')}")
            if isinstance(resp, dict):
                server_resp = resp
            deleted_from_server = True

        local_purge: dict[str, Any] = {"deleted_runs": 0, "deleted_events": 0, "deleted_checkpoints": 0, "deleted_versions": []}
        if repo is not None:
            try:
                local_purge = repo.delete_workflow_records(workflow_id)
                deleted_from_server = True
            except Exception:
                pass

        deleted_local_file: str | None = server_resp.get("deleted_local_file")
        if local_path is not None and local_path.is_file():
            try:
                local_path.unlink()
                deleted_local_file = str(local_path)
            except OSError as exc:
                raise CliError(f"could not remove workflow definition file {local_path}: {exc}") from exc
        elif deleted_local_file is None and local_path is not None and wf_source_dict is not None:
            deleted_local_file = str(local_path)

        deleted_runs = max(int(local_purge.get("deleted_runs", 0)), int(server_resp.get("deleted_runs", 0)))
        deleted_events = max(int(local_purge.get("deleted_events", 0)), int(server_resp.get("deleted_events", 0)))
        deleted_checkpoints = max(int(local_purge.get("deleted_checkpoints", 0)), int(server_resp.get("deleted_checkpoints", 0)))

        return {
            "id": workflow_id,
            "workflow_id": workflow_id,
            "status": "deleted",
            "deleted": True,
            "deleted_from_server": deleted_from_server,
            "deleted_local_file": deleted_local_file,
            "deleted_versions": server_resp.get("deleted_versions") or local_purge.get("deleted_versions") or db_inspection["versions"],
            "deleted_runs": deleted_runs,
            "deleted_events": deleted_events,
            "deleted_checkpoints": deleted_checkpoints,
            "retained": {
                "agents": referenced_agents,
                "unrelated_workflows": other_workflows,
            },
            "message": f"Workflow '{workflow_id}' and all associated data were permanently deleted.",
        }
    finally:
        if repo:
            try:
                repo.close()
            except Exception:
                pass


def build_parser() -> argparse.ArgumentParser:
    fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(
        prog="agent-platform",
        description="CLI for managing agents, tools, workflows, runs, and approvals on the agent_platform.",
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              # Connect an external Python agent and inspect registered agents
              python -m app.cli agents connect ./my_agent_project
              python -m app.cli agents list

              # Create a workflow (defaults to version 1.0.0 and infers node IDs & mappings)
              python -m app.cli workflows create text_pipeline --agents external_text_analysis

              # Add another agent to the workflow (auto-increments version to 1.0.1)
              python -m app.cli workflows add-agent text_pipeline external_quality_checker

              # Start a workflow run interactively or from a JSON/YAML input file
              python -m app.cli runs start --workflow text_pipeline --interactive
              python -m app.cli runs start --workflow text_pipeline --input input.json
        """),
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("AGENT_PLATFORM_BASE_URL", "http://127.0.0.1:8000"),
        help="FastAPI server base URL (optional; default: %(default)s or $AGENT_PLATFORM_BASE_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("AGENT_PLATFORM_API_TOKEN"),
        help="Bearer token for API authentication (optional; default: $AGENT_PLATFORM_API_TOKEN)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP request timeout in seconds (optional; default: %(default)s)",
    )
    parser.add_argument(
        "--project-root",
        default=str(Path(__file__).resolve().parents[1]),
        help="Project root directory for local manifests and workflow definitions (optional; default: workspace root)",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # ------------------------------------------------------------------ agents
    agents = commands.add_parser(
        "agents",
        help="Create, connect, disconnect, delete, validate, and run agents",
        description="Manage local and external agents registered with the platform.",
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli agents list
              python -m app.cli agents show external_text_analysis
              python -m app.cli agents connect ./external_agent_demo
              python -m app.cli agents create my_summarizer
              python -m app.cli agents run external_text_analysis --interactive
              python -m app.cli agents disconnect external_text_analysis
              python -m app.cli agents delete external_text_analysis
        """),
    )
    agents_commands = agents.add_subparsers(dest="action", required=True, metavar="SUBCOMMAND")
    agents_commands.add_parser(
        "list",
        help="List all registered agents from the API",
        description="List all registered agents and their metadata from the API.",
        formatter_class=fmt,
        epilog="Example:\n  python -m app.cli agents list\n",
    )
    agent_show = agents_commands.add_parser(
        "show",
        help="Show metadata and schemas for a registered agent",
        description="Display the full registration metadata and input/output schemas for AGENT_ID.",
        formatter_class=fmt,
        epilog="Example:\n  python -m app.cli agents show external_text_analysis\n",
    )
    agent_show.add_argument("agent_id", help="Registered agent ID (required)")

    agent_run = agents_commands.add_parser(
        "run",
        help="Execute a single registered agent directly through the API",
        description=(
            "Run a single registered agent directly through the API.\n"
            "When running in an interactive terminal without --input-file, prompts for inputs automatically."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli agents run external_text_analysis --interactive
              python -m app.cli agents run external_text_analysis --input sample_input.json
        """),
    )
    agent_run.add_argument("agent_id", help="Registered agent ID to execute (required)")
    agent_input = agent_run.add_mutually_exclusive_group(required=False)
    agent_input.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Prompt interactively for fields from the agent's input schema (default in interactive terminals)",
    )
    agent_input.add_argument(
        "--input-file", "--input",
        dest="input_file",
        help="Path to a JSON or YAML object file containing agent inputs",
    )

    agent_validate = agents_commands.add_parser(
        "validate",
        help="Validate an agent manifest file or registered agent ID",
        description="Validate an agent manifest file or a registered agent ID offline.",
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli agents validate external_text_analysis
              python -m app.cli agents validate plugins/manifests/external_text_analysis.yaml
        """),
    )
    agent_validate.add_argument("target", help="Registered agent ID or path to an agent YAML/JSON manifest (required)")

    def _configure_agent_create_parser(subparser: argparse.ArgumentParser, *, is_alias: bool = False) -> None:
        alias_note = " (compatibility alias for 'agents create')" if is_alias else ""
        subparser.description = (
            f"Create a new local Python agent plugin and manifest{alias_note}.\n"
            "Display name and description are optional and default sensibly from AGENT_ID."
        )
        subparser.epilog = textwrap.dedent("""\
            Examples:
              python -m app.cli agents create my_summarizer
              python -m app.cli agents create my_summarizer --name "My Summarizer" --description "Summarizes text"
        """)
        subparser.add_argument("agent_id", help="Lowercase Python identifier for the new agent (required)")
        subparser.add_argument(
            "--name",
            default=None,
            help="Human-readable display name (optional; default: derived from AGENT_ID)",
        )
        subparser.add_argument(
            "--description",
            default=None,
            help="Short description of the agent (optional; default: derived from AGENT_ID)",
        )

    agent_create = agents_commands.add_parser(
        "create",
        help="Create a new local agent plugin with sensible defaults",
        formatter_class=fmt,
    )
    _configure_agent_create_parser(agent_create, is_alias=False)

    agent_scaffold = agents_commands.add_parser(
        "scaffold",
        help="Create a new local agent plugin (compatibility alias for 'agents create')",
        formatter_class=fmt,
    )
    _configure_agent_create_parser(agent_scaffold, is_alias=True)

    agent_connect = agents_commands.add_parser(
        "connect",
        help="Connect or reconnect an external Python agent by ID, name, path, or interactive menu",
        description=(
            "Connect an external Python agent project or reconnect a previously disconnected agent.\n"
            "  - Run 'agents connect' interactively to choose from a menu of disconnected agents or enter a new path.\n"
            "  - Run 'agents connect AGENT_ID' to reconnect a known disconnected agent using its saved metadata.\n"
            "  - Run 'agents connect PATH' or 'agents connect --path PATH' to connect an external project directory."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli agents connect
              python -m app.cli agents connect external_text_analysis
              python -m app.cli agents connect external_text_analysis --trust
              python -m app.cli agents connect ./external_agent_demo
              python -m app.cli agents connect --path ./external_agent_demo --trust
              python -m app.cli agents connect ./external_agent_demo --id custom_id --entry-point agent.py:MyAgent
        """),
    )
    agent_connect.add_argument(
        "path_positional",
        nargs="?",
        metavar="AGENT_ID_OR_PATH",
        help="Disconnected agent ID/name to reconnect, or external Python project directory (optional in interactive mode)",
    )
    agent_connect.add_argument(
        "--path",
        dest="path_flag",
        help="External Python project directory (alternative to positional AGENT_ID_OR_PATH)",
    )
    agent_connect.add_argument(
        "--id", "--agent-id",
        dest="agent_id",
        help="Registered agent ID (optional; default: inferred from project/entry point)",
    )
    agent_connect.add_argument(
        "--name",
        help="Display name (optional; default: inferred from entry point)",
    )
    agent_connect.add_argument(
        "--entry-point", "--entrypoint",
        dest="entry_point",
        help="Entry point as relative_file.py:ClassName or relative_file.py:run (optional; default: auto-discovered)",
    )
    agent_connect.add_argument(
        "--test-input",
        help="JSON/YAML object file passed to run(input_dict) for verification (optional; default: auto-detected sample)",
    )
    agent_connect.add_argument(
        "--trust",
        action="store_true",
        help="Explicitly approve importing and invoking this external code in-process without interactive prompt",
    )
    agent_connect.add_argument(
        "--db",
        help="Path to SQLite database to sync reconnected workflow nodes (optional; default: agent_platform.db)",
    )

    agent_disconnect = agents_commands.add_parser(
        "disconnect",
        help="Disconnect an external agent or permanently purge its platform records",
        description=(
            "Disconnect a connected external agent while preserving history and workflows by default,\n"
            "or pass --purge to permanently delete platform-managed records for the agent."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli agents disconnect external_text_analysis
              python -m app.cli agents disconnect external_text_analysis --purge
              python -m app.cli agents disconnect external_text_analysis --purge --yes
        """),
    )
    agent_disconnect.add_argument("agent_id", help="Connected agent ID to disconnect (required)")
    agent_disconnect.add_argument(
        "--purge",
        action="store_true",
        help="Permanently delete platform-managed registration, events, direct runs, and checkpoints (optional; default: False)",
    )
    agent_disconnect.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Confirm destructive --purge without an interactive prompt (optional; default: False)",
    )
    agent_disconnect.add_argument(
        "--db",
        help="Path to SQLite database (optional; default: agent_platform.db in project root)",
    )

    agent_delete = agents_commands.add_parser(
        "delete",
        help="Permanently delete an agent and its platform-managed registration, adapters, catalog entry, and records",
        description=(
            "Permanently delete an agent from the platform, removing its registration manifest,\n"
            "generated adapter/package, saved connection-catalog entry, direct run history, events,\n"
            "and checkpoints, while safely updating any workflows that reference it.\n"
            "External project source files on disk are never deleted."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli agents delete external_text_analysis
              python -m app.cli agents delete external_text_analysis --yes
        """),
    )
    agent_delete.add_argument("agent_id", help="Agent ID to permanently delete (required)")
    agent_delete.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Confirm permanent agent deletion without an interactive prompt (optional; default: False)",
    )
    agent_delete.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database (optional; default: agent_platform.db in project root)",
    )

    # ------------------------------------------------------------------- tools
    tools = commands.add_parser(
        "tools",
        help="Create, validate, and list local tools",
        description="Manage deterministic local tools available to authorized agents.",
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli tools list
              python -m app.cli tools create word_counter
              python -m app.cli tools validate word_counter
        """),
    )
    tools_commands = tools.add_subparsers(dest="action", required=True, metavar="SUBCOMMAND")
    tools_commands.add_parser(
        "list",
        help="List all registered tools from the API",
        description="List all registered tools from the API.",
        formatter_class=fmt,
        epilog="Example:\n  python -m app.cli tools list\n",
    )
    tool_validate = tools_commands.add_parser(
        "validate",
        help="Validate a tool manifest file or tool ID",
        description="Validate a tool manifest by tool ID or YAML/JSON file path.",
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli tools validate word_counter
              python -m app.cli tools validate plugins/tool_manifests/word_counter.yaml
        """),
    )
    tool_validate.add_argument("path", help="Tool ID or path to a tool manifest YAML/JSON file (required)")

    def _configure_tool_create_parser(subparser: argparse.ArgumentParser, *, is_alias: bool = False) -> None:
        alias_note = " (compatibility alias for 'tools create')" if is_alias else ""
        subparser.description = (
            f"Create a new local tool implementation, manifest, and documentation{alias_note}.\n"
            "Display name and description are optional and default sensibly from TOOL_ID."
        )
        subparser.epilog = textwrap.dedent("""\
            Examples:
              python -m app.cli tools create word_counter
              python -m app.cli tools create word_counter --name "Word Counter" --description "Counts words"
        """)
        subparser.add_argument("tool_id", help="Lowercase Python identifier for the new tool (required)")
        subparser.add_argument(
            "--name",
            default=None,
            help="Human-readable display name (optional; default: derived from TOOL_ID)",
        )
        subparser.add_argument(
            "--description",
            default=None,
            help="Short description of the tool (optional; default: derived from TOOL_ID)",
        )

    tool_create = tools_commands.add_parser(
        "create",
        help="Create a new local tool with sensible defaults",
        formatter_class=fmt,
    )
    _configure_tool_create_parser(tool_create, is_alias=False)

    tool_scaffold = tools_commands.add_parser(
        "scaffold",
        help="Create a new local tool (compatibility alias for 'tools create')",
        formatter_class=fmt,
    )
    _configure_tool_create_parser(tool_scaffold, is_alias=True)

    # --------------------------------------------------------------- workflows
    workflows = commands.add_parser(
        "workflows",
        help="Create, compose, validate, register, inspect, disconnect, and delete workflows",
        description=(
            "Create and manage multi-agent workflows.\n"
            "New workflows default to version 1.0.0, and modifications automatically increment the patch version."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli workflows list
              python -m app.cli workflows create text_pipeline --agents external_text_analysis
              python -m app.cli workflows add-agent text_pipeline external_quality_checker
              python -m app.cli workflows validate text_pipeline
              python -m app.cli workflows register text_pipeline
              python -m app.cli workflows show text_pipeline
              python -m app.cli workflows disconnect text_pipeline
              python -m app.cli workflows delete text_pipeline
        """),
    )
    workflow_commands = workflows.add_subparsers(dest="action", required=True, metavar="SUBCOMMAND")
    workflow_commands.add_parser(
        "list",
        help="List saved and registered workflows",
        description="List workflow definitions from workflow_definitions/ and the API server.",
        formatter_class=fmt,
        epilog="Example:\n  python -m app.cli workflows list\n",
    )
    workflow_show = workflow_commands.add_parser(
        "show",
        help="Show a registered workflow definition",
        description="Fetch and display a registered workflow definition by WORKFLOW_ID.",
        formatter_class=fmt,
        epilog="Example:\n  python -m app.cli workflows show text_analysis_validation\n",
    )
    workflow_show.add_argument("workflow_id", help="Registered workflow ID (required)")

    workflow_validate = workflow_commands.add_parser(
        "validate",
        help="Validate a workflow by ID or YAML file path",
        description="Validate a workflow definition and its agent dependencies by WORKFLOW_ID or file path.",
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli workflows validate text_analysis_validation
              python -m app.cli workflows validate workflow_definitions/text_analysis_validation.yaml
        """),
    )
    workflow_validate.add_argument(
        "path",
        metavar="WORKFLOW_ID_OR_PATH",
        help="Workflow ID (resolves workflow_definitions/<id>.yaml) or YAML file path (required)",
    )

    workflow_register = workflow_commands.add_parser(
        "register",
        help="Validate and register a workflow with the API by ID or YAML path",
        description=(
            "Validate and register a workflow definition with the API.\n"
            "Accepts either WORKFLOW_ID or a file path. If the workflow was modified and the version\n"
            "already exists on the server, the semantic patch version is automatically incremented."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli workflows register text_analysis_validation
              python -m app.cli workflows register workflow_definitions/text_analysis_validation.yaml
              python -m app.cli workflows register text_analysis_validation --version 2.0.0
        """),
    )
    workflow_register.add_argument(
        "path",
        metavar="WORKFLOW_ID_OR_PATH",
        help="Workflow ID (resolves workflow_definitions/<id>.yaml) or YAML file path (required)",
    )
    workflow_register.add_argument(
        "--version",
        default=None,
        help="Explicit workflow version override (optional; default: file version or auto-incremented patch version)",
    )

    workflow_create = workflow_commands.add_parser(
        "create",
        help="Create a new workflow interactively, with agents, or as an empty draft (version 1.0.0)",
        description=(
            "Create a new workflow definition in workflow_definitions/<workflow_id>.yaml.\n"
            "When run interactively without agent arguments, prompts whether to create with agents\n"
            "or create an empty workflow draft and add agents later.\n"
            "Automatically assigns version 1.0.0 (unless overridden via --version) and infers node IDs\n"
            "and unambiguous input mappings from registered agent schemas."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli workflows create my_workflow
              python -m app.cli workflows create my_workflow --empty
              python -m app.cli workflows create my_workflow --agents external_text_analysis
              python -m app.cli workflows create my_workflow external_text_analysis external_quality_checker
              python -m app.cli workflows create my_workflow --agents external_text_analysis --no-register
        """),
    )
    workflow_create.add_argument("workflow_id", help="Unique workflow identifier (required)")
    workflow_create.add_argument(
        "agent_ids",
        nargs="*",
        metavar="AGENT_ID",
        help="Agent ID(s) in execution order (optional if --agents or --empty is passed, or selected interactively)",
    )
    workflow_create.add_argument(
        "-a", "--agents", "--agent",
        dest="agents",
        help="Comma-separated agent IDs in execution order (optional in interactive mode)",
    )
    workflow_create.add_argument(
        "-e", "--empty",
        action="store_true",
        help="Create an empty workflow draft (version 1.0.0) without prompting for agents (optional; default: False)",
    )
    workflow_create.add_argument(
        "--node-id",
        default=None,
        help="Custom node ID when creating a single-agent workflow (optional; default: agent ID)",
    )
    workflow_create.add_argument(
        "--map",
        action="append",
        metavar="FIELD=PATH",
        help="Explicit input mapping override, e.g. text=workflow_input.text (optional, repeatable)",
    )
    workflow_create.add_argument(
        "--literal",
        action="append",
        metavar="FIELD=JSON",
        help="Explicit JSON literal input value, e.g. mode='\"fast\"' (optional, repeatable)",
    )
    workflow_create.add_argument(
        "--version",
        default="1.0.0",
        help="Initial workflow version (optional; default: %(default)s)",
    )
    workflow_create.add_argument(
        "--register",
        dest="register",
        action="store_true",
        default=None,
        help="Explicitly require registration with the API server (auto-registration is active by default when agents are present)",
    )
    workflow_create.add_argument(
        "--no-register",
        dest="no_register",
        action="store_true",
        default=False,
        help="Skip API server registration and save locally only (default: False)",
    )

    workflow_scaffold = workflow_commands.add_parser(
        "scaffold",
        help="Generate a starter workflow template (compatibility alias for 'workflows create')",
        description=(
            "Generate a starter workflow YAML file in workflow_definitions/<workflow_id>.yaml.\n"
            "Preserved as a compatibility alias; prefer 'workflows create' for automatic mapping inference."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli workflows scaffold code_analysis --agents source_inspector,code_reviewer
        """),
    )
    workflow_scaffold.add_argument("workflow_id", help="Unique workflow identifier (required)")
    workflow_scaffold.add_argument(
        "agent_ids",
        nargs="*",
        metavar="AGENT_ID",
        help="Agent ID(s) in execution order (optional if --agents is passed)",
    )
    workflow_scaffold.add_argument(
        "-a", "--agents", "--agent",
        dest="agents",
        help="Comma-separated agent IDs in execution order",
    )
    workflow_scaffold.add_argument(
        "--version",
        default="1.0.0",
        help="Initial workflow version (optional; default: %(default)s)",
    )

    workflow_add = workflow_commands.add_parser(
        "add-agent",
        help="Add a connected agent to a workflow, infer mappings, bump version, validate, and register",
        description=(
            "Add an agent node to an existing workflow, infer unambiguous input mappings from preceding\n"
            "nodes and workflow inputs, automatically bump the semantic patch version (1.0.0 -> 1.0.1),\n"
            "validate, save, and register with the API."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli workflows add-agent text_pipeline external_quality_checker
              python -m app.cli workflows add-agent text_pipeline external_quality_checker --after external_text_analysis
              python -m app.cli workflows add-agent text_pipeline external_quality_checker --map summary=node_outputs.external_text_analysis.summary
        """),
    )
    workflow_add.add_argument("workflow", help="Workflow ID (workflow_definitions/<id>.yaml) or YAML path (required)")
    workflow_add.add_argument(
        "agent_id",
        nargs="?",
        default=None,
        help="Connected agent ID to add (required in non-interactive mode; prompted interactively if omitted)",
    )
    workflow_add.add_argument(
        "--after",
        help="Existing node ID that precedes the new node (optional; default: inferred when unambiguous)",
    )
    workflow_add.add_argument(
        "--node-id",
        help="ID for the new workflow node (optional; default: AGENT_ID)",
    )
    workflow_add.add_argument(
        "--map",
        action="append",
        metavar="FIELD=PATH",
        help="Explicit path mapping override, e.g. text=workflow_input.text (optional, repeatable)",
    )
    workflow_add.add_argument(
        "--literal",
        action="append",
        metavar="FIELD=JSON",
        help="Explicit JSON literal value for an input field (optional, repeatable)",
    )
    workflow_add.add_argument(
        "--version",
        help="Explicit version override when the workflow changes (optional; default: auto-increment patch version)",
    )

    workflow_disconnect = workflow_commands.add_parser(
        "disconnect",
        help="Unregister/disable a workflow from the API while preserving its local YAML definition and run history",
        description=(
            "Unregister (disconnect) a workflow from the active API workflow registry so it cannot be newly\n"
            "executed through the registered workflow API, while preserving its local YAML definition,\n"
            "node configuration, mappings, referenced agents, and execution history."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli workflows disconnect text_pipeline
              python -m app.cli workflows disconnect text_pipeline --yes
        """),
    )
    workflow_disconnect.add_argument(
        "workflow_id",
        metavar="WORKFLOW_ID",
        help="Workflow ID (resolves workflow_definitions/<id>.yaml) or YAML file path to disconnect (required)",
    )
    workflow_disconnect.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Confirm workflow disconnection without an interactive prompt (optional; default: False)",
    )
    workflow_disconnect.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database (optional; default: agent_platform.db in project root)",
    )

    workflow_delete = workflow_commands.add_parser(
        "delete",
        help="Delete a workflow definition locally and from the API registry",
        description=(
            "Delete a workflow from the API/server-side registry and remove its local YAML definition\n"
            "in workflow_definitions/<workflow_id>.yaml.\n"
            "Requires explicit confirmation interactively or via --yes.\n"
            "Historical workflow execution records (runs and events) are preserved by default."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli workflows delete text_pipeline
              python -m app.cli workflows delete text_pipeline --yes
        """),
    )
    workflow_delete.add_argument(
        "workflow_id",
        metavar="WORKFLOW_ID",
        help="Workflow ID (resolves workflow_definitions/<id>.yaml) or YAML file path to delete (required)",
    )
    workflow_delete.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Confirm workflow deletion without an interactive prompt (optional; default: False)",
    )
    workflow_delete.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database (optional; default: agent_platform.db in project root)",
    )

    # -------------------------------------------------------------------- runs
    runs = commands.add_parser(
        "runs",
        help="Start and inspect workflow runs and execution events",
        description="Execute registered workflows and inspect individual agent outputs and execution events.",
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli runs start --workflow text_analysis_validation --interactive
              python -m app.cli runs start text_analysis_validation --input input.json
              python -m app.cli runs start --workflow text_analysis_validation --interactive --strict
              python -m app.cli runs show <run_id>
              python -m app.cli runs events <run_id> --include-payload
        """),
    )
    run_commands = runs.add_subparsers(dest="action", required=True, metavar="SUBCOMMAND")
    run_start = run_commands.add_parser(
        "start",
        help="Start a workflow run (automatically executes available agents if others are disconnected)",
        description=(
            "Start a workflow run through the API.\n"
            "By default, available agents execute in dependency order even if downstream agents are disconnected.\n"
            "Pass --strict to reject the entire workflow before execution when any node is unavailable."
        ),
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli runs start --workflow text_analysis_validation --interactive
              python -m app.cli runs start text_analysis_validation --input input.json
              python -m app.cli runs start --workflow text_analysis_validation --interactive --strict
        """),
    )
    run_start.add_argument(
        "workflow_positional",
        nargs="?",
        metavar="WORKFLOW_ID",
        help="Registered workflow ID to execute (alternative to --workflow)",
    )
    run_start.add_argument(
        "-w", "--workflow",
        dest="workflow",
        help="Registered workflow ID to execute (required unless passed positionally)",
    )
    run_mode = run_start.add_mutually_exclusive_group(required=False)
    run_mode.add_argument(
        "--strict",
        action="store_true",
        help="Reject the entire workflow before execution if any required agent is unavailable (optional; default: False)",
    )
    run_mode.add_argument(
        "--allow-partial",
        action="store_true",
        help="Execute available workflow nodes even when other nodes are unavailable (optional; default behavior)",
    )
    run_input = run_start.add_mutually_exclusive_group(required=False)
    run_input.add_argument(
        "--input", "--input-file",
        dest="input_path",
        help="JSON/YAML object file containing the workflow initial input",
    )
    run_input.add_argument(
        "-i", "--interactive",
        action="store_true",
        help="Prompt for the workflow's initial input in the terminal (default in interactive terminals)",
    )

    run_show = run_commands.add_parser(
        "show",
        help="Show status and per-agent outputs for a workflow run",
        description="Display the status, individual agent_outputs, final_output, and skipped nodes for RUN_ID.",
        formatter_class=fmt,
        epilog="Example:\n  python -m app.cli runs show <run_id>\n",
    )
    run_show.add_argument("run_id", help="Workflow run ID (required)")

    run_events = run_commands.add_parser(
        "events",
        help="List execution events for a workflow run",
        description="List chronological node execution events for RUN_ID.",
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli runs events <run_id>
              python -m app.cli runs events <run_id> --include-payload
        """),
    )
    run_events.add_argument("run_id", help="Workflow run ID (required)")
    run_events.add_argument(
        "--include-payload",
        action="store_true",
        help="Include sanitized node output payloads in each event record (optional; default: False)",
    )

    # --------------------------------------------------------------- approvals
    approvals = commands.add_parser(
        "approvals",
        help="List and resume workflow runs waiting for human approval",
        description="Inspect and resume workflow runs paused at a human_approval node.",
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli approvals list
              python -m app.cli approvals resume <run_id> --decision approve
              python -m app.cli approvals resume <run_id> approve
        """),
    )
    approval_commands = approvals.add_subparsers(dest="action", required=True, metavar="SUBCOMMAND")
    approval_commands.add_parser(
        "list",
        help="List runs currently waiting for human approval",
        description="List all workflow runs owned by the caller that are waiting for human approval.",
        formatter_class=fmt,
        epilog="Example:\n  python -m app.cli approvals list\n",
    )
    approval_resume = approval_commands.add_parser(
        "resume",
        help="Submit a decision to resume a run waiting for human approval",
        description="Resume a workflow run paused at a human_approval node with an allowed decision.",
        formatter_class=fmt,
        epilog=textwrap.dedent("""\
            Examples:
              python -m app.cli approvals resume <run_id> --decision approve
              python -m app.cli approvals resume <run_id> approve
        """),
    )
    approval_resume.add_argument("run_id", help="Paused workflow run ID (required)")
    approval_resume.add_argument(
        "decision_positional",
        nargs="?",
        metavar="DECISION",
        help="Approval decision, e.g. approve or reject (alternative to --decision)",
    )
    approval_resume.add_argument(
        "-d", "--decision",
        dest="decision",
        help="Approval decision, e.g. approve or reject (required unless passed positionally or interactively)",
    )

    # ------------------------------------------------------------------ worker
    worker_parser = commands.add_parser(
        "worker",
        help="Start Temporal background worker for distributed LangGraph workflows",
        formatter_class=fmt,
    )
    worker_parser.add_argument("--task-queue", default=os.getenv("TEMPORAL_TASK_QUEUE", "agent-platform-queue"), help="Temporal task queue")
    worker_parser.add_argument("--target-host", default=os.getenv("TEMPORAL_TARGET_HOST", "localhost:7233"), help="Temporal target host")
    worker_parser.add_argument("--namespace", default=os.getenv("TEMPORAL_NAMESPACE", "default"), help="Temporal namespace")
    worker_parser.add_argument("--concurrency", type=int, default=int(os.getenv("TEMPORAL_WORKER_CONCURRENCY", "10")), help="Worker concurrency")
    worker_parser.add_argument("--db", default="agent_platform.db", help="Path to SQLite repository")

    return parser


def main(
    argv: list[str] | None = None,
    *,
    client: httpx.Client | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    input_fn=None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    is_interactive = input_fn is not None or sys.stdin.isatty()
    api = ApiClient(args.base_url, args.timeout, client, args.token)
    try:
        if args.command == "agents" and args.action == "list":
            _print_json(api.get("/v1/agents"), output)
        elif args.command == "agents" and args.action == "show":
            _print_json(api.get(f"/v1/agents/{args.agent_id}"), output)
        elif args.command == "agents" and args.action == "run":
            if not args.interactive and not args.input_file:
                if is_interactive:
                    args.interactive = True
                else:
                    parser.error("one of the arguments --interactive --input-file/--input is required")
            agent_id = _connected_agent_id(args.agent_id)
            if args.interactive:
                metadata = api.get(f"/v1/agents/{agent_id}")
                inputs = _interactive_agent_inputs(metadata, input_fn or input, output)
            else:
                inputs = _read_document(args.input_file)
            record = api.post(f"/v1/agents/{agent_id}/runs", {"inputs": inputs})
            _print_json(_run_summary(record), output)
        elif args.command == "agents" and args.action == "validate":
            candidate = Path(args.target)
            if candidate.exists() or candidate.suffix.lower() in {".yaml", ".yml", ".json"}:
                _print_json(_validate_manifest(args.target, "agent"), output)
            else:
                _print_json(_validate_agent_id(args.project_root, args.target), output)
        elif args.command == "agents" and args.action in {"create", "scaffold"}:
            _print_json(
                _scaffold_agent(
                    args.project_root,
                    args.agent_id,
                    args.name,
                    args.description,
                    input_fn=input_fn or input,
                    is_interactive=is_interactive,
                ),
                output,
            )
        elif args.command == "agents" and args.action == "connect":
            if args.path_positional and args.path_flag:
                raise CliError("pass the external project path either positionally or with --path, not both")
            target_path = args.path_flag if args.path_flag is not None else args.path_positional
            _print_json(_connect_agent(
                args.project_root,
                target_path,
                args.agent_id,
                args.name,
                args.entry_point,
                args.test_input,
                trust_approved=args.trust,
                db_path=args.db,
                explicit_path=args.path_flag is not None,
                input_fn=input_fn or input,
                is_interactive=is_interactive,
                error_output=errors,
            ), output)
        elif args.command == "agents" and args.action == "disconnect":
            _print_json(
                _disconnect_agent(
                    args.project_root,
                    args.agent_id,
                    purge=args.purge,
                    yes=args.yes,
                    db_path=args.db,
                    input_fn=input_fn or input,
                    is_interactive=is_interactive,
                    error_output=errors,
                ),
                output,
            )
        elif args.command == "agents" and args.action == "delete":
            _print_json(
                _delete_agent(
                    args.project_root,
                    args.agent_id,
                    api,
                    yes=args.yes,
                    db_path=args.db,
                    input_fn=input_fn or input,
                    is_interactive=is_interactive,
                    error_output=errors,
                ),
                output,
            )
        elif args.command == "tools" and args.action == "list":
            _print_json(api.get("/v1/tools"), output)
        elif args.command == "tools" and args.action == "validate":
            candidate = Path(args.path)
            if candidate.exists() or candidate.suffix.lower() in {".yaml", ".yml", ".json"}:
                _print_json(_validate_manifest(args.path, "tool"), output)
            else:
                _print_json(_validate_tool_id(args.project_root, args.path), output)
        elif args.command == "tools" and args.action in {"create", "scaffold"}:
            _print_json(
                _scaffold_tool(
                    args.project_root,
                    args.tool_id,
                    args.name,
                    args.description,
                    input_fn=input_fn or input,
                    is_interactive=is_interactive,
                ),
                output,
            )
        elif args.command == "workflows" and args.action == "list":
            _print_json(_list_workflows(args.project_root, api), output)
        elif args.command == "workflows" and args.action == "show":
            _print_json(_show_workflow(args.project_root, args.workflow_id, api), output)
        elif args.command == "workflows" and args.action == "validate":
            _print_json(_validate_workflow(args.path, args.project_root).model_dump(by_alias=True), output)
        elif args.command == "workflows" and args.action == "register":
            _print_json(
                _register_workflow(args.project_root, args.path, api, version=args.version),
                output,
            )
        elif args.command == "workflows" and args.action == "create":
            combined_agents: list[str] = []
            if args.agents:
                combined_agents.append(args.agents)
            if args.agent_ids:
                combined_agents.extend(args.agent_ids)
            _print_json(
                _create_workflow(
                    args.project_root,
                    args.workflow_id,
                    combined_agents or None,
                    args.version,
                    empty=args.empty,
                    strict_mappings=True,
                    node_id=args.node_id,
                    maps=args.map,
                    literals=args.literal,
                    register=args.register,
                    no_register=args.no_register,
                    api=api,
                    input_fn=input_fn or input,
                    is_interactive=is_interactive,
                    error_output=errors,
                ),
                output,
            )
        elif args.command == "workflows" and args.action == "scaffold":
            combined_agents = []
            if args.agents:
                combined_agents.append(args.agents)
            if args.agent_ids:
                combined_agents.extend(args.agent_ids)
            _print_json(
                _scaffold_workflow(
                    args.project_root,
                    args.workflow_id,
                    combined_agents or None,
                    args.version,
                    input_fn=input_fn or input,
                    is_interactive=is_interactive,
                    error_output=errors,
                ),
                output,
            )
        elif args.command == "workflows" and args.action == "add-agent":
            _print_json(_add_agent_to_workflow(
                args.project_root, args.workflow, args.agent_id, api,
                after=args.after, node_id=args.node_id, maps=args.map, literals=args.literal, version=args.version,
                input_fn=input_fn or input,
                is_interactive=is_interactive,
                error_output=errors,
            ), output)
        elif args.command == "workflows" and args.action == "disconnect":
            _print_json(
                _disconnect_workflow(
                    args.project_root,
                    args.workflow_id,
                    api,
                    yes=args.yes,
                    db_path=args.db,
                    input_fn=input_fn or input,
                    is_interactive=is_interactive,
                    error_output=errors,
                ),
                output,
            )
        elif args.command == "workflows" and args.action == "delete":
            _print_json(
                _delete_workflow(
                    args.project_root,
                    args.workflow_id,
                    api,
                    yes=args.yes,
                    db_path=args.db,
                    input_fn=input_fn or input,
                    is_interactive=is_interactive,
                    error_output=errors,
                ),
                output,
            )
        elif args.command == "runs" and args.action == "start":
            if args.workflow_positional and args.workflow:
                raise CliError("specify the workflow ID either positionally or with --workflow, not both")
            workflow_id = args.workflow or args.workflow_positional
            if not workflow_id:
                parser.error("the following arguments are required: WORKFLOW_ID (or --workflow)")
            if not args.input_path and not args.interactive:
                if is_interactive:
                    args.interactive = True
                else:
                    parser.error("one of the arguments --input/--input-file --interactive is required")
            allow_partial = not args.strict
            if args.interactive:
                inputs = _interactive_workflow_inputs(
                    api,
                    workflow_id,
                    input_fn or input,
                    errors,
                    allow_partial=allow_partial,
                    project_root=args.project_root,
                )
            else:
                inputs = _read_document(args.input_path)
            run_payload: dict[str, Any] = {"workflow_id": workflow_id, "inputs": inputs}
            if args.strict:
                run_payload["strict"] = True
                run_payload["allow_partial"] = False
            elif args.allow_partial:
                run_payload["allow_partial"] = True
            try:
                record = api.post("/v1/runs", run_payload)
            except CliError as exc:
                if "API 404:" in str(exc):
                    _check_local_empty_workflow(args.project_root, workflow_id)
                raise
            _print_json(_run_summary(record), output)
            if args.interactive and record.get("status") == "waiting_for_approval":
                print(
                    f"Run {record.get('run_id')} is waiting for approval; resume it with: "
                    f"approvals resume {record.get('run_id')} --decision <option>",
                    file=errors,
                )
        elif args.command == "runs" and args.action == "show":
            _print_json(_run_summary(api.get(f"/v1/runs/{args.run_id}")), output)
        elif args.command == "runs" and args.action == "events":
            events = api.get(f"/v1/runs/{args.run_id}/events")
            _print_json([_event_summary(event, args.include_payload) for event in events], output)
        elif args.command == "approvals" and args.action == "list":
            _print_json([_run_summary(record) for record in api.get("/v1/approvals")], output)
        elif args.command == "approvals" and args.action == "resume":
            if args.decision_positional and args.decision:
                raise CliError("specify the approval decision either positionally or with --decision, not both")
            decision = args.decision or args.decision_positional
            if not decision and is_interactive:
                decision = (input_fn or input)(f"Approval decision for run {args.run_id} (e.g. approve/reject): ").strip()
            if not decision:
                parser.error("the following arguments are required: DECISION (or --decision)")
            record = api.post(f"/v1/runs/{args.run_id}/resume", {"decision": decision})
            _print_json(_run_summary(record), output)
        elif args.command == "worker":
            from app.temporal.worker import run_worker
            from app.temporal.config import TemporalConfig
            cfg = TemporalConfig(
                target_host=args.target_host,
                namespace=args.namespace,
                task_queue=args.task_queue,
                worker_concurrency=args.concurrency,
            )
            print(f"Starting Temporal worker on queue '{args.task_queue}' (concurrency: {args.concurrency})...", file=output)
            asyncio.run(run_worker(config=cfg, repository_path=args.db))
        else:
            raise CliError("unsupported command")
        return 0
    except (CliError, OSError, ValidationError, ValueError) as exc:
        print(f"error: {exc}", file=errors)
        return 2
    finally:
        api.close()


if __name__ == "__main__":
    raise SystemExit(main())
