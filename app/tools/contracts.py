from __future__ import annotations

from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.sdk.contracts import ErrorInfo


class ToolMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str
    description: str = ""
    version: str = "1.0.0"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = Field(default_factory=list)
    adapter_type: Literal["python_callable"] = "python_callable"
    enabled: bool = True
    idempotent: bool = True
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def validate_json_schemas(self) -> "ToolMetadata":
        for name, schema in (("input_schema", self.input_schema), ("output_schema", self.output_schema)):
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as exc:
                raise ValueError(f"invalid {name}: {exc}") from exc
        return self


class ToolExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    workflow_id: str | None = None
    node_id: str | None = None
    agent_id: str
    permissions: list[str] = Field(default_factory=list)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    execution_context: ToolExecutionContext


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["succeeded", "failed"]
    output: dict[str, Any] = Field(default_factory=dict)
    error: ErrorInfo | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_error_state(self) -> "ToolResult":
        if self.status == "failed" and self.error is None:
            raise ValueError("failed tool results require error information")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("succeeded tool results cannot contain an error")
        return self

