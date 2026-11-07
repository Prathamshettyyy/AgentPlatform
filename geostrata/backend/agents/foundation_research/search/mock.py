from __future__ import annotations

from typing import List, Optional

from .base import SearchProvider, SearchResult


class MockSearchProvider(SearchProvider):
    """Deterministic mock search provider for unit tests without network calls."""

    def __init__(self, canned_results: Optional[List[SearchResult]] = None) -> None:
        self.queries_received: List[str] = []
        self.canned_results = canned_results or [
            SearchResult(
                title="FHWA GEC 10: Drilled Shafts Construction and Design",
                url="https://www.fhwa.dot.gov/engineering/geotech/nhi18024.pdf",
                snippet="FHWA technical manual on drilled shafts in stiff clays. Recommends casing when calcareous nodules induce bell caving.",
                publisher="Federal Highway Administration (FHWA)",
                publication_date="September 2018",
                authority_category="GOVERNMENT_AGENCY",
            ),
            SearchResult(
                title="PTI DC10.5: Post-Tensioned Slabs on Expansive Clays",
                url="https://www.post-tensioning.org/technical/standards",
                snippet="Post-Tensioning Institute specification for slabs on expansive soils with PVR > 1.0 inch.",
                publisher="Post-Tensioning Institute (PTI)",
                publication_date="2020",
                authority_category="STANDARDS_ORGANIZATION",
            ),
        ]

    async def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        self.queries_received.append(query)
        return self.canned_results[:max_results]

    async def fetch_page_content(self, url: str) -> Optional[str]:
        for r in self.canned_results:
            if r.url == url:
                return r.snippet
        return "Mock content for " + url
