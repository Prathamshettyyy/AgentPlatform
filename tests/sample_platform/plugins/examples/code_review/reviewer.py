from __future__ import annotations

from app.sdk.context import AgentContext
from app.sdk.contracts import AgentRequest


def run(request: AgentRequest, context: AgentContext) -> dict:
    """Turn source-inspection facts into deterministic structured findings."""

    inspection = request.inputs.get("inspection")
    if not isinstance(inspection, dict):
        raise ValueError("inspection must be an object")

    findings: list[dict] = []
    for construct in inspection.get("dangerous_constructs", []):
        name = construct.get("name", "unknown")
        line = construct.get("line", 0)
        severity = "high" if name in {"eval", "exec", "compile", "system", "popen"} else "medium"
        findings.append({
            "rule": "unsafe-operation",
            "severity": severity,
            "message": f"Review use of {name}; it can execute or invoke external operations.",
            "line": line,
        })
    if not inspection.get("function_names"):
        findings.append({
            "rule": "missing-function",
            "severity": "low",
            "message": "The snippet does not define a function; confirm that this is intentional.",
            "line": 1,
        })

    risk_level = "high" if any(item["severity"] == "high" for item in findings) else "low" if findings else "clear"
    return {
        "summary": f"Code review found {len(findings)} finding(s).",
        "findings": findings,
        "finding_count": len(findings),
        "risk_level": risk_level,
    }
