from typing import Any

from .config import TemporalConfig
from .client import get_temporal_client, set_temporal_client, is_temporal_available
from .workflows import DynamicLangGraphWorkflow, BatchLangGraphWorkflow
from .schedules import (
    create_temporal_schedule,
    get_temporal_schedule,
    list_temporal_schedules,
    pause_temporal_schedule,
    unpause_temporal_schedule,
    trigger_temporal_schedule,
    delete_temporal_schedule,
)


def __getattr__(name: str) -> Any:
    if name in ("create_temporal_worker", "run_worker", "build_registered_graphs"):
        import importlib
        mod = importlib.import_module(".worker", __name__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "TemporalConfig",
    "get_temporal_client",
    "set_temporal_client",
    "is_temporal_available",
    "DynamicLangGraphWorkflow",
    "BatchLangGraphWorkflow",
    "create_temporal_worker",
    "run_worker",
    "build_registered_graphs",
    "create_temporal_schedule",
    "get_temporal_schedule",
    "list_temporal_schedules",
    "pause_temporal_schedule",
    "unpause_temporal_schedule",
    "trigger_temporal_schedule",
    "delete_temporal_schedule",
]

