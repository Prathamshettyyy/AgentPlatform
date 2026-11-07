from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SearchResult:
    """Standardized result returned by a search provider."""
    title: str
    url: str
    snippet: str
    publisher: str = "Unknown"
    publication_date: Optional[str] = None
    authority_category: str = "INDUSTRY_TECHNICAL"


class SearchProvider(ABC):
    """Abstract interface for external technical research search providers."""

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Execute a technical query and return structured search results."""
        ...

    @abstractmethod
    async def fetch_page_content(self, url: str) -> Optional[str]:
        """Fetch raw page or extract snippet content from a URL."""
        ...
