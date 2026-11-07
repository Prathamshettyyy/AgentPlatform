from app.sdk.context import AgentContext
from app.sdk.contracts import AgentMetadata, AgentRequest

metadata = AgentMetadata(id="deterministic_echo", name="Deterministic Echo", description="Returns deterministic structured data.", capabilities=["testing"])


def run(request: AgentRequest, context: AgentContext) -> dict:
    return {"message": request.inputs.get("message", ""), "run_id": context.run_id, "received": True}

