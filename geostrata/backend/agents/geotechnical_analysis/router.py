from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .models import GeotechnicalAnalysisReport, HumanReviewRecord
from .service import GeotechnicalAnalysisService

logger = logging.getLogger("agent_platform.geotechnical_analysis.router")

router = APIRouter(prefix="/v1/geotechnical-analysis", tags=["geotechnical-analysis"])


class RunAnalysisRequest(BaseModel):
    document_id: str
    project_id: str = "default"
    llm_profile: str = "document_analysis"


class ReviewSubmissionRequest(BaseModel):
    decision: str = Field(pattern="^(PENDING_REVIEW|HUMAN_VERIFIED|REJECTED|CHANGES_REQUESTED)$")
    reviewer_id: str = "licensed_engineer"
    comments: Optional[str] = None


def get_analysis_service(request: Request) -> GeotechnicalAnalysisService:
    service = getattr(request.app.state, "geotechnical_analysis_service", None)
    if service is None:
        from .repository import GeotechnicalAnalysisRepository
        repo_conn = request.app.state.repository._connection
        lock = request.app.state.repository._lock
        geo_repo = GeotechnicalAnalysisRepository(repo_conn, lock)
        doc_service = getattr(request.app.state, "document_service", None)
        if doc_service is None:
            from geostrata.backend.documents import DocumentRepository, DocumentService, DocumentStorage
            doc_repo = DocumentRepository(repo_conn, lock)
            doc_service = DocumentService(doc_repo, DocumentStorage())
            request.app.state.document_service = doc_service
        service = GeotechnicalAnalysisService(
            repository=geo_repo,
            document_service=doc_service,
        )
        request.app.state.geotechnical_analysis_service = service
    return service


@router.post("/runs", response_model=GeotechnicalAnalysisReport)
def run_analysis(
    req: RunAnalysisRequest,
    service: GeotechnicalAnalysisService = Depends(get_analysis_service),
) -> GeotechnicalAnalysisReport:
    """Execute the Geotechnical Analysis Agent pipeline for a document."""
    try:
        return service.run_analysis(
            document_id=req.document_id,
            project_id=req.project_id,
            llm_profile=req.llm_profile,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))
    except Exception as exc:
        logger.error("Analysis execution failed for document %s: %s", req.document_id, exc)
        raise HTTPException(status_code=500, detail=f"Geotechnical analysis failed: {exc}")


@router.get("/reports/{report_id}", response_model=GeotechnicalAnalysisReport)
def get_report(
    report_id: str,
    service: GeotechnicalAnalysisService = Depends(get_analysis_service),
) -> GeotechnicalAnalysisReport:
    """Retrieve full structured report by ID."""
    rep = service.get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found.")
    return rep


@router.get("/documents/{document_id}/latest", response_model=Optional[GeotechnicalAnalysisReport])
def get_latest_report_for_document(
    document_id: str,
    service: GeotechnicalAnalysisService = Depends(get_analysis_service),
) -> Optional[GeotechnicalAnalysisReport]:
    """Retrieve the latest geotechnical report for a specific document, or 404 if none."""
    rep = service.get_latest_report_for_document(document_id)
    if not rep:
        raise HTTPException(status_code=404, detail=f"No analysis report found for document '{document_id}'.")
    return rep


@router.get("/reports", response_model=list[dict])
def list_reports(
    project_id: str = Query("default"),
    document_id: Optional[str] = Query(None),
    service: GeotechnicalAnalysisService = Depends(get_analysis_service),
) -> list[dict]:
    """List geotechnical reports."""
    return service.list_reports(project_id=project_id, document_id=document_id)


@router.post("/reports/{report_id}/review", response_model=GeotechnicalAnalysisReport)
def submit_review(
    report_id: str,
    req: ReviewSubmissionRequest,
    service: GeotechnicalAnalysisService = Depends(get_analysis_service),
) -> GeotechnicalAnalysisReport:
    """Submit a professional human review decision (HUMAN_VERIFIED, REJECTED, CHANGES_REQUESTED)."""
    try:
        return service.submit_review(
            report_id=report_id,
            decision=req.decision,
            reviewer_id=req.reviewer_id,
            comments=req.comments,
        )
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Review submission failed: {exc}")

