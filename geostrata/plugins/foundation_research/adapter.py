from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, List, Optional

from geostrata.backend.documents import DocumentRepository, DocumentService, DocumentStorage
from geostrata.backend.agents.foundation_research import (
    FoundationResearchRepository,
    FoundationResearchService,
    get_search_provider,
)
from geostrata.backend.agents.geotechnical_analysis import GeotechnicalAnalysisRepository
from app.sdk.context import AgentContext
from app.sdk.contracts import AgentRequest, AgentResult

logger = logging.getLogger("geostrata.plugins.foundation_research")


def _validate_confirmed_documents(
    doc_service: DocumentService,
    project_id: str,
    confirmed_ids: Optional[List[str]] = None,
    document_id: Optional[str] = None,
) -> List[str]:
    """Validate that documents entering foundation research are confirmed and not mismatched."""
    assocs = doc_service.get_associations_for_project(project_id)
    assoc_by_doc = {a.document_id: a for a in assocs}

    check_ids = list(confirmed_ids or [])
    if document_id and document_id not in check_ids:
        check_ids.append(document_id)

    # Fallback to document-level association lookup if project_id did not match directly
    for cid in check_ids:
        if cid not in assoc_by_doc:
            try:
                with doc_service.repo._lock:
                    cur = doc_service.repo._conn.cursor()
                    cur.execute(
                        "SELECT * FROM document_project_associations WHERE document_id = ? ORDER BY created_at DESC",
                        (cid,),
                    )
                    rows = cur.fetchall()
                    if rows:
                        assoc_by_doc[cid] = doc_service.repo._row_to_association(rows[0], cur.description)
            except Exception:
                pass

    for cid in check_ids:
        assoc = assoc_by_doc.get(cid)
        if assoc:
            match_status = getattr(assoc, "match_status", None)
            match_status_val = match_status.value if hasattr(match_status, "value") else str(match_status)
            user_decision = getattr(assoc, "user_decision", None)
            user_decision_val = user_decision.value if hasattr(user_decision, "value") else str(user_decision)

            if match_status_val == "MISMATCH" or user_decision_val == "REJECTED":
                raise ValueError(
                    f"Document '{cid}' is marked as MISMATCH / REJECTED and cannot enter the foundation research workflow."
                )

    return check_ids


def run(request: AgentRequest, context: AgentContext | None = None) -> dict[str, Any]:
    """Agent Platform adapter entrypoint for Foundation Research Agent."""
    inputs = request.inputs or {}
    document_id = inputs.get("document_id")
    project_id = inputs.get("project_id", "default")
    analysis_report_id = inputs.get("geotechnical_report_id") or inputs.get("analysis_report_id")
    confirmed_document_ids = inputs.get("confirmed_document_ids")
    foundation_types = inputs.get("foundation_types_to_research")
    search_provider_name = inputs.get("search_provider") or inputs.get("search_provider_name")
    llm_profile = inputs.get("llm_profile", "document_analysis")
    db_path = inputs.get("db_path") or os.getenv("GEOSTRATA_DB_PATH", "geostrata.db")

    # Connect to SQLite database
    conn = sqlite3.connect(db_path, check_same_thread=False)
    doc_repo = DocumentRepository(conn)
    doc_storage = DocumentStorage()
    doc_service = DocumentService(repository=doc_repo, storage=doc_storage)

    geo_repo = GeotechnicalAnalysisRepository(conn)
    fr_repo = FoundationResearchRepository(conn)

    # If exact upstream geotechnical report is provided, consume and validate it
    upstream_report = None
    if analysis_report_id:
        upstream_report = geo_repo.get_report(analysis_report_id)
        if not upstream_report:
            raise ValueError(f"Upstream geotechnical report '{analysis_report_id}' not found.")
        if not document_id:
            document_id = upstream_report.document_id

    # Fallback to project document if document_id still missing
    if not document_id:
        docs = doc_service.list_documents(project_id)
        if docs:
            document_id = docs[0].document_id
        else:
            raise ValueError("No document_id provided and no documents exist in project.")

    # Validate that unconfirmed or mismatched documents do not enter the workflow
    validated_confirmed_ids = _validate_confirmed_documents(
        doc_service=doc_service,
        project_id=project_id,
        confirmed_ids=confirmed_document_ids,
        document_id=document_id,
    )

    search_provider = get_search_provider(search_provider_name)

    research_service = FoundationResearchService(
        repository=fr_repo,
        document_service=doc_service,
        geotechnical_repository=geo_repo,
        search_provider=search_provider,
    )

    existing_fr_id = inputs.get("existing_foundation_research_report_id")
    reuse_existing = bool(inputs.get("reuse_existing", False))
    report = None
    if existing_fr_id:
        candidate = fr_repo.get_report(existing_fr_id)
        if (
            candidate
            and str(candidate.review_status.value if hasattr(candidate.review_status, "value") else candidate.review_status).upper() != "REJECTED"
            and candidate.document_id == document_id
        ):
            logger.info("Reusing existing Foundation Research Report '%s'", candidate.report_id)
            report = candidate
    elif reuse_existing and analysis_report_id:
        for candidate in fr_repo.list_reports_for_project(project_id):
            c_status = str(candidate.review_status.value if hasattr(candidate.review_status, "value") else candidate.review_status).upper()
            if c_status != "REJECTED" and candidate.analysis_report_id == analysis_report_id and candidate.document_id == document_id:
                logger.info("Reusing valid Foundation Research Report '%s' matching geo_report '%s'", candidate.report_id, analysis_report_id)
                report = candidate
                break

    if report is None:
        logger.info(
            "Executing Foundation Research Agent (run_id=%s) consuming report '%s' for project '%s', document '%s'",
            request.run_id,
            analysis_report_id or "(latest)",
            project_id,
            document_id,
        )
        report = research_service.run_research(
            document_id=document_id,
            project_id=project_id,
            analysis_report_id=analysis_report_id,
            foundation_types_to_research=foundation_types,
            run_id=request.run_id,
            llm_profile=llm_profile,
            search_provider_name=search_provider_name,
        )

    output = report.model_dump()
    output["report_id"] = report.report_id
    output["geotechnical_report_id"] = analysis_report_id
    output["status"] = "succeeded"
    output["execution_status"] = "succeeded"
    output["project_id"] = project_id
    output["document_id"] = document_id
    output["confirmed_document_ids"] = validated_confirmed_ids

    logger.info("Foundation Research completed successfully: report_id=%s", report.report_id)
    return output
