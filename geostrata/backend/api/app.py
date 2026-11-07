"""GeoStrata Application Factory.

Independent FastAPI application providing all domain-specific geotechnical capabilities:
- Document intelligence & PDF/image ingestion pipeline (/v1/documents)
- AI Geotechnical Analysis Agent & Reporting (/v1/geotechnical-analysis)
- AI Foundation Research Agent & Web Intelligence (/v1/foundation-research)
- AI Vendor Requirement Agent & Procurement Specification (/v1/requirements)
- Workflow proxy/forwarder to Agent Platform (/v1/runs)
"""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import threading
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx

from geostrata.backend.documents import (
    DocumentRepository,
    DocumentService,
    document_router,
)
from geostrata.backend.agents.geotechnical_analysis import (
    GeotechnicalAnalysisRepository,
    GeotechnicalAnalysisService,
    geotechnical_analysis_router,
)
from geostrata.backend.agents.foundation_research import (
    FoundationResearchRepository,
    FoundationResearchService,
    foundation_research_router,
)
from geostrata.backend.agents.requirement_agent import (
    RequirementAgentRepository,
    RequirementAgentService,
    requirement_agent_router,
)


def create_geostrata_app(
    db_path: str | None = None,
    connection: sqlite3.Connection | None = None,
    lock: threading.RLock | None = None,
    document_service: DocumentService | None = None,
    geotechnical_analysis_service: GeotechnicalAnalysisService | None = None,
    foundation_research_service: FoundationResearchService | None = None,
    requirement_agent_service: RequirementAgentService | None = None,
    agent_platform_url: str | None = None,
) -> FastAPI:
    """Create and configure the GeoStrata domain application."""

    platform_url = (
        agent_platform_url
        or os.getenv("AGENT_PLATFORM_URL", "http://127.0.0.1:8000")
    ).rstrip("/")

    app = FastAPI(
        title="GeoStrata API",
        description="GeoStrata — Soil & Foundation Intelligence Platform API",
        version="1.0.0",
    )

    # Enable CORS for GeoStrata Portal and Agent Platform frontends
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize persistence
    if connection is not None:
        conn = connection
        db_lock = lock or threading.RLock()
    elif hasattr(db_path, "_connection"):
        conn = db_path._connection
        db_lock = lock or getattr(db_path, "_lock", threading.RLock())
    else:
        if hasattr(db_path, "path"):
            resolved_path = db_path.path
        elif isinstance(db_path, str):
            resolved_path = db_path
        else:
            resolved_path = os.getenv("GEOSTRATA_DB_PATH", "geostrata.db")

        if resolved_path == ":memory:":
            conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            db_file = Path(resolved_path).resolve()
            db_file.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_file), check_same_thread=False)
            conn.execute("PRAGMA busy_timeout = 5000")
            conn.execute("PRAGMA journal_mode = WAL")
        db_lock = lock or threading.RLock()

    app.state.db_connection = conn
    app.state.db_lock = db_lock
    app.state.agent_platform_url = platform_url

    class _RepositoryShim:
        def __init__(self, c, l):
            self._connection = c
            self._lock = l

    app.state.repository = _RepositoryShim(conn, db_lock)

    # 1. Document Intelligence Pipeline
    if document_service is not None:
        doc_svc = document_service
    else:
        doc_repo = DocumentRepository(conn, db_lock)
        doc_svc = DocumentService(doc_repo)
    app.state.document_service = doc_svc
    app.include_router(document_router)

    # 2. Geotechnical Analysis Agent & Reporting
    if geotechnical_analysis_service is not None:
        geo_svc = geotechnical_analysis_service
    else:
        geo_repo = GeotechnicalAnalysisRepository(conn, db_lock)
        geo_svc = GeotechnicalAnalysisService(
            repository=geo_repo,
            document_service=doc_svc,
        )
    app.state.geotechnical_analysis_service = geo_svc
    app.include_router(geotechnical_analysis_router)

    # 3. Foundation Research Agent & Web Intelligence
    if foundation_research_service is not None:
        fr_svc = foundation_research_service
    else:
        fr_repo = FoundationResearchRepository(conn, db_lock)
        fr_svc = FoundationResearchService(
            repository=fr_repo,
            document_service=doc_svc,
            geotechnical_repository=getattr(geo_svc, "repository", None),
        )
    app.state.foundation_research_service = fr_svc
    app.include_router(foundation_research_router)

    # 4. Vendor Requirement Agent & RFQ Specification
    if requirement_agent_service is not None:
        req_svc = requirement_agent_service
    else:
        req_repo = RequirementAgentRepository(conn, db_lock)
        req_svc = RequirementAgentService(
            repository=req_repo,
            geotechnical_repository=getattr(geo_svc, "repository", None),
            foundation_research_repository=getattr(fr_svc, "repository", None),
            document_service=doc_svc,
        )
    app.state.requirement_agent_service = req_svc
    app.include_router(requirement_agent_router)

    # 5. Independent Health Endpoints
    @app.get("/v1/health")
    @app.get("/health")
    def health():
        return {
            "status": "healthy",
            "service": "geostrata",
            "version": "1.0.0",
            "agent_platform_url": platform_url,
        }

    # 6. Workflow & Run Proxy Routes (integrating GeoStrata with Agent Platform)
    platform_proxy = APIRouter()

    @platform_proxy.post("/v1/runs")
    async def proxy_start_run(http_request: Request):
        body = await http_request.json()

        # Pre-workflow validation for project documents
        inputs = body.get("inputs") or {}
        if isinstance(inputs, dict) and inputs.get("project_id") and "confirmed_document_ids" in inputs:
            val_res = doc_svc.validate_project_documents(
                project_id=inputs["project_id"],
                confirmed_document_ids=inputs.get("confirmed_document_ids") or [],
                expected_versions=inputs.get("expected_versions"),
            )
            if not val_res.is_valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Pre-workflow document validation failed: {'; '.join(val_res.validation_errors)}",
                )

        # Forward request to Agent Platform
        async with httpx.AsyncClient(timeout=60.0) as client:
            headers = {k: v for k, v in http_request.headers.items() if k.lower() not in {"host", "content-length"}}
            try:
                resp = await client.post(
                    f"{platform_url}/v1/runs",
                    json=body,
                    headers=headers,
                )
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type=resp.headers.get("content-type", "application/json"),
                )
            except httpx.ConnectError:
                raise HTTPException(
                    status_code=503,
                    detail=f"Agent Platform unavailable at {platform_url}. Ensure Agent Platform is running.",
                )

    @platform_proxy.get("/v1/runs")
    async def proxy_list_runs(http_request: Request):
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {k: v for k, v in http_request.headers.items() if k.lower() not in {"host", "content-length"}}
            try:
                resp = await client.get(
                    f"{platform_url}/v1/runs",
                    params=http_request.query_params,
                    headers=headers,
                )
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type=resp.headers.get("content-type", "application/json"),
                )
            except httpx.ConnectError:
                raise HTTPException(
                    status_code=503,
                    detail=f"Agent Platform unavailable at {platform_url}",
                )

    @platform_proxy.get("/v1/runs/{run_id}")
    async def proxy_get_run(run_id: str, http_request: Request):
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {k: v for k, v in http_request.headers.items() if k.lower() not in {"host", "content-length"}}
            try:
                resp = await client.get(
                    f"{platform_url}/v1/runs/{run_id}",
                    headers=headers,
                )
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type=resp.headers.get("content-type", "application/json"),
                )
            except httpx.ConnectError:
                raise HTTPException(
                    status_code=503,
                    detail=f"Agent Platform unavailable at {platform_url}",
                )

    @platform_proxy.get("/v1/runs/{run_id}/events")
    async def proxy_get_run_events(run_id: str, http_request: Request):
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {k: v for k, v in http_request.headers.items() if k.lower() not in {"host", "content-length"}}
            try:
                resp = await client.get(
                    f"{platform_url}/v1/runs/{run_id}/events",
                    headers=headers,
                )
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type=resp.headers.get("content-type", "application/json"),
                )
            except httpx.ConnectError:
                raise HTTPException(
                    status_code=503,
                    detail=f"Agent Platform unavailable at {platform_url}",
                )

    @platform_proxy.get("/v1/workflows")
    @platform_proxy.get("/v1/workflows/{workflow_id}")
    async def proxy_get_workflows(http_request: Request, workflow_id: str | None = None):
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {k: v for k, v in http_request.headers.items() if k.lower() not in {"host", "content-length"}}
            path = f"/v1/workflows/{workflow_id}" if workflow_id else "/v1/workflows"
            try:
                resp = await client.get(
                    f"{platform_url}{path}",
                    params=http_request.query_params,
                    headers=headers,
                )
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type=resp.headers.get("content-type", "application/json"),
                )
            except httpx.ConnectError:
                raise HTTPException(
                    status_code=503,
                    detail=f"Agent Platform unavailable at {platform_url}",
                )

    @platform_proxy.get("/v1/overview")
    async def proxy_get_overview(http_request: Request):
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {k: v for k, v in http_request.headers.items() if k.lower() not in {"host", "content-length"}}
            try:
                resp = await client.get(
                    f"{platform_url}/v1/overview",
                    headers=headers,
                )
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type=resp.headers.get("content-type", "application/json"),
                )
            except httpx.ConnectError:
                raise HTTPException(
                    status_code=503,
                    detail=f"Agent Platform unavailable at {platform_url}",
                )

    app.include_router(platform_proxy)

    return app

