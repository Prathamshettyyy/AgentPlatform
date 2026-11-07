from __future__ import annotations

import logging
from typing import Optional
from temporalio.client import Client

from .config import TemporalConfig

logger = logging.getLogger(__name__)

_global_client: Optional[Client] = None


async def get_temporal_client(
    config: Optional[TemporalConfig] = None,
    *,
    force_new: bool = False,
) -> Client:
    """Connect to or return the cached Temporal client."""
    global _global_client
    if _global_client is not None and not force_new:
        return _global_client

    cfg = config or TemporalConfig.from_env()
    logger.info("Connecting to Temporal at %s (namespace: %s)...", cfg.target_host, cfg.namespace)
    client = await Client.connect(
        cfg.target_host,
        namespace=cfg.namespace,
    )
    _global_client = client
    return client


def set_temporal_client(client: Optional[Client]) -> None:
    """Inject or reset the global Temporal client (useful for tests or mocking)."""
    global _global_client
    _global_client = client


async def is_temporal_available(config: Optional[TemporalConfig] = None) -> bool:
    """Check whether the Temporal server is reachable."""
    try:
        client = await get_temporal_client(config=config)
        # Attempt to describe the namespace or check service reachability
        await client.service_client.check_health()
        return True
    except Exception as exc:
        logger.debug("Temporal health check failed: %s", exc)
        return False

