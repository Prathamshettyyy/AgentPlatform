from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, List, Optional

from .models import (
    FoundationResearchReport,
    HumanReviewRecord,
    ReviewStatus,
)

logger = logging.getLogger("agent_platform.foundation_research.repository")


class FoundationResearchRepository:
    """Thread-safe SQLite repository for Foundation Research Reports and Sources."""

    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock | None = None) -> None:
        self._conn = connection
        self._lock = lock or threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS foundation_research_reports (
                    report_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    analysis_report_id TEXT,
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
                "CREATE INDEX IF NOT EXISTS idx_fr_project ON foundation_research_reports (project_id, created_at DESC)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_fr_doc ON foundation_research_reports (document_id, created_at DESC)"
            )
            self._conn.commit()

    def save_report(self, report: FoundationResearchReport) -> None:
        """Insert or replace a foundation research report."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO foundation_research_reports (
                    report_id, project_id, document_id, analysis_report_id,
                    review_status, reviewed_by, reviewed_at, review_notes,
                    report_data, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.project_id,
                    report.document_id,
                    report.analysis_report_id,
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
            logger.info("Saved foundation research report %s for project %s", report.report_id, report.project_id)

    def get_report(self, report_id: str) -> Optional[FoundationResearchReport]:
        """Retrieve a specific research report by ID."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT report_data FROM foundation_research_reports WHERE report_id = ? LIMIT 1",
                (report_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return FoundationResearchReport.model_validate_json(row[0])

    def get_latest_report_for_project(self, project_id: str) -> Optional[FoundationResearchReport]:
        """Retrieve the newest research report for a project."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT report_data FROM foundation_research_reports WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
                (project_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return FoundationResearchReport.model_validate_json(row[0])

    def get_latest_report_for_document(self, document_id: str) -> Optional[FoundationResearchReport]:
        """Retrieve the newest research report for a document."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT report_data FROM foundation_research_reports WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
                (document_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return FoundationResearchReport.model_validate_json(row[0])

    def list_reports_for_project(self, project_id: str) -> List[FoundationResearchReport]:
        """List all historical research reports for a project, newest first."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT report_data FROM foundation_research_reports WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            )
            rows = cur.fetchall()
            return [FoundationResearchReport.model_validate_json(r[0]) for r in rows]

    def update_review_status(
        self,
        report_id: str,
        decision: ReviewStatus,
        reviewed_by: str,
        notes: Optional[str] = None,
    ) -> Optional[FoundationResearchReport]:
        """Update human review decision and record audit history."""
        report = self.get_report(report_id)
        if not report:
            return None

        now_iso = datetime.now(timezone.utc).isoformat()
        report.review_status = decision
        report.reviewed_by = reviewed_by
        report.reviewed_at = now_iso
        report.review_notes = notes
        report.updated_at = now_iso

        report.review_history.append(
            HumanReviewRecord(
                reviewer=reviewed_by,
                decision=decision,
                reviewed_at=now_iso,
                notes=notes,
            )
        )

        self.save_report(report)
        return report

    def delete_report(self, report_id: str) -> bool:
        """Delete a report by ID."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("DELETE FROM foundation_research_reports WHERE report_id = ?", (report_id,))
            self._conn.commit()
            return cur.rowcount > 0
