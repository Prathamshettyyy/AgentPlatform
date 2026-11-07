from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class MappingValue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str | None = Field(default=None, pattern=r"^(workflow_input|node_outputs)\.[A-Za-z0-9_.-]+$")
    literal: Any = None

    @model_validator(mode="after")
    def exactly_one_source(self):
        has_path = self.path is not None
        has_literal = "literal" in self.model_fields_set
        # Older persisted workflow JSON included the default ``literal: null``
        # alongside a valid path. Treat that representation as a path mapping;
        # an explicitly non-null literal remains a genuine conflict.
        if has_path and self.literal is not None:
            raise ValueError("mapping must specify exactly one of path or literal")
        if not has_path and not has_literal:
            raise ValueError("mapping must specify exactly one of path or literal")
        return self


class Condition(BaseModel):
    path: str = Field(pattern=r"^(workflow_input|node_outputs|loop_counters)(\.[A-Za-z0-9_.-]+)?$")
    operator: Literal[
        "equals",
        "not_equals",
        "exists",
        "truthy",
        "less_than",
        "greater_than",
        "less_than_or_equals",
        "greater_than_or_equals",
    ]
    value: Any = None


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    type: Literal["agent", "human_approval", "trigger"]
    agent_id: str | None = None
    trigger_type: Literal["webhook", "schedule", "manual"] | None = None
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    status: Literal["available", "disconnected"] = "available"
    input_mappings: dict[str, MappingValue] = Field(default_factory=dict)
    approval_payload_path: str | None = Field(default=None, pattern=r"^(workflow_input|node_outputs)(\.[A-Za-z0-9_.-]+)?$")
    approval_options: list[str] = Field(default_factory=lambda: ["approve", "reject"])
    # Temporal execution configuration
    execute_in: Literal["activity", "workflow"] = "activity"
    timeout_seconds: int | None = Field(default=None, gt=0)
    max_retries: int | None = Field(default=None, ge=1)
    retry_backoff_seconds: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_type_fields(self):
        if self.type == "agent" and not self.agent_id:
            raise ValueError("agent nodes require agent_id")
        if self.type == "human_approval":
            self.execute_in = "workflow"
            if not self.approval_payload_path:
                raise ValueError("human approval nodes require approval_payload_path")
            if not self.approval_options or len(self.approval_options) != len(set(self.approval_options)):
                raise ValueError("human approval nodes require unique approval options")
        if self.type == "trigger":
            self.execute_in = "workflow"
            if not self.trigger_type:
                self.trigger_type = "webhook"
        return self


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    from_node: str = Field(alias="from")
    to: str
    condition: Condition | None = None

    @property
    def source(self) -> str:
        return self.from_node

    @property
    def target(self) -> str:
        return self.to


class WorkflowDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    version: str = "1.0.0"
    nodes: list[WorkflowNode]
    edges: list[WorkflowEdge]
    max_steps: int = Field(default=100, gt=0, le=1000)
    registered: bool | None = None
    registration_status: str | None = None
    workflow_file: str | None = None

