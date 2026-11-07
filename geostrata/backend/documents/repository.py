from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import sqlite3
import threading
from typing import Any, Optional

from .models import (
    BoundingBox,
    DocumentMetadata,
    DocumentPage,
    DocumentExtractionResult,
    ExtractedTable,
    EvidenceRecord,
    ProjectInfo,
)
from .vision.models import (
    VisualEvidence,
    VisualRegion,
    CrossModalDisagreement,
    PageContentType,
)
from .matching_models import (
    DocumentProjectAssociation,
    FieldComparison,
    MatchStatus,
    UserDecision,
)

logger = logging.getLogger("agent_platform.documents.repository")


class DocumentRepository:
    """Thread-safe SQLite repository for document metadata, pages, tables, and evidence records."""

    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock | None = None):
        self._conn = connection
        self._lock = lock or threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    sha256_hash TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    is_scanned INTEGER NOT NULL DEFAULT 0,
                    document_type TEXT NOT NULL DEFAULT 'text_based',
                    status TEXT NOT NULL DEFAULT 'uploaded',
                    storage_path TEXT NOT NULL DEFAULT '',
                    error_message TEXT,
                    pdf_metadata TEXT,
                    project_info TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents (sha256_hash, project_id)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document_pages (
                    document_id TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    printed_page_number TEXT,
                    width REAL NOT NULL DEFAULT 612.0,
                    height REAL NOT NULL DEFAULT 792.0,
                    is_scanned INTEGER NOT NULL DEFAULT 0,
                    char_count INTEGER NOT NULL DEFAULT 0,
                    word_count INTEGER NOT NULL DEFAULT 0,
                    raw_text TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'extracted',
                    error_message TEXT,
                    PRIMARY KEY (document_id, page_index)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document_tables (
                    table_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    printed_page_number TEXT,
                    table_name TEXT,
                    table_classification TEXT NOT NULL DEFAULT 'engineering_data',
                    headers TEXT NOT NULL,
                    rows TEXT NOT NULL,
                    bounding_box TEXT,
                    caption TEXT,
                    cell_count INTEGER NOT NULL DEFAULT 0,
                    confidence_score REAL NOT NULL DEFAULT 1.0,
                    is_fragment INTEGER NOT NULL DEFAULT 0,
                    parent_table_id TEXT
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_tables_doc ON document_tables (document_id, page_index)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    document_name TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    printed_page_number TEXT,
                    extracted_text TEXT NOT NULL,
                    property_type TEXT,
                    property_name TEXT,
                    original_value TEXT NOT NULL DEFAULT '',
                    numeric_value REAL,
                    unit TEXT,
                    boring_id TEXT,
                    depth TEXT,
                    bounding_box TEXT,
                    extraction_method TEXT NOT NULL,
                    verification_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                    confidence_category TEXT NOT NULL DEFAULT 'VERIFIED_TEXT',
                    confidence_score REAL NOT NULL DEFAULT 1.0,
                    is_reported INTEGER NOT NULL DEFAULT 1,
                    foundation_system TEXT,
                    load_case TEXT,
                    factor_of_safety REAL,
                    conditions TEXT,
                    context_snippet TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_doc ON document_evidence (document_id, page_index)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_evidence_prop ON document_evidence (property_type)"
            )

            # Multimodal Visual Evidence table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document_visual_evidence (
                    visual_evidence_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    pdf_page_number INTEGER NOT NULL,
                    printed_page_number TEXT,
                    content_type TEXT NOT NULL,
                    title_or_caption TEXT,
                    visual_description TEXT NOT NULL DEFAULT '',
                    extracted_labels TEXT NOT NULL DEFAULT '[]',
                    detected_entities TEXT NOT NULL DEFAULT '[]',
                    structured_findings TEXT NOT NULL DEFAULT '{}',
                    detected_regions TEXT NOT NULL DEFAULT '[]',
                    bounding_box TEXT,
                    crop_coordinates TEXT,
                    extraction_method TEXT NOT NULL DEFAULT 'vlm_vision_prompt',
                    vision_model TEXT,
                    confidence_category TEXT NOT NULL DEFAULT 'HIGH',
                    review_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                    human_notes TEXT,
                    verified_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_evidence_doc ON document_visual_evidence (document_id, page_index)"
            )

            # Cross-modal Disagreements table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document_visual_disagreements (
                    disagreement_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    property_name TEXT NOT NULL,
                    text_value TEXT,
                    table_value TEXT,
                    visual_value TEXT,
                    discrepancy_description TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'MEDIUM',
                    status TEXT NOT NULL DEFAULT 'OPEN',
                    resolution_notes TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_visual_disagreements_doc ON document_visual_disagreements (document_id, page_index)"
            )

            # Auto-migrate existing tables with missing columns
            existing_tables_cols = {row[1] for row in cur.execute("PRAGMA table_info(document_tables)").fetchall()}
            if "table_name" not in existing_tables_cols:
                try:
                    cur.execute("ALTER TABLE document_tables ADD COLUMN table_name TEXT")
                    cur.execute("ALTER TABLE document_tables ADD COLUMN table_classification TEXT NOT NULL DEFAULT 'engineering_data'")
                    cur.execute("ALTER TABLE document_tables ADD COLUMN confidence_score REAL NOT NULL DEFAULT 1.0")
                    cur.execute("ALTER TABLE document_tables ADD COLUMN is_fragment INTEGER NOT NULL DEFAULT 0")
                    cur.execute("ALTER TABLE document_tables ADD COLUMN parent_table_id TEXT")
                except sqlite3.OperationalError:
                    pass

            existing_ev_cols = {row[1] for row in cur.execute("PRAGMA table_info(document_evidence)").fetchall()}
            if "property_name" not in existing_ev_cols:
                try:
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN property_name TEXT")
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN original_value TEXT NOT NULL DEFAULT ''")
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN numeric_value REAL")
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN unit TEXT")
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN boring_id TEXT")
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN depth TEXT")
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN confidence_category TEXT NOT NULL DEFAULT 'VERIFIED_TEXT'")
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN is_reported INTEGER NOT NULL DEFAULT 1")
                except sqlite3.OperationalError:
                    pass

            if "foundation_system" not in existing_ev_cols:
                try:
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN foundation_system TEXT")
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN load_case TEXT")
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN factor_of_safety REAL")
                    cur.execute("ALTER TABLE document_evidence ADD COLUMN conditions TEXT")
                except sqlite3.OperationalError:
                    pass

            # Document Project Associations table
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS document_project_associations (
                    association_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    filename TEXT NOT NULL DEFAULT '',
                    match_status TEXT NOT NULL,
                    confidence_score REAL NOT NULL DEFAULT 0.0,
                    match_reasons TEXT NOT NULL DEFAULT '[]',
                    conflict_reasons TEXT NOT NULL DEFAULT '[]',
                    field_comparisons TEXT NOT NULL DEFAULT '[]',
                    user_decision TEXT NOT NULL DEFAULT 'PENDING',
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_assoc_proj ON document_project_associations (project_id, document_id)"
            )

            self._conn.commit()

    def find_by_sha256(self, sha256_hash: str, project_id: str = "default") -> Optional[DocumentMetadata]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM documents WHERE sha256_hash = ? AND project_id = ? LIMIT 1",
                (sha256_hash, project_id),
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_metadata(row, cur.description)

    def _save_metadata_unlocked(self, cur: sqlite3.Cursor, metadata: DocumentMetadata) -> None:
        pdf_meta = dict(metadata.pdf_metadata)
        if metadata.readiness_status:
            pdf_meta["readiness_status"] = metadata.readiness_status
        cur.execute(
            """
            INSERT OR REPLACE INTO documents (
                document_id, project_id, filename, sha256_hash, file_size_bytes,
                page_count, is_scanned, document_type, status, storage_path,
                error_message, pdf_metadata, project_info, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metadata.document_id,
                metadata.project_id,
                metadata.filename,
                metadata.sha256_hash,
                metadata.file_size_bytes,
                metadata.page_count,
                1 if metadata.is_scanned else 0,
                metadata.document_type,
                metadata.status,
                metadata.storage_path,
                metadata.error_message,
                json.dumps(pdf_meta),
                metadata.project_info.model_dump_json() if metadata.project_info else None,
                metadata.created_at,
                metadata.updated_at,
            ),
        )

    def save_document_metadata(self, metadata: DocumentMetadata) -> None:
        with self._lock:
            cur = self._conn.cursor()
            self._save_metadata_unlocked(cur, metadata)
            self._conn.commit()

    def update_document_status(
        self, document_id: str, status: str, error_message: str | None = None
    ) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE documents SET status = ?, error_message = ? WHERE document_id = ?",
                (status, error_message, document_id),
            )
            self._conn.commit()

    def save_extraction_result(self, result: DocumentExtractionResult) -> None:
        with self._lock:
            cur = self._conn.cursor()
            self._save_metadata_unlocked(cur, result.metadata)

            # Clear any previous pages, tables, and evidence for clean reprocessing
            cur.execute("DELETE FROM document_pages WHERE document_id = ?", (result.metadata.document_id,))
            cur.execute("DELETE FROM document_tables WHERE document_id = ?", (result.metadata.document_id,))
            cur.execute("DELETE FROM document_evidence WHERE document_id = ?", (result.metadata.document_id,))

            # Save pages
            for page in result.pages:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO document_pages (
                        document_id, page_index, printed_page_number, width, height,
                        is_scanned, char_count, word_count, raw_text, status, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.metadata.document_id,
                        page.page_index,
                        page.printed_page_number,
                        page.width,
                        page.height,
                        1 if page.is_scanned else 0,
                        page.char_count,
                        page.word_count,
                        page.raw_text,
                        page.status,
                        page.error_message,
                    ),
                )

            # Save tables
            for tbl in result.tables:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO document_tables (
                        table_id, document_id, page_index, printed_page_number,
                        table_name, table_classification, headers, rows,
                        bounding_box, caption, cell_count, confidence_score,
                        is_fragment, parent_table_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tbl.table_id,
                        tbl.document_id,
                        tbl.page_index,
                        tbl.printed_page_number,
                        tbl.table_name,
                        tbl.table_classification,
                        json.dumps(tbl.headers),
                        json.dumps(tbl.rows),
                        tbl.bounding_box.model_dump_json() if tbl.bounding_box else None,
                        tbl.caption,
                        tbl.cell_count,
                        tbl.confidence_score,
                        1 if tbl.is_fragment else 0,
                        tbl.parent_table_id,
                    ),
                )

            # Save evidence records
            for ev in result.evidence:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO document_evidence (
                        evidence_id, document_id, document_name, page_index,
                        printed_page_number, extracted_text, property_type,
                        property_name, original_value, numeric_value, unit,
                        boring_id, depth, bounding_box, extraction_method,
                        verification_status, confidence_category, confidence_score,
                        is_reported, foundation_system, load_case, factor_of_safety,
                        conditions, context_snippet, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev.evidence_id,
                        ev.document_id,
                        ev.document_name,
                        ev.page_index,
                        ev.printed_page_number,
                        ev.extracted_text,
                        ev.property_type,
                        ev.property_name,
                        ev.original_value,
                        ev.numeric_value,
                        ev.unit,
                        ev.boring_id,
                        ev.depth,
                        ev.bounding_box.model_dump_json() if ev.bounding_box else None,
                        ev.extraction_method,
                        ev.verification_status,
                        ev.confidence_category,
                        ev.confidence_score,
                        1 if ev.is_reported else 0,
                        ev.foundation_system,
                        ev.load_case,
                        ev.factor_of_safety,
                        ev.conditions,
                        ev.context_snippet,
                        ev.created_at,
                    ),
                )

            self._conn.commit()

    def get_document(self, document_id: str) -> Optional[DocumentMetadata]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT * FROM documents WHERE document_id = ?", (document_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_metadata(row, cur.description)

    def list_documents(self, project_id: Optional[str] = None) -> list[DocumentMetadata]:
        with self._lock:
            cur = self._conn.cursor()
            if project_id:
                cur.execute(
                    "SELECT * FROM documents WHERE project_id = ? ORDER BY created_at DESC",
                    (project_id,),
                )
            else:
                cur.execute("SELECT * FROM documents ORDER BY created_at DESC")
            rows = cur.fetchall()
            return [self._row_to_metadata(r, cur.description) for r in rows]

    def save_document_pages(self, document_id: str, pages: list[DocumentPage]) -> None:
        with self._lock:
            cur = self._conn.cursor()
            for page in pages:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO document_pages (
                        document_id, page_index, printed_page_number, width, height,
                        is_scanned, char_count, word_count, raw_text, status, error_message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        page.page_index,
                        page.printed_page_number,
                        page.width,
                        page.height,
                        1 if page.is_scanned else 0,
                        page.char_count,
                        page.word_count,
                        page.raw_text,
                        page.status,
                        page.error_message,
                    ),
                )
            self._conn.commit()

    def get_document_pages(self, document_id: str) -> list[DocumentPage]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM document_pages WHERE document_id = ? ORDER BY page_index ASC",
                (document_id,),
            )
            rows = cur.fetchall()
            pages: list[DocumentPage] = []
            for r in rows:
                d = dict(zip([col[0] for col in cur.description], r))
                pages.append(
                    DocumentPage(
                        page_index=d["page_index"],
                        printed_page_number=d.get("printed_page_number"),
                        width=d["width"],
                        height=d["height"],
                        is_scanned=bool(d["is_scanned"]),
                        char_count=d["char_count"],
                        word_count=d["word_count"],
                        raw_text=d["raw_text"],
                        status=d["status"],
                        error_message=d.get("error_message"),
                    )
                )
            return pages

    def get_document_page(self, document_id: str, page_index: int) -> Optional[DocumentPage]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM document_pages WHERE document_id = ? AND page_index = ?",
                (document_id, page_index),
            )
            row = cur.fetchone()
            if not row:
                return None
            d = dict(zip([col[0] for col in cur.description], row))
            return DocumentPage(
                page_index=d["page_index"],
                printed_page_number=d.get("printed_page_number"),
                width=d["width"],
                height=d["height"],
                is_scanned=bool(d["is_scanned"]),
                char_count=d["char_count"],
                word_count=d["word_count"],
                raw_text=d["raw_text"],
                status=d["status"],
                error_message=d.get("error_message"),
            )

    def get_document_tables(self, document_id: str) -> list[ExtractedTable]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM document_tables WHERE document_id = ? ORDER BY page_index ASC",
                (document_id,),
            )
            rows = cur.fetchall()
            tables: list[ExtractedTable] = []
            for r in rows:
                d = dict(zip([col[0] for col in cur.description], r))
                bbox = BoundingBox.model_validate_json(d["bounding_box"]) if d.get("bounding_box") else None
                tables.append(
                    ExtractedTable(
                        table_id=d["table_id"],
                        document_id=d["document_id"],
                        page_index=d["page_index"],
                        printed_page_number=d.get("printed_page_number"),
                        table_name=d.get("table_name"),
                        table_classification=d.get("table_classification") or "engineering_data",
                        headers=json.loads(d["headers"]),
                        rows=json.loads(d["rows"]),
                        bounding_box=bbox,
                        caption=d.get("caption"),
                        cell_count=d.get("cell_count", 0),
                        confidence_score=d.get("confidence_score", 1.0),
                        is_fragment=bool(d.get("is_fragment", 0)),
                        parent_table_id=d.get("parent_table_id"),
                    )
                )
            return tables

    def get_document_evidence(
        self,
        document_id: str,
        property_type: str | None = None,
        confidence_category: str | None = None,
        boring_id: str | None = None,
        page_index: int | None = None,
    ) -> list[EvidenceRecord]:
        with self._lock:
            cur = self._conn.cursor()
            query = "SELECT * FROM document_evidence WHERE document_id = ?"
            params: list[Any] = [document_id]

            if property_type:
                query += " AND property_type = ?"
                params.append(property_type)
            if confidence_category:
                query += " AND confidence_category = ?"
                params.append(confidence_category)
            if boring_id:
                query += " AND boring_id = ?"
                params.append(boring_id)
            if page_index is not None:
                query += " AND page_index = ?"
                params.append(page_index)

            query += " ORDER BY page_index ASC, created_at ASC"
            cur.execute(query, tuple(params))
            rows = cur.fetchall()

            evidence_list: list[EvidenceRecord] = []
            for r in rows:
                d = dict(zip([col[0] for col in cur.description], r))
                bbox = BoundingBox.model_validate_json(d["bounding_box"]) if d.get("bounding_box") else None
                evidence_list.append(
                    EvidenceRecord(
                        evidence_id=d["evidence_id"],
                        document_id=d["document_id"],
                        document_name=d["document_name"],
                        page_index=d["page_index"],
                        printed_page_number=d.get("printed_page_number"),
                        extracted_text=d["extracted_text"],
                        property_type=d.get("property_type"),
                        property_name=d.get("property_name"),
                        original_value=d.get("original_value") or d["extracted_text"],
                        numeric_value=d.get("numeric_value"),
                        unit=d.get("unit"),
                        boring_id=d.get("boring_id"),
                        depth=d.get("depth"),
                        bounding_box=bbox,
                        extraction_method=d["extraction_method"],
                        verification_status=d["verification_status"],
                        confidence_category=d.get("confidence_category") or "VERIFIED_TEXT",
                        confidence_score=d.get("confidence_score", 1.0),
                        is_reported=bool(d.get("is_reported", 1)),
                        foundation_system=d.get("foundation_system"),
                        load_case=d.get("load_case"),
                        factor_of_safety=d.get("factor_of_safety"),
                        conditions=d.get("conditions"),
                        context_snippet=d.get("context_snippet"),
                        created_at=d["created_at"],
                    )
                )
            return evidence_list

    def update_evidence_status(self, evidence_id: str, status: str) -> bool:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "UPDATE document_evidence SET verification_status = ? WHERE evidence_id = ?",
                (status, evidence_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delete_document(self, document_id: str) -> bool:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM document_visual_disagreements WHERE document_id = ?", (document_id,))
            cur.execute("DELETE FROM document_visual_evidence WHERE document_id = ?", (document_id,))
            cur.execute("DELETE FROM document_evidence WHERE document_id = ?", (document_id,))
            cur.execute("DELETE FROM document_tables WHERE document_id = ?", (document_id,))
            cur.execute("DELETE FROM document_pages WHERE document_id = ?", (document_id,))
            cur.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ==========================================================================
    # Visual Evidence & Cross-Modal Disagreements
    # ==========================================================================

    def save_visual_evidence(self, ev: VisualEvidence) -> None:
        with self._lock:
            cur = self._conn.cursor()
            bbox_json = ev.bounding_box.model_dump_json() if ev.bounding_box else None
            crop_json = json.dumps(ev.crop_coordinates) if ev.crop_coordinates else None
            labels_json = json.dumps(ev.extracted_labels)
            entities_json = json.dumps(ev.detected_entities)
            findings_json = json.dumps(ev.structured_findings)
            regions_json = json.dumps([r.model_dump() for r in ev.detected_regions])

            cur.execute(
                """
                INSERT INTO document_visual_evidence (
                    visual_evidence_id, document_id, page_index, pdf_page_number,
                    printed_page_number, content_type, title_or_caption, visual_description,
                    extracted_labels, detected_entities, structured_findings, detected_regions,
                    bounding_box, crop_coordinates, extraction_method, vision_model,
                    confidence_category, review_status, human_notes, verified_by,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(visual_evidence_id) DO UPDATE SET
                    content_type = excluded.content_type,
                    title_or_caption = excluded.title_or_caption,
                    visual_description = excluded.visual_description,
                    extracted_labels = excluded.extracted_labels,
                    detected_entities = excluded.detected_entities,
                    structured_findings = excluded.structured_findings,
                    detected_regions = excluded.detected_regions,
                    bounding_box = excluded.bounding_box,
                    crop_coordinates = excluded.crop_coordinates,
                    extraction_method = excluded.extraction_method,
                    vision_model = excluded.vision_model,
                    confidence_category = excluded.confidence_category,
                    review_status = excluded.review_status,
                    human_notes = excluded.human_notes,
                    verified_by = excluded.verified_by,
                    updated_at = excluded.updated_at
                """,
                (
                    ev.visual_evidence_id,
                    ev.document_id,
                    ev.page_index,
                    ev.pdf_page_number,
                    ev.printed_page_number,
                    ev.content_type.value if hasattr(ev.content_type, "value") else str(ev.content_type),
                    ev.title_or_caption,
                    ev.visual_description,
                    labels_json,
                    entities_json,
                    findings_json,
                    regions_json,
                    bbox_json,
                    crop_json,
                    ev.extraction_method,
                    ev.vision_model,
                    ev.confidence_category,
                    ev.review_status,
                    ev.human_notes,
                    ev.verified_by,
                    ev.created_at,
                    ev.updated_at,
                ),
            )
            self._conn.commit()

    def save_visual_evidence_batch(self, evidence_list: list[VisualEvidence]) -> None:
        for ev in evidence_list:
            self.save_visual_evidence(ev)

    def get_visual_evidence(
        self,
        document_id: str,
        page_index: Optional[int] = None,
    ) -> list[VisualEvidence]:
        with self._lock:
            cur = self._conn.cursor()
            if page_index is not None:
                cur.execute(
                    "SELECT * FROM document_visual_evidence WHERE document_id = ? AND page_index = ? ORDER BY created_at ASC",
                    (document_id, page_index),
                )
            else:
                cur.execute(
                    "SELECT * FROM document_visual_evidence WHERE document_id = ? ORDER BY page_index ASC, created_at ASC",
                    (document_id,),
                )
            rows = cur.fetchall()
            cols = [c[0] for c in cur.description]
            return [self._row_to_visual_evidence(r, cols) for r in rows]

    def get_visual_evidence_by_id(self, visual_evidence_id: str) -> Optional[VisualEvidence]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM document_visual_evidence WHERE visual_evidence_id = ?",
                (visual_evidence_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [c[0] for c in cur.description]
            return self._row_to_visual_evidence(row, cols)

    def update_visual_evidence_review(
        self,
        visual_evidence_id: str,
        review_status: str,
        human_notes: Optional[str] = None,
        verified_by: Optional[str] = None,
    ) -> bool:
        with self._lock:
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat()
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE document_visual_evidence
                SET review_status = ?, human_notes = COALESCE(?, human_notes),
                    verified_by = COALESCE(?, verified_by), updated_at = ?
                WHERE visual_evidence_id = ?
                """,
                (review_status, human_notes, verified_by, now_iso, visual_evidence_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def save_visual_disagreements(self, disagreements: list[CrossModalDisagreement]) -> None:
        with self._lock:
            cur = self._conn.cursor()
            for d in disagreements:
                cur.execute(
                    """
                    INSERT INTO document_visual_disagreements (
                        disagreement_id, document_id, page_index, property_name,
                        text_value, table_value, visual_value, discrepancy_description,
                        severity, status, resolution_notes, created_at, resolved_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(disagreement_id) DO UPDATE SET
                        status = excluded.status,
                        resolution_notes = excluded.resolution_notes,
                        resolved_at = excluded.resolved_at
                    """,
                    (
                        d.disagreement_id,
                        d.document_id,
                        d.page_index,
                        d.property_name,
                        d.text_value,
                        d.table_value,
                        d.visual_value,
                        d.discrepancy_description,
                        d.severity,
                        d.status,
                        d.resolution_notes,
                        d.created_at,
                        d.resolved_at,
                    ),
                )
            self._conn.commit()

    def get_visual_disagreements(
        self,
        document_id: str,
        status: Optional[str] = None,
    ) -> list[CrossModalDisagreement]:
        with self._lock:
            cur = self._conn.cursor()
            if status:
                cur.execute(
                    "SELECT * FROM document_visual_disagreements WHERE document_id = ? AND status = ? ORDER BY created_at DESC",
                    (document_id, status),
                )
            else:
                cur.execute(
                    "SELECT * FROM document_visual_disagreements WHERE document_id = ? ORDER BY created_at DESC",
                    (document_id,),
                )
            rows = cur.fetchall()
            cols = [c[0] for c in cur.description]
            results: list[CrossModalDisagreement] = []
            for r in rows:
                data = dict(zip(cols, r))
                results.append(
                    CrossModalDisagreement(
                        disagreement_id=data["disagreement_id"],
                        document_id=data["document_id"],
                        page_index=data["page_index"],
                        property_name=data["property_name"],
                        text_value=data.get("text_value"),
                        table_value=data.get("table_value"),
                        visual_value=data.get("visual_value"),
                        discrepancy_description=data["discrepancy_description"],
                        severity=data["severity"],
                        status=data["status"],
                        resolution_notes=data.get("resolution_notes"),
                        created_at=data["created_at"],
                        resolved_at=data.get("resolved_at"),
                    )
                )
            return results

    def update_visual_disagreement_status(
        self,
        disagreement_id: str,
        status: str,
        resolution_notes: Optional[str] = None,
    ) -> bool:
        with self._lock:
            from datetime import datetime, timezone
            now_iso = datetime.now(timezone.utc).isoformat() if status in ("RESOLVED", "IGNORED") else None
            cur = self._conn.cursor()
            cur.execute(
                """
                UPDATE document_visual_disagreements
                SET status = ?, resolution_notes = COALESCE(?, resolution_notes), resolved_at = ?
                WHERE disagreement_id = ?
                """,
                (status, resolution_notes, now_iso, disagreement_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def _row_to_visual_evidence(self, row: tuple, cols: list[str]) -> VisualEvidence:
        data = dict(zip(cols, row))
        bbox = BoundingBox.model_validate_json(data["bounding_box"]) if data.get("bounding_box") else None
        crop = json.loads(data["crop_coordinates"]) if data.get("crop_coordinates") else None
        labels = json.loads(data["extracted_labels"]) if data.get("extracted_labels") else []
        entities = json.loads(data["detected_entities"]) if data.get("detected_entities") else []
        findings = json.loads(data["structured_findings"]) if data.get("structured_findings") else {}
        regions_raw = json.loads(data["detected_regions"]) if data.get("detected_regions") else []
        regions = [VisualRegion.model_validate(r) for r in regions_raw]

        return VisualEvidence(
            visual_evidence_id=data["visual_evidence_id"],
            document_id=data["document_id"],
            page_index=data["page_index"],
            pdf_page_number=data["pdf_page_number"],
            printed_page_number=data.get("printed_page_number"),
            content_type=PageContentType(data["content_type"]) if data["content_type"] in PageContentType.__members__ else PageContentType.UNKNOWN,
            title_or_caption=data.get("title_or_caption"),
            visual_description=data.get("visual_description", ""),
            extracted_labels=labels,
            detected_entities=entities,
            structured_findings=findings,
            detected_regions=regions,
            bounding_box=bbox,
            crop_coordinates=crop,
            extraction_method=data.get("extraction_method", "vlm_vision_prompt"),
            vision_model=data.get("vision_model"),
            confidence_category=data.get("confidence_category", "HIGH"),
            review_status=data.get("review_status", "PENDING_REVIEW"),
            human_notes=data.get("human_notes"),
            verified_by=data.get("verified_by"),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )


    def _row_to_metadata(self, row: tuple, description: Any) -> DocumentMetadata:
        d = dict(zip([col[0] for col in description], row))
        pdf_meta = json.loads(d["pdf_metadata"]) if d.get("pdf_metadata") else {}
        proj_info = ProjectInfo.model_validate_json(d["project_info"]) if d.get("project_info") else None
        readiness = d.get("readiness_status") or pdf_meta.get("readiness_status")
        return DocumentMetadata(
            document_id=d["document_id"],
            project_id=d["project_id"],
            filename=d["filename"],
            sha256_hash=d["sha256_hash"],
            file_size_bytes=d["file_size_bytes"],
            page_count=d["page_count"],
            is_scanned=bool(d["is_scanned"]),
            document_type=d["document_type"],
            status=d["status"],
            readiness_status=readiness,
            storage_path=d["storage_path"],
            error_message=d.get("error_message"),
            pdf_metadata=pdf_meta,
            project_info=proj_info,
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )

    # =========================================================================
    # Multi-Document Project Associations
    # =========================================================================

    def save_document_association(self, assoc: DocumentProjectAssociation) -> None:
        """Insert or replace a document-to-project association record."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO document_project_associations (
                    association_id, project_id, document_id, filename,
                    match_status, confidence_score, match_reasons, conflict_reasons,
                    field_comparisons, user_decision, reviewed_by, reviewed_at,
                    notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assoc.association_id,
                    assoc.project_id,
                    assoc.document_id,
                    assoc.filename,
                    assoc.match_status.value,
                    assoc.confidence_score,
                    json.dumps(assoc.match_reasons),
                    json.dumps(assoc.conflict_reasons),
                    json.dumps([fc.model_dump() for fc in assoc.field_comparisons]),
                    assoc.user_decision.value,
                    assoc.reviewed_by,
                    assoc.reviewed_at,
                    assoc.notes,
                    assoc.created_at,
                    assoc.updated_at,
                ),
            )
            self._conn.commit()

    def get_document_associations(self, project_id: str) -> list[DocumentProjectAssociation]:
        """Retrieve all document associations for a project."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM document_project_associations WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            )
            rows = cur.fetchall()
            return [self._row_to_association(r, cur.description) for r in rows]

    def get_document_association(self, association_id: str) -> Optional[DocumentProjectAssociation]:
        """Retrieve a specific association by ID."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT * FROM document_project_associations WHERE association_id = ? LIMIT 1",
                (association_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_association(row, cur.description)

    def update_association_decision(
        self,
        association_id: str,
        decision: UserDecision,
        reviewed_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[DocumentProjectAssociation]:
        """Update the human confirmation/rejection decision on an association."""
        with self._lock:
            cur = self._conn.cursor()
            now_iso = datetime.now(timezone.utc).isoformat()
            cur.execute(
                """
                UPDATE document_project_associations
                SET user_decision = ?, reviewed_by = ?, reviewed_at = ?, notes = ?, updated_at = ?
                WHERE association_id = ?
                """,
                (decision.value, reviewed_by, now_iso, notes, now_iso, association_id),
            )
            self._conn.commit()
            return self.get_document_association(association_id)

    def get_confirmed_document_ids(self, project_id: str) -> list[str]:
        """Return document IDs that are confirmed for multi-document project analysis.

        Includes documents where match_status == 'MATCHED' and user_decision != 'REJECTED',
        or where user_decision == 'CONFIRMED'.
        """
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT document_id FROM document_project_associations
                WHERE project_id = ? AND (
                    (match_status = 'MATCHED' AND user_decision != 'REJECTED')
                    OR user_decision = 'CONFIRMED'
                )
                """,
                (project_id,),
            )
            return [row[0] for row in cur.fetchall()]

    def _row_to_association(self, row: tuple, description: Any) -> DocumentProjectAssociation:
        d = dict(zip([col[0] for col in description], row))
        comparisons_raw = json.loads(d["field_comparisons"]) if d.get("field_comparisons") else []
        comparisons = [FieldComparison.model_validate(c) for c in comparisons_raw]
        return DocumentProjectAssociation(
            association_id=d["association_id"],
            project_id=d["project_id"],
            document_id=d["document_id"],
            filename=d.get("filename", ""),
            match_status=MatchStatus(d["match_status"]),
            confidence_score=float(d["confidence_score"]),
            match_reasons=json.loads(d["match_reasons"]) if d.get("match_reasons") else [],
            conflict_reasons=json.loads(d["conflict_reasons"]) if d.get("conflict_reasons") else [],
            field_comparisons=comparisons,
            user_decision=UserDecision(d["user_decision"]),
            reviewed_by=d.get("reviewed_by"),
            reviewed_at=d.get("reviewed_at"),
            notes=d.get("notes"),
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )

