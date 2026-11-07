from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, List, Optional

from geostrata.backend.documents import DocumentRepository, DocumentService, DocumentStorage
from geostrata.backend.agents.geotechnical_analysis import (
    GeotechnicalAnalysisRepository,
    GeotechnicalAnalysisService,
)
from app.sdk.context import AgentContext
from app.sdk.contracts import AgentRequest, AgentResult

logger = logging.getLogger("geostrata.plugins.geotechnical_analysis")


def _validate_and_filter_confirmed_documents(
    doc_service: DocumentService,
    project_id: str,
    confirmed_ids: Optional[List[str]] = None,
    document_id: Optional[str] = None,
) -> tuple[str, List[str]]:
    """Validate confirmed project documents and reject any unconfirmed or mismatched documents."""
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

    # Validate that none of the documents are mismatched or rejected
    for cid in check_ids:
        assoc = assoc_by_doc.get(cid)
        if assoc:
            match_status = getattr(assoc, "match_status", None)
            match_status_val = match_status.value if hasattr(match_status, "value") else str(match_status)
            user_decision = getattr(assoc, "user_decision", None)
            user_decision_val = user_decision.value if hasattr(user_decision, "value") else str(user_decision)

            if match_status_val == "MISMATCH" or user_decision_val == "REJECTED":
                raise ValueError(
                    f"Document '{cid}' is marked as MISMATCH / REJECTED and cannot enter the geotechnical analysis workflow."
                )

    resolved_confirmed = list(confirmed_ids or [])

    # If document_id is not explicitly specified, find the geotechnical soil report
    resolved_doc_id = document_id
    if not resolved_doc_id:
        # Search among confirmed documents first
        candidates = resolved_confirmed if resolved_confirmed else [d.document_id for d in doc_service.list_documents(project_id)]
        for cid in candidates:
            doc_meta = doc_service.get_document(cid)
            if doc_meta:
                fn = (doc_meta.filename or "").lower()
                doc_type = getattr(doc_meta, "document_type", "") or ""
                if "soil" in fn or "geotech" in fn or "report" in fn or "soil" in doc_type:
                    resolved_doc_id = cid
                    break
        if not resolved_doc_id and candidates:
            resolved_doc_id = candidates[0]

    if not resolved_doc_id:
        raise ValueError(f"No valid geotechnical documents found for project '{project_id}'.")

    if resolved_doc_id not in resolved_confirmed:
        resolved_confirmed.append(resolved_doc_id)

    return resolved_doc_id, resolved_confirmed


def run(request: AgentRequest, context: AgentContext | None = None) -> dict[str, Any]:
    """Agent Platform adapter entrypoint for Geotechnical Analysis Agent."""
    inputs = request.inputs or {}
    document_id = inputs.get("document_id")
    project_id = inputs.get("project_id", "default")
    confirmed_document_ids = inputs.get("confirmed_document_ids")
    llm_profile = inputs.get("llm_profile", "document_analysis")
    db_path = inputs.get("db_path") or os.getenv("GEOSTRATA_DB_PATH", "geostrata.db")

    # Connect to SQLite database
    conn = sqlite3.connect(db_path, check_same_thread=False)
    doc_repo = DocumentRepository(conn)
    doc_storage = DocumentStorage()
    doc_service = DocumentService(repository=doc_repo, storage=doc_storage)

    # Validate document confirmation and resolve primary geotechnical document
    target_doc_id, validated_confirmed_ids = _validate_and_filter_confirmed_documents(
        doc_service=doc_service,
        project_id=project_id,
        confirmed_ids=confirmed_document_ids,
        document_id=document_id,
    )

    geo_repo = GeotechnicalAnalysisRepository(conn)
    analysis_service = GeotechnicalAnalysisService(
        repository=geo_repo,
        document_service=doc_service,
    )

    existing_report_id = inputs.get("existing_geotechnical_report_id")
    reuse_existing = bool(inputs.get("reuse_existing", False))
    report = None
    if existing_report_id:
        candidate = geo_repo.get_report(existing_report_id)
        if candidate and str(candidate.review_status).upper() != "REJECTED" and candidate.document_id == target_doc_id:
            logger.info("Reusing existing Geotechnical Analysis Report '%s'", candidate.report_id)
            report = candidate
    elif reuse_existing:
        candidate = geo_repo.get_latest_report_for_project(project_id) or geo_repo.get_latest_report_for_document(target_doc_id)
        if candidate and str(candidate.review_status).upper() != "REJECTED" and candidate.document_id == target_doc_id:
            logger.info("Reusing latest valid Geotechnical Analysis Report '%s'", candidate.report_id)
            report = candidate

    if report is None:
        logger.info(
            "Executing Geotechnical Analysis Agent (run_id=%s) for project '%s', document '%s'",
            request.run_id,
            project_id,
            target_doc_id,
        )
        report = analysis_service.run_analysis(
            document_id=target_doc_id,
            project_id=project_id,
            run_id=request.run_id,
            llm_profile=llm_profile,
        )

    output = report.model_dump()
    output["report_id"] = report.report_id
    output["status"] = "succeeded"
    output["execution_status"] = "succeeded"
    output["project_id"] = project_id
    output["document_id"] = target_doc_id
    output["confirmed_document_ids"] = validated_confirmed_ids

    logger.info("Geotechnical Analysis completed successfully: report_id=%s", report.report_id)
    return output
