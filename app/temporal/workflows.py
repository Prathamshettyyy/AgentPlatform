from __future__ import annotations

import asyncio
from typing import Any
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from temporalio import workflow
from temporalio.langgraph import graph


@workflow.defn(name="DynamicLangGraphWorkflow")
class DynamicLangGraphWorkflow:
    """Temporal Workflow executing dynamically registered LangGraph StateGraphs.

    Uses LangGraphPlugin to execute agent nodes as Temporal Activities,
    fan-in and routing in workflow context, and InMemorySaver for graph
    durability managed by Temporal's event history.
    """

    def __init__(self) -> None:
        self._current_status: str = "running"
        self._latest_output: dict[str, Any] = {}
        self._pending_approval: dict[str, Any] | None = None
        self._received_approval: str | None = None

    @workflow.query(name="get_status")
    def get_status(self) -> dict[str, Any]:
        """Query execution progress and current state from outside."""
        return {
            "status": self._current_status,
            "latest_output": self._latest_output,
            "pending_approval": self._pending_approval,
        }

    @workflow.signal(name="resume_approval")
    def resume_approval(self, decision: str) -> None:
        """Signal an approval decision to resume a paused workflow."""
        self._received_approval = decision

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow_id = payload["workflow_id"]
        run_id = payload.get("run_id") or workflow.info().run_id
        workflow_version = payload.get("workflow_version", "1.0.0")
        workflow_input = payload.get("workflow_input", {})
        max_steps = int(payload.get("max_steps", 100))

        # Retrieve registered graph from LangGraphPlugin (versioned or base)
        versioned_key = f"{workflow_id}@{workflow_version}"
        try:
            g = graph(versioned_key)
        except (KeyError, RuntimeError):
            g = graph(workflow_id)
        checkpointer = InMemorySaver()
        compiled = g.compile(checkpointer=checkpointer)

        state_input: dict[str, Any] = {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "workflow_version": workflow_version,
            "workflow_input": workflow_input,
            "node_outputs": {},
            "agent_outputs": {},
            "loop_counters": {},
        }

        config = {
            "configurable": {"thread_id": run_id},
            "recursion_limit": max_steps,
        }

        result = await compiled.ainvoke(state_input, config)

        # Handle human approval pause/resume if graph interrupted
        while isinstance(result, dict) and "__interrupt__" in result:
            interrupt_info = result["__interrupt__"]
            self._current_status = "waiting_for_approval"
            self._pending_approval = interrupt_info
            self._latest_output = dict(result)

            # Wait until signal arrives
            await workflow.wait_condition(lambda: self._received_approval is not None)

            decision = self._received_approval
            self._received_approval = None
            self._pending_approval = None
            self._current_status = "running"

            # Resume execution
            result = await compiled.ainvoke(Command(resume=decision), config)

        self._current_status = "succeeded"
        self._latest_output = dict(result) if isinstance(result, dict) else {"result": result}
        return self._latest_output


@workflow.defn(name="BatchLangGraphWorkflow")
class BatchLangGraphWorkflow:
    """Temporal Parent Workflow coordinating parallel batch execution of LangGraph workflows.

    Dispatches bounded concurrent child workflows for each item, aggregates
    individual outcomes, and provides failure isolation.
    """

    @workflow.run
    async def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        batch_id = payload.get("batch_id") or workflow.info().workflow_id
        workflow_id = payload["workflow_id"]
        workflow_version = payload.get("workflow_version", "1.0.0")
        items: list[dict[str, Any]] = payload.get("items", [])
        raw_concurrency = int(payload.get("concurrency", 5))
        concurrency = max(1, min(raw_concurrency, 50))
        max_steps = int(payload.get("max_steps", 100))

        sem = asyncio.Semaphore(concurrency)

        async def process_item(index: int, item: dict[str, Any]) -> dict[str, Any]:
            item_id = item.get("item_id", f"item-{index}")
            item_input = item.get("input", item)
            child_workflow_id = f"{batch_id}-{item_id}"

            async with sem:
                try:
                    result = await workflow.execute_child_workflow(
                        DynamicLangGraphWorkflow.run,
                        {
                            "workflow_id": workflow_id,
                            "workflow_version": workflow_version,
                            "run_id": child_workflow_id,
                            "workflow_input": item_input,
                            "max_steps": max_steps,
                        },
                        id=child_workflow_id,
                    )
                    return {
                        "item_id": item_id,
                        "status": "succeeded",
                        "output": result,
                    }
                except Exception as exc:
                    return {
                        "item_id": item_id,
                        "status": "failed",
                        "error": str(exc),
                    }

        tasks = [process_item(i, item) for i, item in enumerate(items)]
        item_results = await asyncio.gather(*tasks)

        succeeded_count = sum(1 for r in item_results if r["status"] == "succeeded")
        failed_count = sum(1 for r in item_results if r["status"] == "failed")

        return {
            "batch_id": batch_id,
            "workflow_id": workflow_id,
            "workflow_version": workflow_version,
            "total_items": len(items),
            "succeeded_count": succeeded_count,
            "failed_count": failed_count,
            "items": item_results,
            "status": "succeeded" if failed_count == 0 else ("partial" if succeeded_count > 0 else "failed"),
        }

