from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt
from temporalio.common import RetryPolicy

from app.registry import AgentRegistry
from app.runtime.runner import AgentRunner
from app.security import redact_sensitive
from app.sdk.contracts import AgentRequest
from .mappings import resolve_mapping
from .models import WorkflowDefinition, WorkflowNode
from .validator import WorkflowValidationError, inspect_node_availability, validate_workflow


def _merge_dicts(
    left: dict[str, dict[str, Any]] | None,
    right: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    merged = dict(left or {})
    if right:
        merged.update(right)
    return merged


def _replace_latest(left: Any, right: Any) -> Any:
    return right if right is not None else left


def _keep_first_str(left: str | None, right: str | None) -> str | None:
    return left if left is not None else right


def _merge_node_records(
    left: list[dict[str, Any]] | None,
    right: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    merged = [dict(item) for item in (left or [])]
    seen = {item.get("node_id") for item in merged}
    for item in right or []:
        if item.get("node_id") not in seen:
            merged.append(dict(item))
            seen.add(item.get("node_id"))
    return merged


def _or_bool(left: bool | None, right: bool | None) -> bool:
    return bool(left or right)


class WorkflowState(TypedDict, total=False):
    run_id: str
    workflow_id: str
    workflow_version: str
    workflow_input: dict[str, Any]
    node_outputs: Annotated[dict[str, dict[str, Any]], _merge_dicts]
    agent_outputs: Annotated[dict[str, dict[str, Any]], _merge_dicts]
    loop_counters: Annotated[dict[str, int], _merge_dicts]
    final_output: Annotated[dict[str, Any], _replace_latest]
    blocked_by_node: Annotated[str | None, _keep_first_str]
    blocked_nodes: Annotated[list[dict[str, Any]], _merge_node_records]
    skipped_nodes: Annotated[list[dict[str, Any]], _merge_node_records]
    partial_execution: Annotated[bool, _or_bool]
    message: Annotated[str, _replace_latest]


def _build_partial_message(
    executed_ids: list[str],
    blocked_by_node: str | None,
    blocked_nodes: list[dict[str, Any]],
    skipped_nodes: list[dict[str, Any]],
) -> str:
    blocker = blocked_nodes[0] if blocked_nodes else (skipped_nodes[0] if skipped_nodes else None)
    blocker_id = blocked_by_node or (blocker["node_id"] if blocker else "unknown")
    blocker_reason = blocker["reason"] if blocker else "a required node was unavailable."
    has_quality_or_validation = any(
        any(
            token in (item.get("node_id") or "").lower() or token in (item.get("agent_id") or "").lower()
            for token in ("quality", "validat", "checker", "verify", "review")
        )
        for item in skipped_nodes
    )
    validation_note = (
        "Quality validation did not run."
        if has_quality_or_validation
        else f"Downstream node(s) [{', '.join(item['node_id'] for item in skipped_nodes)}] did not run; quality validation did not run."
    )
    if executed_ids:
        executed_str = ", ".join(f"'{nid}'" for nid in executed_ids)
        return (
            f"Workflow partially succeeded: executed {executed_str}, "
            f"but execution stopped at node '{blocker_id}'. {blocker_reason} {validation_note}"
        )
    return (
        f"Workflow could not execute any nodes: execution was blocked at node '{blocker_id}'. "
        f"{blocker_reason} {validation_note}"
    )


class WorkflowBuilder:
    def __init__(self, registry: AgentRegistry, runner: AgentRunner | None = None, checkpointer=None):
        self.registry = registry
        self.runner = runner or AgentRunner(registry)
        self.checkpointer = checkpointer or InMemorySaver()

    def build_state_graph(self, workflow: WorkflowDefinition, *, allow_partial: bool = False) -> StateGraph:
        validate_workflow(workflow, self.registry, allow_partial=allow_partial)
        graph = StateGraph(WorkflowState)
        outgoing: dict[str, list] = {node.id: [] for node in workflow.nodes}
        incoming_sources: dict[str, list[str]] = {node.id: [] for node in workflow.nodes}
        for edge in workflow.edges:
            outgoing[edge.from_node].append(edge)
            if edge.from_node not in incoming_sources[edge.to]:
                incoming_sources[edge.to].append(edge.from_node)
        for node in workflow.nodes:
            exec_in = getattr(node, "execute_in", "activity") or "activity"
            metadata: dict[str, Any] = {
                "execute_in": exec_in,
            }
            if exec_in == "activity":
                timeout_s = getattr(node, "timeout_seconds", None) or 120
                metadata["start_to_close_timeout"] = timedelta(seconds=timeout_s)
                max_retries = getattr(node, "max_retries", None) or 3
                backoff_s = getattr(node, "retry_backoff_seconds", None) or 1.0
                metadata["retry_policy"] = RetryPolicy(
                    maximum_attempts=max_retries,
                    initial_interval=timedelta(seconds=backoff_s),
                )
            graph.add_node(
                node.id,
                self._node_callable(
                    node,
                    workflow,
                    allow_partial=allow_partial,
                    incoming_sources=incoming_sources[node.id],
                    outgoing=outgoing,
                ),
                metadata=metadata,
            )
        # Collect unconditional incoming edges grouped by destination node
        unconditional_incoming: dict[str, list[str]] = {node.id: [] for node in workflow.nodes}
        for node in workflow.nodes:
            edges = outgoing[node.id]
            if node.type != "human_approval" and edges and all(edge.condition is None for edge in edges):
                for edge in edges:
                    if node.id not in unconditional_incoming[edge.to]:
                        unconditional_incoming[edge.to].append(node.id)

        # Explicitly check for ambiguous cases where conditional and unconditional incoming edges target the same join node
        for node in workflow.nodes:
            edges = outgoing[node.id]
            if (node.type == "human_approval") or not (edges and all(e.condition is None for e in edges)):
                for edge in edges:
                    if edge.to != node.id and unconditional_incoming.get(edge.to):
                        raise WorkflowValidationError(
                            f"ambiguous incoming edges for node '{edge.to}': cannot mix conditional and unconditional incoming edges to the same join node"
                        )

        # Add node outgoing edges (terminal END, human approval router, and conditional router)
        for node in workflow.nodes:
            edges = outgoing[node.id]
            if not edges:
                graph.add_edge(node.id, END)
            elif node.type == "human_approval" and len(edges) == 1 and edges[0].condition is None:
                target = edges[0].to
                graph.add_conditional_edges(
                    node.id,
                    self._approval_router(node.id, "approve" if "approve" in node.approval_options else node.approval_options[0], target),
                    {target: target, END: END},
                )
            elif node.type != "human_approval" and all(edge.condition is None for edge in edges):
                # Unconditional edges are added via unconditional_incoming barrier handling below
                pass
            else:
                destinations = {edge.to: edge.to for edge in edges}
                destinations[END] = END
                graph.add_conditional_edges(
                    node.id,
                    self._router(edges, from_node_id=node.id, allow_partial=allow_partial),
                    destinations,
                )

        # Add unconditional incoming edges to destinations
        # Multi-source barrier edge when destination has multiple unconditional predecessors;
        # single-source edge when destination has exactly one.
        for dest_id, sources in unconditional_incoming.items():
            if len(sources) > 1:
                graph.add_edge(sources, dest_id)
            elif len(sources) == 1:
                graph.add_edge(sources[0], dest_id)
        incoming = {n.id: 0 for n in workflow.nodes}
        for edge in workflow.edges:
            incoming[edge.to] += 1
        starts = [n.id for n in workflow.nodes if incoming[n.id] == 0]
        if not starts:
            starts = [n.id for n in workflow.nodes if all(src == n.id for src in incoming_sources[n.id])]
        for node_id in starts:
            graph.add_edge(START, node_id)
        return graph

    def build(self, workflow: WorkflowDefinition, *, allow_partial: bool = False):
        graph = self.build_state_graph(workflow, allow_partial=allow_partial)
        compiled = graph.compile(checkpointer=self.checkpointer)
        if allow_partial:
            orig_ainvoke = compiled.ainvoke

            async def _ainvoke(input_data, config=None, **kwargs):
                res = await orig_ainvoke(input_data, config=config, **kwargs)
                if isinstance(res, dict) and res.get("partial_execution"):
                    res["message"] = _build_partial_message(
                        list((res.get("agent_outputs") or {}).keys()),
                        res.get("blocked_by_node"),
                        res.get("blocked_nodes") or [],
                        res.get("skipped_nodes") or [],
                    )
                return res

            object.__setattr__(compiled, "ainvoke", _ainvoke)
        return compiled

    def _record_partial_skip(
        self,
        state: WorkflowState,
        workflow: WorkflowDefinition,
        node: WorkflowNode,
        *,
        reason: str,
        is_blocker: bool,
        blocker_status: str = "disconnected",
        outgoing: dict[str, list] | None = None,
    ) -> dict[str, Any]:
        blocked_nodes = [dict(item) for item in state.get("blocked_nodes", [])]
        skipped_nodes = [dict(item) for item in state.get("skipped_nodes", [])]
        blocked_by_node = state.get("blocked_by_node")

        if is_blocker:
            if not blocked_by_node:
                blocked_by_node = node.id
            if not any(item["node_id"] == node.id for item in blocked_nodes):
                blocked_nodes.append({
                    "node_id": node.id,
                    "agent_id": node.agent_id,
                    "status": blocker_status,
                    "reason": reason,
                })

        if not any(item["node_id"] == node.id for item in skipped_nodes):
            skipped_nodes.append({
                "node_id": node.id,
                "agent_id": node.agent_id,
                "status": "blocked" if is_blocker else "skipped",
                "reason": reason,
            })

        # If this node routes conditionally or is human_approval, routing will terminate at END;
        # record any downstream descendants in skipped_nodes so they are still reported.
        edges = (outgoing or {}).get(node.id, [])
        stops_routing = node.type == "human_approval" or any(edge.condition is not None for edge in edges)
        if stops_routing and outgoing:
            node_map = {n.id: n for n in workflow.nodes}
            queue = [edge.to for edge in edges]
            seen: set[str] = set()
            while queue:
                curr_id = queue.pop(0)
                if curr_id in seen:
                    continue
                seen.add(curr_id)
                desc_node = node_map.get(curr_id)
                if desc_node and not any(item["node_id"] == curr_id for item in skipped_nodes):
                    skipped_nodes.append({
                        "node_id": curr_id,
                        "agent_id": desc_node.agent_id,
                        "status": "skipped",
                        "reason": f"Node '{curr_id}' was skipped because upstream node '{node.id}' did not execute.",
                    })
                for next_edge in outgoing.get(curr_id, []):
                    queue.append(next_edge.to)

        executed_ids = list((state.get("agent_outputs") or {}).keys())
        message = _build_partial_message(executed_ids, blocked_by_node, blocked_nodes, skipped_nodes)
        return {
            "blocked_by_node": blocked_by_node,
            "blocked_nodes": blocked_nodes,
            "skipped_nodes": skipped_nodes,
            "partial_execution": True,
            "message": message,
        }

    def _node_callable(
        self,
        node: WorkflowNode,
        workflow: WorkflowDefinition,
        *,
        allow_partial: bool = False,
        incoming_sources: list[str] | None = None,
        outgoing: dict[str, list] | None = None,
    ):
        async def invoke(state: WorkflowState):
            if allow_partial:
                skipped_ids = {item["node_id"] for item in state.get("skipped_nodes", [])} | {
                    item["node_id"] for item in state.get("blocked_nodes", [])
                }
                for field, mapping in node.input_mappings.items():
                    if mapping.path and mapping.path.startswith("node_outputs."):
                        ref_node = mapping.path.split(".")[1]
                        if ref_node in skipped_ids or ref_node not in state.get("node_outputs", {}):
                            reason = (
                                f"Node '{node.id}' was skipped because upstream node '{ref_node}' "
                                f"did not execute (required for input '{field}')."
                            )
                            return self._record_partial_skip(
                                state, workflow, node, reason=reason, is_blocker=False, outgoing=outgoing
                            )
                for src in incoming_sources or []:
                    if src in skipped_ids:
                        reason = f"Node '{node.id}' was skipped because upstream node '{src}' did not execute."
                        return self._record_partial_skip(
                            state, workflow, node, reason=reason, is_blocker=False, outgoing=outgoing
                        )

                if node.type == "agent":
                    available, unavail_reason = inspect_node_availability(node, self.registry)
                    if not available:
                        reason = f"Node '{node.id}' could not execute because {unavail_reason}."
                        blocker_status = "disconnected" if node.status == "disconnected" or "disconnected" in (unavail_reason or "") else "unavailable"
                        return self._record_partial_skip(
                            state,
                            workflow,
                            node,
                            reason=reason,
                            is_blocker=True,
                            blocker_status=blocker_status,
                            outgoing=outgoing,
                        )

            if node.type == "trigger":
                trigger_data = dict(state.get("workflow_input", {}))
                outputs = {**state.get("node_outputs", {}), node.id: trigger_data}
                return {
                    "node_outputs": outputs,
                    "final_output": trigger_data,
                }

            if node.type == "human_approval":
                if allow_partial and node.approval_payload_path and node.approval_payload_path.startswith("node_outputs."):
                    ref_node = node.approval_payload_path.split(".")[1]
                    if ref_node not in state.get("node_outputs", {}):
                        reason = f"Node '{node.id}' was skipped because upstream node '{ref_node}' did not execute."
                        return self._record_partial_skip(
                            state, workflow, node, reason=reason, is_blocker=False, outgoing=outgoing
                        )
                payload = resolve_mapping(state, type("Mapping", (), {"path": node.approval_payload_path, "literal": None})())
                decision = interrupt({"node_id": node.id, "payload": payload, "options": node.approval_options})
                if decision not in node.approval_options:
                    raise ValueError(f"invalid approval decision: {decision}")
                return {"node_outputs": {**state.get("node_outputs", {}), node.id: {"decision": decision}}}

            if allow_partial:
                inputs: dict[str, Any] = {}
                for key, mapping in node.input_mappings.items():
                    try:
                        inputs[key] = resolve_mapping(state, mapping)
                    except KeyError:
                        reason = f"Node '{node.id}' could not execute because required input '{key}' ({mapping.path}) is unavailable."
                        return self._record_partial_skip(
                            state,
                            workflow,
                            node,
                            reason=reason,
                            is_blocker=True,
                            blocker_status="missing_input",
                            outgoing=outgoing,
                        )
                registered = self.registry.get(node.agent_id)
                schema = registered.metadata.input_schema if isinstance(registered.metadata.input_schema, dict) else {}
                req_fields = schema.get("required") if isinstance(schema.get("required"), list) else []
                props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
                for req_field in req_fields:
                    prop_schema = props.get(req_field) if isinstance(props.get(req_field), dict) else {}
                    prop_type = prop_schema.get("type")
                    null_allowed = prop_type == "null" or (isinstance(prop_type, list) and "null" in prop_type)
                    if req_field not in inputs or (inputs[req_field] is None and not null_allowed):
                        reason = f"Node '{node.id}' could not execute because required input '{req_field}' is unavailable."
                        return self._record_partial_skip(
                            state,
                            workflow,
                            node,
                            reason=reason,
                            is_blocker=True,
                            blocker_status="missing_input",
                            outgoing=outgoing,
                        )
            else:
                inputs = {key: resolve_mapping(state, mapping) for key, mapping in node.input_mappings.items()}

            curr_counters = dict(state.get("loop_counters", {}))
            node_exec_count = curr_counters.get(node.id, 0) + 1
            curr_counters[node.id] = node_exec_count
            if node_exec_count > workflow.max_steps:
                raise RuntimeError(
                    f"Workflow execution exceeded maximum loop limit ({workflow.max_steps}) at node '{node.id}'"
                )

            result = await self.runner.run(node.agent_id, AgentRequest(task="workflow node", inputs=inputs, run_id=state["run_id"], workflow_id=workflow.id, node_id=node.id))
            if result.status == "failed":
                raise RuntimeError(result.error.message if result.error else "agent failed")
            safe_output = redact_sensitive(result.output)
            outputs = {**state.get("node_outputs", {}), node.id: safe_output}
            agent_outputs = {**state.get("agent_outputs", {}), node.id: safe_output}
            update: dict[str, Any] = {
                "node_outputs": outputs,
                "agent_outputs": agent_outputs,
                "loop_counters": curr_counters,
                "final_output": safe_output,
            }
            if state.get("partial_execution"):
                update["message"] = _build_partial_message(
                    list(agent_outputs.keys()),
                    state.get("blocked_by_node"),
                    state.get("blocked_nodes", []),
                    state.get("skipped_nodes", []),
                )
            return update

        invoke.__module__ = "app.workflows.builder"
        invoke.__qualname__ = f"node_exec_{node.id}"
        return invoke

    @staticmethod
    def _approval_router(node_id: str, approved_decision: str, target: str):
        async def route(state):
            decision = state.get("node_outputs", {}).get(node_id, {}).get("decision")
            return target if decision == approved_decision else END

        route.__module__ = "app.workflows.builder"
        route.__qualname__ = f"approval_route_{node_id}"
        return route

    @staticmethod
    def _router(edges, *, from_node_id: str | None = None, allow_partial: bool = False):
        async def route(state):
            if allow_partial and from_node_id and from_node_id not in state.get("node_outputs", {}):
                return END
            for edge in edges:
                if edge.condition is None:
                    return edge.to
                condition = edge.condition
                try:
                    value = resolve_mapping(state, type("Mapping", (), {"path": condition.path, "literal": None})())
                except Exception:
                    value = None
                if condition.operator == "exists" and value is not None:
                    return edge.to
                if condition.operator == "truthy" and bool(value):
                    return edge.to
                if condition.operator == "equals" and value == condition.value:
                    return edge.to
                if condition.operator == "not_equals" and value != condition.value:
                    return edge.to
                if condition.operator == "less_than" and value is not None and value < condition.value:
                    return edge.to
                if condition.operator == "greater_than" and value is not None and value > condition.value:
                    return edge.to
                if condition.operator == "less_than_or_equals" and value is not None and value <= condition.value:
                    return edge.to
                if condition.operator == "greater_than_or_equals" and value is not None and value >= condition.value:
                    return edge.to
            return END

        route.__module__ = "app.workflows.builder"
        route.__qualname__ = f"route_{from_node_id or 'edge'}"
        return route

