from __future__ import annotations

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .models import FoundationResearchReport, ReviewStatus
from .service import FoundationResearchService

logger = logging.getLogger("agent_platform.foundation_research.router")

router = APIRouter(prefix="/v1/foundation-research", tags=["foundation-research"])


class RunFoundationResearchRequest(BaseModel):
    document_id: str
    project_id: str = "default"
    analysis_report_id: Optional[str] = None
    foundation_types_to_research: Optional[List[str]] = None
    llm_profile: str = "document_analysis"
    search_provider_name: Optional[str] = None


class ReviewFoundationResearchRequest(BaseModel):
    decision: str = Field(pattern="^(PENDING_REVIEW|APPROVED|REJECTED)$")
    reviewer_id: str = "licensed_engineer"
    comments: Optional[str] = None


def get_foundation_research_service(request: Request) -> FoundationResearchService:
    service = getattr(request.app.state, "foundation_research_service", None)
    if service is None:
        from .repository import FoundationResearchRepository
        from geostrata.backend.agents.geotechnical_analysis.repository import GeotechnicalAnalysisRepository
        from geostrata.backend.documents import DocumentRepository, DocumentService, DocumentStorage

        repo_conn = request.app.state.repository._connection
        lock = request.app.state.repository._lock
        fr_repo = FoundationResearchRepository(repo_conn, lock)
        geo_repo = GeotechnicalAnalysisRepository(repo_conn, lock)

        doc_service = getattr(request.app.state, "document_service", None)
        if doc_service is None:
            doc_repo = DocumentRepository(repo_conn, lock)
            doc_service = DocumentService(doc_repo, DocumentStorage())
            request.app.state.document_service = doc_service

        service = FoundationResearchService(
            repository=fr_repo,
            document_service=doc_service,
            geotechnical_repository=geo_repo,
        )
        request.app.state.foundation_research_service = service
    return service


@router.post("/runs", response_model=FoundationResearchReport)
@router.post("/run", response_model=FoundationResearchReport)
def run_research(
    req: RunFoundationResearchRequest,
    service: FoundationResearchService = Depends(get_foundation_research_service),
) -> FoundationResearchReport:
    """Execute the Foundation Research Agent pipeline for a geotechnical report / project."""
    try:
        return service.run_research(
            document_id=req.document_id,
            project_id=req.project_id,
            analysis_report_id=req.analysis_report_id,
            foundation_types_to_research=req.foundation_types_to_research,
            llm_profile=req.llm_profile,
            search_provider_name=req.search_provider_name,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=404, detail=str(val_err))
    except Exception as exc:
        logger.error("Foundation research execution failed for document %s: %s", req.document_id, exc)
        raise HTTPException(status_code=500, detail=f"Foundation research failed: {exc}")


@router.get("/reports/{report_id}", response_model=FoundationResearchReport)
@router.get("/{report_id}", response_model=FoundationResearchReport)
def get_report(
    report_id: str,
    service: FoundationResearchService = Depends(get_foundation_research_service),
) -> FoundationResearchReport:
    """Retrieve full structured foundation research report by ID."""
    rep = service.get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail=f"Foundation research report '{report_id}' not found.")
    return rep


@router.get("/projects/{project_id}/latest", response_model=Optional[FoundationResearchReport])
@router.get("/project/{project_id}/latest", response_model=Optional[FoundationResearchReport])
def get_latest_report_for_project(
    project_id: str,
    service: FoundationResearchService = Depends(get_foundation_research_service),
) -> Optional[FoundationResearchReport]:
    """Retrieve the latest foundation research report for a project."""
    rep = service.get_latest_report_for_project(project_id)
    if not rep:
        raise HTTPException(status_code=404, detail=f"No foundation research report found for project '{project_id}'.")
    return rep


@router.get("/documents/{document_id}/latest", response_model=Optional[FoundationResearchReport])
def get_latest_report_for_document(
    document_id: str,
    service: FoundationResearchService = Depends(get_foundation_research_service),
) -> Optional[FoundationResearchReport]:
    """Retrieve the latest foundation research report for a document."""
    rep = service.get_latest_report_for_document(document_id)
    if not rep:
        raise HTTPException(status_code=404, detail=f"No foundation research report found for document '{document_id}'.")
    return rep


@router.get("/projects/{project_id}/reports", response_model=List[FoundationResearchReport])
@router.get("/project/{project_id}/history", response_model=List[FoundationResearchReport])
def list_reports_for_project(
    project_id: str,
    service: FoundationResearchService = Depends(get_foundation_research_service),
) -> List[FoundationResearchReport]:
    """List historical foundation research reports for a project."""
    return service.list_reports_for_project(project_id=project_id)


@router.post("/reports/{report_id}/review", response_model=FoundationResearchReport)
@router.patch("/{report_id}/review", response_model=FoundationResearchReport)
def submit_review(
    report_id: str,
    req: ReviewFoundationResearchRequest,
    service: FoundationResearchService = Depends(get_foundation_research_service),
) -> FoundationResearchReport:
    """Submit a licensed engineering review decision (PENDING_REVIEW, APPROVED, REJECTED)."""
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
