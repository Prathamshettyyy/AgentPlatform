from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class AgentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str
    description: str = ""
    version: str = "1.0.0"
    capabilities: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    adapter_type: Literal["python_callable", "compiled_langgraph"] = "python_callable"
    execution: dict[str, Any] = Field(default_factory=dict)


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    run_id: str
    workflow_id: str | None = None
    node_id: str | None = None
    session_id: str | None = None


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["succeeded", "failed"]
    output: dict[str, Any] = Field(default_factory=dict)
    error: ErrorInfo | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_error_state(self) -> "AgentResult":
        if self.status == "failed" and self.error is None:
            raise ValueError("failed results require error information")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("succeeded results cannot contain an error")
        return self

