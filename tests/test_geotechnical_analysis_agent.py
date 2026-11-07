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
from geostrata.backend.agents.geotechnical_analysis import (
    GeotechnicalAnalysisReport,
    GeotechnicalAnalysisRepository,
    GeotechnicalAnalysisService,
    build_geotechnical_analysis_graph,
)
from app.registry import AgentLoader, AgentRegistry
from app.runtime.runner import AgentRunner
from app.sdk.contracts import AgentRequest

REAL_SOIL_REPORT_PATH = Path("storage/documents/7d500784-af45-4a86-a437-e90c3f7b54f2/original.pdf")


@pytest.fixture
def test_setup(tmp_path):
    db_file = tmp_path / "test_geotech.db"
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    doc_repo = DocumentRepository(conn)
    doc_storage = DocumentStorage(root_dir=tmp_path / "storage")
    extractor = PDFExtractor()
    doc_service = DocumentService(repository=doc_repo, storage=doc_storage, extractor=extractor)

    geo_repo = GeotechnicalAnalysisRepository(conn)
    geo_service = GeotechnicalAnalysisService(repository=geo_repo, document_service=doc_service)

    return {
        "conn": conn,
        "doc_service": doc_service,
        "geo_service": geo_service,
        "geo_repo": geo_repo,
        "tmp_path": tmp_path,
    }


def test_agent_registration():
    """Verify that Geotechnical Analysis Agent is registered and loaded via manifest."""
    registry = AgentRegistry()
    manifests_dir = Path("geostrata/plugins/manifests")
    loader = AgentLoader(registry, manifests_dir)
    loaded = loader.load_all()

    agent_ids = {a.id for a in loaded}
    assert "geotechnical_analysis" in agent_ids

    agent = registry.get("geotechnical_analysis")
    assert agent.metadata.name == "Geotechnical Analysis Agent"
    assert agent.metadata.adapter_type == "python_callable"
    assert agent.metadata.enabled is True
    assert "document_id" in agent.metadata.input_schema.get("properties", {})


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
@pytest.mark.asyncio
async def test_agent_runner_direct_invocation(test_setup):
    """Verify execution of geotechnical_analysis through the platform AgentRunner."""
    registry = AgentRegistry()
    loader = AgentLoader(registry, Path("geostrata/plugins/manifests"))
    loader.load_all()

    runner = AgentRunner(registry)
    req = AgentRequest(
        task="Synthesize geotechnical engineering report and analyze foundation recommendations",
        inputs={
            "document_id": "7d500784-af45-4a86-a437-e90c3f7b54f2",
            "project_id": "default",
        },
        run_id="run_runner_test_01",
    )
    result = await runner.run("geotechnical_analysis", req)
    assert result.status == "succeeded"
    assert "report_id" in result.output
    assert result.output["report_id"].startswith("geo_rep_")
    assert result.output["review_status"] == "PENDING_REVIEW"


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_geotechnical_analysis_graph_execution(test_setup):
    """Execute LangGraph pipeline on real Soil report 25-0117 v1.pdf and verify all 14 sections."""
    doc_service = test_setup["doc_service"]
    geo_service = test_setup["geo_service"]

    # 1. Ingest document
    pdf_bytes = REAL_SOIL_REPORT_PATH.read_bytes()
    meta = doc_service.upload_document(
        filename="Soil report 25-0117 v1.pdf",
        content=pdf_bytes,
        project_id="test_project",
    )
    assert meta.document_id is not None

    # 2. Run Analysis
    report = geo_service.run_analysis(
        document_id=meta.document_id,
        project_id="test_project",
        run_id="run_test_001",
    )

    assert isinstance(report, GeotechnicalAnalysisReport)
    assert report.report_id.startswith("geo_rep_")
    assert report.review_status == "PENDING_REVIEW"
    assert report.document_id == meta.document_id

    # 3. Section 1: Executive Summary
    assert "SANDY LEAN CLAY (CL)" in report.executive_summary.dominant_soil_classification
    assert len(report.executive_summary.primary_foundation_options) == 4
    assert report.executive_summary.professional_review_required is True

    # 4. Section 2: Project Context
    assert report.project_context.project_name == "Proposed 2 Residences"
    assert "25-0117" in (report.project_context.project_number or "")
    assert "2434 White Oak Drive" in (report.project_context.site_location or "")
    assert report.project_context.legal_description == "Lots 1 & 2, Block 1, White Oak Terrace"
    assert report.project_context.client_name == "Novel Signature Homes"
    assert report.project_context.geotechnical_consultant == "AmeriKor Consultants, Inc."
    assert "February 20, 2025" in (report.project_context.report_date or "")
    assert report.project_context.cross_document_status == "NOT_ASSESSED"

    # 5. Section 3 & 4: Subsurface Stratigraphy & Boring Logs
    assert report.investigation_summary.total_borings == 2
    assert "B-1" in report.investigation_summary.boring_identifiers
    assert "B-2" in report.investigation_summary.boring_identifiers
    assert report.subsurface_conditions.uscs_group_symbol == "CL"
    assert len(report.subsurface_conditions.strata) >= 2

    # Verify B-1 depth observations
    b1_stratum = [s for s in report.subsurface_conditions.strata if s.boring_id == "B-1"][0]
    assert any("4" in obs for obs in b1_stratum.observations)
    assert any("Calcareous nodules" in obs for obs in b1_stratum.observations)

    # 6. Section 5: Laboratory Interpretation & PVR
    assert "17" in report.laboratory_interpretation.plasticity_index_range and "24" in report.laboratory_interpretation.plasticity_index_range
    assert "32" in report.laboratory_interpretation.liquid_limit_range and "42" in report.laboratory_interpretation.liquid_limit_range
    assert "15.0" in report.laboratory_interpretation.moisture_content_range and "23.9" in report.laboratory_interpretation.moisture_content_range
    assert "54.8" in report.laboratory_interpretation.percent_passing_no_200_range and "68.6" in report.laboratory_interpretation.percent_passing_no_200_range
    assert report.laboratory_interpretation.pvr_value_inches == 1.20
    assert report.laboratory_interpretation.shrink_swell_potential == "MODERATE"
    assert report.laboratory_interpretation.spt_blow_counts_reported is False
    assert "NOT_REPORTED" in report.laboratory_interpretation.spt_status

    # 7. Section 6: Groundwater Assessment
    assert report.groundwater_assessment.encountered is True
    assert len(report.groundwater_assessment.measurements) == 2
    gw_b1 = [m for m in report.groundwater_assessment.measurements if m.boring_id == "B-1"][0]
    assert gw_b1.drilling_depth_ft == 15.4
    assert gw_b1.post_drilling_depth_ft == 14.8

    # 8. Section 7 & 8: Foundation Recommendations & Separation
    fs = report.foundation_systems
    assert fs.post_tensioned_slabs.is_foundation_system is True
    assert fs.drilled_underreamed_piers.is_foundation_system is True
    assert fs.continuous_footings_grade_beams.is_foundation_system is True
    assert fs.slab_on_grade_floor.is_foundation_system is False  # Distinct floor slab!

    # Post-Tensioned Slabs verification
    pt = fs.post_tensioned_slabs
    pt_bearings = {p["load_case"]: p["pressure_psf"] for p in pt.allowable_bearing_pressures}
    assert pt_bearings["Total Load"] == 2100.0
    assert pt_bearings["Dead Load + Sustained Live Load"] == 1400.0

    # Drilled Underreamed Piers verification
    pier = fs.drilled_underreamed_piers
    pier_bearings = {p["load_case"]: p["pressure_psf"] for p in pier.allowable_bearing_pressures if "load_case" in p}
    assert pier_bearings["Total Dead + Transient Live Load"] == 3000.0
    assert pier_bearings["Dead Load + Sustained Live Load"] == 2000.0
    assert pier.embedment_depth_ft == 10.0
    assert any("caving" in c.lower() for c in pier.construction_considerations)

    # Continuous Footings verification
    foot = fs.continuous_footings_grade_beams
    foot_bearings = {p["load_case"]: p["pressure_psf"] for p in foot.allowable_bearing_pressures}
    assert foot_bearings["Total Dead + Transient Live Load"] == 2700.0
    assert foot_bearings["Dead Load + Sustained Live Load"] == 1800.0
    assert foot.embedment_depth_ft == 2.5
    assert len(foot.evidence_ids) >= 4
    assert any("exceed 1 inch" in w for w in foot.risks_and_limitations)
    # Ensure no fabricated settlement numbers
    assert not any("0.5 to 0.75" in w for w in foot.risks_and_limitations)

    # Slab-on-Grade Floor verification (600 psf on 2 ft select fill)
    slab = fs.slab_on_grade_floor
    assert slab.allowable_bearing_pressures[0]["pressure_psf"] == 600.0
    assert "2.00 ft" in slab.recommended_preparation or "2.0 ft" in slab.recommended_preparation
    assert len(slab.evidence_ids) >= 2
    # Ensure no invented restrictions
    assert "pedestrian-only" not in slab.applicable_structures.lower()
    assert "strictly isolated" not in slab.prerequisites_and_conditions[0].lower()

    # 9. Section 9: Site Preparation (all 12 specifications)
    assert len(report.site_preparation.specifications) == 12
    assert "ASTM D 698" in report.site_preparation.compaction_standard
    assert "15-ton" in report.site_preparation.proofrolling_requirement

    # 10. Section 10: Risks & Concerns
    assert len(report.risks_and_concerns.identified_risks) >= 4
    risk_titles = [r.title for r in report.risks_and_concerns.identified_risks]
    assert any("Caving" in t for t in risk_titles)
    assert any("Shrink-Swell" in t or "Expansive" in t for t in risk_titles)
    caving_risk = [r for r in report.risks_and_concerns.identified_risks if "Caving" in r.title][0]
    assert "calcareous nodules" in caving_risk.description.lower()
    assert "sandy lenses" not in caving_risk.description.lower()
    assert "intersecting the groundwater" not in caving_risk.description.lower()

    # Exact source accuracy checks for RISK-01 and RISK-03
    risk_01 = [r for r in report.risks_and_concerns.identified_risks if r.risk_id == "RISK-01"][0]
    assert "6 inches in the first 10 feet" in risk_01.mitigation_in_report
    assert "Section 5.2" in risk_01.mitigation_in_report
    assert "5% slope" not in risk_01.mitigation_in_report

    risk_03 = [r for r in report.risks_and_concerns.identified_risks if r.risk_id == "RISK-03"][0]
    assert "drying or stabilizing agents" in risk_03.mitigation_in_report
    assert "discing" in risk_03.mitigation_in_report
    assert "[EXTERNAL ENGINEERING CONSIDERATION" in risk_03.mitigation_in_report

    # 11. Section 11: Missing Information
    assert len(report.missing_information.items) >= 4
    missing_titles = [m.title for m in report.missing_information.items]
    assert any("Column" in t or "Load" in t for t in missing_titles)
    assert any("Drainage" in t or "Grading" in t for t in missing_titles)

    drainage_item = [m for m in report.missing_information.items if m.item_id == "MISSING-04"][0]
    assert "6 inches in the first 10 feet" in drainage_item.impact_on_design
    assert "Section 5.2" in drainage_item.impact_on_design

    # 12. Questions for Engineers & External Consideration Labeling
    questions = report.questions_for_engineers.questions
    assert len(questions) >= 4

    civil_q = [q for q in questions if "Civil" in q.target_discipline][0]
    assert "6 inches in the first 10 feet" in civil_q.question
    assert "Section 5.2" in civil_q.referenced_section_or_risk
    assert "[EXTERNAL ENGINEERING CONSIDERATION" in civil_q.engineering_rationale

    void_q = [q for q in questions if "carton-form" in q.question.lower() or "void box" in q.question.lower()][0]
    assert "[EXTERNAL ENGINEERING CONSIDERATION" in void_q.engineering_rationale

    # 13. Section 13: Evidence Verification
    assert report.evidence_references.total_citations > 0
    assert report.evidence_references.unresolved_citations_count == 0


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_human_review_and_approval_persistence(test_setup):
    """Verify human reviewer approval, changes requested, rejection, and audit log persistence."""
    doc_service = test_setup["doc_service"]
    geo_service = test_setup["geo_service"]

    # Ingest & run
    pdf_bytes = REAL_SOIL_REPORT_PATH.read_bytes()
    meta = doc_service.upload_document(filename="Soil report 25-0117 v1.pdf", content=pdf_bytes)
    report = geo_service.run_analysis(document_id=meta.document_id)

    # Automated extractions must never be auto-approved
    assert report.review_status == "PENDING_REVIEW"

    # Action 1: Submit Changes Requested
    r1 = geo_service.submit_review(
        report_id=report.report_id,
        decision="CHANGES_REQUESTED",
        reviewer_id="PE_Structural_Lead",
        comments="Please verify edge lift distance em for center-lift scenario.",
    )
    assert r1.review_status == "CHANGES_REQUESTED"
    assert len(r1.review_history) == 1
    assert r1.review_history[0].reviewer_id == "PE_Structural_Lead"

    # Action 2: Submit Human Verification & Stamp
    r2 = geo_service.submit_review(
        report_id=report.report_id,
        decision="HUMAN_VERIFIED",
        reviewer_id="PE_Geotech_Principal",
        comments="Parameters verified against geotechnical report. Post-tensioned slab approved.",
    )
    assert r2.review_status == "HUMAN_VERIFIED"
    assert len(r2.review_history) == 2

    # Verify database reload preserves review history
    reloaded = geo_service.get_report(report.report_id)
    assert reloaded is not None
    assert reloaded.review_status == "HUMAN_VERIFIED"
    assert len(reloaded.review_history) == 2


def test_handling_of_missing_evidence_or_invalid_ids():
    """Verify validate_evidence_references filters out fabricated or missing evidence IDs."""
    from geostrata.backend.agents.geotechnical_analysis.graph import validate_evidence_references

    dummy_state = {
        "evidence_lookup": {
            "ev_valid_01": {"evidence_id": "ev_valid_01", "original_value": "2100 psf", "page_index": 7, "printed_page_number": "4"},
        },
        "investigation_summary": {"evidence_ids": ["ev_valid_01", "ev_fake_nonexistent_99"]},
        "subsurface_conditions": {"evidence_ids": []},
        "laboratory_interpretation": {"evidence_ids": []},
        "groundwater_assessment": {"evidence_ids": []},
        "risks_and_concerns": {"evidence_ids": []},
        "foundation_systems": {},
        "site_preparation": {"specifications": []},
    }

    result = validate_evidence_references(dummy_state)
    assert len(result["evidence_citations"]) == 1
    assert result["evidence_citations"][0]["evidence_id"] == "ev_valid_01"
    assert result["unresolved_citations_count"] == 1


def test_conflicting_documents_handling():
    """Verify validate_document_context flags discrepancy when document titles or revisions conflict."""
    from geostrata.backend.agents.geotechnical_analysis.graph import validate_document_context

    conflicting_state = {
        "document_metadata": {
            "filename": "Soil report 25-0117 v1.pdf",
            "project_info": {
                "project_name": "Highway Overpass Phase 2 v2 Draft",
                "project_number": "25-0117",
            },
        }
    }

    result = validate_document_context(conflicting_state)
    ctx = result["project_context"]
    assert ctx["has_discrepancies"] is True
    assert len(ctx["discrepancies"]) >= 1
    assert "Revision Version" in ctx["discrepancies"][0]["field_name"]


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_fastapi_geotechnical_analysis_endpoints(test_setup):
    """Verify REST API routes for executing analysis and submitting human reviews."""
    doc_service = test_setup["doc_service"]
    geo_service = test_setup["geo_service"]

    # Ingest document
    pdf_bytes = REAL_SOIL_REPORT_PATH.read_bytes()
    meta = doc_service.upload_document(filename="Soil report 25-0117 v1.pdf", content=pdf_bytes)

    app = create_app()
    app.state.document_service = doc_service
    app.state.geotechnical_analysis_service = geo_service
    client = TestClient(app)

    # 1. Trigger analysis via POST /v1/geotechnical-analysis/runs
    run_resp = client.post(
        "/v1/geotechnical-analysis/runs",
        json={"document_id": meta.document_id, "project_id": "test_api"},
    )
    assert run_resp.status_code == 200
    report_data = run_resp.json()
    rep_id = report_data["report_id"]
    assert rep_id.startswith("geo_rep_")
    assert report_data["review_status"] == "PENDING_REVIEW"

    # 2. Retrieve report via GET /v1/geotechnical-analysis/reports/{report_id}
    get_resp = client.get(f"/v1/geotechnical-analysis/reports/{rep_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["report_id"] == rep_id

    # 3. Retrieve latest report via GET /v1/geotechnical-analysis/documents/{document_id}/latest
    latest_resp = client.get(f"/v1/geotechnical-analysis/documents/{meta.document_id}/latest")
    assert latest_resp.status_code == 200
    assert latest_resp.json()["report_id"] == rep_id

    # 4. Submit human review via POST /v1/geotechnical-analysis/reports/{report_id}/review
    rev_resp = client.post(
        f"/v1/geotechnical-analysis/reports/{rep_id}/review",
        json={
            "decision": "HUMAN_VERIFIED",
            "reviewer_id": "Licensed_PE_Jane",
            "comments": "Reviewed and approved foundation systems.",
        },
    )
    assert rev_resp.status_code == 200
    assert rev_resp.json()["review_status"] == "HUMAN_VERIFIED"
    assert len(rev_resp.json()["review_history"]) == 1


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_source_accuracy_audit_mitigations_and_external_considerations(test_setup):
    """Regression test ensuring mitigations, drainage slope, pumping remediation, and void forms strictly match source accuracy."""
    doc_service = test_setup["doc_service"]
    geo_service = test_setup["geo_service"]

    pdf_bytes = REAL_SOIL_REPORT_PATH.read_bytes()
    meta = doc_service.upload_document(filename="Soil report 25-0117 v1.pdf", content=pdf_bytes)
    report = geo_service.run_analysis(document_id=meta.document_id)

    # 1. Drainage specification in RISK-01 must say "6 inches in the first 10 feet" and Section 5.2
    risk_01 = next(r for r in report.risks_and_concerns.identified_risks if r.risk_id == "RISK-01")
    assert "6 inches in the first 10 feet" in risk_01.mitigation_in_report
    assert "Section 5.2" in risk_01.mitigation_in_report
    assert "5% slope" not in risk_01.mitigation_in_report

    # 2. Subgrade pumping in RISK-03 must cite drying/stabilizing agents, select fill replacement, discing, and isolate lime/undercut as external
    risk_03 = next(r for r in report.risks_and_concerns.identified_risks if r.risk_id == "RISK-03")
    assert "drying or stabilizing agents" in risk_03.mitigation_in_report
    assert "discing" in risk_03.mitigation_in_report
    assert "[EXTERNAL ENGINEERING CONSIDERATION - Not specified in geotechnical report]" in risk_03.mitigation_in_report
    # Ensure consultant requirement does NOT claim lime or undercut are mandated by the report
    assert "Mandatory" not in risk_03.mitigation_in_report.split("[EXTERNAL")[0] or "lime" not in risk_03.mitigation_in_report.split("[EXTERNAL")[0]

    # 3. Missing info MISSING-04 must cite Section 5.2 and 6 inches in the first 10 feet
    missing_04 = next(m for m in report.missing_information.items if m.item_id == "MISSING-04")
    assert "6 inches in the first 10 feet" in missing_04.impact_on_design
    assert "Section 5.2" in missing_04.impact_on_design

    # 4. Civil engineer question must cite Section 5.2 and 6 inches in 10 feet, labeling 5% slope and 5 ft extension as external
    civil_q = next(q for q in report.questions_for_engineers.questions if "Civil" in q.target_discipline)
    assert "6 inches in the first 10 feet" in civil_q.question
    assert "Section 5.2" in civil_q.referenced_section_or_risk
    assert "[EXTERNAL ENGINEERING CONSIDERATION - Not specified in geotechnical report]" in civil_q.engineering_rationale

    # 5. Structural engineer void box question must clearly label void box as external consideration
    void_q = next(q for q in report.questions_for_engineers.questions if "carton-form" in q.question or "void box" in q.question)
    assert "[EXTERNAL ENGINEERING CONSIDERATION - Not specified in geotechnical report]" in void_q.engineering_rationale

    # 6. Check markdown content reflects these accurate texts
    md = report.markdown_content
    assert "6 inches in the first 10 feet" in md
    assert "[EXTERNAL ENGINEERING CONSIDERATION" in md

