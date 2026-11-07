from __future__ import annotations

import contextvars
import logging
import uuid
from typing import Any, Optional

from geostrata.backend.documents import DocumentService, DocumentRepository, DocumentStorage
from app.llm import get_llm, LLMClient
from .models import GeotechnicalAnalysisReport, HumanReviewRecord
from .graph import build_geotechnical_analysis_graph
from .repository import GeotechnicalAnalysisRepository

logger = logging.getLogger("agent_platform.geotechnical_analysis.service")

_CURRENT_DOC_SERVICE: contextvars.ContextVar[Optional[DocumentService]] = contextvars.ContextVar(
    "current_doc_service", default=None
)
_CURRENT_LLM_CLIENT: contextvars.ContextVar[Optional[LLMClient]] = contextvars.ContextVar(
    "current_llm_client", default=None
)


def get_current_document_service() -> Optional[DocumentService]:
    return _CURRENT_DOC_SERVICE.get()


def get_current_llm_client() -> Optional[LLMClient]:
    return _CURRENT_LLM_CLIENT.get()


class GeotechnicalAnalysisService:
    """Coordinates LangGraph execution, report generation, and human review persistence."""

    def __init__(
        self,
        repository: GeotechnicalAnalysisRepository,
        document_service: DocumentService,
        llm_client: LLMClient | None = None,
    ):
        self.repo = repository
        self.doc_service = document_service
        self.llm_client = llm_client
        self._graph = build_geotechnical_analysis_graph()

    def run_analysis(
        self,
        document_id: str,
        project_id: str = "default",
        run_id: Optional[str] = None,
        llm_profile: str = "document_analysis",
    ) -> GeotechnicalAnalysisReport:
        """Execute the 8-node LangGraph Geotechnical Analysis Agent pipeline."""
        initial_state = {
            "document_id": document_id,
            "project_id": project_id,
            "run_id": run_id or str(uuid.uuid4()),
            "llm_profile": llm_profile,
        }

        from langchain_core.runnables.config import var_child_runnable_config
        token_doc = _CURRENT_DOC_SERVICE.set(self.doc_service)
        token_llm = _CURRENT_LLM_CLIENT.set(self.llm_client)
        token_cfg = var_child_runnable_config.set(None)

        logger.info("Executing Geotechnical Analysis LangGraph for document %s (run_id=%s)", document_id, run_id)
        try:
            final_state = self._graph.invoke(initial_state)
        finally:
            var_child_runnable_config.reset(token_cfg)
            _CURRENT_DOC_SERVICE.reset(token_doc)
            _CURRENT_LLM_CLIENT.reset(token_llm)

        report_dict = final_state.get("report")
        if not report_dict:
            raise RuntimeError("LangGraph execution completed but produced no report output.")

        report = GeotechnicalAnalysisReport.model_validate(report_dict)
        self.repo.save_report(report)
        logger.info("Saved Geotechnical Analysis Report '%s' for document '%s'", report.report_id, document_id)
        return report

    def get_report(self, report_id: str) -> Optional[GeotechnicalAnalysisReport]:
        return self.repo.get_report(report_id)

    def get_latest_report_for_document(self, document_id: str) -> Optional[GeotechnicalAnalysisReport]:
        return self.repo.get_latest_report_for_document(document_id)

    def list_reports(self, project_id: str = "default", document_id: Optional[str] = None) -> list[dict[str, Any]]:
        return self.repo.list_reports(project_id=project_id, document_id=document_id)

    def submit_review(
        self,
        report_id: str,
        decision: str,
        reviewer_id: str,
        comments: Optional[str] = None,
    ) -> GeotechnicalAnalysisReport:
        """Submit a human engineering review (HUMAN_VERIFIED, REJECTED, CHANGES_REQUESTED)."""
        report = self.get_report(report_id)
        if not report:
            raise FileNotFoundError(f"Report '{report_id}' not found.")

        review_rec = HumanReviewRecord(
            review_id=f"rev_{uuid.uuid4().hex[:8]}",
            report_id=report_id,
            decision=decision,
            reviewer_id=reviewer_id,
            comments=comments,
        )

        updated_report = self.repo.add_review(review_rec)
        if not updated_report:
            raise RuntimeError(f"Failed to record review for report '{report_id}'.")
        return updated_report
