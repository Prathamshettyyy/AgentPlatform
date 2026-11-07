from app.sdk.contracts import AgentMetadata, AgentRequest
from app.sdk.context import AgentContext
metadata = AgentMetadata(id="mock_sender", name="Mock Sender", description="Simulates sending without external access.", capabilities=["mock_send"])
async def run(request: AgentRequest, context: AgentContext):
    draft = request.inputs.get("draft", "")
    result = await context.call_tool("email_send", {"to": request.inputs.get("to", "mock-recipient@example.invalid"), "subject": request.inputs.get("subject", "Mock reply"), "body": draft})
    if result.status == "failed":
        raise RuntimeError(result.error.message if result.error else "mock send failed")
    return {"sent": result.output["sent"], "message_id": result.output["message_id"], "draft": draft}

