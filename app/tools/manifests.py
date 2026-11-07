from __future__ import annotations

from typing import Any, Literal

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import ToolMetadata


class ToolManifest(BaseModel):
    """Declarative metadata for a trusted local tool implementation."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,63}$")
    name: str
    version: str
    description: str
    adapter_type: Literal["python_callable"]
    entrypoint: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*$")
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    required_permissions: list[str]
    enabled: bool
    idempotent: bool = True
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def validate_json_schemas(self) -> "ToolManifest":
        for name, schema in (("input_schema", self.input_schema), ("output_schema", self.output_schema)):
            try:
                Draft202012Validator.check_schema(schema)
            except Exception as exc:
                raise ValueError(f"invalid {name}: {exc}") from exc
        return self

    def to_metadata(self) -> ToolMetadata:
        return ToolMetadata(
            id=self.id,
            name=self.name,
            description=self.description,
            version=self.version,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            required_permissions=self.required_permissions,
            adapter_type=self.adapter_type,
            enabled=self.enabled,
            idempotent=self.idempotent,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
        )
