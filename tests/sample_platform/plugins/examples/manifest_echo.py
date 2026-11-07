from app.sdk.context import AgentContext
from app.sdk.contracts import AgentRequest


def run(request: AgentRequest, context: AgentContext) -> dict:
    return {"echoed": request.inputs.get("value", ""), "agent": "manifest_echo", "run_id": context.run_id}

