from __future__ import annotations

import os
from typing import Optional

from .base import SearchProvider
from .duckduckgo import DuckDuckGoSearchProvider
from .curated import CuratedEngineeringSearchProvider
from .mock import MockSearchProvider


def get_search_provider(name: Optional[str] = None) -> SearchProvider:
    """Retrieve configured search provider instance.

    Priority:
    1. Explicit function argument `name`
    2. Environment variable `FOUNDATION_SEARCH_PROVIDER`
    3. Default to `duckduckgo` with automatic fallback capability
    """
    provider_name = (name or os.getenv("FOUNDATION_SEARCH_PROVIDER", "duckduckgo")).lower().strip()

    if provider_name == "mock":
        return MockSearchProvider()
    if provider_name == "curated":
        return CuratedEngineeringSearchProvider()

    # Default live search provider
    return DuckDuckGoSearchProvider()
