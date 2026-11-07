from __future__ import annotations

from app.sdk.context import AgentContext
from app.sdk.contracts import AgentRequest


def run(request: AgentRequest, context: AgentContext) -> dict:
    """Validate the review contract without changing or executing source code."""

    review = request.inputs.get("review")
    errors: list[str] = []
    if not isinstance(review, dict):
        errors.append("review must be an object")
        review = {}
    if not isinstance(review.get("summary"), str):
        errors.append("summary must be a string")
    if not isinstance(review.get("findings"), list):
        errors.append("findings must be an array")
    else:
        for index, finding in enumerate(review["findings"]):
            if not isinstance(finding, dict):
                errors.append(f"findings[{index}] must be an object")
                continue
            for field in ("rule", "severity", "message", "line"):
                if field not in finding:
                    errors.append(f"findings[{index}] is missing {field}")
            if finding.get("severity") not in {"low", "medium", "high"}:
                errors.append(f"findings[{index}].severity is invalid")
            if not isinstance(finding.get("line"), int):
                errors.append(f"findings[{index}].line must be an integer")
    if not isinstance(review.get("finding_count"), int):
        errors.append("finding_count must be an integer")
    elif isinstance(review.get("findings"), list) and review["finding_count"] != len(review["findings"]):
        errors.append("finding_count does not match findings")
    if review.get("risk_level") not in {"clear", "low", "high"}:
        errors.append("risk_level is invalid")
    return {
        "valid": not errors,
        "errors": errors,
        "checked_findings": len(review.get("findings", [])) if isinstance(review.get("findings"), list) else 0,
    }
