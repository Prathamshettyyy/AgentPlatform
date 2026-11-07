from __future__ import annotations

import contextvars
import logging
import uuid
from typing import Any, List, Optional

from geostrata.backend.documents.service import DocumentService
from geostrata.backend.agents.geotechnical_analysis.repository import GeotechnicalAnalysisRepository
from app.llm.client import LLMClient

from .graph import build_foundation_research_graph
from .models import FoundationResearchReport, ReviewStatus
from .repository import FoundationResearchRepository
from .search.base import SearchProvider
from .search.factory import get_search_provider

logger = logging.getLogger("agent_platform.foundation_research.service")

_CURRENT_FR_DOC_SERVICE: contextvars.ContextVar[Optional[DocumentService]] = contextvars.ContextVar(
    "current_fr_doc_service", default=None
)
_CURRENT_FR_GEO_REPO: contextvars.ContextVar[Optional[GeotechnicalAnalysisRepository]] = contextvars.ContextVar(
    "current_fr_geo_repo", default=None
)
_CURRENT_FR_SEARCH_PROVIDER: contextvars.ContextVar[Optional[SearchProvider]] = contextvars.ContextVar(
    "current_fr_search_provider", default=None
)
_CURRENT_FR_LLM_CLIENT: contextvars.ContextVar[Optional[LLMClient]] = contextvars.ContextVar(
    "current_fr_llm_client", default=None
)


def get_current_fr_document_service() -> Optional[DocumentService]:
    return _CURRENT_FR_DOC_SERVICE.get()


def get_current_fr_geo_repo() -> Optional[GeotechnicalAnalysisRepository]:
    return _CURRENT_FR_GEO_REPO.get()


def get_current_fr_search_provider() -> Optional[SearchProvider]:
    return _CURRENT_FR_SEARCH_PROVIDER.get()


def get_current_fr_llm_client() -> Optional[LLMClient]:
    return _CURRENT_FR_LLM_CLIENT.get()


class FoundationResearchService:
    """Coordinates external technical foundation research using LangGraph, multi-document context, and web search."""

    def __init__(
        self,
        repository: FoundationResearchRepository,
        document_service: DocumentService,
        geotechnical_repository: Optional[GeotechnicalAnalysisRepository] = None,
        llm_client: Optional[LLMClient] = None,
        search_provider: Optional[SearchProvider] = None,
    ) -> None:
        self.repo = repository
        self.doc_service = document_service
        self.geo_repo = geotechnical_repository
        self.llm_client = llm_client
        self.search_provider = search_provider
        self._graph = build_foundation_research_graph()

    def run_research(
        self,
        document_id: str,
        project_id: str = "default",
        analysis_report_id: Optional[str] = None,
        foundation_types_to_research: Optional[List[str]] = None,
        run_id: Optional[str] = None,
        llm_profile: str = "document_analysis",
        search_provider_name: Optional[str] = None,
    ) -> FoundationResearchReport:
        """Execute the 10-node LangGraph Foundation Research Agent pipeline."""
        initial_state = {
            "document_id": document_id,
            "project_id": project_id,
            "analysis_report_id": analysis_report_id,
            "run_id": run_id or str(uuid.uuid4()),
            "llm_profile": llm_profile,
            "search_provider_name": search_provider_name or "duckduckgo",
            "foundation_types_to_research": foundation_types_to_research,
        }

        from langchain_core.runnables.config import var_child_runnable_config
        token_doc = _CURRENT_FR_DOC_SERVICE.set(self.doc_service)
        token_geo = _CURRENT_FR_GEO_REPO.set(self.geo_repo)
        token_search = _CURRENT_FR_SEARCH_PROVIDER.set(self.search_provider)
        token_llm = _CURRENT_FR_LLM_CLIENT.set(self.llm_client)
        token_cfg = var_child_runnable_config.set(None)

        logger.info(
            "Executing Foundation Research LangGraph for document '%s', project '%s' (run_id=%s)",
            document_id,
            project_id,
            initial_state["run_id"],
        )
        try:
            final_state = self._graph.invoke(initial_state)
        finally:
            var_child_runnable_config.reset(token_cfg)
            _CURRENT_FR_DOC_SERVICE.reset(token_doc)
            _CURRENT_FR_GEO_REPO.reset(token_geo)
            _CURRENT_FR_SEARCH_PROVIDER.reset(token_search)
            _CURRENT_FR_LLM_CLIENT.reset(token_llm)

        report_dict = final_state.get("report")
        if not report_dict:
            raise RuntimeError("LangGraph execution completed but produced no report output.")

        report = FoundationResearchReport.model_validate(report_dict)
        self.repo.save_report(report)
        logger.info(
            "Saved Foundation Research Report '%s' for project '%s', document '%s'",
            report.report_id,
            report.project_id,
            report.document_id,
        )
        return report

    def get_report(self, report_id: str) -> Optional[FoundationResearchReport]:
        return self.repo.get_report(report_id)

    def get_latest_report_for_project(self, project_id: str) -> Optional[FoundationResearchReport]:
        return self.repo.get_latest_report_for_project(project_id)

    def get_latest_report_for_document(self, document_id: str) -> Optional[FoundationResearchReport]:
        return self.repo.get_latest_report_for_document(document_id)

    def list_reports_for_project(self, project_id: str = "default") -> List[FoundationResearchReport]:
        return self.repo.list_reports_for_project(project_id)

    def submit_review(
        self,
        report_id: str,
        decision: str | ReviewStatus,
        reviewer_id: str,
        comments: Optional[str] = None,
    ) -> FoundationResearchReport:
        """Submit a licensed engineering review for the foundation research report."""
        if isinstance(decision, str):
            try:
                review_status = ReviewStatus(decision)
            except ValueError:
                review_status = ReviewStatus.PENDING_REVIEW
        else:
            review_status = decision

        updated = self.repo.update_review_status(
            report_id=report_id,
            decision=review_status,
            reviewed_by=reviewer_id,
            notes=comments,
        )
        if not updated:
            raise FileNotFoundError(f"Report '{report_id}' not found.")
        return updated
