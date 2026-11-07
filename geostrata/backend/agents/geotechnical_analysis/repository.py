from __future__ import annotations

import json
import logging
import sqlite3
import threading
from typing import Any, Optional

from .models import GeotechnicalAnalysisReport, HumanReviewRecord

logger = logging.getLogger("agent_platform.geotechnical_analysis.repository")


class GeotechnicalAnalysisRepository:
    """Thread-safe SQLite repository for Geotechnical Analysis Reports and Human Reviews."""

    def __init__(self, connection: sqlite3.Connection, lock: threading.RLock | None = None):
        self._conn = connection
        self._lock = lock or threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS geotechnical_analysis_reports (
                    report_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    run_id TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                    report_json TEXT NOT NULL,
                    markdown_content TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_geo_reports_doc ON geotechnical_analysis_reports (document_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_geo_reports_proj ON geotechnical_analysis_reports (project_id)"
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS geotechnical_analysis_reviews (
                    review_id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL,
                    reviewer_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    comments TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (report_id) REFERENCES geotechnical_analysis_reports (report_id)
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_geo_reviews_rep ON geotechnical_analysis_reviews (report_id)"
            )
            self._conn.commit()

    def save_report(self, report: GeotechnicalAnalysisReport) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO geotechnical_analysis_reports (
                    report_id, document_id, project_id, run_id, status, report_json, markdown_content, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.report_id,
                    report.document_id,
                    report.project_id,
                    report.run_id,
                    report.review_status,
                    report.model_dump_json(indent=2),
                    report.markdown_content,
                    report.created_at,
                    report.updated_at,
                ),
            )
            self._conn.commit()

    def get_report(self, report_id: str) -> Optional[GeotechnicalAnalysisReport]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT report_json FROM geotechnical_analysis_reports WHERE report_id = ?",
                (report_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return GeotechnicalAnalysisReport.model_validate_json(row[0])

    def get_latest_report_for_document(self, document_id: str) -> Optional[GeotechnicalAnalysisReport]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT report_json FROM geotechnical_analysis_reports WHERE document_id = ? ORDER BY created_at DESC LIMIT 1",
                (document_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return GeotechnicalAnalysisReport.model_validate_json(row[0])

    def list_reports(self, project_id: str = "default", document_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.cursor()
            if document_id:
                cur.execute(
                    """
                    SELECT report_id, document_id, project_id, run_id, status, created_at, updated_at
                    FROM geotechnical_analysis_reports
                    WHERE document_id = ?
                    ORDER BY created_at DESC
                    """,
                    (document_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT report_id, document_id, project_id, run_id, status, created_at, updated_at
                    FROM geotechnical_analysis_reports
                    WHERE project_id = ?
                    ORDER BY created_at DESC
                    """,
                    (project_id,),
                )
            rows = cur.fetchall()
            return [
                {
                    "report_id": r[0],
                    "document_id": r[1],
                    "project_id": r[2],
                    "run_id": r[3],
                    "status": r[4],
                    "created_at": r[5],
                    "updated_at": r[6],
                }
                for r in rows
            ]

    def add_review(self, review: HumanReviewRecord) -> Optional[GeotechnicalAnalysisReport]:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                INSERT INTO geotechnical_analysis_reviews (
                    review_id, report_id, reviewer_id, decision, comments, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    review.review_id,
                    review.report_id,
                    review.reviewer_id,
                    review.decision,
                    review.comments,
                    review.timestamp,
                ),
            )
            # Update status in reports table and in report_json
            report = self.get_report(review.report_id)
            if report:
                report.review_status = review.decision
                report.review_history.append(review)
                from datetime import datetime, timezone
                report.updated_at = datetime.now(timezone.utc).isoformat()
                self.save_report(report)
            self._conn.commit()
            return report
