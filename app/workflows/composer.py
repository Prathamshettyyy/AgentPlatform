"""Schema-driven input-mapping inference for adding an agent to a workflow.

This module is deliberately free of I/O and of agent-specific knowledge. It
compares the selected agent's declared input schema with the values that are
actually available to a new node: the original workflow input and the output of
the preceding node. A mapping is only inferred when exactly one compatible
source is the best match; everything else is returned as a question for the
developer so that no incorrect value is passed silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any

from app.registry import AgentRegistry
from .models import WorkflowDefinition

JsonTypes = frozenset[str] | None

_PATH = re.compile(r"^(workflow_input|node_outputs)\.[A-Za-z0-9_.-]+$")


class MappingError(ValueError):
    """An explicit or inferred mapping cannot be used safely."""


def _properties(schema: Any) -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema, dict) else None
    return properties if isinstance(properties, dict) else {}


def _required(schema: Any) -> list[str]:
    required = schema.get("required") if isinstance(schema, dict) else None
    if isinstance(required, list):
        return [item for item in required if isinstance(item, str)]
    return []


def _types(schema: Any) -> JsonTypes:
    if not isinstance(schema, dict):
        return None
    declared = schema.get("type")
    if isinstance(declared, str):
        return frozenset({declared})
    if isinstance(declared, list) and declared and all(isinstance(item, str) for item in declared):
        return frozenset(declared)
    return None


def types_compatible(source: JsonTypes, target: JsonTypes) -> bool | None:
    """True/False when both JSON types are declared, otherwise None (unverified)."""
    if source is None or target is None:
        return None
    return any(s == t or (s == "integer" and t == "number") for s in source for t in target)


def _describe(types: JsonTypes) -> str:
    return "/".join(sorted(types)) if types else "unknown"


def _agent_schema(registry: AgentRegistry, agent_id: str | None, kind: str) -> dict[str, Any]:
    if not agent_id:
        return {}
    try:
        value = getattr(registry.get(agent_id, require_enabled=False).metadata, kind)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _merge(target: dict[str, JsonTypes], name: str, types: JsonTypes) -> None:
    if name not in target:
        target[name] = types
    elif target[name] != types:
        target[name] = None


def workflow_input_fields(workflow: WorkflowDefinition, registry: AgentRegistry) -> dict[str, JsonTypes]:
    """Top-level workflow input fields already consumed by existing nodes."""
    found: dict[str, JsonTypes] = {}
    for node in workflow.nodes:
        if node.type != "agent":
            continue
        properties = _properties(_agent_schema(registry, node.agent_id, "input_schema"))
        for key, mapping in node.input_mappings.items():
            if not mapping.path or not mapping.path.startswith("workflow_input."):
                continue
            parts = mapping.path.split(".")[1:]
            types = _types(properties.get(key)) if len(parts) == 1 else None
            _merge(found, parts[0], types)
    return found


def known_node_outputs(
    node_id: str,
    workflow: WorkflowDefinition,
    registry: AgentRegistry,
    other_workflows: list[WorkflowDefinition] | None = None,
) -> dict[str, JsonTypes]:
    """Output fields of a node from its declared schema and from existing usage.

    Existing mappings (in this and other workflow definitions) that consume the
    same agent's output are real evidence of output fields, so they are reused
    when the agent manifest declares only a generic object output.
    """
    node = next(item for item in workflow.nodes if item.id == node_id)
    if node.type == "human_approval":
        return {"decision": frozenset({"string"})}
    declared = {
        name: _types(schema)
        for name, schema in _properties(_agent_schema(registry, node.agent_id, "output_schema")).items()
    }
    observed: dict[str, JsonTypes] = {}
    for candidate in [workflow, *(other_workflows or [])]:
        nodes = {item.id: item for item in candidate.nodes}
        for consumer in candidate.nodes:
            if consumer.type != "agent":
                continue
            properties = _properties(_agent_schema(registry, consumer.agent_id, "input_schema"))
            for key, mapping in consumer.input_mappings.items():
                if not mapping.path or not mapping.path.startswith("node_outputs."):
                    continue
                parts = mapping.path.split(".")[1:]
                source = nodes.get(parts[0])
                if len(parts) < 2 or source is None or source.type != "agent" or source.agent_id != node.agent_id:
                    continue
                types = _types(properties.get(key)) if len(parts) == 2 else None
                _merge(observed, parts[1], types)
    return {**{name: types for name, types in observed.items() if name not in declared}, **declared}


def name_score(target_field: str, source_field: str) -> int:
    """3 = identical, 2 = one name is a whole-word suffix of the other, 0 = unrelated."""
    left = target_field.lower().replace("-", "_").split("_")
    right = source_field.lower().replace("-", "_").split("_")
    if left == right:
        return 3
    shorter, longer = sorted((left, right), key=len)
    if longer[-len(shorter):] == shorter:
        return 2
    return 0


@dataclass(frozen=True)
class Candidate:
    path: str
    types: JsonTypes = None

    def label(self) -> str:
        return f"{self.path} ({_describe(self.types)})"


@dataclass
class Decision:
    field: str
    path: str | None = None
    literal: Any = None
    is_literal: bool = False
    origin: str = "inferred"  # inferred | override | answered | existing
    type_check: str = "unverified"  # verified | unverified | not-applicable

    def mapping(self) -> dict[str, Any]:
        return {"literal": self.literal} if self.is_literal else {"path": self.path}

    def describe(self) -> dict[str, Any]:
        source = {"literal": self.literal} if self.is_literal else {"path": self.path}
        return {"field": self.field, **source, "origin": self.origin, "type_check": self.type_check}


@dataclass
class Question:
    field: str
    required: bool
    reason: str  # ambiguous | unmapped | schema_mismatch
    candidates: list[Candidate] = dc_field(default_factory=list)
    rejected: list[Candidate] = dc_field(default_factory=list)

    def describe(self) -> str:
        requirement = "required" if self.required else "optional"
        if self.reason == "ambiguous":
            options = ", ".join(item.label() for item in self.candidates)
            return f"{self.field} ({requirement}) is ambiguous between {options}"
        if self.reason == "schema_mismatch":
            options = ", ".join(item.label() for item in self.rejected)
            return f"{self.field} ({requirement}) only matches sources with incompatible types: {options}"
        return f"{self.field} ({requirement}) has no matching source"


@dataclass
class MappingPlan:
    decisions: list[Decision]
    questions: list[Question]
    skipped_optional: list[str]
    target_types: dict[str, JsonTypes]
    inputs: dict[str, JsonTypes]
    outputs: dict[str, dict[str, JsonTypes]]
    fields: list[str]

    def type_of(self, path: str) -> JsonTypes:
        parts = path.split(".")
        if parts[0] == "workflow_input" and len(parts) == 2:
            return self.inputs.get(parts[1])
        if parts[0] == "node_outputs" and len(parts) == 3:
            return self.outputs.get(parts[1], {}).get(parts[2])
        return None

    def decide_path(self, target_field: str, path: str, origin: str) -> Decision:
        """Validate an explicit path for a field and turn it into a decision."""
        if target_field not in self.fields:
            raise MappingError(f"{target_field!r} is not an input field of the selected agent (fields: {', '.join(self.fields) or 'none'})")
        if not _PATH.fullmatch(path):
            raise MappingError(f"mapping path must start with workflow_input. or node_outputs.: {path!r}")
        compatible = types_compatible(self.type_of(path), self.target_types.get(target_field))
        if compatible is False:
            raise MappingError(
                f"schema mismatch: {path} is {_describe(self.type_of(path))} but {target_field} expects "
                f"{_describe(self.target_types.get(target_field))}"
            )
        return Decision(target_field, path=path, origin=origin, type_check="verified" if compatible else "unverified")

    def decide_literal(self, target_field: str, value: Any, origin: str) -> Decision:
        if target_field not in self.fields:
            raise MappingError(f"{target_field!r} is not an input field of the selected agent (fields: {', '.join(self.fields) or 'none'})")
        return Decision(target_field, literal=value, is_literal=True, origin=origin, type_check="not-applicable")


def _ancestors(workflow: WorkflowDefinition, node_id: str) -> set[str]:
    parents: dict[str, set[str]] = {}
    for edge in workflow.edges:
        parents.setdefault(edge.to, set()).add(edge.from_node)
    seen: set[str] = set()
    pending = [node_id]
    while pending:
        for parent in parents.get(pending.pop(), ()):
            if parent not in seen:
                seen.add(parent)
                pending.append(parent)
    return seen


def plan_agent_mappings(
    workflow: WorkflowDefinition,
    registry: AgentRegistry,
    agent_id: str,
    after_id: str,
    other_workflows: list[WorkflowDefinition] | None = None,
    path_overrides: dict[str, str] | None = None,
    literal_overrides: dict[str, Any] | None = None,
) -> MappingPlan:
    """Infer input mappings for ``agent_id`` placed directly after ``after_id``."""
    input_schema = _agent_schema(registry, agent_id, "input_schema")
    properties = _properties(input_schema)
    required = _required(input_schema)
    fields = list(properties) + [name for name in required if name not in properties]
    target_types = {name: _types(properties.get(name)) for name in fields}

    inputs = workflow_input_fields(workflow, registry)
    outputs = {
        node_id: known_node_outputs(node_id, workflow, registry, other_workflows)
        for node_id in {after_id, *_ancestors(workflow, after_id)}
    }
    plan = MappingPlan([], [], [], target_types, inputs, outputs, fields)

    path_overrides = path_overrides or {}
    literal_overrides = literal_overrides or {}
    clash = sorted(set(path_overrides) & set(literal_overrides))
    if clash:
        raise MappingError(f"field given both --map and --literal: {', '.join(clash)}")
    for name, path in path_overrides.items():
        plan.decisions.append(plan.decide_path(name, path, "override"))
    for name, value in literal_overrides.items():
        plan.decisions.append(plan.decide_literal(name, value, "override"))

    available = [Candidate(f"node_outputs.{after_id}.{name}", types) for name, types in outputs[after_id].items()]
    available += [Candidate(f"workflow_input.{name}", types) for name, types in inputs.items()]

    for name in fields:
        if name in path_overrides or name in literal_overrides:
            continue
        is_required = name in required
        scored = [(name_score(name, item.path.rsplit(".", 1)[1]), item) for item in available]
        scored = [(score, item) for score, item in scored if score > 0]
        accepted: list[tuple[int, Candidate]] = []
        rejected: list[Candidate] = []
        for score, item in scored:
            if types_compatible(item.types, target_types[name]) is False:
                rejected.append(item)
            else:
                accepted.append((score, item))
        if accepted:
            best = max(score for score, _ in accepted)
            winners = [item for score, item in accepted if score == best]
            if len(winners) == 1:
                verified = types_compatible(winners[0].types, target_types[name])
                plan.decisions.append(Decision(
                    name, path=winners[0].path, origin="inferred",
                    type_check="verified" if verified else "unverified",
                ))
            else:
                plan.questions.append(Question(name, is_required, "ambiguous", winners, rejected))
        elif rejected:
            plan.questions.append(Question(name, is_required, "schema_mismatch", [], rejected))
        elif is_required:
            plan.questions.append(Question(name, True, "unmapped"))
        else:
            plan.skipped_optional.append(name)
    return plan
