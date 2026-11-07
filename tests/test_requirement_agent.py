from __future__ import annotations

import os
import sqlite3
from pathlib import Path
import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.app import create_app
from geostrata.backend.documents import DocumentRepository, DocumentService, DocumentStorage
from geostrata.backend.agents.foundation_research import (
    FoundationResearchRepository,
    FoundationResearchService,
    ReviewStatus,
    get_search_provider,
)
from geostrata.backend.agents.geotechnical_analysis import (
    GeotechnicalAnalysisRepository,
    GeotechnicalAnalysisService,
)
from app.registry import AgentLoader, AgentRegistry
from geostrata.backend.agents.requirement_agent import (
    RequirementAgentRepository,
    RequirementAgentService,
    RequirementDocument,
    RequirementReviewStatus,
    RequirementSource,
    build_requirement_agent_graph,
)
from app.runtime.runner import AgentRunner
from app.sdk.contracts import AgentRequest
from app.workflows.builder import WorkflowBuilder
from app.workflows.models import WorkflowDefinition

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
MANIFESTS_DIR = WORKSPACE_ROOT / "geostrata" / "plugins" / "manifests"
WORKFLOW_YAML_PATH = WORKSPACE_ROOT / "geostrata" / "workflow_definitions" / "geotechnical_foundation_investigation.yaml"
WHITE_OAK_PROJECT_ID = "7d500784-af45-4a86-a437-e90c3f7b54f2"
WHITE_OAK_SOIL_DOC_ID = "7d500784-af45-4a86-a437-e90c3f7b54f2"
WHITE_OAK_SITE_PLAN_2436_ID = "58e1ebc4-b70c-401e-b2c1-a842cadd764a"
WHITE_OAK_MISMATCH_2434_ID = "ef3832f5-6364-4611-b259-c12a83338802"


@pytest.fixture(scope="module")
def upstream_white_oak_reports():
    """Ensure exact Agent 1 and Agent 2 reports exist in agent_platform.db for White Oak."""
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    doc_repo = DocumentRepository(conn)
    doc_service = DocumentService(repository=doc_repo, storage=DocumentStorage())
    geo_repo = GeotechnicalAnalysisRepository(conn)
    fr_repo = FoundationResearchRepository(conn)

    existing_geo = geo_repo.get_latest_report_for_document(WHITE_OAK_SOIL_DOC_ID)
    existing_fr = fr_repo.get_latest_report_for_document(WHITE_OAK_SOIL_DOC_ID)
    if existing_geo and existing_fr:
        return existing_geo, existing_fr

    geo_service = GeotechnicalAnalysisService(repository=geo_repo, document_service=doc_service)
    geo_report = geo_service.run_analysis(
        document_id=WHITE_OAK_SOIL_DOC_ID,
        project_id=WHITE_OAK_PROJECT_ID,
        run_id="test_req_agent_geo_seed",
    )

    fr_service = FoundationResearchService(
        repository=fr_repo,
        document_service=doc_service,
        geotechnical_repository=geo_repo,
        search_provider=get_search_provider("curated"),
    )
    fr_report = fr_service.run_research(
        document_id=WHITE_OAK_SOIL_DOC_ID,
        project_id=WHITE_OAK_PROJECT_ID,
        analysis_report_id=geo_report.report_id,
        run_id="test_req_agent_fr_seed",
        search_provider_name="curated",
    )
    return geo_report, fr_report


def test_1_requirement_agent_registration():
    """1. Verify Requirement Agent manifest loads and registers in AgentRegistry."""
    reg = AgentRegistry()
    loader = AgentLoader(reg, MANIFESTS_DIR)
    loader.load_all()

    registered = reg.get("requirement_agent")
    assert registered is not None
    assert registered.metadata.id == "requirement_agent"
    assert registered.metadata.name == "Vendor Requirement Agent"
    assert registered.metadata.enabled is True
    assert "vendor_requirements" in registered.metadata.capabilities
    assert "provenance_traceability" in registered.metadata.capabilities


@pytest.mark.asyncio
async def test_2_agent_runner_execution(upstream_white_oak_reports):
    """2. Verify AgentRunner executes requirement_agent via its registered adapter."""
    geo_report, fr_report = upstream_white_oak_reports

    reg = AgentRegistry()
    AgentLoader(reg, MANIFESTS_DIR).load_all()
    runner = AgentRunner(reg)

    req = AgentRequest(
        run_id="runner_req_test_01",
        task="Generate Vendor Foundation Requirement Document",
        inputs={
            "project_id": WHITE_OAK_PROJECT_ID,
            "geotechnical_report_id": geo_report.report_id,
            "foundation_research_report_id": fr_report.report_id,
            "confirmed_document_ids": [WHITE_OAK_SOIL_DOC_ID, WHITE_OAK_SITE_PLAN_2436_ID],
            "snapshot_id": "snap_test_runner",
        },
    )

    result = await runner.run("requirement_agent", req)
    assert result.status == "succeeded"
    out = result.output
    assert out["report_id"].startswith("req_")
    assert out["geotechnical_report_id"] == geo_report.report_id
    assert out["foundation_research_report_id"] == fr_report.report_id
    assert out["project_id"] == WHITE_OAK_PROJECT_ID
    assert out["review_status"] == "PENDING_REVIEW"
    assert out["is_preliminary_draft"] is True


def test_3_langgraph_10_node_execution(upstream_white_oak_reports):
    """3. Verify 10-node LangGraph execution produces all 12 structured sections."""
    geo_report, fr_report = upstream_white_oak_reports

    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    doc_service = DocumentService(repository=DocumentRepository(conn), storage=DocumentStorage())
    geo_repo = GeotechnicalAnalysisRepository(conn)
    fr_repo = FoundationResearchRepository(conn)
    req_repo = RequirementAgentRepository(conn)

    service = RequirementAgentService(
        repository=req_repo,
        geotechnical_repository=geo_repo,
        foundation_research_repository=fr_repo,
        document_service=doc_service,
    )

    doc = service.run_requirement_generation(
        project_id=WHITE_OAK_PROJECT_ID,
        geotechnical_report_id=geo_report.report_id,
        foundation_research_report_id=fr_report.report_id,
        confirmed_document_ids=[WHITE_OAK_SOIL_DOC_ID, WHITE_OAK_SITE_PLAN_2436_ID],
        snapshot_id="snap_white_oak_lg",
    )

    assert isinstance(doc, RequirementDocument)
    assert doc.section_1_project_overview.project_number == "25-0117"
    assert doc.section_2_geotechnical_conditions.pvr_value_inches == 1.20
    assert len(doc.section_3_foundation_systems) >= 5
    assert len(doc.section_4_vendor_scope_of_work) == 8
    assert len(doc.section_5_technical_requirements) >= 12
    assert len(doc.section_6_quality_and_documentation) >= 7
    assert len(doc.section_7_vendor_proposal_requirements) == 10
    assert len(doc.section_8_risks_and_precautions) >= 3
    assert len(doc.section_9_missing_information) >= 5
    assert len(doc.section_10_vendor_response_checklist) >= 7
    assert len(doc.section_11_references_and_evidence) >= 15
    assert doc.section_12_limitations_and_approval.is_preliminary_unapproved_draft is True
    assert doc.section_12_limitations_and_approval.suitable_for_construction_or_contractual_issuance is False
    assert "9. Supporting References and Review Status" in doc.markdown_content


def test_4_exact_upstream_report_id_retrieval_and_no_arbitrary_latest(upstream_white_oak_reports):
    """4. Verify Requirement Agent retrieves exact report IDs and blocks if IDs are missing or nonexistent."""
    geo_report, fr_report = upstream_white_oak_reports
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    service = RequirementAgentService(
        repository=RequirementAgentRepository(conn),
        geotechnical_repository=GeotechnicalAnalysisRepository(conn),
        foundation_research_repository=FoundationResearchRepository(conn),
        document_service=DocumentService(repository=DocumentRepository(conn), storage=DocumentStorage()),
    )

    # Missing geotechnical_report_id must fail (never pick arbitrary latest)
    with pytest.raises(ValueError, match="requires an explicit 'geotechnical_report_id'"):
        service.run_requirement_generation(
            project_id=WHITE_OAK_PROJECT_ID,
            geotechnical_report_id="",
            foundation_research_report_id=fr_report.report_id,
        )

    # Nonexistent report ID must fail
    with pytest.raises(ValueError, match="not found in database"):
        service.run_requirement_generation(
            project_id=WHITE_OAK_PROJECT_ID,
            geotechnical_report_id="geo_rep_nonexistent_999",
            foundation_research_report_id=fr_report.report_id,
        )


def test_5_cross_project_report_rejection(upstream_white_oak_reports):
    """5. Verify cross-project report mismatch is blocked."""
    geo_report, fr_report = upstream_white_oak_reports
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    service = RequirementAgentService(
        repository=RequirementAgentRepository(conn),
        geotechnical_repository=GeotechnicalAnalysisRepository(conn),
        foundation_research_repository=FoundationResearchRepository(conn),
        document_service=DocumentService(repository=DocumentRepository(conn), storage=DocumentStorage()),
    )

    with pytest.raises(ValueError, match="Cross-project report mismatch"):
        service.run_requirement_generation(
            project_id="proj_unrelated_parcel_xyz",
            geotechnical_report_id=geo_report.report_id,
            foundation_research_report_id=fr_report.report_id,
        )


def test_6_rejected_upstream_report_blocks_execution(upstream_white_oak_reports):
    """6. Verify that a REJECTED upstream report blocks Requirement Agent execution."""
    geo_report, fr_report = upstream_white_oak_reports
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    geo_repo = GeotechnicalAnalysisRepository(conn)
    fr_repo = FoundationResearchRepository(conn)
    req_repo = RequirementAgentRepository(conn)
    doc_service = DocumentService(repository=DocumentRepository(conn), storage=DocumentStorage())

    # Create a temporary copy of fr_report marked REJECTED
    rejected_fr = fr_report.model_copy(update={"report_id": "fnd_rep_rejected_test", "review_status": ReviewStatus.REJECTED})
    fr_repo.save_report(rejected_fr)

    service = RequirementAgentService(
        repository=req_repo,
        geotechnical_repository=geo_repo,
        foundation_research_repository=fr_repo,
        document_service=doc_service,
    )

    with pytest.raises(ValueError, match="has status 'REJECTED' and cannot be used"):
        service.run_requirement_generation(
            project_id=WHITE_OAK_PROJECT_ID,
            geotechnical_report_id=geo_report.report_id,
            foundation_research_report_id="fnd_rep_rejected_test",
        )


def test_7_requirement_provenance_and_separation(upstream_white_oak_reports):
    """7. Verify mandatory provenance classification and separation of consultant vs research items."""
    geo_report, fr_report = upstream_white_oak_reports
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    service = RequirementAgentService(
        repository=RequirementAgentRepository(conn),
        geotechnical_repository=GeotechnicalAnalysisRepository(conn),
        foundation_research_repository=FoundationResearchRepository(conn),
        document_service=DocumentService(repository=DocumentRepository(conn), storage=DocumentStorage()),
    )

    doc = service.run_requirement_generation(
        project_id=WHITE_OAK_PROJECT_ID,
        geotechnical_report_id=geo_report.report_id,
        foundation_research_report_id=fr_report.report_id,
        confirmed_document_ids=[WHITE_OAK_SOIL_DOC_ID, WHITE_OAK_SITE_PLAN_2436_ID],
    )

    # All 5 provenance classifications must be represented
    for src in RequirementSource:
        assert doc.provenance_summary.get(src.value, 0) >= 1, f"Missing provenance category {src.value}"

    # Verify external research systems in Section 3 are NOT marked consultant recommended
    ext_systems = [s for s in doc.section_3_foundation_systems if s.origin == "EXTERNAL_FOUNDATION_RESEARCH"]
    assert len(ext_systems) >= 1
    for ext_sys in ext_systems:
        assert ext_sys.is_consultant_recommended is False
        assert ext_sys.source_classification == RequirementSource.EXTERNAL_RESEARCH_REFERENCE
        assert "NOT APPROVED" in ext_sys.approval_status_note.upper()

    # Verify Section 6 distinguishes source-specified vs proposed vendor submittals
    source_subs = [s for s in doc.section_6_quality_and_documentation if s.is_source_specified]
    proposed_subs = [s for s in doc.section_6_quality_and_documentation if not s.is_source_specified]
    assert len(source_subs) >= 2
    assert len(proposed_subs) >= 4
    assert all(s.source_classification == RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT for s in source_subs)
    assert all(s.source_classification == RequirementSource.PROPOSED_VENDOR_SUBMITTAL for s in proposed_subs)


def test_8_exact_preservation_of_source_technical_values(upstream_white_oak_reports):
    """8. Verify exact numerical values, units, load cases, and FS from White Oak Soil Report 25-0117."""
    geo_report, fr_report = upstream_white_oak_reports
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    service = RequirementAgentService(
        repository=RequirementAgentRepository(conn),
        geotechnical_repository=GeotechnicalAnalysisRepository(conn),
        foundation_research_repository=FoundationResearchRepository(conn),
        document_service=DocumentService(repository=DocumentRepository(conn), storage=DocumentStorage()),
    )

    doc = service.run_requirement_generation(
        project_id=WHITE_OAK_PROJECT_ID,
        geotechnical_report_id=geo_report.report_id,
        foundation_research_report_id=fr_report.report_id,
    )

    reqs_by_id = {r.requirement_id: r for r in doc.section_5_technical_requirements}

    # Stripping: at least 6 inches extending at least 5 ft beyond building limits
    assert "at least 6" in (reqs_by_id["REQ-TECH-01"].numerical_value or "")
    assert "5 feet beyond the building limits" in reqs_by_id["REQ-TECH-01"].specification_text

    # Proofrolling: 15-ton roller
    assert "15" in (reqs_by_id["REQ-TECH-02"].numerical_value or "")
    assert "15-ton roller" in reqs_by_id["REQ-TECH-02"].specification_text

    # Select fill: LL max 35; PI 8 to 20
    assert "LL max 35; PI 8 to 20" in (reqs_by_id["REQ-TECH-03"].numerical_value or "")

    # Compaction: 95% of max. standard dry density (ASTM D 698), +/-2% of optimum, 8-in loose / 6-in compacted lifts
    assert "95%" in (reqs_by_id["REQ-TECH-04"].numerical_value or "")
    assert "+/-2%" in (reqs_by_id["REQ-TECH-04"].numerical_value or "")
    assert "8-in loose / 6-in compacted" in (reqs_by_id["REQ-TECH-04"].numerical_value or "")
    assert "ASTM D 698" in (reqs_by_id["REQ-TECH-04"].standard_reference or "")

    # Select fill pad thickness by system: PT slab 1.00 ft; piers' slab-on-grade floor 2.00 ft; continuous footings 2.00 ft
    assert "1.00 ft" in (reqs_by_id["REQ-TECH-05"].numerical_value or "")
    assert "2.00 ft" in (reqs_by_id["REQ-TECH-05"].numerical_value or "")

    # Post-Tensioned Slab: 2,100 psf (total load, FS 2.0) and 1,400 psf (DL + sustained LL, FS 3), grade beams >= 1.50 ft
    assert "2,100 psf (total load, FS 2.0)" in (reqs_by_id["REQ-TECH-06"].numerical_value or "")
    assert "1,400 psf (DL + sustained LL, FS 3)" in (reqs_by_id["REQ-TECH-06"].numerical_value or "")
    assert "grade beams >= 1.50 ft below finished grade" in (reqs_by_id["REQ-TECH-06"].numerical_value or "")
    assert "em = 8.8 ft (center lift) / 4.9 ft (edge lift)" in reqs_by_id["REQ-TECH-06"].specification_text
    assert "ym = 0.65 in (center lift) / 0.49 in (edge lift)" in reqs_by_id["REQ-TECH-06"].specification_text
    assert "3.45 pF" in reqs_by_id["REQ-TECH-06"].specification_text

    # Drilled Underreamed Piers founding depth & geometry: about 10.0 ft, max bell 5 ft, ratio 3, spacing >= 1.5x, shaft friction 300 psf below 5 ft
    assert "about 10.0 ft founding depth" in (reqs_by_id["REQ-TECH-07"].numerical_value or "")
    assert "max bell dia. 5 ft" in (reqs_by_id["REQ-TECH-07"].numerical_value or "")
    assert "max bell-to-shaft ratio 3" in (reqs_by_id["REQ-TECH-07"].numerical_value or "")
    assert "spacing >= 1.5 x avg. bell dia." in (reqs_by_id["REQ-TECH-07"].numerical_value or "")
    assert "shaft friction 300 psf below 5 ft" in (reqs_by_id["REQ-TECH-07"].numerical_value or "")

    # Drilled Underreamed Piers bearing pressures: 2,000 psf (DL + sustained LL, FS 3) and 3,000 psf (total load, FS 2)
    assert "2,000 psf (DL + sustained LL, FS 3)" in (reqs_by_id["REQ-TECH-08"].numerical_value or "")
    assert "3,000 psf (total load, FS 2)" in (reqs_by_id["REQ-TECH-08"].numerical_value or "")
    assert reqs_by_id["REQ-TECH-08"].units == "psf"
    assert reqs_by_id["REQ-TECH-08"].factor_of_safety == "3 (DL + sustained LL) / 2 (total load)"

    # Continuous Footings / Grade Beams: 1,800 psf (DL + sustained LL, FS 3), 2,700 psf (total load, FS 2), minimum embedment 2.50 ft
    assert "1,800 psf (DL + sustained LL, FS 3)" in (reqs_by_id["REQ-TECH-10"].numerical_value or "")
    assert "2,700 psf (total load, FS 2)" in (reqs_by_id["REQ-TECH-10"].numerical_value or "")
    assert "minimum embedment 2.50 ft" in (reqs_by_id["REQ-TECH-10"].numerical_value or "")
    assert "exceed 1 inch" in reqs_by_id["REQ-TECH-10"].specification_text

    # Slab-on-Grade Floor (separate from structural foundation): 600 psf on >= 2.00 ft select fill
    assert reqs_by_id["REQ-TECH-12"].numerical_value == "600"
    assert "2.00 ft" in reqs_by_id["REQ-TECH-12"].specification_text

    # Groundwater: 15.4 ft (B-1) and 14.5 ft (B-2) during drilling; 14.8 ft and 14.0 ft after 15 minutes
    assert "15.4 ft" in reqs_by_id["REQ-TECH-13"].specification_text
    assert "14.5 ft" in reqs_by_id["REQ-TECH-13"].specification_text
    assert "14.8 ft" in reqs_by_id["REQ-TECH-13"].specification_text
    assert "14.0 ft" in reqs_by_id["REQ-TECH-13"].specification_text

    # Concrete placement: 4 to 6-inch slump, <= 1 inch water for free-drop
    assert reqs_by_id["REQ-TECH-14"].numerical_value == "4 to 6"
    assert "1 inch or less of water" in reqs_by_id["REQ-TECH-14"].specification_text

    # Surface drainage: minimum 6 inches slope in the first 10 feet
    assert reqs_by_id["REQ-TECH-15"].numerical_value == "minimum 6 inches slope in the first 10 feet"
    assert "minimum slope of 6 inches in the first 10 feet" in reqs_by_id["REQ-TECH-15"].specification_text


def test_9_missing_information_across_all_5_roles(upstream_white_oak_reports):
    """9. Verify Section 9 covers Geotechnical, Structural, Civil, Architect, and Project Owner roles."""
    geo_report, fr_report = upstream_white_oak_reports
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    service = RequirementAgentService(
        repository=RequirementAgentRepository(conn),
        geotechnical_repository=GeotechnicalAnalysisRepository(conn),
        foundation_research_repository=FoundationResearchRepository(conn),
    )

    doc = service.run_requirement_generation(
        project_id=WHITE_OAK_PROJECT_ID,
        geotechnical_report_id=geo_report.report_id,
        foundation_research_report_id=fr_report.report_id,
    )

    roles_found = {g.required_from_role for g in doc.section_9_missing_information}
    assert roles_found == {
        "GEOTECHNICAL_ENGINEER",
        "STRUCTURAL_ENGINEER",
        "CIVIL_ENGINEER",
        "ARCHITECT",
        "PROJECT_OWNER",
    }
    assert any(g.blocks_final_vendor_specification is True for g in doc.section_9_missing_information)
    assert any(g.blocks_final_vendor_specification is False for g in doc.section_9_missing_information)


def test_10_and_11_persistence_history_and_human_review(upstream_white_oak_reports):
    """10 & 11. Verify SQLite persistence, project history, and human review audit trail."""
    geo_report, fr_report = upstream_white_oak_reports
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    req_repo = RequirementAgentRepository(conn)
    service = RequirementAgentService(
        repository=req_repo,
        geotechnical_repository=GeotechnicalAnalysisRepository(conn),
        foundation_research_repository=FoundationResearchRepository(conn),
    )

    doc = service.run_requirement_generation(
        project_id=WHITE_OAK_PROJECT_ID,
        geotechnical_report_id=geo_report.report_id,
        foundation_research_report_id=fr_report.report_id,
    )

    # Retrieve by ID
    loaded = service.get_report(doc.report_id)
    assert loaded is not None
    assert loaded.report_id == doc.report_id
    assert loaded.review_status == RequirementReviewStatus.PENDING_REVIEW

    # Retrieve history
    history = service.list_reports_for_project(WHITE_OAK_PROJECT_ID)
    assert len(history) >= 1
    assert any(h.report_id == doc.report_id for h in history)

    # Submit human review (and then restore PENDING_REVIEW so the stored project draft remains unapproved)
    reviewed = service.submit_review(
        report_id=doc.report_id,
        decision="APPROVED",
        reviewer_id="Dr. Jane Smith, P.E.",
        comments="Verified select fill and pier bearing specifications against Report 25-0117.",
    )
    assert reviewed.review_status == RequirementReviewStatus.APPROVED
    assert reviewed.reviewed_by == "Dr. Jane Smith, P.E."
    assert len(reviewed.review_history) == 1
    assert reviewed.review_history[0].decision == RequirementReviewStatus.APPROVED

    # Restore to PENDING_REVIEW so the Vendor Requirement Document remains an unapproved preliminary draft
    restored = doc.model_copy(update={"review_status": RequirementReviewStatus.PENDING_REVIEW, "is_preliminary_draft": True, "suitable_for_contractual_issuance": False})
    req_repo.save_report(restored)


@pytest.mark.asyncio
async def test_12_and_13_workflow_integration_and_retry(upstream_white_oak_reports):
    """12 & 13. Verify 4-stage workflow passes exact report IDs and supports retry behaviour."""
    reg = AgentRegistry()
    AgentLoader(reg, MANIFESTS_DIR).load_all()
    raw = yaml.safe_load(WORKFLOW_YAML_PATH.read_text(encoding="utf-8"))
    wf_def = WorkflowDefinition.model_validate(raw)

    builder = WorkflowBuilder(reg)
    compiled = builder.build(wf_def)

    run_id = "test_4stage_workflow_run"
    result = await compiled.ainvoke(
        {
            "run_id": run_id,
            "workflow_id": wf_def.id,
            "workflow_version": wf_def.version,
            "workflow_input": {
                "project_id": WHITE_OAK_PROJECT_ID,
                "confirmed_document_ids": [WHITE_OAK_SOIL_DOC_ID, WHITE_OAK_SITE_PLAN_2436_ID],
            },
            "node_outputs": {},
            "agent_outputs": {},
        },
        {"configurable": {"thread_id": run_id}},
    )

    node_outputs = result["node_outputs"]
    geo_id = node_outputs["geotechnical_analysis_node"]["report_id"]
    fr_id = node_outputs["foundation_research_node"]["report_id"]
    snap_id = node_outputs["validate_project_documents_node"]["snapshot_id"]

    req_out = node_outputs["requirement_agent_node"]
    assert req_out["status"] == "succeeded"
    assert req_out["geotechnical_report_id"] == geo_id
    assert req_out["foundation_research_report_id"] == fr_id
    assert req_out["snapshot_id"] == snap_id

    # Verify standalone retry of Requirement Agent using existing upstream report IDs without re-running Agent 1 or Agent 2
    runner = AgentRunner(reg)
    retry_res = await runner.run(
        "requirement_agent",
        AgentRequest(
            task="retry requirement_agent",
            inputs={
                "project_id": WHITE_OAK_PROJECT_ID,
                "geotechnical_report_id": geo_id,
                "foundation_research_report_id": fr_id,
                "confirmed_document_ids": [WHITE_OAK_SOIL_DOC_ID, WHITE_OAK_SITE_PLAN_2436_ID],
                "snapshot_id": snap_id,
            },
            run_id="test_req_agent_retry_only",
            workflow_id=wf_def.id,
            node_id="requirement_agent_node",
        ),
    )
    assert retry_res.status == "succeeded"
    assert retry_res.output["geotechnical_report_id"] == geo_id
    assert retry_res.output["foundation_research_report_id"] == fr_id


def test_14_fastapi_routes_and_geostrata_portal_retrieval(upstream_white_oak_reports):
    """14. Verify FastAPI /v1/requirements endpoints used by GeoStrata Portal."""
    geo_report, fr_report = upstream_white_oak_reports
    app = create_app(manifests_dir=MANIFESTS_DIR)
    client = TestClient(app)

    # POST /v1/requirements/run
    run_resp = client.post(
        "/v1/requirements/run",
        json={
            "project_id": WHITE_OAK_PROJECT_ID,
            "geotechnical_report_id": geo_report.report_id,
            "foundation_research_report_id": fr_report.report_id,
            "confirmed_document_ids": [WHITE_OAK_SOIL_DOC_ID, WHITE_OAK_SITE_PLAN_2436_ID],
            "snapshot_id": "snap_api_test",
        },
    )
    assert run_resp.status_code == 200, run_resp.text
    created_doc = run_resp.json()
    req_report_id = created_doc["report_id"]
    assert req_report_id.startswith("req_")
    assert created_doc["geotechnical_report_id"] == geo_report.report_id
    assert created_doc["foundation_research_report_id"] == fr_report.report_id

    # GET /v1/requirements/reports/{report_id}
    get_resp = client.get(f"/v1/requirements/reports/{req_report_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["report_id"] == req_report_id

    # GET /v1/requirements/projects/{project_id}/latest
    latest_resp = client.get(f"/v1/requirements/projects/{WHITE_OAK_PROJECT_ID}/latest")
    assert latest_resp.status_code == 200
    assert latest_resp.json()["report_id"] == req_report_id

    # GET /v1/requirements/projects/{project_id}/history
    hist_resp = client.get(f"/v1/requirements/projects/{WHITE_OAK_PROJECT_ID}/history")
    assert hist_resp.status_code == 200
    assert len(hist_resp.json()) >= 1

    # POST /v1/requirements/reports/{report_id}/review (test REVISION_REQUESTED so report is never marked APPROVED)
    rev_resp = client.post(
        f"/v1/requirements/reports/{req_report_id}/review",
        json={
            "decision": "PENDING_REVIEW",
            "reviewer_id": "Lead Geotechnical Engineer, P.E.",
            "comments": "Preliminary draft remains pending full P.E. review.",
        },
    )
    assert rev_resp.status_code == 200
    assert rev_resp.json()["review_status"] == "PENDING_REVIEW"


def test_15_regression_unsupported_requirements_and_conditional_casing(upstream_white_oak_reports):
    """15. Regression test verifying removal of unsupported requirements, carton void form provenance,
    conditional casing preservation, and provenance guard against fabricated bearing values."""
    from geostrata.backend.agents.requirement_agent.graph import validate_requirement_provenance

    geo_report, fr_report = upstream_white_oak_reports
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    service = RequirementAgentService(
        repository=RequirementAgentRepository(conn),
        geotechnical_repository=GeotechnicalAnalysisRepository(conn),
        foundation_research_repository=FoundationResearchRepository(conn),
        document_service=DocumentService(repository=DocumentRepository(conn), storage=DocumentStorage()),
    )

    doc = service.run_requirement_generation(
        project_id=WHITE_OAK_PROJECT_ID,
        geotechnical_report_id=geo_report.report_id,
        foundation_research_report_id=fr_report.report_id,
    )

    reqs_by_id = {r.requirement_id: r for r in doc.section_5_technical_requirements}

    # 1. Carton void forms (REQ-TECH-16) must NOT be classified as GEOTECHNICAL_SOURCE_REQUIREMENT
    void_req = reqs_by_id["REQ-TECH-16"]
    assert void_req.source_classification == RequirementSource.ENGINEER_CONFIRMATION_REQUIRED
    assert void_req.numerical_value is None
    assert "The geotechnical report does not require them" in void_req.specification_text
    assert "may be formed directly on the subgrade soils" in void_req.specification_text

    # 2. Conditional casing (REQ-TECH-09) must preserve conditional nature
    casing_req = reqs_by_id["REQ-TECH-09"]
    assert "CONDITIONAL" in casing_req.specification_text
    assert "only for cases where excavations cave so rapidly" in casing_req.specification_text
    assert "not an unconditional requirement" in casing_req.specification_text

    # 3. Ensure previously fabricated values are completely absent from the generated document
    full_blob = doc.markdown_content.lower()
    for forbidden in ("3,600 psf", "5,400 psf", "1,600 psf", "2,400 psf", "6-inch carton"):
        assert forbidden not in full_blob, f"Forbidden fabricated value '{forbidden}' found in RequirementDocument!"

    # 4. Document must remain a preliminary draft pending engineering review
    assert doc.review_status == RequirementReviewStatus.PENDING_REVIEW
    assert doc.is_preliminary_draft is True
    assert doc.suitable_for_contractual_issuance is False
    assert doc.section_12_limitations_and_approval.is_preliminary_unapproved_draft is True
    assert doc.section_12_limitations_and_approval.suitable_for_construction_or_contractual_issuance is False

    # 5. Provenance guard must reject fabricated geotechnical source requirements
    bad_state = {
        "geotechnical_report": geo_report.model_dump(),
        "foundation_research_report": fr_report.model_dump(),
        "section_3_foundation_systems": [],
        "section_4_vendor_scope_of_work": [],
        "section_5_technical_requirements": [
            {
                "requirement_id": "REQ-BAD-01",
                "title": "Fabricated Pier Bearing",
                "specification_text": "Drilled piers 3,600 psf DL+LL",
                "numerical_value": "3,600 psf",
                "source_classification": RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT.value,
                "supporting_report_id": geo_report.report_id,
                "pdf_page_reference": "PDF Page 10",
                "evidence_ids": [],
            }
        ],
        "section_6_quality_and_documentation": [],
        "section_7_vendor_proposal_requirements": [],
        "section_8_risks_and_precautions": [],
        "section_9_missing_information": [],
        "section_10_vendor_response_checklist": [],
    }
    with pytest.raises(ValueError, match="Provenance violation"):
        validate_requirement_provenance(bad_state)
