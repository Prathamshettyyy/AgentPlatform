"""Utilities for explicitly trusted, local Python-agent connections.

This module performs static discovery before approval and delegates invocation
to the external implementation after approval. It is not a sandbox.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.abc
import importlib
import importlib.machinery
import importlib.util
import inspect
import re
import sys
import threading
import tomllib
import types
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterator


_IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules", "build",
    "dist", "tests", "test",
}
_IMPORT_LOCK = threading.RLock()
_PLUGIN_NAMESPACE_LOCK = threading.RLock()
_LOADED_ENTRYPOINTS: dict[tuple[str, ...], Any] = {}
_EXTERNAL_IMPORT_FINDERS: dict[str, Any] = {}


@dataclass(frozen=True)
class PythonEntryPoint:
    """A statically discovered function or no-argument class with ``run``."""

    relative_file: str
    symbol: str
    kind: str

    @property
    def spec(self) -> str:
        return f"{self.relative_file}:{self.symbol}"


def _safe_project_root(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"external project path is not a directory: {root}")
    return root


def _python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for source in root.rglob("*.py"):
        relative = source.relative_to(root)
        if any(part in _IGNORED_DIRS or part.startswith(".") for part in relative.parts[:-1]):
            continue
        if source.is_symlink():
            continue
        resolved = source.resolve()
        if root not in resolved.parents:
            continue
        files.append(source)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix().casefold())


def _has_one_payload_argument(arguments: ast.arguments, *, bound_receiver: bool) -> bool:
    positional = list(arguments.posonlyargs) + list(arguments.args)
    if bound_receiver:
        if not positional:
            return False
        positional = positional[1:]
    if not positional:
        return False
    defaults_count = len(arguments.defaults)
    required_count = len(arguments.posonlyargs) + len(arguments.args) - defaults_count
    if bound_receiver:
        required_count -= 1
    return required_count <= 1 and len(positional) >= 1


def discover_python_entrypoints(path: str | Path) -> list[PythonEntryPoint]:
    """Find supported entry points using AST only; project code is not imported."""
    root = _safe_project_root(path)
    found: list[PythonEntryPoint] = []
    parse_errors: list[str] = []
    for source in _python_files(root):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, UnicodeError, SyntaxError) as exc:
            parse_errors.append(f"{source.relative_to(root).as_posix()}: {exc}")
            continue
        relative = source.relative_to(root).as_posix()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
                if _has_one_payload_argument(node.args, bound_receiver=False):
                    found.append(PythonEntryPoint(relative, node.name, "function"))
            elif isinstance(node, ast.ClassDef):
                run_methods = [
                    member for member in node.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == "run"
                ]
                if len(run_methods) != 1:
                    continue
                is_static = any(
                    isinstance(decorator, ast.Name) and decorator.id == "staticmethod"
                    for decorator in run_methods[0].decorator_list
                )
                if is_static:
                    if _has_one_payload_argument(run_methods[0].args, bound_receiver=False):
                        found.append(PythonEntryPoint(relative, node.name, "class"))
                    continue
                init_methods = [
                    member for member in node.body
                    if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == "__init__"
                ]
                if init_methods:
                    init_args = list(init_methods[0].args.posonlyargs) + list(init_methods[0].args.args)
                    required_init = len(init_args) - len(init_methods[0].args.defaults)
                    if required_init > 1:
                        continue
                if _has_one_payload_argument(run_methods[0].args, bound_receiver=True):
                    found.append(PythonEntryPoint(relative, node.name, "class"))
    if not found and parse_errors:
        raise ValueError("no supported run(input_dict) entry point found; Python parse errors: " + "; ".join(parse_errors[:5]))
    return sorted(found, key=lambda item: (item.relative_file.casefold(), item.symbol.casefold(), item.kind))


def resolve_python_entrypoint(path: str | Path, requested: str | None = None) -> PythonEntryPoint:
    root = _safe_project_root(path)
    candidates = discover_python_entrypoints(root)
    if requested:
        relative_file, separator, symbol = requested.partition(":")
        win_path = PureWindowsPath(relative_file)
        posix_path = PurePosixPath(relative_file.replace("\\", "/"))
        if not separator or not symbol or win_path.is_absolute() or posix_path.is_absolute() or ".." in posix_path.parts:
            raise ValueError("--entry-point must be a safe relative path and symbol, such as agent.py:TextAnalysisAgent")
        normalized = posix_path.as_posix()
        matches = [item for item in candidates if item.relative_file == normalized and item.symbol == symbol]
        if not matches:
            discovered = ", ".join(item.spec for item in candidates) or "none"
            raise ValueError(f"entry point {requested!r} was not discovered; supported entry points: {discovered}")
        return matches[0]
    if len(candidates) != 1:
        discovered = ", ".join(item.spec for item in candidates) or "none"
        if candidates:
            raise ValueError(f"entry point discovery is ambiguous; specify --entry-point. Candidates: {discovered}")
        raise ValueError("no supported Python entry point found (expected a top-level run(input_dict) or class with run(input_dict))")
    return candidates[0]


def source_fingerprint(path: str | Path) -> dict[str, str]:
    """Hash importable Python source files so post-approval edits are detected."""
    root = _safe_project_root(path)
    result: dict[str, str] = {}
    for source in _python_files(root):
        relative = source.relative_to(root).as_posix()
        result[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
    if not result:
        raise ValueError("external project contains no Python source files")
    return result


def inspect_dependencies(path: str | Path) -> dict[str, Any]:
    """Report likely third-party imports and declarations without importing them."""
    root = _safe_project_root(path)
    stdlib = getattr(__import__("sys"), "stdlib_module_names", set())
    local_names = {item.stem for item in root.glob("*.py")}
    local_names.update(item.name for item in root.iterdir() if item.is_dir())
    imports: set[str] = set()
    for source in _python_files(root):
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        except (OSError, UnicodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module.split(".", 1)[0])
    third_party = sorted(name for name in imports if name not in stdlib and name not in local_names and name != "__future__")
    availability = []
    for name in third_party:
        try:
            installed = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError, AttributeError):
            installed = False
        availability.append({"module": name, "available_in_current_environment": installed})
    declared: list[str] = []
    requirements = root / "requirements.txt"
    if requirements.is_file():
        for line in requirements.read_text(encoding="utf-8").splitlines():
            item = line.split("#", 1)[0].strip()
            if item and not item.startswith(("-", "git+", "http:", "https:")):
                match = re.match(r"([A-Za-z0-9_.-]+)", item)
                if match:
                    declared.append(match.group(1) + (" (direct reference)" if " @ " in item else ""))
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            project_metadata = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project_table = project_metadata.get("project", {})
            dependencies = project_table.get("dependencies", []) if isinstance(project_table, dict) else []
            if isinstance(dependencies, list):
                for item in dependencies:
                    if isinstance(item, str):
                        match = re.match(r"\s*([A-Za-z0-9_.-]+)", item)
                        if match:
                            declared.append(match.group(1) + (" (direct reference)" if " @ " in item else ""))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            declared.append("<could not parse pyproject.toml dependencies>")
    return {
        "declared_requirements": declared,
        "detected_imports": availability,
        "note": "Dependencies are inspected but never installed automatically.",
    }


def infer_json_schema(example: Any) -> dict[str, Any]:
    """Infer only observed JSON field shapes; a sample does not imply requiredness."""
    if isinstance(example, dict):
        properties = {str(key): infer_json_schema(value) for key, value in example.items()}
        schema: dict[str, Any] = {"type": "object"}
        if properties:
            schema["properties"] = properties
        return schema
    if isinstance(example, bool):
        return {"type": "boolean"}
    if isinstance(example, int):
        return {"type": "integer"}
    if isinstance(example, float):
        return {"type": "number"}
    if isinstance(example, str):
        return {"type": "string"}
    if isinstance(example, list):
        schema = {"type": "array"}
        if example:
            item_schemas = [infer_json_schema(item) for item in example]
            distinct = {repr(sorted(item.items())) for item in item_schemas}
            if len(distinct) == 1:
                schema["items"] = item_schemas[0]
        return schema
    return {}


def default_agent_id(entrypoint: PythonEntryPoint, project_path: str | Path) -> str:
    label = entrypoint.symbol
    if entrypoint.kind == "function" or label.lower() in {"run", "agent"}:
        label = Path(project_path).name
    if label.endswith("Agent") and len(label) > len("Agent"):
        label = label[:-len("Agent")]
    slug = re.sub(r"(?<!^)(?=[A-Z])", "_", label).lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_") or "python_agent"
    agent_id = f"external_{slug}"
    return agent_id[:64].rstrip("_")


def default_agent_name(entrypoint: PythonEntryPoint, project_path: str | Path) -> str:
    label = entrypoint.symbol if entrypoint.kind == "class" else Path(project_path).name
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", label).replace("_", " ").replace("-", " ")
    return words.title() if words else "External Python Agent"


def render_adapter_source(agent_id: str, configuration: dict[str, Any]) -> str:
    return (
        "# Generated by agent_platform agents connect. Do not edit by hand.\n"
        "from app.registry.external_connector import invoke_python_agent\n"
        "from app.sdk.context import AgentContext\n"
        "from app.sdk.contracts import AgentRequest\n\n\n"
        f"_CONNECTED_AGENT_ID = {agent_id!r}\n"
        f"_CONNECTION = {configuration!r}\n\n\n"
        "async def run(request: AgentRequest, context: AgentContext) -> dict:\n"
        "    \"\"\"Delegate to the explicitly trusted external implementation.\"\"\"\n"
        "    return await invoke_python_agent(_CONNECTION, request.inputs)\n"
    )


@contextlib.contextmanager
def project_plugin_namespace(project_root: str | Path) -> Iterator[None]:
    """Temporarily add a project's trusted plugin directories to package paths."""
    root = Path(project_root).resolve()
    framework_root = Path(__file__).resolve().parents[2]
    plugins_dir = root / "plugins"
    examples_dir = plugins_dir / "examples"
    with _PLUGIN_NAMESPACE_LOCK:
        previous_plugin_modules = {
            name: module for name, module in list(sys.modules.items())
            if name == "plugins" or name.startswith("plugins.")
        }
        original_sys_path = list(sys.path)
        for name in previous_plugin_modules:
            sys.modules.pop(name, None)
        try:
            preferred_paths = [str(framework_root)]
            if root != framework_root:
                preferred_paths.append(str(root))
            sys.path[:] = preferred_paths + [item for item in original_sys_path if item not in preferred_paths]
            importlib.invalidate_caches()
            plugins_package = importlib.import_module("plugins")
            framework_plugins = str(framework_root / "plugins")
            plugin_paths = [str(plugins_dir)] if root != framework_root and plugins_dir.is_dir() else []
            plugin_paths.extend([framework_plugins, *plugins_package.__path__])
            plugins_package.__path__ = list(dict.fromkeys(plugin_paths))
            examples_package = importlib.import_module("plugins.examples")
            framework_examples = str(framework_root / "plugins" / "examples")
            example_paths = [str(examples_dir)] if root != framework_root and examples_dir.is_dir() else []
            example_paths.extend([framework_examples, *examples_package.__path__])
            examples_package.__path__ = list(dict.fromkeys(example_paths))
            importlib.invalidate_caches()
            yield
        finally:
            for name in list(sys.modules):
                if name == "plugins" or name.startswith("plugins."):
                    sys.modules.pop(name, None)
            sys.modules.update(previous_plugin_modules)
            sys.path[:] = original_sys_path
            importlib.invalidate_caches()


class _HashCheckedSourceLoader(importlib.abc.Loader):
    """Compile the exact approved bytes instead of trusting external pyc files."""

    def __init__(self, root: Path, expected_hashes: dict[str, str], source_path: Path):
        self.root = root
        self.expected_hashes = expected_hashes
        self.source_path = source_path

    def create_module(self, spec):
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        source = self.source_path.resolve()
        if self.root not in source.parents:
            raise ImportError("external import escaped its connected project")
        relative = source.relative_to(self.root).as_posix()
        contents = source.read_bytes()
        if hashlib.sha256(contents).hexdigest() != self.expected_hashes.get(relative):
            raise ImportError("external agent source changed since connection approval; reconnect and review it again")
        module.__file__ = str(source)
        module.__loader__ = self
        exec(compile(contents, str(source), "exec"), module.__dict__)


class _HashCheckedSourceFinder(importlib.abc.MetaPathFinder):
    def __init__(self, namespace: str, root: Path, expected_hashes: dict[str, str]):
        self.namespace = namespace
        self.root = root
        self.expected_hashes = expected_hashes

    def find_spec(self, fullname: str, path=None, target=None):
        prefix = self.namespace + "."
        if not fullname.startswith(prefix):
            return None
        parts = fullname[len(prefix):].split(".")
        search_paths = [Path(item) for item in path] if path else [self.root]
        for directory in search_paths:
            package_path = directory.joinpath(*parts)
            if package_path.is_dir():
                init_path = package_path / "__init__.py"
                if init_path.is_file():
                    loader = _HashCheckedSourceLoader(self.root, self.expected_hashes, init_path)
                    return importlib.util.spec_from_file_location(
                        fullname, init_path, loader=loader, submodule_search_locations=[str(package_path)]
                    )
                spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
                spec.submodule_search_locations = [str(package_path)]
                return spec
            source = directory.joinpath(*parts[:-1], parts[-1] + ".py")
            if source.is_file():
                loader = _HashCheckedSourceLoader(self.root, self.expected_hashes, source)
                return importlib.util.spec_from_file_location(fullname, source, loader=loader)
        return None


def _load_external_module(root: Path, relative_file: str, expected_hashes: dict[str, str]) -> types.ModuleType:
    source = (root / relative_file).resolve()
    if root not in source.parents or not source.is_file():
        raise ValueError("connected entry point escaped its external project or no longer exists")
    digest = hashlib.sha256(repr(sorted(expected_hashes.items())).encode("utf-8")).hexdigest()[:12]
    namespace = "_agent_platform_external_" + hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12] + "_" + digest
    package = sys.modules.get(namespace)
    if package is None:
        package = types.ModuleType(namespace)
        package.__path__ = [str(root)]
        package.__package__ = namespace
        package.__spec__ = importlib.machinery.ModuleSpec(namespace, loader=None, is_package=True)
        sys.modules[namespace] = package
    finder = _EXTERNAL_IMPORT_FINDERS.get(namespace)
    if finder is None:
        finder = _HashCheckedSourceFinder(namespace, root, expected_hashes)
        _EXTERNAL_IMPORT_FINDERS[namespace] = finder
        sys.meta_path.insert(0, finder)

    relative = Path(relative_file)
    if relative.name == "__init__.py" and not relative.parent.parts:
        _HashCheckedSourceLoader(root, expected_hashes, source).exec_module(package)
        return package
    if relative.name == "__init__.py":
        module_name = ".".join([namespace, *relative.parent.parts])
    else:
        module_name = ".".join([namespace, *relative.with_suffix("").parts])
    return importlib.import_module(module_name)


async def invoke_python_agent(configuration: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Verify approved source and invoke its one-dictionary Python interface."""
    root = _safe_project_root(configuration["project_path"])
    expected = configuration["source_hashes"]
    actual = source_fingerprint(root)
    if actual != expected:
        raise RuntimeError("external agent source changed since connection approval; reconnect and review it again")
    relative_file = configuration["relative_file"]
    symbol = configuration["symbol"]
    kind = configuration["kind"]
    digest = hashlib.sha256(repr(sorted(expected.items())).encode("utf-8")).hexdigest()
    cache_key = (str(root), relative_file, symbol, kind, digest)
    with _IMPORT_LOCK:
        callable_agent = _LOADED_ENTRYPOINTS.get(cache_key)
        if callable_agent is None:
            module = _load_external_module(root, relative_file, expected)
            implementation = getattr(module, symbol)
            if kind == "class":
                instance = implementation()
                callable_agent = getattr(instance, "run")
            elif kind == "function" and callable(implementation):
                callable_agent = implementation
            else:
                raise TypeError("external entry point is no longer a supported class or function")
            if not callable(callable_agent):
                raise TypeError("external entry point run method is not callable")
            _LOADED_ENTRYPOINTS[cache_key] = callable_agent
    result = callable_agent(dict(inputs))
    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, dict):
        raise TypeError("connected Python agents must return a dictionary")
    return result


def evict_external_agent_cache(project_path: str | Path | None = None, package_name: str | None = None) -> int:
    """Remove cached external entrypoints and module loaders for a deleted agent."""
    removed = 0
    with _IMPORT_LOCK:
        if project_path:
            try:
                resolved_root = str(Path(project_path).expanduser().resolve())
            except Exception:
                resolved_root = str(project_path)
            for key in [k for k in _LOADED_ENTRYPOINTS if k and k[0] == resolved_root]:
                _LOADED_ENTRYPOINTS.pop(key, None)
                removed += 1
            ns_prefix = "_agent_platform_external_" + hashlib.sha256(resolved_root.encode("utf-8")).hexdigest()[:12]
            for ns in [k for k in _EXTERNAL_IMPORT_FINDERS if k.startswith(ns_prefix)]:
                finder = _EXTERNAL_IMPORT_FINDERS.pop(ns, None)
                if finder in sys.meta_path:
                    sys.meta_path.remove(finder)
                removed += 1
            for mod_name in [m for m in list(sys.modules) if m.startswith(ns_prefix)]:
                sys.modules.pop(mod_name, None)
                removed += 1
        if package_name:
            mod_prefix = f"plugins.examples.{package_name}"
            for mod_name in [m for m in list(sys.modules) if m == mod_prefix or m.startswith(mod_prefix + ".")]:
                sys.modules.pop(mod_name, None)
                removed += 1
    return removed

