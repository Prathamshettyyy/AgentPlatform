from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from .models import (
    RequirementDocument,
    RequirementReview,
    RequirementReviewStatus,
)

logger = logging.getLogger("agent_platform.requirement_agent.repository")


class RequirementAgentRepository:
    """Thread-safe SQLite repository for Vendor Foundation Requirement Documents and review audit records."""

    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock | None = None) -> None:
        self._conn = connection
        self._lock = lock or threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vendor_requirement_reports (
                    report_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    geotechnical_report_id TEXT NOT NULL,
                    foundation_research_report_id TEXT NOT NULL,
                    review_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    review_notes TEXT,
                    report_data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS vendor_requirement_reviews (
                    review_id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    notes TEXT,
                    reviewed_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_vr_project ON vendor_requirement_reports (project_id, created_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_vr_doc ON vendor_requirement_reports (document_id, created_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_vr_geo_fr ON vendor_requirement_reports (geotechnical_report_id, foundation_research_report_id)"
            )
            self._conn.commit()

    def save_report(self, report: RequirementDocument) -> None:
        """Insert or replace a Vendor Foundation Requirement Document."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO vendor_requirement_reports (
                    report_id, project_id, document_id,
                    geotechnical_report_id, foundation_research_report_id,
                    review_status, reviewed_by, reviewed_at, review_notes,
                    report_data, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.project_id,
                    report.document_id,
                    report.geotechnical_report_id,
                    report.foundation_research_report_id,
                    report.review_status.value,
                    report.reviewed_by,
                    report.reviewed_at,
                    report.review_notes,
                    report.model_dump_json(),
                    report.created_at,
                    report.updated_at,
                ),
            )
            self._conn.commit()
            logger.info(
                "Saved Vendor Requirement Document %s for project %s (geo=%s, fr=%s)",
                report.report_id,
                report.project_id,
                report.geotechnical_report_id,
                report.foundation_research_report_id,
            )

    def get_report(self, report_id: str) -> Optional[RequirementDocument]:
        """Retrieve a specific RequirementDocument by ID."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT report_data FROM vendor_requirement_reports WHERE report_id = ? LIMIT 1",
                (report_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return RequirementDocument.model_validate_json(row[0])

    def get_latest_report_for_project(self, project_id: str) -> Optional[RequirementDocument]:
        """Retrieve the newest RequirementDocument for a project."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT report_data FROM vendor_requirement_reports WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            )
            row = cur.fetchone()
            if not row:
                # Also check by document_id if project_id was passed as primary document UUID
                cur.execute(
                    "SELECT report_data FROM vendor_requirement_reports WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
                    (project_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
            return RequirementDocument.model_validate_json(row[0])

    def get_latest_report_for_document(self, document_id: str) -> Optional[RequirementDocument]:
        """Retrieve the newest RequirementDocument for a document."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT report_data FROM vendor_requirement_reports WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
                (document_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return RequirementDocument.model_validate_json(row[0])

    def list_reports_for_project(self, project_id: str) -> List[RequirementDocument]:
        """List all historical RequirementDocuments for a project, newest first."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT report_data FROM vendor_requirement_reports WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            )
            rows = cur.fetchall()
            if not rows:
                cur.execute(
                    "SELECT report_data FROM vendor_requirement_reports WHERE document_id = ? ORDER BY created_at DESC",
                    (project_id,),
                )
                rows = cur.fetchall()
            return [RequirementDocument.model_validate_json(r[0]) for r in rows]

    def update_review_status(
        self,
        report_id: str,
        decision: RequirementReviewStatus,
        reviewed_by: str,
        notes: Optional[str] = None,
    ) -> Optional[RequirementDocument]:
        """Update human review decision and record audit history."""
        report = self.get_report(report_id)
        if not report:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        review_id = f"rev_{uuid.uuid4().hex[:10]}"
        report.review_status = decision
        report.reviewed_by = reviewed_by
        report.reviewed_at = now_iso
        report.review_notes = notes
        report.updated_at = now_iso

        if decision in (RequirementReviewStatus.APPROVED, RequirementReviewStatus.HUMAN_VERIFIED):
            report.is_preliminary_draft = False
            report.suitable_for_contractual_issuance = True
            report.issuance_status_banner = (
                f"ENGINEER APPROVED ({decision.value}) BY {reviewed_by} ON {now_iso}"
            )
            report.section_12_limitations_and_approval.is_preliminary_unapproved_draft = False
            report.section_12_limitations_and_approval.suitable_for_construction_or_contractual_issuance = True
        elif decision == RequirementReviewStatus.REJECTED:
            report.is_preliminary_draft = True
            report.suitable_for_contractual_issuance = False
            report.issuance_status_banner = (
                f"REJECTED BY {reviewed_by} — NOT VALID FOR ISSUANCE OR CONSTRUCTION"
            )
            report.section_12_limitations_and_approval.is_preliminary_unapproved_draft = True
            report.section_12_limitations_and_approval.suitable_for_construction_or_contractual_issuance = False
        else:
            report.is_preliminary_draft = True
            report.suitable_for_contractual_issuance = False
            report.issuance_status_banner = (
                "UNAPPROVED PRELIMINARY DRAFT — NOT SUITABLE FOR CONSTRUCTION OR CONTRACTUAL ISSUANCE WITHOUT P.E. APPROVAL"
            )

        review_record = RequirementReview(
            review_id=review_id,
            report_id=report_id,
            reviewer=reviewed_by,
            decision=decision,
            reviewed_at=now_iso,
            notes=notes,
        )
        report.review_history.append(review_record)

        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO vendor_requirement_reviews (
                    review_id, report_id, reviewer, decision, notes, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    report_id,
                    reviewed_by,
                    decision.value,
                    notes,
                    now_iso,
                ),
            )
            self._conn.commit()

        self.save_report(report)
        return report

    def delete_report(self, report_id: str) -> bool:
        """Delete a report by ID."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM vendor_requirement_reports WHERE report_id = ?", (report_id,))
            self._conn.commit()
            return cur.rowcount > 0

