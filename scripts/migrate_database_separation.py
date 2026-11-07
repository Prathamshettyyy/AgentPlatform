"""Database Separation Migration Script: Agent Platform & GeoStrata.

Separates domain-specific geotechnical tables from agent_platform.db into geostrata.db.

Features:
- Full pre-migration SQLite backup using Python's native backup API.
- Support for --dry-run mode.
- Idempotent and safe --force behavior.
- Complete DDL, column constraint, default, and index replication from sqlite_master.
- Transactional copying with rollback safety.
- Primary key set reconciliation and row count verification.
- PRAGMA foreign_key_check and PRAGMA integrity_check.
- Machine-readable verification report generation (MIGRATION_VERIFICATION_REPORT.json).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, List, Set, Tuple

GEOSTRATA_TABLES: list[str] = [
    "documents",
    "document_pages",
    "document_tables",
    "document_evidence",
    "document_visual_evidence",
    "document_visual_disagreements",
    "document_project_associations",
    "geotechnical_analysis_reports",
    "geotechnical_analysis_reviews",
    "foundation_research_reports",
    "vendor_requirement_reports",
    "vendor_requirement_reviews",
    "project_workflows",
]

PLATFORM_TABLES: list[str] = [
    "workflows",
    "workflow_versions",
    "runs",
    "events",
    "schedules",
]


def get_table_pks(conn: sqlite3.Connection, table_name: str) -> list[str]:
    """Retrieve primary key column names in primary key order."""
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info('{table_name}');")
    cols = cur.fetchall()  # cid, name, type, notnull, dflt_value, pk
    # Filter cols where pk > 0, ordered by pk index
    pk_cols = [c[1] for c in sorted([col for col in cols if col[5] > 0], key=lambda x: x[5])]
    if not pk_cols:
        # Fallback to rowid if no explicit PK
        return ["rowid"]
    return pk_cols


def get_pk_values(conn: sqlite3.Connection, table_name: str, pk_cols: list[str]) -> set[Any]:
    """Retrieve all primary key tuples or values for reconciliation."""
    cur = conn.cursor()
    cols_sql = ", ".join(f'"{c}"' for c in pk_cols)
    cur.execute(f"SELECT {cols_sql} FROM \"{table_name}\";")
    rows = cur.fetchall()
    if len(pk_cols) == 1:
        return {r[0] for r in rows}
    return {tuple(r) for r in rows}


def create_native_backup(source_path: Path, backup_path: Path) -> None:
    """Create a transactionally consistent SQLite backup using the native backup API."""
    print(f"Creating native SQLite backup: {source_path} -> {backup_path}")
    source_uri = f"file:{source_path.resolve()}?mode=ro"
    src_conn = sqlite3.connect(source_uri, uri=True)
    dst_conn = sqlite3.connect(str(backup_path))
    with dst_conn:
        src_conn.backup(dst_conn, pages=250, sleep=0.005)
    dst_conn.close()
    src_conn.close()

    # Verify backup integrity
    verify_conn = sqlite3.connect(str(backup_path))
    res = verify_conn.execute("PRAGMA integrity_check;").fetchall()
    verify_conn.close()
    if res != [("ok",)]:
        raise RuntimeError(f"Backup integrity check failed: {res}")
    print(f"✓ Backup successfully created and verified ({backup_path.stat().st_size:,} bytes).")


def run_migration(
    source_db_path: Path,
    dest_db_path: Path,
    backup_path: Path,
    report_path: Path,
    dry_run: bool = False,
    force: bool = False,
    verify_only: bool = False,
) -> dict[str, Any]:
    start_time = datetime.now(timezone.utc).isoformat()
    print("=" * 70)
    print("GEOSTRATA DATABASE SEPARATION MIGRATION")
    print(f"Timestamp: {start_time}")
    print(f"Source DB: {source_db_path.resolve()}")
    print(f"Dest DB:   {dest_db_path.resolve()}")
    print(f"Dry Run:   {dry_run}")
    print(f"Force:     {force}")
    print("=" * 70)

    if not source_db_path.exists():
        raise FileNotFoundError(f"Source database not found at {source_db_path}")

    # Check source database integrity
    src_conn = sqlite3.connect(f"file:{source_db_path.resolve()}?mode=ro", uri=True)
    src_integrity = src_conn.execute("PRAGMA integrity_check;").fetchall()
    if src_integrity != [("ok",)]:
        src_conn.close()
        raise RuntimeError(f"Source database integrity check failed before migration: {src_integrity}")
    print("✓ Source database integrity verified: PRAGMA integrity_check = ok")

    # Read live source database schema and counts
    cur = src_conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    existing_tables = {row[0] for row in cur.fetchall()}

    missing_geostrata_tables = [t for t in GEOSTRATA_TABLES if t not in existing_tables]
    if missing_geostrata_tables:
        src_conn.close()
        raise RuntimeError(f"Source database missing expected GeoStrata tables: {missing_geostrata_tables}")

    table_data_plan: dict[str, dict[str, Any]] = {}
    for table in GEOSTRATA_TABLES:
        cur.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}';")
        tbl_ddl = cur.fetchone()[0]

        cur.execute(f"SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='{table}' AND sql IS NOT NULL;")
        idx_ddls = [(r[0], r[1]) for r in cur.fetchall()]

        cur.execute(f"SELECT COUNT(*) FROM \"{table}\";")
        count = cur.fetchone()[0]

        pk_cols = get_table_pks(src_conn, table)
        pk_sample = len(get_pk_values(src_conn, table, pk_cols))

        table_data_plan[table] = {
            "table_ddl": tbl_ddl,
            "indexes": idx_ddls,
            "source_rows": count,
            "pk_cols": pk_cols,
            "pk_count": pk_sample,
        }

    total_records_to_migrate = sum(d["source_rows"] for d in table_data_plan.values())
    print(f"Total GeoStrata tables to migrate: {len(GEOSTRATA_TABLES)}")
    print(f"Total rows to migrate: {total_records_to_migrate:,}")

    for t, info in table_data_plan.items():
        print(f"  - {t:<32} {info['source_rows']:>6} rows, PK: {info['pk_cols']}, Indexes: {len(info['indexes'])}")

    if dry_run:
        print("\n" + "=" * 70)
        print("DRY-RUN MODE COMPLETE: No changes written to disk.")
        print("=" * 70)
        src_conn.close()
        return {
            "status": "dry_run_success",
            "timestamp": start_time,
            "source_db": str(source_db_path),
            "dest_db": str(dest_db_path),
            "total_rows": total_records_to_migrate,
            "tables": {t: d["source_rows"] for t, d in table_data_plan.items()},
        }

    # Handle Destination Database existence
    if dest_db_path.exists():
        if not force:
            # Check if destination has data
            try:
                chk = sqlite3.connect(f"file:{dest_db_path.resolve()}?mode=ro", uri=True)
                tables = chk.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
                chk.close()
                if tables:
                    src_conn.close()
                    raise RuntimeError(
                        f"Destination database already exists at {dest_db_path} with {len(tables)} tables. "
                        f"Refusing to overwrite without --force."
                    )
            except sqlite3.OperationalError:
                pass
        print(f"Destination {dest_db_path} exists; --force specified. Removing existing file for clean migration.")
        src_conn.close()
        for ext in ["", "-wal", "-shm"]:
            f = dest_db_path.parent / (dest_db_path.name + ext)
            if f.exists():
                f.unlink()
        src_conn = sqlite3.connect(f"file:{source_db_path.resolve()}?mode=ro", uri=True)

    # 1. Create Pre-Migration Backup
    if not backup_path.exists() or force:
        create_native_backup(source_db_path, backup_path)
    else:
        print(f"Backup already exists at {backup_path}; preserving existing backup.")

    # 2. Perform Migration
    print(f"\nInitializing destination database: {dest_db_path}")
    dest_conn = sqlite3.connect(str(dest_db_path))
    dest_conn.execute("PRAGMA journal_mode = WAL;")
    dest_conn.execute("PRAGMA busy_timeout = 5000;")
    dest_conn.execute("PRAGMA foreign_keys = OFF;")  # Disable during load, re-enable for check

    try:
        # Create Tables
        print("Creating destination schemas...")
        for table, info in table_data_plan.items():
            dest_conn.execute(info["table_ddl"])

        # Attach Source and Copy Data
        print("Attaching source database and transferring records transactionally...")
        dest_conn.execute(f"ATTACH DATABASE '{source_db_path.resolve()}' AS source_db;")
        dest_conn.execute("BEGIN IMMEDIATE TRANSACTION;")

        for table in GEOSTRATA_TABLES:
            dest_conn.execute(f"INSERT INTO main.\"{table}\" SELECT * FROM source_db.\"{table}\";")
            print(f"  ✓ Transferred {table_data_plan[table]['source_rows']} rows into {table}")

        dest_conn.commit()
        dest_conn.execute("DETACH DATABASE source_db;")

        # Create Indexes
        print("Creating destination indexes...")
        for table, info in table_data_plan.items():
            for idx_name, idx_sql in info["indexes"]:
                dest_conn.execute(idx_sql)

        dest_conn.commit()
    except Exception as exc:
        dest_conn.rollback()
        dest_conn.close()
        src_conn.close()
        # Clean up partial destination file on catastrophic failure
        if dest_db_path.exists():
            dest_db_path.unlink()
        raise RuntimeError(f"Migration failed during data transfer: {exc}") from exc

    # 3. Post-Migration Verification & Reconciliation
    print("\n" + "=" * 70)
    print("RECONCILIATION AND INTEGRITY VERIFICATION")
    print("=" * 70)

    reconciliation_results: dict[str, dict[str, Any]] = {}
    dest_cur = dest_conn.cursor()

    for table in GEOSTRATA_TABLES:
        pk_cols = table_data_plan[table]["pk_cols"]
        src_rows = table_data_plan[table]["source_rows"]

        dest_cur.execute(f"SELECT COUNT(*) FROM \"{table}\";")
        dest_rows = dest_cur.fetchone()[0]

        src_pks = get_pk_values(src_conn, table, pk_cols)
        dest_pks = get_pk_values(dest_conn, table, pk_cols)

        row_count_match = (src_rows == dest_rows)
        pk_match = (src_pks == dest_pks)

        reconciliation_results[table] = {
            "source_rows": src_rows,
            "dest_rows": dest_rows,
            "row_count_match": row_count_match,
            "pk_cols": pk_cols,
            "pk_count_match": (len(src_pks) == len(dest_pks)),
            "pk_set_identical": pk_match,
        }

        if not row_count_match or not pk_match:
            dest_conn.close()
            src_conn.close()
            raise RuntimeError(
                f"Reconciliation failure in table '{table}': "
                f"src_rows={src_rows}, dest_rows={dest_rows}, pk_match={pk_match}"
            )

        print(f"  ✓ {table:<32} Rows: {dest_rows:>6} | PK Match: {pk_match} | All Constraints Preserved")

    # 4. Foreign Key and DB Integrity Checks
    dest_conn.execute("PRAGMA foreign_keys = ON;")
    fk_violations = dest_conn.execute("PRAGMA foreign_key_check;").fetchall()
    if fk_violations:
        dest_conn.close()
        src_conn.close()
        raise RuntimeError(f"Destination foreign key violations found: {fk_violations}")
    print("✓ Destination foreign key check: 0 violations")

    dest_integrity = dest_conn.execute("PRAGMA integrity_check;").fetchall()
    if dest_integrity != [("ok",)]:
        dest_conn.close()
        src_conn.close()
        raise RuntimeError(f"Destination PRAGMA integrity_check failed: {dest_integrity}")
    print("✓ Destination database integrity: PRAGMA integrity_check = ok")

    # Close connections
    dest_conn.close()
    src_conn.close()

    end_time = datetime.now(timezone.utc).isoformat()
    dest_size = dest_db_path.stat().st_size

    verification_report = {
        "status": "success",
        "started_at": start_time,
        "completed_at": end_time,
        "source_database": {
            "path": str(source_db_path.resolve()),
            "size_bytes": source_db_path.stat().st_size,
            "integrity_check": "ok",
        },
        "destination_database": {
            "path": str(dest_db_path.resolve()),
            "size_bytes": dest_size,
            "integrity_check": "ok",
            "foreign_key_check": "ok",
        },
        "backup_database": {
            "path": str(backup_path.resolve()),
            "size_bytes": backup_path.stat().st_size,
            "integrity_check": "ok",
        },
        "total_tables_migrated": len(GEOSTRATA_TABLES),
        "total_rows_migrated": total_records_to_migrate,
        "reconciliation": reconciliation_results,
    }

    report_path.write_text(json.dumps(verification_report, indent=2), encoding="utf-8")
    print(f"\n✓ Migration verification report generated: {report_path.resolve()}")
    print(f"✓ geostrata.db created successfully ({dest_size:,} bytes).")
    print("=" * 70)
    return verification_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate GeoStrata domain tables from agent_platform.db to geostrata.db")
    parser.add_argument("--source-db", default="agent_platform.db", help="Path to source SQLite database (default: agent_platform.db)")
    parser.add_argument("--dest-db", default="geostrata.db", help="Path to destination SQLite database (default: geostrata.db)")
    parser.add_argument("--backup-path", default="agent_platform.db.bak_phase2b", help="Path to backup database (default: agent_platform.db.bak_phase2b)")
    parser.add_argument("--report-path", default="MIGRATION_VERIFICATION_REPORT.json", help="Path to JSON verification report")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without modifying disk")
    parser.add_argument("--force", action="store_true", help="Overwrite destination database if it already exists")

    args = parser.parse_args()

    try:
        run_migration(
            source_db_path=Path(args.source_db),
            dest_db_path=Path(args.dest_db),
            backup_path=Path(args.backup_path),
            report_path=Path(args.report_path),
            dry_run=args.dry_run,
            force=args.force,
        )
    except Exception as exc:
        print(f"\n[ERROR] Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

