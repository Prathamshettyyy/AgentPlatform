from __future__ import annotations

import contextvars
import logging
import uuid
from typing import Dict, List, Optional

from geostrata.backend.documents.service import DocumentService
from geostrata.backend.agents.foundation_research.repository import FoundationResearchRepository
from geostrata.backend.agents.geotechnical_analysis.repository import GeotechnicalAnalysisRepository
from app.llm.client import LLMClient

from .graph import build_requirement_agent_graph
from .models import RequirementDocument, RequirementReviewStatus
from .repository import RequirementAgentRepository

logger = logging.getLogger("agent_platform.requirement_agent.service")

_CURRENT_REQ_DOC_SERVICE: contextvars.ContextVar[Optional[DocumentService]] = contextvars.ContextVar(
    "current_req_doc_service", default=None
)
_CURRENT_REQ_GEO_REPO: contextvars.ContextVar[Optional[GeotechnicalAnalysisRepository]] = contextvars.ContextVar(
    "current_req_geo_repo", default=None
)
_CURRENT_REQ_FR_REPO: contextvars.ContextVar[Optional[FoundationResearchRepository]] = contextvars.ContextVar(
    "current_req_fr_repo", default=None
)
_CURRENT_REQ_LLM_CLIENT: contextvars.ContextVar[Optional[LLMClient]] = contextvars.ContextVar(
    "current_req_llm_client", default=None
)


def get_current_req_doc_service() -> Optional[DocumentService]:
    return _CURRENT_REQ_DOC_SERVICE.get()


def get_current_req_geo_repo() -> Optional[GeotechnicalAnalysisRepository]:
    return _CURRENT_REQ_GEO_REPO.get()


def get_current_req_fr_repo() -> Optional[FoundationResearchRepository]:
    return _CURRENT_REQ_FR_REPO.get()


def get_current_req_llm_client() -> Optional[LLMClient]:
    return _CURRENT_REQ_LLM_CLIENT.get()


class RequirementAgentService:
    """Coordinates Agent 3: Vendor Requirement Agent using LangGraph and exact upstream reports."""

    def __init__(
        self,
        repository: RequirementAgentRepository,
        geotechnical_repository: GeotechnicalAnalysisRepository,
        foundation_research_repository: FoundationResearchRepository,
        document_service: Optional[DocumentService] = None,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        self.repo = repository
        self.geo_repo = geotechnical_repository
        self.fr_repo = foundation_research_repository
        self.doc_service = document_service
        self.llm_client = llm_client
        self._graph = build_requirement_agent_graph()

    def run_requirement_generation(
        self,
        project_id: str,
        geotechnical_report_id: str,
        foundation_research_report_id: str,
        confirmed_document_ids: Optional[List[str]] = None,
        document_id: Optional[str] = None,
        snapshot_id: Optional[str] = None,
        document_versions: Optional[Dict[str, str]] = None,
        run_id: Optional[str] = None,
        llm_profile: str = "document_analysis",
    ) -> RequirementDocument:
        """Execute the 10-node LangGraph Requirement Agent pipeline."""
        initial_state = {
            "run_id": run_id or str(uuid.uuid4()),
            "project_id": project_id,
            "document_id": document_id,
            "geotechnical_report_id": geotechnical_report_id,
            "foundation_research_report_id": foundation_research_report_id,
            "confirmed_document_ids": confirmed_document_ids or [],
            "snapshot_id": snapshot_id,
            "document_versions": document_versions or {},
            "llm_profile": llm_profile,
        }

        from langchain_core.runnables.config import var_child_runnable_config

        token_doc = _CURRENT_REQ_DOC_SERVICE.set(self.doc_service)
        token_geo = _CURRENT_REQ_GEO_REPO.set(self.geo_repo)
        token_fr = _CURRENT_REQ_FR_REPO.set(self.fr_repo)
        token_llm = _CURRENT_REQ_LLM_CLIENT.set(self.llm_client)
        token_cfg = var_child_runnable_config.set(None)

        logger.info(
            "Executing Requirement Agent LangGraph for project '%s' (geo_report='%s', fr_report='%s', run_id=%s)",
            project_id,
            geotechnical_report_id,
            foundation_research_report_id,
            initial_state["run_id"],
        )
        try:
            final_state = self._graph.invoke(initial_state)
        finally:
            var_child_runnable_config.reset(token_cfg)
            _CURRENT_REQ_DOC_SERVICE.reset(token_doc)
            _CURRENT_REQ_GEO_REPO.reset(token_geo)
            _CURRENT_REQ_FR_REPO.reset(token_fr)
            _CURRENT_REQ_LLM_CLIENT.reset(token_llm)

        report_dict = final_state.get("report")
        if not report_dict:
            raise RuntimeError("Requirement Agent LangGraph completed without producing a report.")

        report = RequirementDocument.model_validate(report_dict)
        self.repo.save_report(report)
        logger.info(
            "Saved RequirementDocument '%s' for project '%s' (geo='%s', fr='%s')",
            report.report_id,
            report.project_id,
            report.geotechnical_report_id,
            report.foundation_research_report_id,
        )
        return report

    def get_report(self, report_id: str) -> Optional[RequirementDocument]:
        return self.repo.get_report(report_id)

    def get_latest_report_for_project(self, project_id: str) -> Optional[RequirementDocument]:
        return self.repo.get_latest_report_for_project(project_id)

    def get_latest_report_for_document(self, document_id: str) -> Optional[RequirementDocument]:
        return self.repo.get_latest_report_for_document(document_id)

    def list_reports_for_project(self, project_id: str = "default") -> List[RequirementDocument]:
        return self.repo.list_reports_for_project(project_id)

    def submit_review(
        self,
        report_id: str,
        decision: str | RequirementReviewStatus,
        reviewer_id: str = "licensed_engineer",
        comments: Optional[str] = None,
    ) -> RequirementDocument:
        """Submit a licensed engineering review for the Vendor Requirement Document."""
        if isinstance(decision, str):
            try:
                review_status = RequirementReviewStatus(decision)
            except ValueError:
                review_status = RequirementReviewStatus.PENDING_REVIEW
        else:
            review_status = decision

        updated = self.repo.update_review_status(
            report_id=report_id,
            decision=review_status,
            reviewed_by=reviewer_id,
            notes=comments,
        )
        if not updated:
            raise FileNotFoundError(f"RequirementDocument '{report_id}' not found.")
        return updated

