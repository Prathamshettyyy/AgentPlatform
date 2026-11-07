from __future__ import annotations

from app.tools.contracts import ToolExecutionContext, ToolMetadata, ToolRequest


MOCK_EMAILS = {
    "email-1": {"email_id": "email-1", "subject": "Release review", "body": "The release review is next Tuesday. Please publish the migration checklist.", "important": True},
    "email-2": {"email_id": "email-2", "subject": "Rollback owner", "body": "Please confirm the rollback owner before the release review.", "important": True},
}


search_metadata = ToolMetadata(
    id="email_search", name="Search Mock Emails", description="Searches deterministic mock email data.",
    input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    output_schema={"type": "object", "properties": {"email_ids": {"type": "array"}, "count": {"type": "integer"}}, "required": ["email_ids", "count"]},
    required_permissions=["email.read"],
)
read_metadata = ToolMetadata(
    id="email_read", name="Read Mock Email", description="Reads one deterministic mock email.",
    input_schema={"type": "object", "properties": {"email_id": {"type": "string"}}, "required": ["email_id"]},
    output_schema={"type": "object", "properties": {"email_id": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["email_id", "subject", "body"]},
    required_permissions=["email.read"],
)
send_metadata = ToolMetadata(
    id="email_send", name="Send Mock Email", description="Records a mock send without external email access.",
    input_schema={"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]},
    output_schema={"type": "object", "properties": {"sent": {"type": "boolean"}, "message_id": {"type": "string"}}, "required": ["sent", "message_id"]},
    required_permissions=["email.send"], idempotent=False,
)


def search_emails(request: ToolRequest, context: ToolExecutionContext) -> dict:
    query = request.inputs["query"].lower()
    ids = [email_id for email_id, email in MOCK_EMAILS.items() if query in (email["subject"] + " " + email["body"]).lower() or query == "inbox"]
    return {"email_ids": ids, "count": len(ids)}


def read_email(request: ToolRequest, context: ToolExecutionContext) -> dict:
    try:
        return dict(MOCK_EMAILS[request.inputs["email_id"]])
    except KeyError as exc:
        raise ValueError(f"mock email not found: {request.inputs['email_id']}") from exc


def send_email(request: ToolRequest, context: ToolExecutionContext) -> dict:
    return {"sent": True, "message_id": f"mock-message-{context.run_id}", "to": request.inputs["to"]}


def register(registry) -> None:
    registry.register(search_metadata, search_emails)
    registry.register(read_metadata, read_email)
    registry.register(send_metadata, send_email)

