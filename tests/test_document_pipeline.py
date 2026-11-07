from __future__ import annotations

import io
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

from app.api.app import create_app
from app.storage.repository import ExecutionRepository
from geostrata.backend.documents import (
    PDFExtractor,
    DocumentStorage,
    DocumentRepository,
    DocumentService,
    DocumentMetadata,
    BoundingBox,
)


# ==============================================================================
# Numbered Canvas for Testing Printed Page Numbers in Header/Footer
# ==============================================================================

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            # Draw header
            self.setFont("Helvetica", 9)
            self.drawString(54, 750, "PROJECT: Highway 101 Overpass | Report No. GEO-2026-904")
            # Draw printed page footer (e.g. "Page 1 of 3")
            self.drawRightString(558, 40, f"Page {self._pageNumber} of {num_pages}")
            super().showPage()
        super().save()


def build_synthetic_geotechnical_pdf(include_scanned_page: bool = False, include_empty_page: bool = False) -> bytes:
    """Generate a multi-page geotechnical report PDF with headers, tables, technical values, and borehole logs."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=54,
        rightMargin=54,
        topMargin=72,
        bottomMargin=72,
    )
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle("CoverTitle", parent=styles["Title"], fontSize=18, leading=22, spaceAfter=14)
    heading_style = ParagraphStyle("ReportHeading", parent=styles["Heading1"], fontSize=14, leading=18, spaceBefore=12, spaceAfter=8)
    body_style = ParagraphStyle("ReportBody", parent=styles["Normal"], fontSize=10, leading=14, spaceAfter=6)

    story = []

    # Page 0 (Cover / Front Matter)
    story.append(Paragraph("GEOTECHNICAL ENGINEERING INVESTIGATION REPORT", title_style))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Project: Highway 101 Overpass Foundation Investigation", body_style))
    story.append(Paragraph("Project No: GEO-2026-904", body_style))
    story.append(Paragraph("Site Location: 4500 Highway 101, San Jose, CA", body_style))
    story.append(Paragraph("Prepared For: Department of Transportation", body_style))
    story.append(Paragraph("Prepared By: Apex Geotechnical Consultants", body_style))
    story.append(Paragraph("Date: October 15, 2026", body_style))
    story.append(Spacer(1, 20))
    story.append(Paragraph("Figure 1: Site Location and Boring Plan", body_style))
    story.append(PageBreak())

    # Page 1 (Subsurface Conditions & Technical Values)
    story.append(Paragraph("1.0 INTRODUCTION AND SCOPE", heading_style))
    story.append(Paragraph(
        "This report presents the results of our subsurface exploration for the proposed bridge foundations. "
        "Two exploratory boreholes, designated as Boring B-1 and Borehole BH-02, were advanced to depths of 15.0 meters.",
        body_style
    ))
    story.append(Paragraph("2.0 SUBSURFACE CONDITIONS", heading_style))
    story.append(Paragraph(
        "Subsurface conditions consist of medium dense silty sand underlain by stiff clay. "
        "Groundwater was encountered at 3.5 m below ground surface during drilling. "
        "The upper silty sand exhibits a total unit weight of 19.2 kN/m3 and natural moisture content of 18.5%. "
        "Standard Penetration Testing yielded an SPT N-value of 22 blows/ft at depth 4.5 m.",
        body_style
    ))
    story.append(Paragraph("3.0 SHALLOW FOUNDATIONS RECOMMENDATIONS", heading_style))
    story.append(Paragraph(
        "For spread footings bearing in the dense sand stratum at depth 2.0 m, an allowable bearing capacity of 250 kPa "
        "may be used for design. Cohesion c = 25 kPa and friction angle phi = 32 deg were measured in shear testing. "
        "Total settlement is estimated at 20 mm under design load.",
        body_style
    ))

    # Add Stratigraphy Table
    table_data = [
        ["Boring ID", "Depth (m)", "Soil Classification", "SPT N", "Allowable qa (kPa)"],
        ["B-1", "0.0 - 2.5", "Silty Sand (SM)", "14", "150 kPa"],
        ["B-1", "2.5 - 6.0", "Dense Sand (SP)", "32", "300 kPa"],
        ["BH-02", "0.0 - 3.0", "Lean Clay (CL)", "8", "120 kPa"],
        ["BH-02", "3.0 - 15.0", "Very Dense Gravelly Sand", "45", "400 kPa"],
    ]
    t = Table(table_data, colWidths=[65, 75, 160, 60, 110])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#94a3b8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.white]),
    ]))
    story.append(Spacer(1, 10))
    story.append(t)
    story.append(Spacer(1, 15))
    story.append(Paragraph("General Notes: All footings must be inspected by a geotechnical engineer prior to pouring.", body_style))

    # Optional Empty Page
    if include_empty_page:
        story.append(PageBreak())
        story.append(Spacer(1, 50))  # Blank spacer with no text

    # Optional Scanned Page (Pure Image, no text)
    if include_scanned_page:
        story.append(PageBreak())
        # Generate dummy 200x200 pixel image
        img_buf = io.BytesIO()
        pil_img = PILImage.new("RGB", (200, 200), color=(220, 220, 220))
        pil_img.save(img_buf, format="PNG")
        img_buf.seek(0)
        from reportlab.platypus import Image as RLImage
        story.append(RLImage(img_buf, width=200, height=200))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


# ==============================================================================
# 1. Ingestion & Validation Unit Tests
# ==============================================================================

def test_storage_validates_pdf_magic_bytes_and_size(tmp_path):
    storage = DocumentStorage(root_dir=tmp_path / "storage", max_size_bytes=1000)

    # Empty content
    valid, err = storage.validate_pdf_content(b"", "empty.pdf")
    assert not valid
    assert "empty" in err

    # Non-PDF content
    valid, err = storage.validate_pdf_content(b"Hello plain text file", "text.txt")
    assert not valid
    assert "missing %PDF-" in err

    # Oversized content
    oversized = b"%PDF-1.4 " + b"0" * 1500
    valid, err = storage.validate_pdf_content(oversized, "big.pdf")
    assert not valid
    assert "exceeds maximum allowed size" in err

    # Valid PDF
    valid, err = storage.validate_pdf_content(b"%PDF-1.4 valid header bytes", "valid.pdf")
    assert valid
    assert err is None


def test_storage_stores_original_pdf_untouched_with_sha256(tmp_path):
    storage = DocumentStorage(root_dir=tmp_path / "storage")
    pdf_bytes = build_synthetic_geotechnical_pdf()

    dest_path, sha256 = storage.store_original_pdf("doc-test-1", pdf_bytes)
    assert dest_path.exists()
    assert dest_path.read_bytes() == pdf_bytes
    assert len(sha256) == 64


# ==============================================================================
# 2. PDF Extractor Tests: Multi-Page, Tables, Evidence, Page Numbers
# ==============================================================================

def test_extractor_extracts_multi_page_document_with_tables_and_evidence(tmp_path):
    pdf_bytes = build_synthetic_geotechnical_pdf()
    pdf_file = tmp_path / "test_geotech.pdf"
    pdf_file.write_bytes(pdf_bytes)

    extractor = PDFExtractor()
    result = extractor.process_document(
        document_id="doc-123",
        filename="Highway_101_Geotech.pdf",
        pdf_path=pdf_file,
        sha256_hash="dummy_hash",
        file_size_bytes=len(pdf_bytes),
    )

    # 1. Page count and metadata
    assert result.metadata.page_count == 2
    assert result.metadata.status == "completed"
    assert result.metadata.document_type == "text_based"
    assert not result.metadata.is_scanned

    # 2. Project info extraction
    proj = result.metadata.project_info
    assert proj is not None
    assert "Highway 101" in proj.project_name
    assert proj.project_number == "GEO-2026-904"
    assert "San Jose" in proj.site_location
    assert "Department of Transportation" in proj.client_name
    assert "Apex Geotechnical" in proj.engineer_firm

    # 3. Printed page numbers preserved
    # Page 0 footer has "Page 1 of 2", Page 1 footer has "Page 2 of 2"
    assert result.pages[0].page_index == 0
    assert result.pages[0].printed_page_number == "1"
    assert result.pages[1].page_index == 1
    assert result.pages[1].printed_page_number == "2"

    # 4. Headings & sections
    section_titles = [s.title for s in result.sections]
    assert any("INTRODUCTION" in s for s in section_titles)
    assert any("SUBSURFACE CONDITIONS" in s for s in section_titles)
    assert any("SHALLOW FOUNDATIONS" in s for s in section_titles)

    # 5. Tables extraction
    assert len(result.tables) >= 1
    tbl = result.tables[0]
    assert tbl.page_index == 1
    assert "Boring ID" in tbl.headers
    assert "Allowable qa (kPa)" in tbl.headers or any("qa" in h for h in tbl.headers)
    assert len(tbl.rows) == 4
    assert tbl.bounding_box is not None
    assert tbl.bounding_box.x0 > 0
    assert tbl.bounding_box.bottom > tbl.bounding_box.top

    # 6. Technical Values & Evidence Records
    evidence_types = {e.property_type for e in result.evidence}
    assert "bearing_capacity" in evidence_types
    assert "water_table" in evidence_types
    assert "unit_weight" in evidence_types
    assert "spt_n_value" in evidence_types
    assert "table_cell" in evidence_types

    # Verify bearing capacity evidence record
    bc_ev = next(e for e in result.evidence if e.property_type == "bearing_capacity")
    assert "250 kPa" in bc_ev.extracted_text or "250" in bc_ev.extracted_text
    assert bc_ev.page_index == 1
    assert bc_ev.printed_page_number == "2"
    assert bc_ev.bounding_box is not None
    assert bc_ev.bounding_box.top > 0
    assert bc_ev.context_snippet is not None

    # 7. Boring logs mapped to page indices
    boring_ids = {b.boring_id for b in result.boring_logs}
    assert "B-1" in boring_ids
    assert "BH-02" in boring_ids or "BH-2" in boring_ids

    # 8. Figure references
    assert any("Figure 1" in f.figure_id or "Figure 1" in f.title for f in result.figures)


def test_extractor_detects_scanned_pages_and_empty_pages(tmp_path):
    pdf_bytes = build_synthetic_geotechnical_pdf(include_scanned_page=True, include_empty_page=True)
    pdf_file = tmp_path / "hybrid_doc.pdf"
    pdf_file.write_bytes(pdf_bytes)

    extractor = PDFExtractor()
    result = extractor.process_document(
        document_id="doc-hybrid",
        filename="hybrid.pdf",
        pdf_path=pdf_file,
        sha256_hash="hash-hybrid",
        file_size_bytes=len(pdf_bytes),
    )

    assert result.metadata.page_count == 4
    # Contains text pages, an empty page, and an image-only scanned page -> hybrid
    assert result.metadata.document_type == "hybrid"
    assert result.metadata.is_scanned is True

    empty_page = result.pages[2]
    assert empty_page.status == "empty"
    assert empty_page.tables_count == 0
    assert empty_page.evidence_count == 0

    scanned_page = result.pages[3]
    assert scanned_page.is_scanned is True


def test_extractor_renders_page_image_using_pypdfium2(tmp_path):
    pdf_bytes = build_synthetic_geotechnical_pdf()
    pdf_file = tmp_path / "render_test.pdf"
    pdf_file.write_bytes(pdf_bytes)

    extractor = PDFExtractor()
    img_out = tmp_path / "page_0.png"
    rendered = extractor.render_page_image(pdf_file, 0, img_out, scale=1.5)

    assert rendered.exists()
    assert rendered.stat().st_size > 1000
    with PILImage.open(rendered) as img:
        assert img.format == "PNG"
        assert img.width > 500
        assert img.height > 500


# ==============================================================================
# 3. Duplicate Detection & Service Layer Tests
# ==============================================================================

def test_document_service_detects_duplicate_uploads_by_sha256(tmp_path):
    storage = DocumentStorage(root_dir=tmp_path / "storage")
    import sqlite3
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    repo = DocumentRepository(conn)
    service = DocumentService(repo, storage)

    pdf_bytes = build_synthetic_geotechnical_pdf()

    # First upload succeeds
    doc1 = service.upload_document("report_original.pdf", pdf_bytes)
    assert doc1.status == "completed"
    assert doc1.document_id

    # Second upload with identical bytes detects duplicate
    doc2 = service.upload_document("report_copy.pdf", pdf_bytes)
    assert doc2.status == "duplicate"
    assert doc2.document_id == doc1.document_id
    assert "Duplicate document" in doc2.error_message


# ==============================================================================
# 4. FastAPI Endpoints & Integration Tests
# ==============================================================================

def test_fastapi_document_endpoints(tmp_path):
    db_path = str(tmp_path / "test_api.db")
    repo = ExecutionRepository(db_path)
    app = create_app(repo)

    with TestClient(app) as client:
        pdf_bytes = build_synthetic_geotechnical_pdf()

        # 1. Upload valid PDF
        response = client.post(
            "/v1/documents/upload",
            files=[("files", ("geotech_report.pdf", pdf_bytes, "application/pdf"))],
            data={"project_id": "proj-101"},
        )
        assert response.status_code == 200
        uploaded_list = response.json()
        assert len(uploaded_list) == 1
        doc_id = uploaded_list[0]["document_id"]
        assert uploaded_list[0]["status"] == "completed"
        assert uploaded_list[0]["page_count"] == 2

        # 2. List documents
        list_res = client.get("/v1/documents?project_id=proj-101")
        assert list_res.status_code == 200
        docs = list_res.json()
        assert len(docs) == 1
        assert docs[0]["document_id"] == doc_id

        # 3. Get document metadata
        meta_res = client.get(f"/v1/documents/{doc_id}")
        assert meta_res.status_code == 200
        assert meta_res.json()["filename"] == "geotech_report.pdf"

        # 4. Get pages
        pages_res = client.get(f"/v1/documents/{doc_id}/pages")
        assert pages_res.status_code == 200
        pages = pages_res.json()
        assert len(pages) == 2

        # 5. Get single page
        p1_res = client.get(f"/v1/documents/{doc_id}/pages/1")
        assert p1_res.status_code == 200
        assert p1_res.json()["page_index"] == 1

        # 6. Render and stream page image
        img_res = client.get(f"/v1/documents/{doc_id}/pages/0/image")
        assert img_res.status_code == 200
        assert img_res.headers["content-type"] == "image/png"
        assert len(img_res.content) > 1000

        # 7. Get extracted tables
        tables_res = client.get(f"/v1/documents/{doc_id}/tables")
        assert tables_res.status_code == 200
        tables = tables_res.json()
        assert len(tables) >= 1

        # 8. Get evidence records
        evidence_res = client.get(f"/v1/documents/{doc_id}/evidence")
        assert evidence_res.status_code == 200
        evidence = evidence_res.json()
        assert len(evidence) > 0
        first_ev_id = evidence[0]["evidence_id"]

        # 9. Update evidence verification status
        patch_res = client.patch(f"/v1/documents/evidence/{first_ev_id}?verification_status=verified")
        assert patch_res.status_code == 200
        assert patch_res.json()["verification_status"] == "verified"

        # 10. Duplicate upload detection via API
        dup_res = client.post(
            "/v1/documents/upload",
            files=[("files", ("duplicate_report.pdf", pdf_bytes, "application/pdf"))],
            data={"project_id": "proj-101"},
        )
        assert dup_res.status_code == 200
        assert dup_res.json()[0]["status"] == "duplicate"

        # 11. Invalid file upload rejected
        bad_res = client.post(
            "/v1/documents/upload",
            files=[("files", ("not_a_pdf.txt", b"plain text only", "text/plain"))],
        )
        assert bad_res.status_code == 400
        assert "not a valid PDF" in bad_res.json()["detail"]


def test_extractor_handles_corrupted_pdf_gracefully(tmp_path):
    corrupted_pdf = tmp_path / "corrupted.pdf"
    corrupted_pdf.write_bytes(b"%PDF-1.4\ncorrupted file stream garbage data")

    extractor = PDFExtractor()
    result = extractor.process_document(
        document_id="doc-corrupt",
        filename="corrupted.pdf",
        pdf_path=corrupted_pdf,
        sha256_hash="hash-corrupt",
        file_size_bytes=corrupted_pdf.stat().st_size,
    )

    assert result.metadata.status == "failed"
    assert result.metadata.error_message is not None


# ==============================================================================
# Regression Tests for Soil report 25-0117 v1.pdf (Phase 1 Validations)
# ==============================================================================

REAL_SOIL_REPORT_PATH = Path("storage/documents/7d500784-af45-4a86-a437-e90c3f7b54f2/original.pdf")


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_real_soil_report_table_defragmentation_and_classification():
    """Verify that table fragmentation is resolved and tables are classified correctly."""
    extractor = PDFExtractor()
    result = extractor.process_document(
        document_id="test-soil-report",
        filename="Soil report 25-0117 v1.pdf",
        pdf_path=REAL_SOIL_REPORT_PATH,
        sha256_hash="test-sha-soil",
        file_size_bytes=REAL_SOIL_REPORT_PATH.stat().st_size,
    )

    assert result.metadata.page_count == 22
    assert result.metadata.status == "completed"

    # 1. Page 7 (idx 6): Laboratory Test Summary must NOT have fragmented subheader tables
    p7_tables = [t for t in result.tables if t.page_index == 6]
    assert len(p7_tables) == 1, f"Expected 1 unified table on page 7, found {len(p7_tables)}"

    lab_table = p7_tables[0]
    assert lab_table.table_classification == "laboratory_summary"
    assert "Laboratory Test Summary" in lab_table.table_name
    assert "LIQUID LIMIT (%) - HIGH" in lab_table.headers
    assert "LIQUID LIMIT (%) - LOW" in lab_table.headers
    assert "MOISTURE CONTENT (%) - HIGH" in lab_table.headers
    assert "PASSING NO. 200 SIEVE (%) - HIGH" in lab_table.headers

    # Check Layer I values: LL 32-42, PI 17-24, Moisture 15.0-23.9, Pass #200 54.8-68.6
    row_values = lab_table.rows[0]
    assert "0 - 20" in row_values
    assert "42" in row_values
    assert "32" in row_values
    assert "24" in row_values
    assert "17" in row_values
    assert "23.9" in row_values
    assert "15.0" in row_values
    assert "68.6" in row_values
    assert "54.8" in row_values

    # 2. Verify Table Classifications across report
    classifications = {t.table_classification for t in result.tables}
    assert "boring_log" in classifications
    assert "laboratory_summary" in classifications
    assert "foundation_design_parameters" in classifications
    assert "reference_legend" in classifications
    assert "figure_drawing_text" in classifications
    assert "engineering_data" in classifications


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_real_soil_report_boring_log_b1_and_b2_extraction():
    """Verify Boring logs B-1 and B-2 exact observations, sample test depths, stratum separation, and Auger SPT representation."""
    extractor = PDFExtractor()
    result = extractor.process_document(
        document_id="test-soil-report-borings",
        filename="Soil report 25-0117 v1.pdf",
        pdf_path=REAL_SOIL_REPORT_PATH,
        sha256_hash="test-sha-borings",
        file_size_bytes=REAL_SOIL_REPORT_PATH.stat().st_size,
    )

    # 1. Boring Log references
    boring_ids = {b.boring_id for b in result.boring_logs}
    assert "B-1" in boring_ids
    assert "B-2" in boring_ids

    # 2. Detailed Boring Reference Data (B-1)
    b1_ref = [b for b in result.boring_logs if b.boring_id == "B-1" and b.observations][0]
    assert b1_ref.stratum_description == "SANDY LEAN CLAY (CL), firm to very stiff, dark gray, gray, and tan"
    assert b1_ref.depth_range == "0 - 20 ft"
    assert b1_ref.sample_depths == [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 14.0, 19.0]
    assert len(b1_ref.sample_depths) == 8
    assert b1_ref.latitude == 29.78197
    assert b1_ref.longitude == -95.38343
    assert "N 29.78197" in b1_ref.gps_coordinates and "95.38343" in b1_ref.gps_coordinates

    # Exact B-1 field observations
    b1_obs_map = {obs["depth_label"]: obs["observation"] for obs in b1_ref.observations}
    assert b1_obs_map.get("4 ft") == "Light gray and tan"
    assert b1_obs_map.get("8 ft") == "Calcareous nodules"
    assert b1_obs_map.get("10 ft") == "Light gray"
    assert b1_obs_map.get("13 ft") == "Gray, tan and reddish brown"

    # 3. Detailed Boring Reference Data (B-2)
    b2_ref = [b for b in result.boring_logs if b.boring_id == "B-2" and b.observations][0]
    assert b2_ref.stratum_description == "SANDY LEAN CLAY (CL), firm to very stiff, gray and tan"
    assert b2_ref.depth_range == "0 - 15 ft"
    assert b2_ref.sample_depths == [1.0, 3.0, 5.0, 7.0, 9.0, 11.0, 14.0]
    assert len(b2_ref.sample_depths) == 7
    assert b2_ref.latitude == 29.78174
    assert b2_ref.longitude == -95.38339
    assert "N 29.78174" in b2_ref.gps_coordinates and "95.38339" in b2_ref.gps_coordinates

    # Exact B-2 field observations
    b2_obs_map = {obs["depth_label"]: obs["observation"] for obs in b2_ref.observations}
    assert b2_obs_map.get("4 ft") == "Calcareous nodules"
    assert b2_obs_map.get("6 ft") == "Light gray and tan"
    assert b2_obs_map.get("10 ft") == "Light gray"

    # 4. Boring B-1 Sample Measurements Table (PDF Page 20 / Page index 19)
    # Must contain ONLY rows for actual sample test locations (8 rows), without repeating soil stratum description
    b1_tables = [t for t in result.tables if t.page_index == 19 and t.table_classification == "boring_log"]
    assert len(b1_tables) == 1
    b1_tbl = b1_tables[0]
    assert "Sample Measurements" in b1_tbl.table_name
    assert "Sample Depth (ft)" in b1_tbl.headers
    assert 'SPT Blows (per 6")' in b1_tbl.headers
    assert "Hand Pen (tsf)" in b1_tbl.headers
    assert "Moisture Content (%)" in b1_tbl.headers
    assert len(b1_tbl.rows) == 8  # 8 sample depths only, no artificial graduation ticks

    # Complete cell-by-cell verification of all 8 B-1 readings
    expected_b1_rows = [
        ["1", "2.00", "NOT_REPORTED", "23.9", "38", "18", "20", "68.6"],
        ["3", "2.00", "NOT_REPORTED", "22.3", "", "", "", ""],
        ["5", "1.50", "NOT_REPORTED", "15.1", "32", "15", "17", "59.3"],
        ["7", "1.50", "NOT_REPORTED", "17.5", "", "", "", ""],
        ["9", "1.50", "NOT_REPORTED", "17.8", "", "", "", ""],
        ["11", "1.00", "NOT_REPORTED", "19.6", "", "", "", ""],
        ["14", "1.00", "NOT_REPORTED", "18.9", "32", "15", "17", "54.8"],
        ["19", "3.00", "NOT_REPORTED", "23.4", "", "", "", ""],
    ]
    assert b1_tbl.rows == expected_b1_rows

    # 5. Boring B-2 Sample Measurements Table (PDF Page 21 / Page index 20)
    b2_tables = [t for t in result.tables if t.page_index == 20 and t.table_classification == "boring_log"]
    assert len(b2_tables) == 1
    b2_tbl = b2_tables[0]
    assert len(b2_tbl.rows) == 7  # 7 sample depths only

    # Complete cell-by-cell verification of all 7 B-2 readings
    expected_b2_rows = [
        ["1", "2.00", "NOT_REPORTED", "23.2", "", "", "", ""],
        ["3", "2.00", "NOT_REPORTED", "19.6", "42", "18", "24", "63.1"],
        ["5", "2.50", "NOT_REPORTED", "15.0", "", "", "", ""],
        ["7", "1.50", "NOT_REPORTED", "17.1", "34", "16", "18", "55.8"],
        ["9", "1.00", "NOT_REPORTED", "17.5", "", "", "", ""],
        ["11", "1.25", "NOT_REPORTED", "19.0", "", "", "", ""],
        ["14", "1.50", "NOT_REPORTED", "20.8", "", "", "", ""],
    ]
    assert b2_tbl.rows == expected_b2_rows

    # 6. Crucial rule: SPT blow counts MUST be represented as NOT_REPORTED, never numeric zero
    spt_evidence = [e for e in result.evidence if "SPT Blow Counts" in (e.property_name or "")]
    assert len(spt_evidence) >= 2
    for ev in spt_evidence:
        assert ev.original_value == "NOT_REPORTED"
        assert ev.numeric_value is None
        assert ev.is_reported is False
        assert ev.verification_status == "PENDING_REVIEW"

    # 7. Groundwater Evidence
    gw_b1_drill = [e for e in result.evidence if e.boring_id == "B-1" and "Drilling" in (e.property_name or "")][0]
    assert gw_b1_drill.numeric_value == 15.4
    assert gw_b1_drill.unit == "ft"

    gw_b1_post = [e for e in result.evidence if e.boring_id == "B-1" and "Post-Drilling" in (e.property_name or "")][0]
    assert gw_b1_post.numeric_value == 14.8
    assert gw_b1_post.unit == "ft"

    gw_b2_drill = [e for e in result.evidence if e.boring_id == "B-2" and "Drilling" in (e.property_name or "")][0]
    assert gw_b2_drill.numeric_value == 14.5
    assert gw_b2_drill.unit == "ft"

    gw_b2_post = [e for e in result.evidence if e.boring_id == "B-2" and "Post-Drilling" in (e.property_name or "")][0]
    assert gw_b2_post.numeric_value == 14.0
    assert gw_b2_post.unit == "ft"


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_real_soil_report_engineering_evidence_and_parameters():
    """Verify allowable bearing table load cases separation and all 4 foundation recommendations."""
    extractor = PDFExtractor()
    result = extractor.process_document(
        document_id="test-soil-report-params",
        filename="Soil report 25-0117 v1.pdf",
        pdf_path=REAL_SOIL_REPORT_PATH,
        sha256_hash="test-sha-params",
        file_size_bytes=REAL_SOIL_REPORT_PATH.stat().st_size,
    )

    # 1. PVR Extraction (1.20 inches)
    pvr_records = [e for e in result.evidence if e.property_type == "pvr"]
    assert len(pvr_records) >= 1
    pvr = pvr_records[0]
    assert pvr.numeric_value == 1.2
    assert pvr.unit == "inches"
    assert pvr.confidence_category == "VERIFIED_TEXT"

    # 2. Allowable Bearing Pressure Table (Page index 7 / Report Page 4)
    bearing_tables = [t for t in result.tables if t.page_index == 7 and t.table_classification == "foundation_design_parameters"]
    assert len(bearing_tables) == 1
    b_table = bearing_tables[0]
    assert b_table.headers == ["Design Parameter / Load Case", "Allowable Bearing Pressure / Value", "Factor of Safety"]
    assert len(b_table.rows) == 3

    # Load cases decomposed into separate rows
    assert b_table.rows[0] == ["Total Load", "2,100 psf", "2.0"]
    assert b_table.rows[1] == ["Dead Load + Sustained Live Load", "1,400 psf", "3.0"]
    assert b_table.rows[2] == ["Percent Fine Clay", "35 %", "-"]

    # 3. All 4 Foundation System Recommendations Extracted
    assert len(result.foundation_recommendations) == 4
    recs_map = {r.system_name: r for r in result.foundation_recommendations}
    assert "Post-Tensioned Slabs" in recs_map
    assert "Drilled Underreamed Piers" in recs_map
    assert "Continuous Footings / Grade Beams" in recs_map
    assert "Slab-on-Grade Floor" in recs_map

    # Post-Tensioned Slabs verification
    pt = recs_map["Post-Tensioned Slabs"]
    pt_params = {p.parameter_name: p for p in pt.parameters}
    assert pt_params["Minimum Select Fill Thickness"].numeric_value == 1.0
    assert pt_params["Allowable Net Bearing Pressure (Total Load)"].numeric_value == 2100.0
    assert pt_params["Allowable Net Bearing Pressure (Total Load)"].factor_of_safety == 2.0
    assert pt_params["Allowable Net Bearing Pressure (Dead Load + Sustained Live Load)"].numeric_value == 1400.0
    assert pt_params["Allowable Net Bearing Pressure (Dead Load + Sustained Live Load)"].factor_of_safety == 3.0
    assert pt_params["Percent Fine Clay"].numeric_value == 35.0
    assert pt_params["Thornwaite Moisture Index (Im)"].numeric_value == 18.0
    assert pt_params["Depth of Constant Soil Suction"].numeric_value == 9.0
    assert pt_params["Constant Soil Suction"].numeric_value == 3.45
    assert pt_params["Edge Moisture Variation Distance (em) - Center Lift"].numeric_value == 8.8
    assert pt_params["Edge Moisture Variation Distance (em) - Edge Lift"].numeric_value == 4.9
    assert pt_params["Differential Soil Movement (ym) - Center Lift"].numeric_value == 0.65
    assert pt_params["Differential Soil Movement (ym) - Edge Lift"].numeric_value == 0.49
    assert pt_params["Effective Plasticity Index"].numeric_value == 22.0

    # Drilled Underreamed Piers verification
    pier = recs_map["Drilled Underreamed Piers"]
    pier_params = {p.parameter_name: p for p in pier.parameters}
    assert pier_params["Maximum Pier Bell Diameter"].numeric_value == 5.0
    assert pier_params["Maximum Bell-to-Shaft Diameter Ratio"].numeric_value == 3.0
    assert "ratio of 3" in pier_params["Maximum Bell-to-Shaft Diameter Ratio"].conditions
    assert pier_params["Approximate Founding Depth"].numeric_value == 10.0
    assert pier_params["Allowable Net Bearing Pressure (Dead Load + Sustained Live Load)"].numeric_value == 2000.0
    assert pier_params["Allowable Net Bearing Pressure (Dead Load + Sustained Live Load)"].factor_of_safety == 3.0
    assert pier_params["Allowable Net Bearing Pressure (Total Dead + Transient Live Load)"].numeric_value == 3000.0
    assert pier_params["Allowable Net Bearing Pressure (Total Dead + Transient Live Load)"].factor_of_safety == 2.0
    assert pier_params["Allowable Shaft Friction"].numeric_value == 300.0
    assert "below a depth of 5 feet beneath finished grade" in pier_params["Allowable Shaft Friction"].conditions.lower()
    assert pier_params["Minimum Center-to-Center Pier Spacing"].numeric_value == 1.5
    assert "caving" in pier_params["Caving Risk and Construction Precautions"].value.lower()
    assert "casing" in pier_params["Caving Risk and Construction Precautions"].conditions

    # Continuous Footings / Grade Beams verification
    foot = recs_map["Continuous Footings / Grade Beams"]
    foot_params = {p.parameter_name: p for p in foot.parameters}
    assert foot_params["Minimum Select Fill Thickness"].numeric_value == 2.0
    assert foot_params["Minimum Footing Embedment Depth"].numeric_value == 2.5
    assert foot_params["Allowable Net Bearing Pressure (Dead Load + Sustained Live Load)"].numeric_value == 1800.0
    assert foot_params["Allowable Net Bearing Pressure (Dead Load + Sustained Live Load)"].factor_of_safety == 3.0
    assert foot_params["Allowable Net Bearing Pressure (Total Dead + Transient Live Load)"].numeric_value == 2700.0
    assert foot_params["Allowable Net Bearing Pressure (Total Dead + Transient Live Load)"].factor_of_safety == 2.0
    assert foot_params["Compaction Requirement"].numeric_value == 95.0
    assert foot_params["Settlement Warning"].numeric_value == 1.0
    assert "without proper compaction" in foot_params["Settlement Warning"].value.lower()
    assert "without proper compaction" in foot_params["Settlement Warning"].conditions.lower()

    # Separate Slab-on-Grade Floor recommendation verification (600 psf on 2 ft select fill)
    slab_floor = recs_map["Slab-on-Grade Floor"]
    slab_params = {p.parameter_name: p for p in slab_floor.parameters}
    assert slab_params["Minimum Select Fill Thickness"].numeric_value == 2.0
    assert slab_params["Allowable Net Bearing Pressure"].numeric_value == 600.0

    # 4. Review Status Verification
    # Automated extractions must be marked PENDING_REVIEW, never automatically verified
    for ev in result.evidence:
        assert ev.verification_status == "PENDING_REVIEW"


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_real_soil_report_site_preparation_requirements():
    """Verify all 12 site and subgrade preparation specifications from Section 1.3.1."""
    extractor = PDFExtractor()
    result = extractor.process_document(
        document_id="test-soil-report-siteprep",
        filename="Soil report 25-0117 v1.pdf",
        pdf_path=REAL_SOIL_REPORT_PATH,
        sha256_hash="test-sha-siteprep",
        file_size_bytes=REAL_SOIL_REPORT_PATH.stat().st_size,
    )

    # 1. Verify exactly 12 site preparation requirements
    assert len(result.site_preparation) == 12
    reqs = {r.requirement_name: r for r in result.site_preparation}

    # (1) Vegetation & Topsoil Removal
    veg = reqs["Vegetation and Organic Topsoil Stripping"]
    assert veg.numeric_value == 6.0
    assert veg.unit == "in"
    assert "at least 6 inches" in veg.original_value

    # (2) Removal of Soft / Unsuitable Soils
    soft = reqs["Removal of Unsuitable / Unstable Soils"]
    assert soft.numeric_value == 6.0
    assert soft.unit == "in"
    assert "select fill" in soft.original_value.lower()

    # (3) Extent Beyond Building Limits
    extent = reqs["Preparation Extent Beyond Building Limits"]
    assert extent.numeric_value == 5.0
    assert extent.unit == "ft"
    assert "at least 5 feet" in extent.original_value

    # (4) Select Fill Material Composition
    comp = reqs["Select Fill Material Composition"]
    assert "inactive lean clays and clayey sands" in comp.original_value.lower()

    # (5) Maximum Liquid Limit
    ll = reqs["Select Fill Maximum Liquid Limit"]
    assert ll.numeric_value == 35.0
    assert "35" in ll.original_value

    # (6) Plasticity Index Range
    pi = reqs["Select Fill Plasticity Index Range"]
    assert "8 to 20" in pi.original_value
    assert pi.numeric_value == 20.0

    # (7) Loose and Compacted Lift Thickness
    lift = reqs["Select Fill Lift Thickness"]
    assert lift.numeric_value == 8.0
    assert lift.unit == "in"
    assert "8-inch" in lift.original_value and "6-inch" in lift.original_value

    # (8) Minimum Compaction Percentage
    compaction = reqs["Select Fill Minimum Compaction Percentage"]
    assert compaction.numeric_value == 95.0
    assert compaction.unit == "%"
    assert compaction.standard_reference == "ASTM D 698"

    # (9) ASTM D 698 Reference
    astm = reqs["Compaction Test Standard Reference"]
    assert astm.standard_reference == "ASTM D 698"
    assert "ASTM D 698" in astm.original_value

    # (10) Moisture Tolerance
    moist = reqs["Select Fill Moisture Content Tolerance"]
    assert moist.numeric_value == 2.0
    assert moist.unit == "%"
    assert "+/- 2%" in moist.original_value

    # (11) Lift-by-Lift Testing
    test_req = reqs["Lift-by-Lift Density Compliance Testing"]
    assert "tested for density compliance" in test_req.original_value.lower()

    # (12) Proofrolling
    proof = reqs["Subgrade Proofrolling Requirement"]
    assert proof.numeric_value == 15.0
    assert proof.unit == "tons"
    assert "15-ton roller or heavier" in proof.original_value

    # 2. Verify all 12 have corresponding evidence records
    site_prep_evidence = [e for e in result.evidence if e.property_type == "site_preparation"]
    assert len(site_prep_evidence) == 12
    for ev in site_prep_evidence:
        assert ev.verification_status == "PENDING_REVIEW"
        assert ev.confidence_score >= 0.95
        assert ev.page_index in (6, 7)
        assert ev.printed_page_number in ("3", "4")


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_real_soil_report_api_endpoints(tmp_path):
    """Verify FastAPI service and endpoints for foundation recommendations, boring logs, and site preparation."""
    import sqlite3
    db_file = tmp_path / "test_api_docs.db"
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    doc_repo = DocumentRepository(conn)
    doc_storage = DocumentStorage(root_dir=tmp_path / "doc_storage")
    doc_service = DocumentService(repository=doc_repo, storage=doc_storage, extractor=PDFExtractor())

    # Ingest real soil report
    pdf_bytes = REAL_SOIL_REPORT_PATH.read_bytes()
    meta = doc_service.upload_document(
        filename="Soil report 25-0117 v1.pdf",
        content=pdf_bytes,
        project_id="geotech_audit",
    )
    assert meta.document_id is not None

    # 1. Foundation systems service method
    foundations = doc_service.get_foundation_recommendations(meta.document_id)
    assert len(foundations) == 4

    # 2. Site preparation service method
    site_prep = doc_service.get_site_preparation(meta.document_id)
    assert len(site_prep) == 12

    # 3. Boring logs service method
    boring_logs = doc_service.get_boring_logs(meta.document_id)
    b_ids = {b.boring_id for b in boring_logs}
    assert "B-1" in b_ids
    assert "B-2" in b_ids

    # 4. App endpoint test
    app = create_app()
    app.state.document_service = doc_service
    client = TestClient(app)

    # Foundation recommendations endpoint
    resp_f = client.get(f"/v1/documents/{meta.document_id}/foundation-recommendations")
    assert resp_f.status_code == 200
    assert len(resp_f.json()) == 4

    # Site preparation endpoint
    resp_sp = client.get(f"/v1/documents/{meta.document_id}/site-preparation")
    assert resp_sp.status_code == 200
    assert len(resp_sp.json()) == 12

    # Boring logs endpoint
    resp_b = client.get(f"/v1/documents/{meta.document_id}/boring-logs")
    assert resp_b.status_code == 200
    assert len(resp_b.json()) >= 2


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_real_soil_report_page_number_detection_and_separation():
    """Verify separate preservation of 1-indexed PDF page numbers and printed folios."""
    extractor = PDFExtractor()
    result = extractor.process_document(
        document_id="test-soil-report-pages",
        filename="Soil report 25-0117 v1.pdf",
        pdf_path=REAL_SOIL_REPORT_PATH,
        sha256_hash="test-sha-pages",
        file_size_bytes=REAL_SOIL_REPORT_PATH.stat().st_size,
    )

    pages_by_idx = {p.page_index: p for p in result.pages}

    # Body pages (0-indexed 4..14 -> Report Folios 1..11)
    for p_idx, expected_folio in [
        (4, "1"), (5, "2"), (6, "3"), (7, "4"), (8, "5"),
        (9, "6"), (10, "7"), (11, "8"), (12, "9"), (13, "10"), (14, "11"),
    ]:
        p = pages_by_idx[p_idx]
        assert p.printed_page_number == expected_folio
        # 1-indexed PDF page must be p_idx + 1
        assert p_idx + 1 == (5 if expected_folio == "1" else p_idx + 1)

    # Figures
    assert pages_by_idx[16].printed_page_number == "Figure 1"
    assert pages_by_idx[17].printed_page_number == "Figure 2"

    # Boring logs: B-1 is PDF Page 20 (p_idx 19), B-2 is PDF Page 21 (p_idx 20)
    assert pages_by_idx[19].page_index == 19  # PDF Page 20
    assert pages_by_idx[20].page_index == 20  # PDF Page 21
    assert pages_by_idx[19].printed_page_number == "1"  # "Page 1 of 1"
    assert pages_by_idx[20].printed_page_number == "1"  # "Page 1 of 1"


@pytest.mark.skipif(not REAL_SOIL_REPORT_PATH.exists(), reason="Soil report 25-0117 v1.pdf not present in local storage")
def test_real_soil_report_reprocessing_idempotence(tmp_path):
    """Verify that reprocessing produces identical database records without duplication or mutation."""
    import sqlite3
    db_file = tmp_path / "test_reprocess.db"
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    doc_repo = DocumentRepository(conn)
    doc_service = DocumentService(doc_repo, storage=DocumentStorage(tmp_path / "storage"))

    meta = doc_service.upload_document(
        filename="Soil report 25-0117 v1.pdf",
        content=REAL_SOIL_REPORT_PATH.read_bytes(),
        project_id="geotech_audit",
    )
    initial_evidence = doc_service.get_document_evidence(meta.document_id)
    initial_tables = doc_service.get_document_tables(meta.document_id)
    initial_count = len(initial_evidence)

    # Reprocess document
    reprocessed = doc_service.reprocess_document(meta.document_id)
    reprocessed_evidence = doc_service.get_document_evidence(meta.document_id)
    reprocessed_tables = doc_service.get_document_tables(meta.document_id)

    # Counts and tables must be identical
    assert len(reprocessed_evidence) == initial_count
    assert len(reprocessed_tables) == len(initial_tables)
    assert len(reprocessed.boring_logs) == 2
    assert len(reprocessed.foundation_recommendations) == 4
    assert len(reprocessed.site_preparation) == 12



