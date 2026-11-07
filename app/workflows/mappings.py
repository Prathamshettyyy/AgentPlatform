from __future__ import annotations

from typing import Any


class MappingResolutionError(ValueError):
    pass


def resolve_path(state: dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    if len(parts) < 1 or parts[0] not in {"workflow_input", "node_outputs", "loop_counters"}:
        raise MappingResolutionError(f"unsupported mapping path: {path}")
    current: Any = state.get(parts[0])
    for part in parts[1:]:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise MappingResolutionError(f"mapping path does not exist: {path}")
    return current


def resolve_mapping(state: dict[str, Any], mapping: Any) -> Any:
    if mapping.path is not None:
        return resolve_path(state, mapping.path)
    return mapping.literal

