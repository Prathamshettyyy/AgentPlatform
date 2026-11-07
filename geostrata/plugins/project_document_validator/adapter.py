from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, List, Optional

from geostrata.backend.documents import DocumentRepository, DocumentService, DocumentStorage
from app.sdk.context import AgentContext
from app.sdk.contracts import AgentRequest

logger = logging.getLogger("geostrata.plugins.project_document_validator")


def run(request: AgentRequest, context: AgentContext | None = None) -> dict[str, Any]:
    """Service task node entrypoint to validate project documents before analysis workflows.

    Enforces:
    - Confirmed documents belong to project and are not marked MISMATCH or REJECTED.
    - All documents are ready (READY_FOR_ANALYSIS) and not FAILED or PROCESSING.
    - Primary geotechnical report is present.
    - Document versions (hashes) match snapshot to prevent silent modifications.
    """
    inputs = request.inputs or {}
    project_id = inputs.get("project_id", "default")
    confirmed_document_ids = inputs.get("confirmed_document_ids") or []
    expected_versions = inputs.get("expected_versions")
    db_path = inputs.get("db_path") or os.getenv("GEOSTRATA_DB_PATH", "geostrata.db")

    conn = sqlite3.connect(db_path, check_same_thread=False)
    doc_repo = DocumentRepository(conn)
    doc_storage = DocumentStorage()
    doc_service = DocumentService(repository=doc_repo, storage=doc_storage)

    logger.info(
        "Executing Validate Project Documents task (run_id=%s) for project '%s' (%d documents)",
        request.run_id,
        project_id,
        len(confirmed_document_ids),
    )

    val_result = doc_service.validate_project_documents(
        project_id=project_id,
        confirmed_document_ids=confirmed_document_ids,
        expected_versions=expected_versions,
    )

    if not val_result.is_valid:
        err_msg = "; ".join(val_result.validation_errors)
        logger.error("Project document validation failed: %s", err_msg)
        raise ValueError(f"Project document validation failed: {err_msg}")

    snapshot_id = val_result.snapshot.snapshot_id if val_result.snapshot else None

    logger.info(
        "Project document validation succeeded: primary_doc=%s, snapshot_id=%s",
        val_result.primary_document_id,
        snapshot_id,
    )

    return {
        "status": "succeeded",
        "execution_status": "succeeded",
        "project_id": project_id,
        "validated_document_ids": val_result.validated_document_ids,
        "confirmed_document_ids": val_result.validated_document_ids,
        "primary_document_id": val_result.primary_document_id,
        "document_id": val_result.primary_document_id,
        "snapshot_id": snapshot_id,
        "document_versions": val_result.document_versions,
        "message": val_result.message,
    }

