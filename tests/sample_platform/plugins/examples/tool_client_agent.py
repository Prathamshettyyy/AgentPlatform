from app.sdk.contracts import AgentRequest
from app.sdk.context import AgentContext


async def run(request: AgentRequest, context: AgentContext) -> dict:
    """Generic example agent that delegates to an allowlisted tool by ID."""

    result = await context.call_tool(
        request.inputs.get("tool_id", "tool_echo"),
        {"value": request.inputs["value"]},
    )
    if result.status == "failed":
        raise RuntimeError(result.error.message if result.error else "tool execution failed")
    return result.output
