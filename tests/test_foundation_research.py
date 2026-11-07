from __future__ import annotations

import sqlite3
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from geostrata.backend.documents import (
    PDFExtractor,
    DocumentStorage,
    DocumentRepository,
    DocumentService,
)
from geostrata.backend.agents.foundation_research import (
    AuthorityCategory,
    CuratedEngineeringSearchProvider,
    FoundationOption,
    FoundationResearchReport,
    FoundationResearchRepository,
    FoundationResearchService,
    MockSearchProvider,
    RelevanceClassification,
    ReviewStatus,
    build_foundation_research_graph,
    get_search_provider,
)
from geostrata.backend.agents.geotechnical_analysis import (
    GeotechnicalAnalysisRepository,
    GeotechnicalAnalysisService,
)
from app.registry import AgentLoader, AgentRegistry
from app.runtime.runner import AgentRunner
from app.sdk.contracts import AgentRequest

REAL_SOIL_REPORT_PATH = Path("storage/documents/7d500784-af45-4a86-a437-e90c3f7b54f2/original.pdf")


@pytest.fixture
def test_setup(tmp_path):
    db_file = tmp_path / "test_research.db"
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    doc_repo = DocumentRepository(conn)
    doc_storage = DocumentStorage(root_dir=tmp_path / "storage")
    extractor = PDFExtractor()
    doc_service = DocumentService(repository=doc_repo, storage=doc_storage, extractor=extractor)

    geo_repo = GeotechnicalAnalysisRepository(conn)
    geo_service = GeotechnicalAnalysisService(repository=geo_repo, document_service=doc_service)

    fr_repo = FoundationResearchRepository(conn)
    mock_search = MockSearchProvider()
    fr_service = FoundationResearchService(
        repository=fr_repo,
        document_service=doc_service,
        geotechnical_repository=geo_repo,
        search_provider=mock_search,
    )

    return {
        "conn": conn,
        "doc_service": doc_service,
        "geo_repo": geo_repo,
        "geo_service": geo_service,
        "fr_repo": fr_repo,
        "fr_service": fr_service,
        "mock_search": mock_search,
        "tmp_path": tmp_path,
    }


def _upload_test_document(doc_service: DocumentService, project_id: str) -> str:
    if REAL_SOIL_REPORT_PATH.exists():
        pdf_bytes = REAL_SOIL_REPORT_PATH.read_bytes()
        meta = doc_service.upload_document(
            filename="Soil report 25-0117 v1.pdf",
            content=pdf_bytes,
            project_id=project_id,
        )
    else:
        meta = doc_service.upload_document(
            filename="test_doc.pdf",
            content=b"%PDF-1.4 dummy content for unit test",
            project_id=project_id,
        )
    return meta.document_id


def test_agent_registration():
    """Verify that Foundation Research Agent is registered and loaded via manifest."""
    registry = AgentRegistry()
    manifests_dir = Path("geostrata/plugins/manifests")
    loader = AgentLoader(registry, manifests_dir)
    loaded = loader.load_all()

    agent_ids = {a.id for a in loaded}
    assert "foundation_research" in agent_ids

    agent = registry.get("foundation_research")
    assert agent.metadata.name == "Foundation Research Agent"
    assert "foundation_research" in agent.metadata.capabilities
    assert "langgraph_workflow" in agent.metadata.capabilities
    assert "web_research" in agent.metadata.capabilities
    assert "multi_document_intelligence" in agent.metadata.capabilities
    assert agent.entrypoint == "geostrata.plugins.foundation_research.adapter:run"


@pytest.mark.asyncio
async def test_search_providers():
    """Verify search provider implementations (Mock, Curated, Factory)."""
    # 1. Mock provider
    mock_prov = MockSearchProvider()
    results = await mock_prov.search("drilled shaft design Houston clay", max_results=3)
    assert len(results) > 0
    assert results[0].url.startswith("http")
    assert results[0].authority_category in ["GOVERNMENT_AGENCY", "STANDARDS_ORGANIZATION", "INDUSTRY_TECHNICAL"]

    # 2. Curated engineering index
    curated = CuratedEngineeringSearchProvider()
    c_results = await curated.search("FHWA drilled shaft GEC 10", max_results=5)
    assert len(c_results) > 0
    assert any("FHWA" in r.title for r in c_results)
    assert any(r.authority_category == AuthorityCategory.GOVERNMENT_AGENCY for r in c_results)

    pti_results = await curated.search("post-tensioned slab expansive clay PTI", max_results=5)
    assert len(pti_results) > 0
    assert any("PTI" in r.title for r in pti_results)

    # 3. Factory lookup
    p_curated = get_search_provider("curated")
    assert isinstance(p_curated, CuratedEngineeringSearchProvider)

    p_mock = get_search_provider("mock")
    assert isinstance(p_mock, MockSearchProvider)


def test_foundation_research_graph_execution(test_setup):
    """Test full 10-node LangGraph workflow execution with mock search."""
    doc_service = test_setup["doc_service"]
    geo_repo = test_setup["geo_repo"]
    mock_search = test_setup["mock_search"]

    doc_id = _upload_test_document(doc_service, "test_proj_1")

    initial_state = {
        "project_id": "test_proj_1",
        "document_id": doc_id,
        "run_id": "test_run_001",
        "llm_profile": "document_analysis",
        "search_provider_name": "mock",
        "document_service": doc_service,
        "geotechnical_repository": geo_repo,
        "search_provider": mock_search,
    }

    graph = build_foundation_research_graph()
    final_state = graph.invoke(initial_state)

    assert "report" in final_state
    report_dict = final_state["report"]
    report = FoundationResearchReport.model_validate(report_dict)

    # Verification of report contents
    assert report.report_id.startswith("fnd_rep_")
    assert report.project_id == "test_proj_1"
    assert report.document_id == doc_id
    assert report.review_status == ReviewStatus.PENDING_REVIEW

    # Options researched
    assert len(report.options_researched) >= 4
    option_names = [o.name for o in report.options_researched]
    assert any("Pier" in t or "Shaft" in t for t in option_names)
    assert any("Slab" in t or "Post-Tensioned" in t for t in option_names)

    # Relevance classifications
    for opt in report.options_researched:
        assert isinstance(opt.relevance_classification, RelevanceClassification)
        assert len(opt.advantages) > 0
        assert len(opt.limitations) > 0
        assert opt.relevance_reasoning != ""

    # Comparisons
    assert len(report.comparisons) >= 4
    for cmp in report.comparisons:
        assert cmp.bearing_considerations != ""
        assert cmp.settlement_considerations != ""
        assert len(cmp.advantages) > 0
        assert len(cmp.limitations) > 0

    # External sources
    assert len(report.external_sources) > 0
    for src in report.external_sources:
        assert src.title != ""
        assert src.url != ""
        assert isinstance(src.authority_category, AuthorityCategory)

    # Research gaps & Questions
    assert len(report.research_gaps) > 0
    assert len(report.engineer_questions) > 0

    # Markdown content with Engineering Disclaimer
    assert "Professional Engineering Disclaimer" in report.markdown_content
    assert "Professional Engineer" in report.markdown_content


def test_foundation_research_service_and_reviews(test_setup):
    """Test FoundationResearchService persistence, listing, and human review."""
    service = test_setup["fr_service"]
    doc_service = test_setup["doc_service"]

    doc_id = _upload_test_document(doc_service, "review_project")

    report = service.run_research(
        document_id=doc_id,
        project_id="review_project",
        search_provider_name="mock",
    )

    assert report.review_status == ReviewStatus.PENDING_REVIEW

    # Retrieve from repository
    fetched = service.get_report(report.report_id)
    assert fetched is not None
    assert fetched.report_id == report.report_id

    # Latest by project
    latest_proj = service.get_latest_report_for_project("review_project")
    assert latest_proj is not None
    assert latest_proj.report_id == report.report_id

    # List reports for project
    reports_list = service.list_reports_for_project("review_project")
    assert len(reports_list) == 1

    # Human engineering review: APPROVED
    reviewed = service.submit_review(
        report_id=report.report_id,
        decision=ReviewStatus.APPROVED,
        reviewer_id="PE_Jane_Doe_TX_98765",
        comments="Approved for structural foundation pre-design sizing.",
    )
    assert reviewed.review_status == ReviewStatus.APPROVED
    assert reviewed.reviewed_by == "PE_Jane_Doe_TX_98765"
    assert reviewed.review_notes == "Approved for structural foundation pre-design sizing."
    assert reviewed.reviewed_at is not None

    # Re-fetch verifies persistence of review
    re_fetched = service.get_report(report.report_id)
    assert re_fetched.review_status == ReviewStatus.APPROVED


@pytest.mark.asyncio
async def test_agent_runner_integration(test_setup):
    """Test executing Foundation Research Agent through AgentRunner and manifest."""
    registry = AgentRegistry()
    loader = AgentLoader(registry, Path("geostrata/plugins/manifests"))
    loader.load_all()

    runner = AgentRunner(registry)
    request = AgentRequest(
        task="Research foundation systems for project",
        inputs={
            "document_id": "7d500784-af45-4a86-a437-e90c3f7b54f2",
            "project_id": "default",
            "search_provider": "curated",
        },
        run_id="run_runner_fnd_01",
    )

    result = await runner.run("foundation_research", request)
    assert result.status == "succeeded"
    assert "report_id" in result.output
    assert "options_researched" in result.output
    assert len(result.output["options_researched"]) >= 4


def test_fastapi_endpoints(test_setup):
    """Test FastAPI foundation research routes with TestClient."""
    doc_service = test_setup["doc_service"]
    geo_service = test_setup["geo_service"]
    fr_service = test_setup["fr_service"]

    doc_id = _upload_test_document(doc_service, "api_proj")

    app = create_app()
    app.state.document_service = doc_service
    app.state.geotechnical_analysis_service = geo_service
    app.state.foundation_research_service = fr_service
    client = TestClient(app)

    # 1. POST /v1/foundation-research/runs
    run_resp = client.post(
        "/v1/foundation-research/runs",
        json={
            "document_id": doc_id,
            "project_id": "api_proj",
            "search_provider_name": "mock",
        },
    )
    assert run_resp.status_code == 200
    report_data = run_resp.json()
    rep_id = report_data["report_id"]
    assert rep_id.startswith("fnd_rep_")
    assert report_data["review_status"] == "PENDING_REVIEW"
    assert len(report_data["options_researched"]) >= 4

    # 2. GET /v1/foundation-research/reports/{report_id}
    get_resp = client.get(f"/v1/foundation-research/reports/{rep_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["report_id"] == rep_id

    # 3. GET /v1/foundation-research/projects/{project_id}/latest
    proj_latest_resp = client.get("/v1/foundation-research/projects/api_proj/latest")
    assert proj_latest_resp.status_code == 200
    assert proj_latest_resp.json()["report_id"] == rep_id

    # 4. GET /v1/foundation-research/documents/{document_id}/latest
    doc_latest_resp = client.get(f"/v1/foundation-research/documents/{doc_id}/latest")
    assert doc_latest_resp.status_code == 200
    assert doc_latest_resp.json()["report_id"] == rep_id

    # 5. GET /v1/foundation-research/projects/{project_id}/reports
    list_resp = client.get("/v1/foundation-research/projects/api_proj/reports")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) >= 1

    # 6. POST /v1/foundation-research/reports/{report_id}/review
    rev_resp = client.post(
        f"/v1/foundation-research/reports/{rep_id}/review",
        json={
            "decision": "APPROVED",
            "reviewer_id": "Senior_PE_Smith",
            "comments": "Concur with helical and drilled shaft options.",
        },
    )
    assert rev_resp.status_code == 200
    rev_data = rev_resp.json()
    assert rev_data["review_status"] == "APPROVED"
    assert rev_data["reviewed_by"] == "Senior_PE_Smith"


def test_engineering_safety_rules(test_setup):
    """Verify professional engineering disclaimer, soil condition warnings, and relevance constraints."""
    service = test_setup["fr_service"]
    doc_service = test_setup["doc_service"]

    doc_id = _upload_test_document(doc_service, "safety_proj")

    report = service.run_research(
        document_id=doc_id,
        project_id="safety_proj",
        search_provider_name="curated",
    )

    # 1. Initial review status MUST be PENDING_REVIEW
    assert report.review_status == ReviewStatus.PENDING_REVIEW

    # 2. Markdown must contain clear Professional Engineering Disclaimer
    assert "Professional Engineering Disclaimer" in report.markdown_content
    assert "Professional Engineer" in report.markdown_content

    # 3. Belled pier caving risk must be addressed in options or gaps
    options_text = " ".join(
        [o.relevance_reasoning + " " + " ".join(o.limitations) for o in report.options_researched]
    )
    gaps_text = " ".join([g.description for g in report.research_gaps])
    combined_notes = (options_text + " " + gaps_text).lower()
    assert "caving" in combined_notes or "calcareous" in combined_notes or "underream" in combined_notes

    # 4. Driven piles should have limited relevance in residential neighborhood
    driven_opts = [o for o in report.options_researched if "Driven" in o.name]
    if driven_opts:
        assert driven_opts[0].relevance_classification in [
            RelevanceClassification.LIMITED_RELEVANCE,
            RelevanceClassification.POTENTIALLY_RELEVANT,
        ]
        limitations_str = " ".join(driven_opts[0].limitations).lower()
        assert "noise" in limitations_str or "vibration" in limitations_str


def test_foundation_research_source_accuracy_and_claim_distinction(test_setup):
    """Regression test verifying Foundation Research Agent preserves exact geotechnical numbers,
    removes invented values, and clearly distinguishes consultant recommendations, external research,
    AI comparisons, and engineer-confirmation requirements."""
    service = test_setup["fr_service"]
    doc_service = test_setup["doc_service"]

    doc_id = _upload_test_document(doc_service, "audit_proj")
    report = service.run_research(
        document_id=doc_id,
        project_id="audit_proj",
        search_provider_name="curated",
    )

    opts_by_name = {o.name: o for o in report.options_researched}

    # 1. Continuous Footings / Grade Beams: 1,800 psf (FS=3) and 2,700 psf (FS=2) at minimum 2.50 ft embedment
    cont_opt = opts_by_name["Continuous Footings / Grade Beams"]
    assert "1,800 psf" in cont_opt.bearing_considerations
    assert "2,700 psf" in cont_opt.bearing_considerations
    assert "2.50 ft" in cont_opt.bearing_considerations
    assert "2,000 psf" not in cont_opt.bearing_considerations
    assert "1,400 psf" not in cont_opt.bearing_considerations

    # 2. Drilled Underreamed Piers: 2,000 psf (FS=3) and 3,000 psf (FS=2) at ~10.0 ft, no invented < 0.5 in settlement,
    #    notes grade beams may be formed directly on subgrade soils, and labels carton void forms as engineer confirmation
    pier_opt = opts_by_name["Drilled Underreamed Piers"]
    assert "2,000 psf" in pier_opt.bearing_considerations
    assert "3,000 psf" in pier_opt.bearing_considerations
    assert "10.0 ft" in pier_opt.bearing_considerations
    assert "< 0.5 in" not in pier_opt.settlement_considerations
    assert "formed directly on the subgrade soils" in pier_opt.expansive_soil_considerations
    assert "[ENGINEER CONFIRMATION REQUIRED]" in pier_opt.expansive_soil_considerations

    # 3. Drilled Straight-Sided Shafts: no invented 12 to 15 ft founding depth or < 0.5 in settlement
    shaft_opt = opts_by_name["Drilled Straight-Sided Shafts"]
    assert "12 to 15 ft" not in shaft_opt.bearing_considerations
    assert "< 0.5 in" not in shaft_opt.settlement_considerations

    # 4. Post-Tensioned Slab-on-Ground: 1,400 psf / 2,100 psf, grade beams >= 1.50 ft beneath finished grade (no 2.0 to 3.0 ft),
    #    and minimum slope of 6 inches in the first 10 feet
    pt_opt = opts_by_name["Post-Tensioned Slab-on-Ground"]
    assert "1,400 psf" in pt_opt.bearing_considerations
    assert "2,100 psf" in pt_opt.bearing_considerations
    assert "1.50 ft" in pt_opt.bearing_considerations
    assert "2.0 to 3.0 ft" not in pt_opt.groundwater_considerations
    assert "6 inches in the first 10 feet" in pt_opt.expansive_soil_considerations

    # 5. Helical Piles: no invented 20 to 50 kips pile capacity
    helical_opt = opts_by_name["Helical Piles (Screw Piles)"]
    assert "20 to 50 kips" not in helical_opt.bearing_considerations

    # 6. Clear distinction labels in report markdown
    md = report.markdown_content
    assert "[GEOTECHNICAL CONSULTANT RECOMMENDATION]" in md
    assert "[EXTERNAL RESEARCH FINDING]" in md
    assert "[AI-GENERATED COMPARISON]" in md
    assert "[ENGINEER CONFIRMATION REQUIRED]" in md
