from __future__ import annotations

import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional
import pdfplumber
import pypdfium2

from .models import (
    BoundingBox,
    DocumentMetadata,
    DocumentPage,
    DocumentExtractionResult,
    ExtractedTable,
    EvidenceRecord,
    DocumentSection,
    BoringLogReference,
    FoundationSystemRecommendation,
    SitePreparationRequirement,
    FigureReference,
)
from .structure import (
    HEADING_PATTERN,
    BORING_PAGE_HEADER_PATTERN,
    BORING_ID_PATTERN,
    FIGURE_PATTERN,
    TECHNICAL_PATTERNS,
    extract_project_info,
    detect_printed_page_number,
)
from .evidence import (
    create_evidence_record,
    find_word_bounding_box,
    extract_context_snippet,
)
from .boring_extractor import BoringLogExtractor
from .table_processor import TableProcessor
from .foundation_extractor import FoundationExtractor
from .site_prep_extractor import SitePreparationExtractor
from .docling_adapter import DoclingAdapter

logger = logging.getLogger("agent_platform.documents.extractor")


class PDFExtractor:
    """Deterministic, memory-conscious PDF ingestion and geotechnical document extraction pipeline."""

    def __init__(self, docling_adapter: DoclingAdapter | None = None):
        self.docling = docling_adapter or DoclingAdapter()

    def render_page_image(
        self,
        pdf_path: str | Path,
        page_index: int,
        output_image_path: str | Path,
        scale: float = 2.0,
    ) -> Path:
        """Render a single PDF page to a crisp PNG image using pypdfium2."""
        out = Path(output_image_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        pdf = pypdfium2.PdfDocument(str(pdf_path))
        try:
            if page_index < 0 or page_index >= len(pdf):
                raise ValueError(f"Page index {page_index} out of range (total pages: {len(pdf)})")
            page = pdf[page_index]
            pil_image = page.render(scale=scale).to_pil()
            pil_image.save(out, format="PNG")
            return out
        finally:
            pdf.close()

    def process_document(
        self,
        document_id: str,
        filename: str,
        pdf_path: str | Path,
        sha256_hash: str,
        file_size_bytes: int,
        project_id: str = "default",
    ) -> DocumentExtractionResult:
        """Execute complete extraction pipeline over a PDF document."""
        started = time.perf_counter()
        pdf_path = Path(pdf_path)

        metadata = DocumentMetadata(
            document_id=document_id,
            project_id=project_id,
            filename=filename,
            sha256_hash=sha256_hash,
            file_size_bytes=file_size_bytes,
            storage_path=str(pdf_path),
            status="processing",
        )

        pages_result: list[DocumentPage] = []
        tables_result: list[ExtractedTable] = []
        evidence_result: list[EvidenceRecord] = []
        sections_result: list[DocumentSection] = []
        boring_logs_result: list[BoringLogReference] = []
        foundation_recs_result: list[FoundationSystemRecommendation] = []
        site_prep_result: list[SitePreparationRequirement] = []
        figures_result: list[FigureReference] = []
        drawing_notes_result: list[str] = []

        pages_text_by_index: dict[int, str] = {}
        pages_words_by_index: dict[int, list[dict[str, Any]]] = {}
        combined_first_pages_text: list[str] = []
        any_page_failed = False

        # Open PDF via pdfplumber
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                total_pages = len(pdf.pages)
                metadata.page_count = total_pages
                metadata.pdf_metadata = dict(pdf.metadata or {})

                scanned_page_count = 0

                # Process page by page (bounded memory allocation for 16GB RAM)
                for page_idx, page in enumerate(pdf.pages):
                    try:
                        page_w = float(page.width)
                        page_h = float(page.height)

                        # 1. Extract words and raw text
                        words = page.extract_words(
                            extra_attrs=["fontname", "size"]
                        )
                        raw_text = page.extract_text() or ""
                        char_count = len(raw_text)
                        word_count = len(words)
                        pages_text_by_index[page_idx] = raw_text
                        pages_words_by_index[page_idx] = words

                        # Body words excluding top/bottom 12% header/footer
                        top_margin = page_h * 0.12
                        bottom_margin = page_h * 0.88
                        body_words = [w for w in words if w.get("top", 0) > top_margin and w.get("bottom", page_h) < bottom_margin]
                        body_char_count = sum(len(w.get("text", "")) for w in body_words)

                        # Detect scanned vs text-based page
                        image_count = len(getattr(page, "images", []))
                        is_scanned = (image_count > 0 and (char_count < 30 or body_char_count < 30))
                        if is_scanned:
                            scanned_page_count += 1

                        is_empty = (char_count == 0 or body_char_count == 0) and image_count == 0
                        status = "empty" if is_empty else "extracted"

                        # 2. Detect printed page number (top/bottom margins)
                        printed_page = detect_printed_page_number(words, page_h)

                        # Save text for project info if in the first 3 pages
                        if page_idx < 3 and raw_text:
                            combined_first_pages_text.append(raw_text)

                        # 3. Detect Sections and Headings
                        page_headings: list[str] = []
                        lines = raw_text.split("\n")
                        for line in lines:
                            line_clean = line.strip()
                            if not line_clean:
                                continue
                            heading_m = HEADING_PATTERN.match(line_clean)
                            if heading_m:
                                sec_num = heading_m.group(1)
                                title = heading_m.group(2) or heading_m.group(3) or heading_m.group(4) or line_clean
                                page_headings.append(title.strip())

                                sec_bbox = find_word_bounding_box(words, title, page_w, page_h)
                                sections_result.append(
                                    DocumentSection(
                                        section_id=f"sec_{uuid.uuid4().hex[:8]}",
                                        title=title.strip(),
                                        section_number=sec_num,
                                        page_index=page_idx,
                                        printed_page_number=printed_page,
                                        bounding_box=sec_bbox,
                                        level=1 if (sec_num and sec_num.count(".") <= 1) else 2,
                                    )
                                )

                        # 4. Extract Tables & Boring Logs
                        page_tables_count = 0
                        page_evidence_count = 0
                        is_boring_page = BoringLogExtractor.is_boring_page(raw_text)

                        if is_boring_page:
                            # Specialist Boring Log Extractor: corrects reversed headers, aligns depths,
                            # enforces Auger SPT = NOT_REPORTED, extracts groundwater & stratum descriptions
                            try:
                                b_tbl, b_evidence, b_ref = BoringLogExtractor.extract_boring_log(
                                    page=page,
                                    page_index=page_idx,
                                    document_id=document_id,
                                    document_name=filename,
                                    printed_page_number=printed_page,
                                )
                                if b_tbl:
                                    tables_result.append(b_tbl)
                                    page_tables_count += 1
                                if b_evidence:
                                    evidence_result.extend(b_evidence)
                                    page_evidence_count += len(b_evidence)
                                if b_ref:
                                    # Replace any prior stub/placeholder reference for this boring_id (e.g. from TOC mentions)
                                    existing_idx = next((i for i, b in enumerate(boring_logs_result) if b.boring_id == b_ref.boring_id), None)
                                    if existing_idx is not None:
                                        boring_logs_result[existing_idx] = b_ref
                                    else:
                                        boring_logs_result.append(b_ref)
                            except Exception as b_err:
                                logger.error("Boring log extraction error on page %d: %s", page_idx, b_err)
                        else:
                            # Standard table extraction with defragmentation and classification
                            try:
                                raw_found_tables = page.find_tables()
                                processed_tables = TableProcessor.process_and_classify_page_tables(
                                    raw_tables=raw_found_tables,
                                    page_raw_text=raw_text,
                                    page_index=page_idx,
                                    document_id=document_id,
                                    page_width=page_w,
                                    page_height=page_h,
                                    printed_page_number=printed_page,
                                )
                                for tbl in processed_tables:
                                    tables_result.append(tbl)
                                    page_tables_count += 1

                                    # Emit cell-level evidence for non-legend engineering and laboratory tables
                                    if tbl.table_classification in ("laboratory_summary", "foundation_design_parameters", "engineering_data"):
                                        if tbl.table_name == "Allowable Net Bearing Pressures & Design Parameters":
                                            for r_i, r in enumerate(tbl.rows):
                                                param_name = r[0] if len(r) > 0 else ""
                                                val_str = r[1] if len(r) > 1 else ""
                                                fs_str = r[2] if len(r) > 2 else ""
                                                fs_val = float(fs_str) if fs_str and fs_str != "-" else None
                                                num_v = None
                                                num_m = re.search(r"([0-9,]+(?:\.[0-9]+)?)", val_str)
                                                if num_m:
                                                    try:
                                                        num_v = float(num_m.group(1).replace(",", ""))
                                                    except ValueError:
                                                        pass
                                                unit_v = "psf" if "psf" in val_str.lower() else ("%" if "%" in val_str else None)

                                                ev = create_evidence_record(
                                                    document_id=document_id,
                                                    document_name=filename,
                                                    page_index=page_idx,
                                                    printed_page_number=printed_page,
                                                    extracted_text=f"{param_name}: {val_str}" + (f" (FS {fs_str})" if fs_val else ""),
                                                    property_type="bearing_capacity" if "Load" in param_name else "soil_classification",
                                                    property_name=f"Allowable Bearing Pressure: {param_name}",
                                                    original_value=val_str,
                                                    numeric_value=num_v,
                                                    unit=unit_v,
                                                    bounding_box=tbl.bounding_box,
                                                    extraction_method="pdfplumber_table",
                                                    confidence_category="VERIFIED_TABLE_CELL",
                                                    confidence_score=tbl.confidence_score,
                                                    foundation_system="Post-Tensioned Slabs",
                                                    load_case=param_name if "Load" in param_name else None,
                                                    factor_of_safety=fs_val,
                                                    verification_status="PENDING_REVIEW",
                                                    context_snippet=f"{tbl.table_name} (Row {r_i + 1})",
                                                )
                                                evidence_result.append(ev)
                                                page_evidence_count += 1
                                        else:
                                            for r_i, r in enumerate(tbl.rows):
                                                for c_i, cell_val in enumerate(r):
                                                    cell_clean = str(cell_val).strip()
                                                    # Ignore empty cells or plain header words
                                                    if cell_clean and any(ch.isdigit() for ch in cell_clean):
                                                        col_h = tbl.headers[c_i] if c_i < len(tbl.headers) else f"Col_{c_i+1}"
                                                        ev = create_evidence_record(
                                                            document_id=document_id,
                                                            document_name=filename,
                                                            page_index=page_idx,
                                                            printed_page_number=printed_page,
                                                            extracted_text=f"{col_h}: {cell_clean}",
                                                            property_type="table_cell",
                                                            property_name=col_h or tbl.table_name,
                                                            original_value=cell_clean,
                                                            bounding_box=tbl.bounding_box,
                                                            extraction_method="pdfplumber_table",
                                                            confidence_category="VERIFIED_TABLE_CELL",
                                                            confidence_score=tbl.confidence_score,
                                                            verification_status="PENDING_REVIEW",
                                                            context_snippet=f"{tbl.table_name} (Row {r_i + 1})",
                                                        )
                                                        evidence_result.append(ev)
                                                        page_evidence_count += 1
                            except Exception as tbl_err:
                                logger.warning("Table extraction error on page %d: %s", page_idx, tbl_err)

                        # 5. Extract Geotechnical Technical Values & Evidence from text
                        for prop_type, patterns in TECHNICAL_PATTERNS.items():
                            for pat in patterns:
                                for m in pat.finditer(raw_text):
                                    match_text = m.group(0).strip()
                                    bbox = find_word_bounding_box(words, match_text, page_w, page_h)
                                    snippet = extract_context_snippet(raw_text, m.start(), m.end())

                                    # Extract captured number and unit from regex groups if present
                                    cap_num: Optional[float] = None
                                    cap_unit: Optional[str] = None
                                    if m.groups():
                                        for g in m.groups():
                                            if g is not None:
                                                try:
                                                    cap_num = float(str(g).strip().replace(",", ""))
                                                    break
                                                except ValueError:
                                                    pass
                                        for g in reversed(m.groups()):
                                            if g is not None and not any(ch.isdigit() for ch in str(g)):
                                                cap_unit = str(g).strip()
                                                break

                                    ev = create_evidence_record(
                                        document_id=document_id,
                                        document_name=filename,
                                        page_index=page_idx,
                                        printed_page_number=printed_page,
                                        extracted_text=match_text,
                                        property_type=prop_type,
                                        numeric_value=cap_num,
                                        unit=cap_unit,
                                        bounding_box=bbox,
                                        extraction_method="pdfplumber_text_coordinates",
                                        confidence_category="VERIFIED_TEXT",
                                        confidence_score=1.0,
                                        context_snippet=snippet,
                                    )
                                    evidence_result.append(ev)
                                    page_evidence_count += 1

                        # 6. Detect Boring Log References on non-boring pages
                        if not is_boring_page:
                            seen_bids = set()
                            for b_m in BORING_ID_PATTERN.finditer(raw_text):
                                clean_bid = (b_m.group(1) or b_m.group(2) or "").strip().upper()
                                if clean_bid and clean_bid not in seen_bids and len(clean_bid) <= 8:
                                    seen_bids.add(clean_bid)
                                    ev = create_evidence_record(
                                        document_id=document_id,
                                        document_name=filename,
                                        page_index=page_idx,
                                        printed_page_number=printed_page,
                                        extracted_text=f"Borehole {clean_bid}",
                                        property_type="boring_reference",
                                        property_name="Borehole Reference",
                                        original_value=clean_bid,
                                        boring_id=clean_bid,
                                        bounding_box=None,
                                        extraction_method="pdfplumber_text_coordinates",
                                        confidence_category="VERIFIED_TEXT",
                                        verification_status="PENDING_REVIEW",
                                    )
                                    evidence_result.append(ev)
                                    page_evidence_count += 1

                                    if not any(b.boring_id == clean_bid for b in boring_logs_result):
                                        boring_logs_result.append(
                                            BoringLogReference(
                                                boring_id=clean_bid,
                                                page_index=page_idx,
                                                printed_page_number=printed_page,
                                                evidence_id=ev.evidence_id,
                                            )
                                        )

                        # 7. Detect Figures & Drawings
                        for fig_m in FIGURE_PATTERN.finditer(raw_text):
                            fig_id = fig_m.group(1).strip()
                            fig_title = fig_m.group(3).strip()
                            fig_bbox = find_word_bounding_box(words, fig_id, page_w, page_h)
                            figures_result.append(
                                FigureReference(
                                    figure_id=fig_id,
                                    title=fig_title,
                                    page_index=page_idx,
                                    printed_page_number=printed_page,
                                    bounding_box=fig_bbox,
                                )
                            )

                        # 8. Detect Drawing Notes
                        for line in lines:
                            line_clean = line.strip()
                            if re.match(r"(?i)^(?:note|general\s+notes?|foundation\s+notes?)[:\s]", line_clean):
                                drawing_notes_result.append(line_clean)

                        pages_result.append(
                            DocumentPage(
                                page_index=page_idx,
                                printed_page_number=printed_page,
                                width=round(page_w, 2),
                                height=round(page_h, 2),
                                is_scanned=is_scanned,
                                char_count=char_count,
                                word_count=word_count,
                                raw_text=raw_text,
                                section_headings=page_headings,
                                tables_count=page_tables_count,
                                evidence_count=page_evidence_count,
                                status=status,
                            )
                        )

                    except Exception as page_exc:
                        logger.error("Failed to extract page %d of %s: %s", page_idx, filename, page_exc)
                        any_page_failed = True
                        pages_result.append(
                            DocumentPage(
                                page_index=page_idx,
                                status="failed",
                                error_message=str(page_exc),
                            )
                        )

                # Classify overall document type
                if total_pages > 0:
                    if scanned_page_count == total_pages:
                        metadata.is_scanned = True
                        metadata.document_type = "scanned"
                    elif scanned_page_count > 0:
                        metadata.is_scanned = True
                        metadata.document_type = "hybrid"
                    else:
                        metadata.is_scanned = False
                        metadata.document_type = "text_based"

                # Extract project info
                if combined_first_pages_text:
                    metadata.project_info = extract_project_info("\n".join(combined_first_pages_text))

                # Extract structured foundation recommendations (Post-Tensioned Slabs, Drilled Piers, Continuous Footings, Slab-on-Grade Floor)
                try:
                    found_recs, found_ev = FoundationExtractor.extract_foundation_systems(
                        pages_text_by_index=pages_text_by_index,
                        pages_words_by_index=pages_words_by_index,
                        document_id=document_id,
                        document_name=filename,
                    )
                    foundation_recs_result = found_recs
                    evidence_result.extend(found_ev)
                except Exception as f_err:
                    logger.error("Foundation recommendation extraction error for %s: %s", filename, f_err)

                # Extract structured site preparation specifications (Section 1.3.1)
                try:
                    prep_recs, prep_ev = SitePreparationExtractor.extract_site_preparation_requirements(
                        pages_text_by_index=pages_text_by_index,
                        pages_words_by_index=pages_words_by_index,
                        document_id=document_id,
                        document_name=filename,
                    )
                    site_prep_result = prep_recs
                    evidence_result.extend(prep_ev)
                except Exception as p_err:
                    logger.error("Site preparation extraction error for %s: %s", filename, p_err)

                metadata.status = "partially_extracted" if any_page_failed else "completed"

        except Exception as doc_exc:
            logger.error("Fatal document extraction failure for %s: %s", filename, doc_exc)
            metadata.status = "failed"
            metadata.error_message = str(doc_exc)

        duration = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "Extracted %s (pages=%d, tables=%d, evidence=%d) in %.1fms with status=%s",
            filename,
            len(pages_result),
            len(tables_result),
            len(evidence_result),
            duration,
            metadata.status,
        )

        return DocumentExtractionResult(
            metadata=metadata,
            pages=pages_result,
            tables=tables_result,
            evidence=evidence_result,
            sections=sections_result,
            boring_logs=boring_logs_result,
            foundation_recommendations=foundation_recs_result,
            site_preparation=site_prep_result,
            figures=figures_result,
            drawing_notes=drawing_notes_result,
            processing_duration_ms=duration,
        )
