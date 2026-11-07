from app.sdk.contracts import AgentMetadata, AgentRequest
from app.sdk.context import AgentContext
metadata = AgentMetadata(id="email_reply_writer", name="Email Reply Drafter", description="Drafts a mock reply.", capabilities=["email_reply_drafting"])
def run(request: AgentRequest, context: AgentContext):
    return {"draft": f"Thanks for the update regarding: {request.inputs.get('email_summary', '')}"}

