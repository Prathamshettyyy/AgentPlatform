from __future__ import annotations

import logging
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .models import RequirementDocument
from .service import RequirementAgentService

logger = logging.getLogger("agent_platform.requirement_agent.router")

router = APIRouter(prefix="/v1/requirements", tags=["requirements"])


class RunRequirementAgentRequest(BaseModel):
    project_id: str
    geotechnical_report_id: str
    foundation_research_report_id: str
    confirmed_document_ids: List[str] = Field(default_factory=list)
    document_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    document_versions: Dict[str, str] = Field(default_factory=dict)
    llm_profile: str = "document_analysis"


class ReviewRequirementDocumentRequest(BaseModel):
    decision: str = Field(pattern="^(PENDING_REVIEW|APPROVED|HUMAN_VERIFIED|REJECTED|CHANGES_REQUESTED)$")
    reviewer_id: str = "licensed_engineer"
    comments: Optional[str] = None


def get_requirement_agent_service(request: Request) -> RequirementAgentService:
    service = getattr(request.app.state, "requirement_agent_service", None)
    if service is None:
        from geostrata.backend.documents import DocumentRepository, DocumentService, DocumentStorage
        from geostrata.backend.agents.foundation_research.repository import FoundationResearchRepository
        from geostrata.backend.agents.geotechnical_analysis.repository import GeotechnicalAnalysisRepository
        from .repository import RequirementAgentRepository

        repo_conn = request.app.state.repository._connection
        lock = request.app.state.repository._lock
        req_repo = RequirementAgentRepository(repo_conn, lock)
        geo_repo = GeotechnicalAnalysisRepository(repo_conn, lock)
        fr_repo = FoundationResearchRepository(repo_conn, lock)

        doc_service = getattr(request.app.state, "document_service", None)
        if doc_service is None:
            doc_repo = DocumentRepository(repo_conn, lock)
            doc_service = DocumentService(doc_repo, DocumentStorage())
            request.app.state.document_service = doc_service

        service = RequirementAgentService(
            repository=req_repo,
            geotechnical_repository=geo_repo,
            foundation_research_repository=fr_repo,
            document_service=doc_service,
        )
        request.app.state.requirement_agent_service = service
    return service


@router.post("/run", response_model=RequirementDocument)
@router.post("/runs", response_model=RequirementDocument)
def run_requirement_agent(
    req: RunRequirementAgentRequest,
    service: RequirementAgentService = Depends(get_requirement_agent_service),
) -> RequirementDocument:
    """Execute Agent 3 (Vendor Requirement Agent) consuming exact upstream Geotechnical & Foundation Research reports."""
    try:
        return service.run_requirement_generation(
            project_id=req.project_id,
            geotechnical_report_id=req.geotechnical_report_id,
            foundation_research_report_id=req.foundation_research_report_id,
            confirmed_document_ids=req.confirmed_document_ids,
            document_id=req.document_id,
            snapshot_id=req.snapshot_id,
            document_versions=req.document_versions,
            llm_profile=req.llm_profile,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        logger.error("Requirement Agent execution failed for project %s: %s", req.project_id, exc)
        raise HTTPException(status_code=500, detail=f"Requirement generation failed: {exc}")


@router.get("/reports/{report_id}", response_model=RequirementDocument)
@router.get("/{report_id}", response_model=RequirementDocument)
def get_report(
    report_id: str,
    service: RequirementAgentService = Depends(get_requirement_agent_service),
) -> RequirementDocument:
    """Retrieve a full structured Vendor Foundation Requirement Document by ID."""
    rep = service.get_report(report_id)
    if not rep:
        raise HTTPException(status_code=404, detail=f"Requirement document '{report_id}' not found.")
    return rep


@router.get("/projects/{project_id}/latest", response_model=Optional[RequirementDocument])
@router.get("/project/{project_id}/latest", response_model=Optional[RequirementDocument])
def get_latest_report_for_project(
    project_id: str,
    service: RequirementAgentService = Depends(get_requirement_agent_service),
) -> Optional[RequirementDocument]:
    """Retrieve the latest Vendor Foundation Requirement Document for a project."""
    rep = service.get_latest_report_for_project(project_id)
    if not rep:
        raise HTTPException(status_code=404, detail=f"No requirement document found for project '{project_id}'.")
    return rep


@router.get("/projects/{project_id}/history", response_model=List[RequirementDocument])
@router.get("/projects/{project_id}/reports", response_model=List[RequirementDocument])
@router.get("/project/{project_id}/history", response_model=List[RequirementDocument])
def list_reports_for_project(
    project_id: str,
    service: RequirementAgentService = Depends(get_requirement_agent_service),
) -> List[RequirementDocument]:
    """List historical Vendor Foundation Requirement Documents for a project."""
    return service.list_reports_for_project(project_id=project_id)


@router.post("/reports/{report_id}/review", response_model=RequirementDocument)
@router.patch("/{report_id}/review", response_model=RequirementDocument)
def submit_review(
    report_id: str,
    req: ReviewRequirementDocumentRequest,
    service: RequirementAgentService = Depends(get_requirement_agent_service),
) -> RequirementDocument:
    """Submit a licensed engineering review decision (PENDING_REVIEW, APPROVED, HUMAN_VERIFIED, REJECTED, CHANGES_REQUESTED)."""
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

