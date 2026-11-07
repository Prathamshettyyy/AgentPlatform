from app.sdk.contracts import AgentMetadata, AgentRequest
from app.sdk.context import AgentContext
metadata = AgentMetadata(id="email_summarizer", name="Email Summarizer", description="Summarizes mock email data.", capabilities=["email_summarization"])
async def run(request: AgentRequest, context: AgentContext):
    emails = request.inputs.get("emails", [])
    if request.inputs.get("use_tools"):
        search = await context.call_tool("email_search", {"query": request.inputs.get("query", "inbox")})
        if search.status == "failed":
            raise RuntimeError(search.error.message if search.error else "email search failed")
        emails = []
        for email_id in search.output["email_ids"]:
            read = await context.call_tool("email_read", {"email_id": email_id})
            if read.status == "failed":
                raise RuntimeError(read.error.message if read.error else "email read failed")
            emails.append(read.output)
    return {"summary": f"{len(emails)} email(s) reviewed", "subjects": [e.get("subject", "") for e in emails], "follow_ups": [e.get("subject", "") for e in emails if e.get("important", False)]}

