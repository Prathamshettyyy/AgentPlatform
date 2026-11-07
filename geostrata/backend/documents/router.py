from __future__ import annotations

import logging
from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from .models import (
    DocumentMetadata,
    DocumentPage,
    ExtractedTable,
    EvidenceRecord,
    FoundationSystemRecommendation,
    BoringLogReference,
    SitePreparationRequirement,
    DocumentReadinessStatus,
    ProjectDocumentValidationResult,
)
from .service import DocumentService
from .vision import (
    PageClassificationResult,
    VisualEvidence,
    CrossModalDisagreement,
    VisualReviewRequest,
    VisualDisagreementResolutionRequest,
    VisionService,
)
from .matching_models import (
    DocumentProjectAssociation,
    DecisionRequest,
    ProjectProfile,
    UserDecision,
)

logger = logging.getLogger("agent_platform.documents.router")

router = APIRouter(prefix="/v1/documents", tags=["documents"])


def get_document_service(request: Request) -> DocumentService:
    service = getattr(request.app.state, "document_service", None)
    if service is None:
        # Fall back to creating one with repo from app state
        repo_conn = request.app.state.repository._connection
        lock = request.app.state.repository._lock
        from .repository import DocumentRepository
        doc_repo = DocumentRepository(repo_conn, lock)
        service = DocumentService(doc_repo)
        request.app.state.document_service = service
    return service


def get_vision_service(request: Request) -> VisionService:
    service = getattr(request.app.state, "vision_service", None)
    if service is None:
        doc_service = get_document_service(request)
        service = VisionService(doc_service.repo, doc_service.storage)
        request.app.state.vision_service = service
    return service


# ==============================================================================
# Ingestion Endpoints
# ==============================================================================

@router.post("/upload", response_model=list[DocumentMetadata])
async def upload_documents(
    files: list[UploadFile] = File(...),
    project_id: str = Form("default"),
    service: DocumentService = Depends(get_document_service),
) -> list[DocumentMetadata]:
    """Upload one or more PDF documents into the document intelligence pipeline."""
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded.")

    results: list[DocumentMetadata] = []
    for upload in files:
        filename = upload.filename or "unknown.pdf"
        try:
            content = await upload.read()
            metadata = service.upload_document(
                filename=filename,
                content=content,
                project_id=project_id,
            )
            results.append(metadata)
        except ValueError as val_err:
            logger.warning("Validation rejected '%s': %s", filename, val_err)
            raise HTTPException(status_code=400, detail=str(val_err))
        except Exception as exc:
            logger.error("Error processing '%s': %s", filename, exc)
            raise HTTPException(status_code=500, detail=f"Failed to process '{filename}': {exc}")

    return results


# ==============================================================================
# Document Retrieval Endpoints
# ==============================================================================

@router.get("", response_model=list[DocumentMetadata])
def list_documents(
    project_id: str = Query("default"),
    service: DocumentService = Depends(get_document_service),
) -> list[DocumentMetadata]:
    """List all documents for a project."""
    return service.list_documents(project_id)


@router.get("/{document_id}", response_model=DocumentMetadata)
def get_document_metadata(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> DocumentMetadata:
    """Retrieve metadata for a specific document."""
    doc = service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    return doc


@router.get("/{document_id}/status")
def get_document_status(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """Retrieve processing status and error information for a document."""
    doc = service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    return {
        "document_id": doc.document_id,
        "status": doc.status,
        "page_count": doc.page_count,
        "is_scanned": doc.is_scanned,
        "document_type": doc.document_type,
        "error_message": doc.error_message,
        "updated_at": doc.updated_at,
    }


# ==============================================================================
# Pages & Rendered Image Endpoints
# ==============================================================================

@router.get("/{document_id}/pages", response_model=list[DocumentPage])
def get_document_pages(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> list[DocumentPage]:
    """Retrieve all extracted pages for a document."""
    doc = service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    return service.get_document_pages(document_id)


@router.get("/{document_id}/pages/classification", response_model=list[PageClassificationResult])
@router.get("/{document_id}/page-classifications", response_model=list[PageClassificationResult])
def get_document_page_classifications(
    document_id: str,
    vision_service: VisionService = Depends(get_vision_service),
) -> list[PageClassificationResult]:
    """Retrieve classification of all pages in a document (drawings, site plans, logs, tables, text)."""
    return vision_service.classify_document_pages(document_id)


@router.get("/{document_id}/pages/{page_index}", response_model=DocumentPage)
def get_document_page(
    document_id: str,
    page_index: int,
    service: DocumentService = Depends(get_document_service),
) -> DocumentPage:
    """Retrieve detailed content for an individual page."""
    page = service.get_document_page(document_id, page_index)
    if not page:
        raise HTTPException(status_code=404, detail=f"Page {page_index} for document '{document_id}' not found.")
    return page


@router.get("/{document_id}/pages/{page_index}/image")
def get_page_image(
    document_id: str,
    page_index: int,
    service: DocumentService = Depends(get_document_service),
) -> FileResponse:
    """Render and stream a crisp PNG image of the requested PDF page."""
    try:
        img_path = service.get_or_render_page_image(document_id, page_index)
        return FileResponse(str(img_path), media_type="image/png")
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except ValueError as val_err:
        raise HTTPException(status_code=400, detail=str(val_err))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to render page image: {exc}")


@router.get("/{document_id}/file")
def get_original_document_file(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> FileResponse:
    """Stream the original uploaded PDF file."""
    try:
        doc = service.get_document(document_id)
        pdf_path = service.resolve_pdf_path(document_id)
        filename = doc.filename if doc and doc.filename else f"{document_id}.pdf"
        return FileResponse(str(pdf_path), media_type="application/pdf", filename=filename)
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stream PDF: {exc}")


# ==============================================================================
# Tables & Evidence Endpoints
# ==============================================================================

@router.get("/{document_id}/tables", response_model=list[ExtractedTable])
def get_document_tables(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> list[ExtractedTable]:
    """Retrieve all structured tables extracted from a document."""
    doc = service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    return service.get_document_tables(document_id)


@router.get("/{document_id}/evidence", response_model=list[EvidenceRecord])
def get_document_evidence(
    document_id: str,
    property_type: Optional[str] = Query(None),
    confidence_category: Optional[str] = Query(None),
    boring_id: Optional[str] = Query(None),
    page_index: Optional[int] = Query(None),
    service: DocumentService = Depends(get_document_service),
) -> list[EvidenceRecord]:
    """Retrieve evidence records with source page indices and bounding boxes."""
    doc = service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    return service.get_document_evidence(
        document_id=document_id,
        property_type=property_type,
        confidence_category=confidence_category,
        boring_id=boring_id,
        page_index=page_index,
    )


@router.get("/{document_id}/foundation-recommendations", response_model=list[FoundationSystemRecommendation])
def get_foundation_recommendations(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> list[FoundationSystemRecommendation]:
    """Retrieve structured engineering recommendations for all foundation systems."""
    doc = service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    return service.get_foundation_recommendations(document_id)


@router.get("/{document_id}/boring-logs", response_model=list[BoringLogReference])
def get_boring_logs(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> list[BoringLogReference]:
    """Retrieve structured borehole log references, soil stratum, and depth observations."""
    doc = service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    return service.get_boring_logs(document_id)


@router.get("/{document_id}/site-preparation", response_model=list[SitePreparationRequirement])
def get_site_preparation(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> list[SitePreparationRequirement]:
    """Retrieve structured site and subgrade preparation specifications."""
    doc = service.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    return service.get_site_preparation(document_id)


@router.patch("/evidence/{evidence_id}")
def update_evidence_status(
    evidence_id: str,
    verification_status: str = Query(..., pattern="^(unverified|verified|flagged|PENDING_REVIEW|HUMAN_VERIFIED|REJECTED)$"),
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """Update human verification status for an extracted evidence record."""
    updated = service.update_evidence_status(evidence_id, verification_status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Evidence record '{evidence_id}' not found.")
    return {"evidence_id": evidence_id, "verification_status": verification_status, "status": "updated"}


# ==============================================================================
# Management Endpoints
# ==============================================================================

@router.post("/{document_id}/reprocess", response_model=dict)
def reprocess_document(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """Trigger re-extraction of an already uploaded document."""
    try:
        result = service.reprocess_document(document_id)
        return {
            "document_id": document_id,
            "status": result.metadata.status,
            "pages_count": len(result.pages),
            "tables_count": len(result.tables),
            "evidence_count": len(result.evidence),
            "duration_ms": result.processing_duration_ms,
        }
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to reprocess: {exc}")


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> dict:
    """Delete document, its records, and stored original files."""
    deleted = service.delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found.")
    return {"document_id": document_id, "deleted": True}


# ==============================================================================
# Multimodal Vision Understanding Endpoints
# ==============================================================================

@router.post("/{document_id}/pages/{page_index}/analyze-visual", response_model=VisualEvidence)
async def analyze_page_visual(
    document_id: str,
    page_index: int,
    model_override: Optional[str] = Query(None, description="Optional VLM model name override"),
    force_reanalyze: bool = Query(False, description="Force re-running vision analysis even if cached"),
    vision_service: VisionService = Depends(get_vision_service),
) -> VisualEvidence:
    """Trigger multimodal vision understanding on a single page or drawing."""
    try:
        return await vision_service.analyze_page_visual(
            document_id=document_id,
            page_index=page_index,
            model_override=model_override,
            force_reanalyze=force_reanalyze,
        )
    except FileNotFoundError as fnf:
        raise HTTPException(status_code=404, detail=str(fnf))
    except Exception as exc:
        logger.exception("Visual understanding analysis failed for doc %s, page %d", document_id, page_index)
        raise HTTPException(status_code=500, detail=f"Vision analysis failed: {exc}")


@router.get("/{document_id}/visual-evidence", response_model=list[VisualEvidence])
def get_document_visual_evidence(
    document_id: str,
    page_index: Optional[int] = Query(None, description="Filter by page index"),
    vision_service: VisionService = Depends(get_vision_service),
) -> list[VisualEvidence]:
    """List all extracted visual evidence records for a document."""
    return vision_service.get_visual_evidence(document_id, page_index=page_index)


@router.patch("/visual-evidence/{visual_evidence_id}/review", response_model=dict)
def review_visual_evidence(
    visual_evidence_id: str,
    body: VisualReviewRequest,
    vision_service: VisionService = Depends(get_vision_service),
) -> dict:
    """Update human verification status and notes for a visual evidence record."""
    updated = vision_service.review_visual_evidence(
        visual_evidence_id=visual_evidence_id,
        review_status=body.review_status,
        human_notes=body.human_notes,
        verified_by=body.verified_by,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Visual evidence record '{visual_evidence_id}' not found.")
    return {"visual_evidence_id": visual_evidence_id, "review_status": body.review_status, "status": "updated"}


@router.get("/{document_id}/visual-disagreements", response_model=list[CrossModalDisagreement])
def get_visual_disagreements(
    document_id: str,
    status: Optional[str] = Query(None, description="Filter by status: OPEN, RESOLVED, IGNORED"),
    vision_service: VisionService = Depends(get_vision_service),
) -> list[CrossModalDisagreement]:
    """List cross-modal disagreements between visual findings and text/table evidence."""
    return vision_service.get_disagreements(document_id, status=status)


@router.patch("/visual-disagreements/{disagreement_id}", response_model=dict)
def update_visual_disagreement(
    disagreement_id: str,
    body: VisualDisagreementResolutionRequest,
    vision_service: VisionService = Depends(get_vision_service),
) -> dict:
    """Update or resolve a cross-modal disagreement."""
    updated = vision_service.resolve_disagreement(
        disagreement_id=disagreement_id,
        status=body.status,
        resolution_notes=body.resolution_notes,
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Disagreement '{disagreement_id}' not found.")
    return {"disagreement_id": disagreement_id, "status": body.status, "updated": True}


# ==============================================================================
# Multi-Document Project Matching Endpoints
# ==============================================================================

@router.post("/projects/{project_id}/match", response_model=list[DocumentProjectAssociation])
def match_project_documents(
    project_id: str,
    project_profile: ProjectProfile,
    doc_service: DocumentService = Depends(get_document_service),
) -> list[DocumentProjectAssociation]:
    """Run project matching algorithm across uploaded documents and store associations."""
    return doc_service.match_documents_for_project(project_profile)


@router.get("/projects/{project_id}/associations", response_model=list[DocumentProjectAssociation])
def get_project_document_associations(
    project_id: str,
    doc_service: DocumentService = Depends(get_document_service),
) -> list[DocumentProjectAssociation]:
    """List all document-project associations for a project."""
    return doc_service.get_associations_for_project(project_id)


@router.patch("/associations/{association_id}/decision", response_model=DocumentProjectAssociation)
def record_association_decision(
    association_id: str,
    body: DecisionRequest,
    doc_service: DocumentService = Depends(get_document_service),
) -> DocumentProjectAssociation:
    """Submit human review decision (CONFIRMED / REJECTED) for a document-project association."""
    assoc = doc_service.update_association_decision(
        association_id=association_id,
        decision=body.decision,
        reviewed_by=body.reviewed_by,
        notes=body.notes,
    )
    if not assoc:
        raise HTTPException(status_code=404, detail=f"Association '{association_id}' not found.")
    return assoc


@router.get("/projects/{project_id}/confirmed-documents", response_model=list[str])
def get_confirmed_project_documents(
    project_id: str,
    doc_service: DocumentService = Depends(get_document_service),
) -> list[str]:
    """Get all confirmed document IDs eligible for multi-document geotechnical analysis."""
    return doc_service.get_confirmed_document_ids(project_id)


@router.get("/{document_id}/readiness", response_model=dict)
def get_document_readiness(
    document_id: str,
    project_id: Optional[str] = Query(None),
    doc_service: DocumentService = Depends(get_document_service),
) -> dict:
    """Retrieve clear readiness status for a document (UPLOADED, PROCESSING, READY_FOR_REVIEW, READY_FOR_ANALYSIS, FAILED)."""
    readiness = doc_service.get_document_readiness_status(document_id, project_id=project_id)
    doc = doc_service.get_document(document_id)
    return {
        "document_id": document_id,
        "readiness_status": readiness.value,
        "filename": doc.filename if doc else None,
        "error_message": doc.error_message if doc else None,
    }


@router.post("/projects/{project_id}/validate-documents", response_model=ProjectDocumentValidationResult)
def validate_project_documents_endpoint(
    project_id: str,
    payload: dict,
    doc_service: DocumentService = Depends(get_document_service),
) -> ProjectDocumentValidationResult:
    """Pre-workflow validation check: verifies all confirmed documents are ready, matched, and unaltered."""
    confirmed_ids = payload.get("confirmed_document_ids", [])
    expected_versions = payload.get("expected_versions")
    return doc_service.validate_project_documents(
        project_id=project_id,
        confirmed_document_ids=confirmed_ids,
        expected_versions=expected_versions,
    )

