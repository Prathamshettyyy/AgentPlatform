from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.sdk.contracts import AgentMetadata


class AgentManifest(BaseModel):
    """Validated metadata and trusted implementation reference for one agent."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str
    version: str = "1.0.0"
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    adapter_type: Literal["python_callable", "compiled_langgraph"] = "python_callable"
    entrypoint: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
    enabled: bool = True
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contracts(self) -> "AgentManifest":
        for name, contract in (("input_schema", self.input_schema), ("output_schema", self.output_schema)):
            if contract and contract.get("type") not in {"object", "array", "string", "number", "integer", "boolean"}:
                raise ValueError(f"{name} must contain a supported JSON-schema type")
            if "properties" in contract and not isinstance(contract["properties"], dict):
                raise ValueError(f"{name}.properties must be an object")
        return self

    def to_metadata(self) -> AgentMetadata:
        return AgentMetadata(
            id=self.id,
            name=self.name,
            description=self.description,
            version=self.version,
            capabilities=self.capabilities,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            enabled=self.enabled,
            adapter_type=self.adapter_type,
            execution=self.execution,
        )

