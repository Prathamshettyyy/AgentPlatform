from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Optional
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
    ScheduleState,
)

from .workflows import DynamicLangGraphWorkflow


def parse_schedule_spec(cron_or_interval: str) -> ScheduleSpec:
    """Parse cron expression or interval string into a Temporal ScheduleSpec.

    Supports:
    - Interval strings: "1h", "30m", "10s", "@every 15m"
    - Standard cron expressions: "0 * * * *", "*/5 * * * *"
    """
    cleaned = cron_or_interval.strip()
    if cleaned.startswith("@every "):
        cleaned = cleaned[7:].strip()

    # Check for duration format, e.g. 10s, 30m, 2h, 1d
    interval_match = re.match(r"^(\d+)\s*(s|sec|m|min|h|hr|d|day)s?$", cleaned, re.IGNORECASE)
    if interval_match:
        val = int(interval_match.group(1))
        unit = interval_match.group(2).lower()
        if unit in ("s", "sec"):
            td = timedelta(seconds=val)
        elif unit in ("m", "min"):
            td = timedelta(minutes=val)
        elif unit in ("h", "hr"):
            td = timedelta(hours=val)
        elif unit in ("d", "day"):
            td = timedelta(days=val)
        else:
            td = timedelta(minutes=val)
        return ScheduleSpec(intervals=[ScheduleIntervalSpec(every=td)])

    # Otherwise treat as standard cron expression
    return ScheduleSpec(cron_expressions=[cleaned])


async def create_temporal_schedule(
    client: Client,
    schedule_id: str,
    workflow_id: str,
    cron_or_interval: str,
    input_payload: Optional[dict[str, Any]] = None,
    workflow_version: str = "1.0.0",
    task_queue: str = "agent-platform-queue",
    paused: bool = False,
) -> Any:
    """Create a new Temporal Schedule targeting DynamicLangGraphWorkflow."""
    spec = parse_schedule_spec(cron_or_interval)
    payload = {
        "workflow_id": workflow_id,
        "workflow_version": workflow_version,
        "workflow_input": input_payload or {},
        "run_id": f"sched-{schedule_id}",
    }

    action = ScheduleActionStartWorkflow(
        DynamicLangGraphWorkflow.run,
        payload,
        id=f"scheduled-{schedule_id}",
        task_queue=task_queue,
    )

    handle = await client.create_schedule(
        schedule_id,
        Schedule(
            action=action,
            spec=spec,
            state=ScheduleState(paused=paused, note=f"Created schedule for {workflow_id}"),
        ),
    )
    return handle


async def get_temporal_schedule(client: Client, schedule_id: str) -> dict[str, Any]:
    """Retrieve detailed description of an existing Temporal Schedule."""
    handle = client.get_schedule_handle(schedule_id)
    desc = await handle.describe()

    next_runs = [dt.isoformat() for dt in (desc.info.next_action_times or [])]
    recent_runs = [
        {
            "action_time": a.actual_time.isoformat() if a.actual_time else None,
            "scheduled_time": a.scheduled_time.isoformat() if a.scheduled_time else None,
        }
        for a in (desc.info.recent_actions or [])
    ]

    return {
        "id": desc.id,
        "paused": desc.schedule.state.paused,
        "note": desc.schedule.state.note,
        "next_run_times": next_runs,
        "recent_actions": recent_runs,
        "total_actions": desc.info.num_actions,
    }


async def list_temporal_schedules(client: Client) -> list[dict[str, Any]]:
    """List all schedules currently registered in Temporal."""
    schedules = []
    async for entry in await client.list_schedules():
        schedules.append({
            "id": entry.id,
            "paused": entry.schedule.state.paused if entry.schedule else False,
            "note": entry.schedule.state.note if entry.schedule else None,
        })
    return schedules


async def pause_temporal_schedule(client: Client, schedule_id: str, note: str = "Paused by user") -> None:
    """Pause execution of a Temporal Schedule."""
    handle = client.get_schedule_handle(schedule_id)
    await handle.pause(note=note)


async def unpause_temporal_schedule(client: Client, schedule_id: str, note: str = "Unpaused by user") -> None:
    """Unpause execution of a Temporal Schedule."""
    handle = client.get_schedule_handle(schedule_id)
    await handle.unpause(note=note)


async def trigger_temporal_schedule(client: Client, schedule_id: str) -> None:
    """Trigger an immediate execution of a Temporal Schedule."""
    handle = client.get_schedule_handle(schedule_id)
    await handle.trigger()


async def delete_temporal_schedule(client: Client, schedule_id: str) -> None:
    """Delete a Temporal Schedule."""
    handle = client.get_schedule_handle(schedule_id)
    await handle.delete()

