from __future__ import annotations

from collections import defaultdict, deque

from app.registry import AgentRegistry
from .models import WorkflowDefinition, WorkflowEdge, WorkflowNode


class WorkflowValidationError(ValueError):
    pass


def inspect_node_availability(node: WorkflowNode, registry: AgentRegistry) -> tuple[bool, str | None]:
    if node.type != "agent":
        return True, None
    registered = None
    try:
        registered = registry.get(node.agent_id, require_enabled=False)
    except Exception:
        registered = None
    if node.status == "disconnected":
        return False, f"agent '{node.agent_id}' is disconnected"
    if registered is None:
        return False, f"unknown or disconnected agent: {node.agent_id}"
    if not registered.metadata.enabled:
        return False, f"agent is disabled: {node.agent_id}"
    return True, None


def validate_workflow(workflow: WorkflowDefinition, registry: AgentRegistry, *, allow_partial: bool = False) -> None:
    if not workflow.nodes:
        raise WorkflowValidationError(
            f"workflow '{workflow.id}' has no valid nodes (workflow has no start node); add at least one agent first"
        )
    ids = [node.id for node in workflow.nodes]
    if len(ids) != len(set(ids)):
        raise WorkflowValidationError("duplicate node id")
    node_ids = set(ids)
    node_map = {node.id: node for node in workflow.nodes}
    incoming: dict[str, int] = defaultdict(int)
    incoming_sources: dict[str, list[str]] = defaultdict(list)
    adjacency: dict[str, list[str]] = defaultdict(list)
    unavailable_by_id: dict[str, str] = {}
    for node in workflow.nodes:
        if node.type == "agent":
            available, reason = inspect_node_availability(node, registry)
            if not available and reason:
                unavailable_by_id[node.id] = reason
    if not allow_partial and unavailable_by_id:
        unavailable_nodes = [f"{nid} ({reason})" for nid, reason in unavailable_by_id.items()]
        raise WorkflowValidationError(
            f"workflow '{workflow.id}' cannot be executed because the following nodes are unavailable: "
            + ", ".join(unavailable_nodes)
        )
    for edge in workflow.edges:
        if edge.from_node not in node_ids or edge.to not in node_ids:
            raise WorkflowValidationError("edge references unknown node")
        incoming[edge.to] += 1
        if edge.from_node not in incoming_sources[edge.to]:
            incoming_sources[edge.to].append(edge.from_node)
        adjacency[edge.from_node].append(edge.to)
    for node in workflow.nodes:
        for mapping in node.input_mappings.values():
            if not mapping.path or not mapping.path.startswith("node_outputs."):
                continue
            target = mapping.path.split(".")[1]
            if target not in node_ids:
                raise WorkflowValidationError(f"mapping references unknown node: {target}")
            if target == node.id:
                raise WorkflowValidationError(f"mapping for {node.id} cannot reference itself")
            pending = [target]
            reachable: set[str] = set()
            while pending:
                source = pending.pop()
                if source in reachable:
                    continue
                reachable.add(source)
                pending.extend(adjacency[source])
            if node.id not in reachable:
                raise WorkflowValidationError(f"mapping for {node.id} must reference an upstream node: {target}")

    starts = [n for n in ids if incoming[n] == 0]
    if not starts:
        # Check if there are nodes whose only incoming edges are self-loops
        starts = [n for n in ids if all(src == n for src in incoming_sources[n])]
    if not starts:
        raise WorkflowValidationError("workflow has no start node")

    # Verify all nodes are reachable from at least one start node
    reachable_from_start: set[str] = set()
    queue = deque(starts)
    visited: list[str] = []
    while queue:
        curr = queue.popleft()
        if curr in reachable_from_start:
            continue
        reachable_from_start.add(curr)
        visited.append(curr)
        for target in adjacency[curr]:
            if target not in reachable_from_start:
                queue.append(target)

    if reachable_from_start != node_ids:
        unreachable = sorted(node_ids - reachable_from_start)
        raise WorkflowValidationError(f"workflow contains unreachable nodes: {', '.join(unreachable)}")

    # Detect cycles and verify they are conditionally guarded with exit paths
    edge_map: dict[tuple[str, str], list] = defaultdict(list)
    for e in workflow.edges:
        edge_map[(e.from_node, e.to)].append(e)

    visited_dfs: set[str] = set()
    stack: list[str] = []
    stack_set: set[str] = set()
    cycles: list[list[str]] = []

    def dfs(curr: str):
        visited_dfs.add(curr)
        stack.append(curr)
        stack_set.add(curr)

        for nxt in adjacency.get(curr, []):
            if nxt in stack_set:
                idx = stack.index(nxt)
                cycles.append(stack[idx:])
            elif nxt not in visited_dfs:
                dfs(nxt)

        stack.pop()
        stack_set.remove(curr)

    for nid in ids:
        if nid not in visited_dfs:
            dfs(nid)

    for cycle in cycles:
        cycle_set = set(cycle)
        has_conditional_edge = False
        has_exit_edge = False
        for i in range(len(cycle)):
            u = cycle[i]
            v = cycle[(i + 1) % len(cycle)]
            for e in edge_map.get((u, v), []):
                if getattr(e, "condition", None) is not None:
                    has_conditional_edge = True
            for target in adjacency.get(u, []):
                if target not in cycle_set:
                    has_exit_edge = True

        if not has_conditional_edge and not has_exit_edge:
            raise WorkflowValidationError(
                f"workflow contains an infinite cycle with no termination condition or exit path: {' -> '.join(cycle)}"
            )

    # Detect ambiguous incoming edges (mixing conditional and unconditional incoming edges to the same join node)
    outgoing_by_node: dict[str, list[WorkflowEdge]] = defaultdict(list)
    for edge in workflow.edges:
        outgoing_by_node[edge.from_node].append(edge)

    for nid in ids:
        incoming_uncond_sources: set[str] = set()
        incoming_cond_sources: set[str] = set()
        for edge in workflow.edges:
            if edge.to != nid or edge.from_node == nid:
                continue
            src_node = node_map[edge.from_node]
            src_edges = outgoing_by_node[edge.from_node]
            is_uncond = (
                src_node.type != "human_approval"
                and bool(src_edges)
                and all(e.condition is None for e in src_edges)
            )
            if is_uncond:
                incoming_uncond_sources.add(edge.from_node)
            else:
                incoming_cond_sources.add(edge.from_node)

        if incoming_uncond_sources and incoming_cond_sources:
            raise WorkflowValidationError(
                f"ambiguous incoming edges for node '{nid}': cannot mix conditional and unconditional incoming edges to the same join node "
                f"(unconditional from {sorted(incoming_uncond_sources)}, conditional from {sorted(incoming_cond_sources)})"
            )

    if allow_partial and unavailable_by_id:
        eligible: set[str] = set()
        for nid in visited:
            if nid in unavailable_by_id:
                continue
            node = node_map[nid]
            if any(src not in eligible for src in incoming_sources[nid]):
                continue
            mapping_blocked = False
            for mapping in node.input_mappings.values():
                if mapping.path and mapping.path.startswith("node_outputs."):
                    ref_node = mapping.path.split(".")[1]
                    if ref_node not in eligible:
                        mapping_blocked = True
                        break
            if mapping_blocked:
                continue
            if (
                node.type == "human_approval"
                and node.approval_payload_path
                and node.approval_payload_path.startswith("node_outputs.")
            ):
                ref_node = node.approval_payload_path.split(".")[1]
                if ref_node not in eligible:
                    continue
            eligible.add(nid)
        if not eligible:
            unavailable_nodes = [f"{nid} ({reason})" for nid, reason in unavailable_by_id.items()]
            raise WorkflowValidationError(
                f"workflow '{workflow.id}' cannot be executed because the following nodes are unavailable: "
                + ", ".join(unavailable_nodes)
            )

