from app.tools import ToolExecutionContext, ToolRequest


def run(request: ToolRequest, context: ToolExecutionContext) -> dict[str, str]:
    """Small deterministic tool used to prove manifest discovery and reuse."""

    return {"result": request.inputs["value"]}
