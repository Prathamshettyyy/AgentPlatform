from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

from geostrata.backend.documents import DocumentRepository, DocumentService, DocumentStorage
from geostrata.backend.agents.foundation_research import FoundationResearchRepository
from geostrata.backend.agents.geotechnical_analysis import GeotechnicalAnalysisRepository
from geostrata.backend.agents.requirement_agent import RequirementAgentRepository, RequirementAgentService
from app.sdk.context import AgentContext
from app.sdk.contracts import AgentRequest

logger = logging.getLogger("geostrata.plugins.requirement_agent")


def run(request: AgentRequest, context: AgentContext | None = None) -> Dict[str, Any]:
    """Agent Platform adapter entrypoint for Agent 3: Vendor Requirement Agent."""
    inputs = request.inputs or {}
    project_id = inputs.get("project_id", "default")
    geotechnical_report_id = inputs.get("geotechnical_report_id") or inputs.get("analysis_report_id")
    foundation_research_report_id = (
        inputs.get("foundation_research_report_id") or inputs.get("research_report_id")
    )
    confirmed_document_ids: Optional[List[str]] = inputs.get("confirmed_document_ids")
    document_id: Optional[str] = inputs.get("document_id")
    snapshot_id: Optional[str] = inputs.get("snapshot_id")
    document_versions: Optional[Dict[str, str]] = inputs.get("document_versions")
    llm_profile = inputs.get("llm_profile", "document_analysis")
    db_path = inputs.get("db_path") or os.getenv("GEOSTRATA_DB_PATH", "geostrata.db")

    if not geotechnical_report_id:
        raise ValueError(
            "Requirement Agent requires an explicit 'geotechnical_report_id' input. "
            "Arbitrary selection of latest reports is prohibited."
        )
    if not foundation_research_report_id:
        raise ValueError(
            "Requirement Agent requires an explicit 'foundation_research_report_id' input. "
            "Arbitrary selection of latest reports is prohibited."
        )

    conn = sqlite3.connect(db_path, check_same_thread=False)
    doc_repo = DocumentRepository(conn)
    doc_storage = DocumentStorage()
    doc_service = DocumentService(repository=doc_repo, storage=doc_storage)

    geo_repo = GeotechnicalAnalysisRepository(conn)
    fr_repo = FoundationResearchRepository(conn)
    req_repo = RequirementAgentRepository(conn)

    req_service = RequirementAgentService(
        repository=req_repo,
        geotechnical_repository=geo_repo,
        foundation_research_repository=fr_repo,
        document_service=doc_service,
    )

    logger.info(
        "Executing Vendor Requirement Agent (run_id=%s) for project '%s' consuming geo='%s' and fr='%s'",
        request.run_id,
        project_id,
        geotechnical_report_id,
        foundation_research_report_id,
    )

    report = req_service.run_requirement_generation(
        project_id=project_id,
        geotechnical_report_id=geotechnical_report_id,
        foundation_research_report_id=foundation_research_report_id,
        confirmed_document_ids=confirmed_document_ids,
        document_id=document_id,
        snapshot_id=snapshot_id,
        document_versions=document_versions,
        run_id=request.run_id,
        llm_profile=llm_profile,
    )

    output = report.model_dump()
    output["report_id"] = report.report_id
    output["geotechnical_report_id"] = report.geotechnical_report_id
    output["foundation_research_report_id"] = report.foundation_research_report_id
    output["status"] = "succeeded"
    output["execution_status"] = "succeeded"
    output["project_id"] = report.project_id
    output["document_id"] = report.document_id
    output["confirmed_document_ids"] = report.confirmed_document_ids

    logger.info("Vendor Requirement Agent completed successfully: report_id=%s", report.report_id)
    return output

