from __future__ import annotations

import ast

from app.sdk.context import AgentContext
from app.sdk.contracts import AgentRequest


class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.function_names: list[str] = []
        self.imports: list[str] = []
        self.dangerous_constructs: list[dict[str, str | int]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.function_names.append(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.function_names.append(node.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.extend(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self.imports.append(node.module)

    def visit_Call(self, node: ast.Call) -> None:
        name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
        if name in {"eval", "exec", "compile", "system", "popen", "run"}:
            self.dangerous_constructs.append({"name": name, "line": node.lineno})
        self.generic_visit(node)


def run(request: AgentRequest, context: AgentContext) -> dict:
    """Inspect Python syntax only; this agent never executes the supplied code."""

    source_code = request.inputs.get("source_code")
    if not isinstance(source_code, str) or not source_code.strip():
        raise ValueError("source_code must be a non-empty string")
    try:
        tree = ast.parse(source_code)
    except SyntaxError as exc:
        raise ValueError(f"source code is not valid Python: {exc.msg} at line {exc.lineno}") from exc

    visitor = _SafetyVisitor()
    visitor.visit(tree)
    return {
        "language": "python",
        "line_count": len(source_code.splitlines()),
        "function_names": visitor.function_names,
        "imports": visitor.imports,
        "dangerous_constructs": visitor.dangerous_constructs,
        "parse_ok": True,
    }
