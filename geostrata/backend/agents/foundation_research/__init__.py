from __future__ import annotations

from .graph import build_foundation_research_graph
from .models import (
    AuthorityCategory,
    EngineerQuestion,
    FoundationComparison,
    FoundationOption,
    FoundationResearchReport,
    FoundationResearchRequest,
    RelevanceClassification,
    ResearchFinding,
    ResearchGap,
    ResearchQuery,
    ResearchSource,
    ReviewStatus,
)
from .repository import FoundationResearchRepository
from .router import router as foundation_research_router
from .search import (
    CuratedEngineeringSearchProvider,
    DuckDuckGoSearchProvider,
    MockSearchProvider,
    SearchProvider,
    SearchResult,
    get_search_provider,
)
from .service import FoundationResearchService

__all__ = [
    "AuthorityCategory",
    "CuratedEngineeringSearchProvider",
    "DuckDuckGoSearchProvider",
    "EngineerQuestion",
    "FoundationComparison",
    "FoundationOption",
    "FoundationResearchReport",
    "FoundationResearchRepository",
    "FoundationResearchRequest",
    "FoundationResearchService",
    "MockSearchProvider",
    "RelevanceClassification",
    "ResearchFinding",
    "ResearchGap",
    "ResearchQuery",
    "ResearchSource",
    "ReviewStatus",
    "SearchProvider",
    "SearchResult",
    "build_foundation_research_graph",
    "foundation_research_router",
    "get_search_provider",
]
