import os
import sys
import sqlite3
import pytest
from starlette.testclient import TestClient

from geostrata.backend.documents.models import ProjectInfo
from geostrata.backend.documents.matching_models import (
    DocumentProjectAssociation,
    MatchStatus,
    ProjectProfile,
    UserDecision,
    DecisionRequest,
)
from geostrata.backend.documents.project_matcher import ProjectMatcher
from geostrata.backend.documents.repository import DocumentRepository
from geostrata.backend.documents.service import DocumentService
from geostrata.backend.agents.geotechnical_analysis.graph import build_geotechnical_analysis_graph
from app.storage.repository import ExecutionRepository
from geostrata_app import create_app


@pytest.fixture
def target_project() -> ProjectProfile:
    return ProjectProfile(
        project_id="proj_white_oak",
        project_name="Proposed 2 Residences",
        project_number="25-0117",
        site_address="2434 White Oak Drive, Houston, Texas 77009",
        legal_description="Lots 1 & 2, Block 1, White Oak Terrace",
        subdivision="White Oak Terrace",
        lot_number="1 & 2",
        block_number="1",
        client_name="Novel Signature Homes",
    )


def test_project_matcher_three_document_scenarios(target_project: ProjectProfile):
    matcher = ProjectMatcher()

    # Scenario 1: Exact match with Soil Report
    soil_info = ProjectInfo(
        project_name="Proposed 2 Residences",
        project_number="25-0117",
        site_location="2434 White Oak Drive, Houston, Texas 77009",
        legal_description="Lots 1 & 2, Block 1, White Oak Terrace",
        subdivision="White Oak Terrace",
        lot="1 & 2",
        block="1",
        client_name="Novel Signature Homes",
    )
    soil_assoc = matcher.match_document(target_project, "doc_soil", "Soil report 25-0117 v1.pdf", soil_info)
    assert soil_assoc.match_status == MatchStatus.MATCHED
    assert soil_assoc.confidence_score >= 0.90
    assert len(soil_assoc.conflict_reasons) == 0
    assert any("Project number matches" in r for r in soil_assoc.match_reasons)

    # Scenario 2: 2436 White Oak Site Plan (Subdivided Lot 2, Adjacent 2436 address)
    plan_2436_info = ProjectInfo(
        project_name="Site Plan",
        project_number="50215",
        site_location="2436 White Oak Drive",
        legal_description="Lot 2, Block 1, White Oak Terrace",
        subdivision="White Oak Terrace",
        lot="2",
        block="1",
        client_name="Novel Texas",
    )
    plan_2436_assoc = matcher.match_document(target_project, "doc_2436", "SITE PLAN 2436 White Oak 2026.04.16.pdf", plan_2436_info)
    assert plan_2436_assoc.match_status == MatchStatus.POSSIBLE_MATCH
    assert 0.60 <= plan_2436_assoc.confidence_score <= 0.85
    assert any("Street address differs" in r for r in plan_2436_assoc.conflict_reasons)
    assert any("Legal subdivision matches" in r for r in plan_2436_assoc.match_reasons)
    assert any("Lot 2 is part of project lot group" in r for r in plan_2436_assoc.match_reasons)

    # Scenario 3: 2434 White Oak Site Plan (Norhill Park subdivision mismatch)
    plan_norhill_info = ProjectInfo(
        project_name="Site Plan",
        project_number="50214",
        site_location="2434 White Oak Drive",
        legal_description="Lot 8, Block 2, Norhill Park",
        subdivision="Norhill Park",
        lot="8",
        block="2",
        client_name="Novel Texas",
    )
    plan_norhill_assoc = matcher.match_document(target_project, "doc_norhill", "SITE PLAN 2434 WHITE OAK 2026.06.04.pdf", plan_norhill_info)
    assert plan_norhill_assoc.match_status == MatchStatus.MISMATCH
    assert plan_norhill_assoc.confidence_score <= 0.30
    assert any("Norhill Park" in r for r in plan_norhill_assoc.conflict_reasons)


def test_repository_association_persistence_and_confirmation(target_project: ProjectProfile):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    repo = DocumentRepository(conn)
    matcher = ProjectMatcher()

    # Create associations
    assoc_soil = matcher.match_document(
        target_project,
        "doc_soil",
        "Soil report 25-0117 v1.pdf",
        ProjectInfo(
            project_number="25-0117",
            site_location="2434 White Oak Drive",
            subdivision="White Oak Terrace",
            block="1",
            lot="1 & 2",
        ),
    )
    assoc_2436 = matcher.match_document(
        target_project,
        "doc_2436",
        "SITE PLAN 2436 White Oak.pdf",
        ProjectInfo(
            project_number="50215",
            site_location="2436 White Oak Drive",
            subdivision="White Oak Terrace",
            block="1",
            lot="2",
        ),
    )
    repo.save_document_association(assoc_soil)
    repo.save_document_association(assoc_2436)

    # Retrieve all
    assocs = repo.get_document_associations(target_project.project_id)
    assert len(assocs) == 2

    # Initially: MATCHED doc_soil is included, but POSSIBLE_MATCH doc_2436 is pending
    confirmed = repo.get_confirmed_document_ids(target_project.project_id)
    assert "doc_soil" in confirmed
    assert "doc_2436" not in confirmed

    # Human confirmation of doc_2436
    updated = repo.update_association_decision(
        association_id=assoc_2436.association_id,
        decision=UserDecision.CONFIRMED,
        reviewed_by="geotech_engineer",
        notes="Verified adjacent subdivided lot 2 within White Oak Terrace.",
    )
    assert updated is not None
    assert updated.user_decision == UserDecision.CONFIRMED
    assert updated.reviewed_by == "geotech_engineer"

    # Now both are confirmed
    confirmed_after = repo.get_confirmed_document_ids(target_project.project_id)
    assert "doc_soil" in confirmed_after
    assert "doc_2436" in confirmed_after

    # Human rejection of doc_soil
    repo.update_association_decision(
        association_id=assoc_soil.association_id,
        decision=UserDecision.REJECTED,
        reviewed_by="auditor",
        notes="Superseded report.",
    )
    confirmed_after_reject = repo.get_confirmed_document_ids(target_project.project_id)
    assert "doc_soil" not in confirmed_after_reject
    assert "doc_2436" in confirmed_after_reject


def test_matching_fastapi_endpoints(target_project: ProjectProfile):
    exec_repo = ExecutionRepository(":memory:")
    app = create_app(exec_repo)

    from geostrata.backend.documents.models import DocumentMetadata
    doc_repo = app.state.document_service.repo
    doc_repo.save_document_metadata(
        DocumentMetadata(
            document_id="doc_mock_1",
            project_id=target_project.project_id,
            filename="Soil report 25-0117 v1.pdf",
            sha256_hash="mockhash123",
            file_size_bytes=1000,
            project_info=ProjectInfo(
                project_name=target_project.project_name,
                project_number=target_project.project_number,
                site_location=target_project.site_address,
                legal_description=target_project.legal_description,
                subdivision=target_project.subdivision,
                lot=target_project.lot_number,
                block=target_project.block_number,
            ),
        )
    )

    with TestClient(app) as client:
        # Match endpoint
        resp = client.post(
            f"/v1/documents/projects/{target_project.project_id}/match",
            json=target_project.model_dump(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

        # Get associations
        resp_get = client.get(f"/v1/documents/projects/{target_project.project_id}/associations")
        assert resp_get.status_code == 200
        assocs = resp_get.json()
        assert len(assocs) >= 1

        target_assoc = assocs[0]
        assoc_id = target_assoc["association_id"]

        # Submit human decision
        resp_dec = client.patch(
            f"/v1/documents/associations/{assoc_id}/decision",
            json={"decision": "CONFIRMED", "reviewed_by": "qa_lead", "notes": "Approved for project synthesis."},
        )
        assert resp_dec.status_code == 200
        assert resp_dec.json()["user_decision"] == "CONFIRMED"

        # Confirmed documents list
        resp_conf = client.get(f"/v1/documents/projects/{target_project.project_id}/confirmed-documents")
        assert resp_conf.status_code == 200
        conf_ids = resp_conf.json()
        assert target_assoc["document_id"] in conf_ids


def test_multi_document_geotechnical_analysis_synthesis():
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    repo = DocumentRepository(conn)
    service = DocumentService(repo)

    soil_id = "7d500784-af45-4a86-a437-e90c3f7b54f2"
    plan_2436_id = "58e1ebc4-b70c-401e-b2c1-a842cadd764a"

    # Confirm 2436 site plan association for the soil report project
    matcher = ProjectMatcher()
    target_project = ProjectProfile(
        project_id=soil_id,
        project_name="Proposed 2 Residences",
        project_number="25-0117",
        site_address="2434 White Oak Drive, Houston, Texas 77009",
        legal_description="Lots 1 & 2, Block 1, White Oak Terrace",
        subdivision="White Oak Terrace",
        lot_number="1 & 2",
        block_number="1",
        client_name="Novel Signature Homes",
    )
    service.match_documents_for_project(target_project, matcher=matcher)
    
    # Confirm 2436 site plan
    assocs = service.get_associations_for_project(soil_id)
    plan_assoc = next((a for a in assocs if a.document_id == plan_2436_id), None)
    if plan_assoc:
        service.update_association_decision(
            plan_assoc.association_id,
            UserDecision.CONFIRMED,
            reviewed_by="test_engineer",
            notes="Confirmed multi-document analysis test",
        )

    # Run LangGraph pipeline
    graph = build_geotechnical_analysis_graph()
    initial_state = {
        "document_id": soil_id,
        "project_id": soil_id,
        "run_id": "test_multi_doc_run",
        "llm_profile": "document_analysis",
        "document_service": service,
    }
    final_state = graph.invoke(initial_state)

    assert final_state["status"] in ("COMPLETED", "succeeded")
    proj_ctx = final_state["project_context"]
    assert len(proj_ctx["documents_reviewed"]) >= 2
    assert "Soil report 25-0117 v1.pdf" in proj_ctx["documents_reviewed"]
    assert "SITE PLAN 2436 White Oak 2026.04.16.pdf" in proj_ctx["documents_reviewed"]
    assert proj_ctx["cross_document_status"] == "MATCHED"
    assert "Multi-document geotechnical synthesis confirmed" in proj_ctx["cross_document_matching_note"]

    # Verify cross-document address discrepancy was captured
    discrepancies = proj_ctx.get("discrepancies", [])
    assert any(d["field_name"] == "Project Site Addresses" for d in discrepancies)

    # Verify slope / high bank risk was synthesized from the site plan
    risks = final_state["risks_and_concerns"]["identified_risks"]
    assert any(r["risk_id"] == "RISK-05" and "High Bank" in r["title"] for r in risks)

    # Verify review status is PENDING_REVIEW
    report = final_state["report"]
    assert report["review_status"] == "PENDING_REVIEW"
