from __future__ import annotations

import asyncio
import io
import json
import sqlite3
import pytest
from unittest.mock import AsyncMock, MagicMock
from PIL import Image

from geostrata.backend.documents.models import BoundingBox, DocumentMetadata, DocumentPage, BoringLogReference, ProjectInfo
from geostrata.backend.documents.repository import DocumentRepository
from geostrata.backend.documents.vision.models import (
    PageContentType,
    PageClassificationResult,
    VisualEvidence,
    VisualRegion,
    CrossModalDisagreement,
)
from geostrata.backend.documents.vision.renderer import PDFVisionRenderer, RenderedPage
from geostrata.backend.documents.vision.image_preprocessor import ImagePreprocessor
from geostrata.backend.documents.vision.page_classifier import PageClassifier
from geostrata.backend.documents.vision.validators import CrossModalValidator
from geostrata.backend.documents.vision.service import VisionService


# ==============================================================================
# 1. Image Preprocessor & Coordinate Preservation Tests
# ==============================================================================

def test_image_preprocessor_downscaling():
    pre = ImagePreprocessor(max_overview_dimension=640)
    img = Image.new("RGB", (1200, 1600), color="white")
    
    downscaled = pre.downscale_for_overview(img, max_dim=640)
    w, h = downscaled.size
    assert max(w, h) == 640
    # Aspect ratio check
    assert round(w / h, 2) == round(1200 / 1600, 2)
    assert w == 480
    assert h == 640


def test_image_preprocessor_cropping_and_coordinate_mapping():
    pre = ImagePreprocessor()
    page_w = 612.0
    page_h = 792.0
    
    # 2x rendered image
    img = Image.new("RGB", (int(page_w * 2), int(page_h * 2)), color="blue")
    
    # Region in middle of page
    bbox = BoundingBox(
        x0=100.0,
        top=150.0,
        x1=300.0,
        bottom=450.0,
        page_width=page_w,
        page_height=page_h,
    )
    
    cropped, crop_coords = pre.crop_region(img, bbox, page_width_pts=page_w, page_height_pts=page_h)
    assert cropped.width == 400
    assert cropped.height == 600
    assert crop_coords.x0 == 100.0
    assert crop_coords.y0 == 150.0
    assert crop_coords.x1 == 300.0
    assert crop_coords.y1 == 450.0
    
    # Map sub-point (center of crop) back to original page points
    crop_center_px = (cropped.width / 2, cropped.height / 2)
    orig_x, orig_y = pre.map_crop_point_to_page_point(
        crop_center_px,
        crop_coords,
        crop_pixel_size=(cropped.width, cropped.height),
    )
    assert orig_x == 200.0  # (100 + 300) / 2
    assert orig_y == 300.0  # (150 + 450) / 2


def test_image_preprocessor_grid_tiling():
    pre = ImagePreprocessor()
    img = Image.new("RGB", (1000, 1000), color="gray")
    
    tiles = pre.create_grid_tiles(
        image=img,
        page_width_pts=500.0,
        page_height_pts=500.0,
        rows=2,
        cols=2,
        overlap_fraction=0.1,
    )
    assert len(tiles) == 4
    for t in tiles:
        assert t.image.width > 0
        assert t.image.height > 0
        assert t.bounding_box.page_width == 500.0
        assert t.bounding_box.page_height == 500.0
        assert t.base64_data_uri.startswith("data:image/png;base64,")


# ==============================================================================
# 2. Page Classifier Tests
# ==============================================================================

def test_page_classifier_deterministic_rules():
    classifier = PageClassifier()

    # Boring log page
    b_page = DocumentPage(
        page_index=19,
        raw_text="LOG OF BORING\nBORING NO.: B-1\nPROJECT: Proposed Residences\nBORING TYPE: Auger\nAPPROX. ELEVATION: 100 ft",
        char_count=150,
    )
    res_b = classifier.classify_deterministic(b_page)
    assert res_b.primary_content_type == PageContentType.BORING_LOG_DRAWING
    assert res_b.confidence >= 0.95

    # Site Location Map (Figure 1)
    map_page = DocumentPage(
        page_index=16,
        raw_text="SITE LOCATION MAP\nPROPOSED 2 RESIDENCES\n2434 WHITE OAK DRIVE\nFigure 1",
        char_count=100,
    )
    res_map = classifier.classify_deterministic(map_page)
    assert res_map.primary_content_type == PageContentType.MAP_OR_LOCATION_DIAGRAM

    # Boring Location Plan (Figure 2)
    plan_page = DocumentPage(
        page_index=17,
        raw_text="LOCATIONS OF BORINGS\nFigure 2\nPROPOSED 2 RESIDENCES\n2434 WHITE OAK DRIVE",
        char_count=100,
    )
    res_plan = classifier.classify_deterministic(plan_page)
    assert res_plan.primary_content_type == PageContentType.SITE_PLAN

    # Chart / Legend
    chart_page = DocumentPage(
        page_index=21,
        raw_text="KEY TO TERMS AND SYMBOLS USED ON BORING LOGS\nSOIL TYPE SAMPLER TYPE\nGRAVEL SAND SILT LEAN CLAY",
        char_count=180,
    )
    res_chart = classifier.classify_deterministic(chart_page)
    assert res_chart.primary_content_type == PageContentType.CHART_OR_GRAPH

    # Text with tables
    tbl_page = DocumentPage(
        page_index=5,
        raw_text="Subsurface Soil Stratum Summary (Layer I: 0 - 20 ft)\nDepth Range Soil Classification\n0 - 20 ft Fat Clay (CH)",
        char_count=500,
        tables_count=1,
    )
    res_tbl = classifier.classify_deterministic(tbl_page, known_tables_count=1)
    assert res_tbl.primary_content_type == PageContentType.TEXT_WITH_TABLES

    # Narrative text
    txt_page = DocumentPage(
        page_index=2,
        raw_text="1.0 INTRODUCTION\nThis geotechnical exploration was performed for the proposed residential project at White Oak Drive. Field exploration was conducted using auger drilling.",
        char_count=800,
    )
    res_txt = classifier.classify_deterministic(txt_page)
    assert res_txt.primary_content_type == PageContentType.TEXT_ONLY


# ==============================================================================
# 3. Cross-Modal Validator Tests
# ==============================================================================

def test_cross_modal_validator_discrepancies():
    validator = CrossModalValidator()
    
    # Textual knowledge
    known_logs = [
        BoringLogReference(
            boring_id="B-1",
            page_index=19,
            termination_depth=20.0,
            groundwater_drilling_depth=15.4,
        ),
        BoringLogReference(
            boring_id="B-2",
            page_index=20,
            termination_depth=20.0,
            groundwater_drilling_depth=14.5,
        ),
    ]
    proj = ProjectInfo(project_number="25-0117", project_name="Proposed 2 Residences")

    # Visual Evidence 1: Site plan reports B-1 and unexpected B-3
    vev_plan = VisualEvidence(
        document_id="doc_1",
        page_index=17,
        pdf_page_number=18,
        content_type=PageContentType.SITE_PLAN,
        structured_findings={
            "project_number": "25-0117",
            "boring_locations": [
                {"boring_id": "B-1", "relative_location": "Northwest"},
                {"boring_id": "B-3", "relative_location": "Southeast"},  # NOT in text records!
            ]
        }
    )

    # Visual Evidence 2: Boring log B-1 reports 15.0 ft depth instead of 20.0 ft
    vev_log = VisualEvidence(
        document_id="doc_1",
        page_index=19,
        pdf_page_number=20,
        content_type=PageContentType.BORING_LOG_DRAWING,
        structured_findings={
            "boring_id": "B-1",
            "project_number": "99-9999",  # WRONG project number!
            "termination_depth_ft": 15.0,  # Deviates by 5.0 ft!
            "groundwater": {"drilling_depth_ft": 15.4},
        }
    )

    disagreements = validator.validate(
        visual_evidence_list=[vev_plan, vev_log],
        boring_logs=known_logs,
        project_info=proj,
    )

    # Verify detected discrepancies
    prop_names = [d.property_name for d in disagreements]
    assert "boring_id_existence" in prop_names
    assert "B-1_termination_depth" in prop_names
    assert "project_number" in prop_names

    # Check severity
    proj_dis = next(d for d in disagreements if d.property_name == "project_number")
    assert proj_dis.severity == "CRITICAL"

    term_dis = next(d for d in disagreements if d.property_name == "B-1_termination_depth")
    assert term_dis.severity == "HIGH"
    assert "15.0 ft" in term_dis.visual_value
    assert "20.0 ft" in term_dis.text_value


# ==============================================================================
# 4. SQLite Repository Persistence & Review Flow Tests
# ==============================================================================

def test_visual_repository_lifecycle():
    conn = sqlite3.connect(":memory:")
    repo = DocumentRepository(conn)

    vev = VisualEvidence(
        visual_evidence_id="vev_test_123",
        document_id="doc_abc",
        page_index=17,
        pdf_page_number=18,
        content_type=PageContentType.SITE_PLAN,
        title_or_caption="Figure 2: Boring Locations Plan",
        visual_description="Site layout showing B-1 and B-2 locations on Lots 1 and 2.",
        extracted_labels=["Lot 1", "Lot 2", "White Oak Drive", "B-1", "B-2"],
        detected_entities=[{"boring_id": "B-1", "x": 0.35, "y": 0.42}],
        structured_findings={"scale": "1\"=30'", "north": "UP"},
        detected_regions=[
            VisualRegion(
                region_id="reg_1",
                label="Boring B-1",
                region_type="boring_location",
                bounding_box=BoundingBox(x0=50.0, top=100.0, x1=90.0, bottom=140.0),
            )
        ],
        extraction_method="vlm_vision_prompt",
        vision_model="qwen3-vl:2b",
        review_status="PENDING_REVIEW",
    )

    # 1. Save and retrieve
    repo.save_visual_evidence(vev)
    retrieved = repo.get_visual_evidence("doc_abc", page_index=17)
    assert len(retrieved) == 1
    item = retrieved[0]
    assert item.visual_evidence_id == "vev_test_123"
    assert item.content_type == PageContentType.SITE_PLAN
    assert len(item.extracted_labels) == 5
    assert len(item.detected_regions) == 1
    assert item.detected_regions[0].label == "Boring B-1"
    assert item.review_status == "PENDING_REVIEW"

    # 2. Update human review status
    ok = repo.update_visual_evidence_review(
        visual_evidence_id="vev_test_123",
        review_status="HUMAN_VERIFIED",
        human_notes="Verified against civil drawings.",
        verified_by="Lead Geotechnical Engineer",
    )
    assert ok is True

    updated = repo.get_visual_evidence_by_id("vev_test_123")
    assert updated is not None
    assert updated.review_status == "HUMAN_VERIFIED"
    assert updated.human_notes == "Verified against civil drawings."
    assert updated.verified_by == "Lead Geotechnical Engineer"

    # 3. Disagreements persistence
    dis = CrossModalDisagreement(
        disagreement_id="dis_test_456",
        document_id="doc_abc",
        page_index=17,
        property_name="test_prop",
        text_value="val_a",
        visual_value="val_b",
        discrepancy_description="Mismatch detected",
        severity="HIGH",
        status="OPEN",
    )
    repo.save_visual_disagreements([dis])
    dis_list = repo.get_visual_disagreements("doc_abc", status="OPEN")
    assert len(dis_list) == 1
    assert dis_list[0].disagreement_id == "dis_test_456"

    # Resolve disagreement
    repo.update_visual_disagreement_status("dis_test_456", "RESOLVED", resolution_notes="Confirmed via CAD")
    resolved_list = repo.get_visual_disagreements("doc_abc", status="RESOLVED")
    assert len(resolved_list) == 1
    assert resolved_list[0].resolution_notes == "Confirmed via CAD"
    assert resolved_list[0].resolved_at is not None


# ==============================================================================
# 5. VisionService End-to-End Analysis with Mocked VLM
# ==============================================================================

def test_vision_service_analyze_page_with_mock_vlm(tmp_path):
    conn = sqlite3.connect(":memory:")
    repo = DocumentRepository(conn)
    
    # Create fake document and page
    pdf_file = tmp_path / "test.pdf"
    # Create valid blank 1-page PDF
    import pypdfium2 as pdfium
    new_doc = pdfium.PdfDocument.new()
    new_doc.new_page(width=612, height=792)
    new_doc.save(str(pdf_file))
    new_doc.close()

    doc_meta = DocumentMetadata(
        document_id="doc_mock_1",
        project_id="proj_1",
        filename="test.pdf",
        sha256_hash="hash123",
        file_size_bytes=1000,
        page_count=1,
        storage_path=str(pdf_file),
        project_info=ProjectInfo(project_number="25-0117"),
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    repo.save_document_metadata(doc_meta)
    
    p = DocumentPage(
        page_index=0,
        raw_text="LOCATIONS OF BORINGS\nPROPOSED 2 RESIDENCES\nFigure 2",
        char_count=60,
    )
    repo.save_document_pages("doc_mock_1", [p])

    # Mock LLM Client
    mock_vlm_response = json.dumps({
        "title": "Figure 2: Locations of Borings",
        "figure_number": "Figure 2",
        "project_number": "25-0117",
        "boring_locations": [
            {"boring_id": "B-1", "relative_location": "Northwest lot", "approx_x_percent": 0.3, "approx_y_percent": 0.4},
            {"boring_id": "B-2", "relative_location": "Southeast lot", "approx_x_percent": 0.7, "approx_y_percent": 0.8},
        ],
        "extracted_labels": ["Lot 1", "Lot 2", "White Oak Dr", "B-1", "B-2"],
        "summary": "Boring locations plan showing boreholes B-1 and B-2 across Lots 1 and 2.",
    })

    from app.llm.contracts import LLMResponse
    mock_client = MagicMock()
    mock_client.config = MagicMock()
    mock_client.config.model = "qwen3-vl:2b"
    mock_client.generate = AsyncMock(return_value=LLMResponse(content=mock_vlm_response, model="qwen3-vl:2b"))

    mock_registry = MagicMock()
    mock_registry.get.return_value = mock_client

    service = VisionService(
        repository=repo,
        registry=mock_registry,
    )

    result = asyncio.run(service.analyze_page_visual(
        document_id="doc_mock_1",
        page_index=0,
    ))

    assert result.document_id == "doc_mock_1"
    assert result.page_index == 0
    assert result.content_type == PageContentType.SITE_PLAN
    assert result.title_or_caption == "Figure 2: Locations of Borings"
    assert len(result.extracted_labels) == 5
    assert len(result.detected_entities) == 2
    assert len(result.detected_regions) == 2
    assert result.detected_regions[0].label == "B-1"
    assert result.review_status == "PENDING_REVIEW"

    # Verify persisted in database
    db_items = repo.get_visual_evidence("doc_mock_1", page_index=0)
    assert len(db_items) == 1
    assert db_items[0].visual_evidence_id == result.visual_evidence_id


# ==============================================================================
# 6. REST API Endpoint Integration Tests
# ==============================================================================

def test_vision_router_endpoints(tmp_path):
    from fastapi.testclient import TestClient
    from app.api.app import create_app
    from app.storage.repository import ExecutionRepository

    app = create_app(ExecutionRepository(":memory:"))
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    repo = DocumentRepository(conn)

    # Setup dummy document in repo
    pdf_file = tmp_path / "test_api.pdf"
    import pypdfium2 as pdfium
    new_doc = pdfium.PdfDocument.new()
    new_doc.new_page(width=612, height=792)
    new_doc.save(str(pdf_file))
    new_doc.close()

    doc_meta = DocumentMetadata(
        document_id="doc_api_test",
        project_id="default",
        filename="test_api.pdf",
        sha256_hash="sha_api_123",
        file_size_bytes=500,
        page_count=1,
        storage_path=str(pdf_file),
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    repo.save_document_metadata(doc_meta)
    page0 = DocumentPage(
        page_index=0,
        raw_text="SITE LOCATION MAP\nFigure 1\nWhite Oak Drive",
        char_count=50,
    )
    repo.save_document_pages("doc_api_test", [page0])

    # Save a visual evidence record
    vev = VisualEvidence(
        visual_evidence_id="vev_api_1",
        document_id="doc_api_test",
        page_index=0,
        pdf_page_number=1,
        content_type=PageContentType.MAP_OR_LOCATION_DIAGRAM,
        title_or_caption="Figure 1: Site Location Map",
        extracted_labels=["White Oak Drive", "Figure 1"],
        review_status="PENDING_REVIEW",
    )
    repo.save_visual_evidence(vev)

    # Save a disagreement record
    dis = CrossModalDisagreement(
        disagreement_id="dis_api_1",
        document_id="doc_api_test",
        page_index=0,
        property_name="test_prop",
        discrepancy_description="Test Discrepancy",
        status="OPEN",
    )
    repo.save_visual_disagreements([dis])

    from geostrata.backend.documents.service import DocumentService
    doc_service = DocumentService(repository=repo)
    vision_service = VisionService(repository=repo)

    app.state.document_service = doc_service
    app.state.vision_service = vision_service

    with TestClient(app) as client:
        # 1. GET page classification
        res = client.get("/v1/documents/doc_api_test/pages/classification")
        assert res.status_code == 200
        classes = res.json()
        assert len(classes) == 1
        assert classes[0]["primary_content_type"] == "MAP_OR_LOCATION_DIAGRAM"

        # 2. GET visual evidence list
        res_ev = client.get("/v1/documents/doc_api_test/visual-evidence")
        assert res_ev.status_code == 200
        ev_list = res_ev.json()
        assert len(ev_list) == 1
        assert ev_list[0]["visual_evidence_id"] == "vev_api_1"

        # 3. PATCH review status
        res_rev = client.patch(
            "/v1/documents/visual-evidence/vev_api_1/review",
            json={"review_status": "HUMAN_VERIFIED", "human_notes": "All good", "verified_by": "Engineer 1"},
        )
        assert res_rev.status_code == 200
        assert res_rev.json()["status"] == "updated"
        assert res_rev.json()["review_status"] == "HUMAN_VERIFIED"

        # 4. GET disagreements
        res_dis = client.get("/v1/documents/doc_api_test/visual-disagreements")
        assert res_dis.status_code == 200
        assert len(res_dis.json()) == 1

        # 5. PATCH resolve disagreement
        res_res = client.patch(
            "/v1/documents/visual-disagreements/dis_api_1",
            json={"status": "RESOLVED", "resolution_notes": "Resolved by site visit"},
        )
        assert res_res.status_code == 200
        assert res_res.json()["status"] == "RESOLVED"

