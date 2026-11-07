from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TemporalConfig:
    target_host: str = "localhost:7233"
    namespace: str = "default"
    task_queue: str = "agent-platform-queue"
    execution_backend: Literal["direct", "temporal"] = "temporal"
    worker_concurrency: int = 10
    activity_timeout_seconds: int = 120
    activity_max_retries: int = 3
    worker_shutdown_timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> TemporalConfig:
        backend = os.getenv("AGENT_PLATFORM_EXECUTION_BACKEND", "temporal").lower()
        if backend not in ("direct", "temporal"):
            backend = "temporal"

        return cls(
            target_host=os.getenv("TEMPORAL_TARGET_HOST", "localhost:7233"),
            namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
            task_queue=os.getenv("TEMPORAL_TASK_QUEUE", "agent-platform-queue"),
            execution_backend=backend,  # type: ignore[arg-type]
            worker_concurrency=int(os.getenv("TEMPORAL_WORKER_CONCURRENCY", "10")),
            activity_timeout_seconds=int(os.getenv("TEMPORAL_ACTIVITY_TIMEOUT_SECONDS", "120")),
            activity_max_retries=int(os.getenv("TEMPORAL_ACTIVITY_MAX_RETRIES", "3")),
            worker_shutdown_timeout_seconds=float(os.getenv("TEMPORAL_WORKER_SHUTDOWN_TIMEOUT_SECONDS", "30.0")),
        )

