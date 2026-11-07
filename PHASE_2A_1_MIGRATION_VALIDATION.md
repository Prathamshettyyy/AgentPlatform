# Phase 2A.1 — Migration Plan Validation Report

**Status:** Validated (Read-Only)  
**Date:** November 7, 2026 (11:48 AM IST / 06:18 UTC)  
**Scope:** Deep-dive technical validation of SQLite schema objects, WAL mode backup safety, checkpoint database ownership, baseline count reconciliation, and hardened Phase 2B migration and verification strategy.

---

## Executive Summary

Phase 2A.1 has performed an exhaustive, read-only validation of the database separation architecture proposed in Phase 2A.

### Key Validation Outcomes
1. **Schema Preservation:** Validated all 19 tables, 33 indexes, 0 triggers, 0 views, and 1 foreign key constraint. The proposed migration strategy will replicate the exact DDL and indexes from `sqlite_master`, ensuring 100% preservation of column constraints, types, defaults, and composite primary keys.
2. **Backup Safety & WAL Mechanics:** Confirmed that both `agent_platform.db` and `agent_platform_checkpoints.db` run in `PRAGMA journal_mode = wal`. A raw filesystem copy (`cp`) during active application execution is unsafe due to uncheckpointed WAL frames. A reliable backup procedure using SQLite's native backup API (`source_conn.backup(backup_conn)`) or a clean application shutdown with `PRAGMA wal_checkpoint(TRUNCATE)` is established.
3. **Checkpoint Ownership:** Verified that `agent_platform_checkpoints.db` is initialized and accessed exclusively by Agent Platform's `AsyncSqliteSaver` for workflow execution channels. It stores zero GeoStrata-specific domain entities and must remain 100% exclusively owned by Agent Platform.
4. **Baseline Count Reconciliation:** Re-counted all tables. The change in `vendor_requirement_reports` (216 to 222) was verified down to the millisecond: 6 test reports were inserted at `2026-11-07 05:36:51 UTC` during the verification run of `tests/test_requirement_agent.py`. The baseline is consistent and reconciled.
5. **Hardened Migration Strategy:** The Phase 2B migration script specification has been enhanced to include: dry-run mode, idempotence, transactional copying, primary key set reconciliation, `PRAGMA foreign_key_check`, and `PRAGMA integrity_check`.

---

## 1. Validation of SQLite Schema Preservation

An exhaustive inspection of `sqlite_master` in `agent_platform.db` revealed:
- **Tables:** 19 (18 application tables + `sqlite_sequence`)
- **Indexes:** 33 (17 explicit named indexes + 16 implicit primary-key autoindexes)
- **Triggers:** 0
- **Views:** 0
- **Foreign Keys:** 1 explicit foreign key constraint (`geotechnical_analysis_reviews.report_id -> geotechnical_analysis_reports(report_id)`)
- **AUTOINCREMENT Usage:** Only 1 table (`events`) uses `AUTOINCREMENT`. All 13 GeoStrata tables use UUID/string primary keys or composite primary keys.

### Schema Details for the 13 GeoStrata Tables

| Table Name | Primary Key | Named Indexes | Constraints & Default Values |
|---|---|---|---|
| `documents` | `document_id` (TEXT) | `idx_documents_sha256` ON `(sha256_hash, project_id)` | `page_count DEFAULT 0`, `is_scanned DEFAULT 0`, `document_type DEFAULT 'text_based'`, `status DEFAULT 'uploaded'` |
| `document_pages` | `(document_id, page_index)` (Composite) | None (uses `sqlite_autoindex`) | `width DEFAULT 612.0`, `height DEFAULT 792.0`, `is_scanned DEFAULT 0`, `status DEFAULT 'extracted'` |
| `document_tables` | `table_id` (TEXT) | `idx_tables_doc` ON `(document_id, page_index)` | `table_classification DEFAULT 'engineering_data'`, `confidence_score DEFAULT 1.0`, `is_fragment DEFAULT 0` |
| `document_evidence` | `evidence_id` (TEXT) | 1. `idx_evidence_doc` ON `(document_id, page_index)`<br>2. `idx_evidence_prop` ON `(property_type)` | `verification_status DEFAULT 'unverified'`, `confidence_score DEFAULT 1.0`, `confidence_category DEFAULT 'VERIFIED_TEXT'` |
| `document_visual_evidence` | `visual_evidence_id` (TEXT) | `idx_visual_evidence_doc` ON `(document_id, page_index)` | `extraction_method DEFAULT 'vlm_vision_prompt'`, `confidence_category DEFAULT 'HIGH'`, `review_status DEFAULT 'PENDING_REVIEW'` |
| `document_visual_disagreements` | `disagreement_id` (TEXT) | `idx_visual_disagreements_doc` ON `(document_id, page_index)` | `severity DEFAULT 'MEDIUM'`, `status DEFAULT 'OPEN'` |
| `document_project_associations` | `association_id` (TEXT) | `idx_assoc_proj` ON `(project_id, document_id)` | `confidence_score DEFAULT 0.0`, `user_decision DEFAULT 'PENDING'` |
| `geotechnical_analysis_reports` | `report_id` (TEXT) | 1. `idx_geo_reports_doc` ON `(document_id)`<br>2. `idx_geo_reports_proj` ON `(project_id)` | `status DEFAULT 'PENDING_REVIEW'` |
| `geotechnical_analysis_reviews` | `review_id` (TEXT) | `idx_geo_reviews_rep` ON `(report_id)` | `FOREIGN KEY (report_id) REFERENCES geotechnical_analysis_reports(report_id)` |
| `foundation_research_reports` | `report_id` (TEXT) | 1. `idx_fr_project` ON `(project_id, created_at DESC)`<br>2. `idx_fr_doc` ON `(document_id, created_at DESC)` | `review_status DEFAULT 'PENDING_REVIEW'` |
| `vendor_requirement_reports` | `report_id` (TEXT) | 1. `idx_vr_project` ON `(project_id, created_at DESC)`<br>2. `idx_vr_doc` ON `(document_id, created_at DESC)`<br>3. `idx_vr_geo_fr` ON `(geotechnical_report_id, foundation_research_report_id)` | `review_status DEFAULT 'PENDING_REVIEW'` |
| `vendor_requirement_reviews` | `review_id` (TEXT) | None (uses `sqlite_autoindex`) | `reviewed_at TEXT NOT NULL` |
| `project_workflows` (Legacy) | `workflow_id` (TEXT) | `idx_pwf_project` ON `(project_id, created_at DESC)` | Historical prototype table; preserved for data retention. |

### Schema Replication Rule for Migration
In `scripts/migrate_database_separation.py`, the migration will extract the exact SQL DDL directly from `sqlite_master`:
```python
SELECT sql FROM sqlite_master WHERE type IN ('table', 'index') AND tbl_name = ? AND sql IS NOT NULL;
```
This guarantees that column defaults, nullability, composite keys, and index column ordering (including `DESC` sorting on timestamp indexes) are replicated with 100% mathematical fidelity.

---

## 2. Validation of Database Backup Safety

### 2.1 WAL Mode Analysis
- Both `agent_platform.db` and `agent_platform_checkpoints.db` run with:
  ```sql
  PRAGMA journal_mode = wal;
  PRAGMA busy_timeout = 5000;
  ```
- In SQLite WAL mode:
  - Read operations read concurrently with write operations.
  - New commits are written to the `-wal` file (`agent_platform.db-wal`) and indexed via shared memory (`agent_platform.db-shm`).
  - Commits are only flushed back to the main `.db` file during a checkpoint operation.
- **Risk Identified in Phase 2A:** A simple file copy (e.g. `shutil.copyfile` or PowerShell `Copy-Item`) while the database is actively in use will copy `agent_platform.db` without guaranteed synchronization of uncheckpointed WAL frames, potentially capturing a torn or outdated database page.

### 2.2 Recommended Safe Backup Procedure
For Phase 2B, backup safety will be enforced using **two distinct levels of protection**:

#### Primary Procedure: Native Online SQLite Backup API
Python's standard library `sqlite3` includes a low-level, lock-aware backup API that interfaces directly with SQLite's internal pager:
```python
def create_safe_backup(source_db_path: str, backup_db_path: str) -> None:
    """Create a transactionally consistent point-in-time SQLite backup.
    
    Safe even if concurrent read connections are open. Acquires a read lock,
    flushes relevant WAL frames into the backup pages, and writes a self-contained
    SQLite database file.
    """
    src = sqlite3.connect(f"file:{source_db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(backup_db_path)
    with dst:
        src.backup(dst, pages=100, sleep=0.01)
    dst.close()
    src.close()
```

#### Secondary Procedure: Controlled Offline Verification
Before executing the schema split:
1. Stop all server processes (ports 8000 and 8001).
2. Issue an explicit truncation checkpoint on `agent_platform.db`:
   ```sql
   PRAGMA wal_checkpoint(TRUNCATE);
   ```
3. Confirm that `agent_platform.db-wal` and `agent_platform.db-shm` are either 0 bytes or removed by SQLite.
4. Execute the backup copy: `agent_platform.db.bak_phase2b`.

---

## 3. Checkpoint Database Ownership Validation

### 3.1 LangGraph Checkpoint Architecture
- **Location:** `agent_platform_checkpoints.db` (3,907,584 bytes)
- **Lifecycle:**
  - Initialized in `app/api/app.py:298-299` via LangGraph's `AsyncSqliteSaver(connection)`.
  - Path dynamically derived in `app/api/app.py:273`:
    `checkpoint_path = str(repository_path.with_name(repository_path.stem + "_checkpoints" + (repository_path.suffix or ".db")))`
  - Closed during application shutdown in `app/api/app.py:84-85`.

### 3.2 Contents and Channel Analysis
Inspection of the 372 rows in `writes` and 91 rows in `checkpoints` shows that stored channels correspond strictly to generic workflow runtime channels:
- `run_id`, `workflow_id`, `workflow_version`, `workflow_input`
- `node_outputs`, `agent_outputs`, `final_output`
- `branch:to:*`, `loop_counters`, `__error__`

### 3.3 Ownership Determination
- **Exclusively Agent Platform-Owned:**
  - GeoStrata application code (`geostrata/`) never imports `AsyncSqliteSaver`, never opens `agent_platform_checkpoints.db`, and has no concept of thread checkpoints.
  - GeoStrata stores its domain findings in `geotechnical_analysis_reports`, `foundation_research_reports`, and `vendor_requirement_reports`.
  - **Conclusion:** `agent_platform_checkpoints.db` must remain **100% exclusively owned by Agent Platform**. It will not be split, migrated, or renamed in Phase 2B.

---

## 4. Reconciliation of Baseline Record Counts

### 4.1 Exact Re-Count (Timestamp: 2026-11-07 11:47:05 IST / 06:17:05 UTC)

#### Agent Platform Tables (Target: `agent_platform.db`)
| Table Name | Baseline Count | Target Database |
|---|---|---|
| `workflows` | 11 | `agent_platform.db` |
| `workflow_versions` | 11 | `agent_platform.db` |
| `runs` | 77 | `agent_platform.db` |
| `events` | 307 | `agent_platform.db` |
| `schedules` | 0 | `agent_platform.db` |
| `checkpoints` | 91 | `agent_platform_checkpoints.db` |
| `writes` | 372 | `agent_platform_checkpoints.db` |

#### GeoStrata Domain Tables (Target: `geostrata.db`)
| Table Name | Baseline Count | Target Database |
|---|---|---|
| `documents` | 42 | `geostrata.db` |
| `document_pages` | 357 | `geostrata.db` |
| `document_tables` | 360 | `geostrata.db` |
| `document_evidence` | 3,705 | `geostrata.db` |
| `document_visual_evidence` | 13 | `geostrata.db` |
| `document_visual_disagreements` | 0 | `geostrata.db` |
| `document_project_associations` | 58 | `geostrata.db` |
| `geotechnical_analysis_reports` | 134 | `geostrata.db` |
| `geotechnical_analysis_reviews` | 1 | `geostrata.db` |
| `foundation_research_reports` | 101 | `geostrata.db` |
| `vendor_requirement_reports` | **222** | `geostrata.db` |
| `vendor_requirement_reviews` | 37 | `geostrata.db` |
| `project_workflows` (Legacy) | 1 | `geostrata.db` |

---

### 4.2 Investigation of `vendor_requirement_reports` Count Change (216 -> 222)

The user requested an investigation into why `vendor_requirement_reports` was previously reported at 216 and is now 222 (a delta of 6 records).

#### Investigation Findings
Querying the 6 newest rows ordered by `created_at DESC`:
```
ID: req_b89dd12447a1 | Project: 7d500784-... | Status: PENDING_REVIEW | Created: 2026-11-07T05:36:52.183455+00:00
ID: req_c3892b44da08 | Project: 7d500784-... | Status: PENDING_REVIEW | Created: 2026-11-07T05:36:51.461958+00:00
ID: req_cf5c2583e560 | Project: 7d500784-... | Status: PENDING_REVIEW | Created: 2026-11-07T05:36:51.394107+00:00
ID: req_7204ca28ec8b | Project: 7d500784-... | Status: PENDING_REVIEW | Created: 2026-11-07T05:36:51.326626+00:00
ID: req_3e36e86fbfb4 | Project: 7d500784-... | Status: PENDING_REVIEW | Created: 2026-11-07T05:36:51.256112+00:00
ID: req_ea66e9f85f23 | Project: 7d500784-... | Status: PENDING_REVIEW | Created: 2026-11-07T05:36:51.005589+00:00
```
- **Creation Timestamp:** `2026-11-07 05:36:51 UTC` (`11:06:51 AM IST`).
- **Root Cause:** At 11:06:51 AM IST during Phase 1.1 verification, the test suite `pytest tests/test_requirement_agent.py -k "not test_2 and not test_12 and not test_14" -v` was executed.
- In that test suite, 6 synchronous test functions (`test_3_langgraph_10_node_execution`, `test_4`, `test_7`, `test_8`, `test_9`, and `test_15`) invoke `RequirementAgentService.run_requirement_generation()`.
- Because `tests/test_requirement_agent.py:47` opened a live connection to `"agent_platform.db"`, each of those 6 tests generated and persisted a valid test requirement document.
- Prior to that test run, the row count was exactly **216**.
- The 6 test runs incremented the count to exactly **222**.

#### Conclusion
The delta was caused by legitimate test execution against the shared database file during Phase 1.1, rather than an inconsistent baseline. This highlights the architectural benefit of Phase 2B: separating `geostrata.db` and isolating test environments will prevent test runs from altering shared production tables.

---

## 5. Improved Migration and Rollback Strategy for Phase 2B

The Phase 2B migration script (`scripts/migrate_database_separation.py`) will be built with the following enterprise safeguards:

```
                                  MIGRATION FLOW
                                        │
           Step 1: Check CLI flags (--dry-run, --force, --verify-only)
                                        │
           Step 2: PRAGMA integrity_check on agent_platform.db
                                        │
           Step 3: Safe online backup -> agent_platform.db.bak_phase2b
                                        │
           Step 4: Create geostrata.db (enable WAL mode + busy_timeout)
                                        │
           Step 5: Clone exact DDL & indexes from sqlite_master
                                        │
           Step 6: ATTACH DATABASE & copy rows in atomic transaction
                                        │
           Step 7: Reconcile Row Counts & Primary Key sets
                                        │
           Step 8: PRAGMA foreign_key_check on geostrata.db
                                        │
           Step 9: PRAGMA integrity_check on geostrata.db
                                        │
          Step 10: Prune 13 tables from agent_platform.db & VACUUM
                                        │
          Step 11: Output MIGRATION_VERIFICATION_REPORT.json
```

### 5.1 Required Script Capabilities
1. **`--dry-run` Flag:**
   - Connects to `agent_platform.db` in read-only mode (`?mode=ro`).
   - Simulates table extraction, parses all 13 DDL definitions, prints row counts to be migrated, and validates integrity without modifying or creating any files.
2. **Idempotence & `--force` Protection:**
   - If `geostrata.db` already exists, the script will abort unless `--force` is provided.
   - When `--force` is used, the script will safely drop and recreate the destination database in a fresh transaction.
3. **Transactional Table Copying:**
   - Data transfer will use SQLite's native `ATTACH DATABASE` engine inside a single immediate transaction (`BEGIN IMMEDIATE;` ... `COMMIT;`).
   - If any insert fails, SQLite rolls back the entire destination transaction atomically.
4. **Primary Key Set Reconciliation:**
   - The script will not rely on `COUNT(*)` alone.
   - For every table, it will extract primary key values into Python sets:
     `assert set(src_pks) == set(dst_pks), f"Primary key mismatch in {table}"`
5. **Foreign Key Integrity Verification:**
   - Executes `PRAGMA foreign_key_check;` on `geostrata.db` and asserts 0 violations.
6. **Integrity Check:**
   - Executes `PRAGMA integrity_check;` on both `geostrata.db` and `agent_platform.db` post-migration.
7. **Safe Rollback Guarantee:**
   - The original `agent_platform.db` is backed up before migration begins.
   - If verification fails at any stage:
     - The uncommitted or incomplete `geostrata.db` is removed.
     - `agent_platform.db` is restored from `agent_platform.db.bak_phase2b`.
     - Zero data is lost or altered.

---

## 6. Recommended Phase 2B Implementation Sequence

When Phase 2B begins, execution will follow this strict order:

1. **Step 1: Create Migration Script (`scripts/migrate_database_separation.py`)**
   - Implement the hardened script with `--dry-run`, backup creation, DDL cloning, transactional copying, and PK reconciliation.
2. **Step 2: Execute Dry Run**
   - Run `python scripts/migrate_database_separation.py --dry-run` to verify schema extraction and planned row counts.
3. **Step 3: Execute Live Migration**
   - Run `python scripts/migrate_database_separation.py` to create `geostrata.db`, copy the 13 tables, and generate `MIGRATION_VERIFICATION_REPORT.json`.
4. **Step 4: Update GeoStrata Application Code**
   - `geostrata_app.py`: set default `GEOSTRATA_DB_PATH="geostrata.db"`.
   - `geostrata/backend/api/app.py`: set default `GEOSTRATA_DB_PATH="geostrata.db"`.
   - `geostrata/plugins/*/adapter.py`: update all 4 adapters to read `GEOSTRATA_DB_PATH`.
   - `geostrata/backend/agents/*/graph.py`: update fallback connections to `GEOSTRATA_DB_PATH`.
5. **Step 5: Update Environment Configuration**
   - `.env.example`: add `GEOSTRATA_DB_PATH=geostrata.db`.
   - `tests/conftest.py`: set `GEOSTRATA_DB_PATH="geostrata.db"`.
6. **Step 6: Prune Agent Platform Database & Vacuum**
   - Drop the 13 domain tables from `agent_platform.db` and execute `VACUUM;`.
7. **Step 7: Full Verification Suite**
   - Verify `uvicorn app.main:app --port 8000` (connects to `agent_platform.db`).
   - Verify `uvicorn geostrata_app:app --port 8001` (connects to `geostrata.db`).
   - Run test suites across both applications.
8. **Step 8: Final Report**
   - Compile `PHASE_2B_DATABASE_SEPARATION_REPORT.md`.

---

## Sign-Off and Hold

This validation was conducted **strictly in read-only mode**. No application code, databases, schemas, or records were modified.  
We await your review and explicit approval before initiating Phase 2B.

