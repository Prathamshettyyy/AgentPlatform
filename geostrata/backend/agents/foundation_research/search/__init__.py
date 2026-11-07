from .base import SearchProvider, SearchResult
from .duckduckgo import DuckDuckGoSearchProvider
from .curated import CuratedEngineeringSearchProvider, CURATED_ENGINEERING_SOURCES
from .mock import MockSearchProvider
from .factory import get_search_provider

__all__ = [
    "SearchProvider",
    "SearchResult",
    "DuckDuckGoSearchProvider",
    "CuratedEngineeringSearchProvider",
    "CURATED_ENGINEERING_SOURCES",
    "MockSearchProvider",
    "get_search_provider",
]
