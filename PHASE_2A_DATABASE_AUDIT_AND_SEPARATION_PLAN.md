# Phase 2A — Database Audit and Separation Plan

**Status:** Plan & Audit Complete (Read-Only)  
**Date:** November 2026  
**Scope:** Comprehensive inspection of existing SQLite databases, table ownership classification, cross-application dependency analysis, and complete architectural roadmap for Phase 2B (Database Separation).

---

## Executive Summary

Currently, **Agent Platform** and **GeoStrata** share a single physical SQLite database file (`agent_platform.db`, 66.3 MB), along with a companion database (`agent_platform_checkpoints.db`, 3.9 MB) used for LangGraph execution checkpoints.

A comprehensive read-only audit of all schema DDL, repository classes, SQL queries, and plugin adapters confirms that **domain data and platform data are already logically decoupled**:
1. **Zero Cross-Domain SQL Joins:** There is not a single SQL query in the entire codebase that joins or references tables across application boundaries.
2. **Zero Cross-Domain Repository Imports:** `app/` contains 0 imports from `geostrata/`, and `geostrata/` contains 0 imports from `app/storage/`.
3. **Clean Schema Isolation:** 5 tables are managed exclusively by Agent Platform's `ExecutionRepository`, while 12 domain tables are managed exclusively by GeoStrata's 4 domain repositories (`DocumentRepository`, `GeotechnicalAnalysisRepository`, `FoundationResearchRepository`, `RequirementAgentRepository`), plus 1 legacy prototype table (`project_workflows`).
4. **Coupling Mechanism:** The *sole* coupling is the default database connection string: GeoStrata application code, plugin adapters, and fallback routines currently default to connecting to `"agent_platform.db"`.

This document details the complete table ownership classification, dependency audit, proposed target architecture (`agent_platform.db` and `geostrata.db`), and a safe, repeatable migration strategy for Phase 2B.

---

## 1. Current Database Architecture

### 1.1 Discovered SQLite Database Files on Disk

| Database File | File Size | Description & Status |
|---|---|---|
| `agent_platform.db` | 66,289,664 bytes (66.3 MB) | Primary production database containing all 18 application tables (both Agent Platform and GeoStrata). |
| `agent_platform_checkpoints.db` | 3,907,584 bytes (3.9 MB) | Internal companion database created by Agent Platform's `AsyncSqliteSaver` for LangGraph workflow thread checkpoints (`checkpoints`, `writes`). |
| `storage/documents.db` | 61,440 bytes (61.4 KB) | Legacy/prototype database file containing 4 empty tables (`documents`, `document_pages`, `document_tables`, `document_evidence`). Not referenced by active runtime code. |

### 1.2 Connection & Concurrency Architecture

Both applications connect to SQLite using the Python standard library `sqlite3` module with identical concurrency settings:
- **Journal Mode:** Write-Ahead Logging (`PRAGMA journal_mode = WAL`) is enabled on all disk-based databases, allowing concurrent readers alongside a single active writer.
- **Busy Timeout:** `PRAGMA busy_timeout = 5000` (5,000 ms) configured on all connections to handle transient write lock contention.
- **Thread Safety:** Connections are opened with `check_same_thread=False` and wrapped in process-level re-entrant locks (`threading.RLock()`).
- **Retry Logic:** `ExecutionRepository` wraps write operations in `_execute_with_retry()` with exponential backoff and jitter (up to 5 retries, 50ms initial delay).

### 1.3 Repository Architecture & Responsibilities

The codebase utilizes 5 distinct repository classes, each with cleanly defined boundaries:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AGENT PLATFORM RUNTIME                          │
│                                                                        │
│   ExecutionRepository (app/storage/repository.py)                      │
│   ├── workflows, workflow_versions                                     │
│   ├── runs, events, schedules                                          │
│   └── (Checkpointer: AsyncSqliteSaver -> agent_platform_checkpoints.db)│
└────────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────────┐
│                          GEOSTRATA APPLICATION                         │
│                                                                        │
│   DocumentRepository (geostrata/backend/documents/repository.py)       │
│   ├── documents, document_pages, document_tables, document_evidence   │
│   ├── document_visual_evidence, document_visual_disagreements          │
│   └── document_project_associations                                    │
│                                                                        │
│   GeotechnicalAnalysisRepository (geostrata/.../geotechnical_analysis) │
│   └── geotechnical_analysis_reports, geotechnical_analysis_reviews     │
│                                                                        │
│   FoundationResearchRepository (geostrata/.../foundation_research)     │
│   └── foundation_research_reports                                      │
│                                                                        │
│   RequirementAgentRepository (geostrata/.../requirement_agent)        │
│   └── vendor_requirement_reports, vendor_requirement_reviews           │
└────────────────────────────────────────────────────────────────────────┘
```

1. **`ExecutionRepository`** ([`app/storage/repository.py:66`](file:///c:/Users/PrathamRShetty/Documents/agent_platform/app/storage/repository.py#L66))
   - **Responsibility:** Generic workflow definitions, workflow version history, run lifecycle records, execution events, and workflow schedules.
   - **Schema Init:** `_init_schema()` ([lines 130–163](file:///c:/Users/PrathamRShetty/Documents/agent_platform/app/storage/repository.py#L130-L163)) creates `workflows`, `workflow_versions`, `runs`, `schedules`, and `events`.
   - **Dynamic Migration:** `_ensure_run_columns()` ([lines 165–185](file:///c:/Users/PrathamRShetty/Documents/agent_platform/app/storage/repository.py#L165-L185)) safely adds missing columns to `runs` via `ALTER TABLE`.

2. **`DocumentRepository`** ([`geostrata/backend/documents/repository.py:35`](file:///c:/Users/PrathamRShetty/Documents/agent_platform/geostrata/backend/documents/repository.py#L35))
   - **Responsibility:** Ingested PDF metadata, extracted text pages, tables, bounding boxes, evidence records, multimodal visual evidence, cross-modal discrepancies, and project document matching associations.
   - **Schema Init:** `_init_schema()` ([lines 43–267](file:///c:/Users/PrathamRShetty/Documents/agent_platform/geostrata/backend/documents/repository.py#L43-L267)) creates 7 tables and 7 indexes. Auto-migrates table columns on initialization.

3. **`GeotechnicalAnalysisRepository`** ([`geostrata/backend/agents/geotechnical_analysis/repository.py:14`](file:///c:/Users/PrathamRShetty/Documents/agent_platform/geostrata/backend/agents/geotechnical_analysis/repository.py#L14))
   - **Responsibility:** Agent 1 analysis reports (stratification, groundwater, bearing capacity, settlement, foundation recommendations) and P.E. human review audit records.
   - **Schema Init:** `_init_schema()` ([lines 22–62](file:///c:/Users/PrathamRShetty/Documents/agent_platform/geostrata/backend/agents/geotechnical_analysis/repository.py#L22-L62)) creates `geotechnical_analysis_reports` and `geotechnical_analysis_reviews`.

4. **`FoundationResearchRepository`** ([`geostrata/backend/agents/foundation_research/repository.py:19`](file:///c:/Users/PrathamRShetty/Documents/agent_platform/geostrata/backend/agents/foundation_research/repository.py#L19))
   - **Responsibility:** Agent 2 foundation research reports (building codes, local geotechnical practice, contractor availability, equipment and pricing).
   - **Schema Init:** `_init_schema()` ([lines 27–53](file:///c:/Users/PrathamRShetty/Documents/agent_platform/geostrata/backend/agents/foundation_research/repository.py#L27-L53)) creates `foundation_research_reports` and 2 indexes.

5. **`RequirementAgentRepository`** ([`geostrata/backend/agents/requirement_agent/repository.py:19`](file:///c:/Users/PrathamRShetty/Documents/agent_platform/geostrata/backend/agents/requirement_agent/repository.py#L19))
   - **Responsibility:** Agent 3 vendor foundation requirement specifications, procurement documents, itemized work scopes, and engineer sign-off records.
   - **Schema Init:** `_init_schema()` ([lines 27–69](file:///c:/Users/PrathamRShetty/Documents/agent_platform/geostrata/backend/agents/requirement_agent/repository.py#L27-L69)) creates `vendor_requirement_reports`, `vendor_requirement_reviews`, and 3 indexes.

---

## 2. Complete Table Ownership Inventory

Every table currently present in `agent_platform.db` and `agent_platform_checkpoints.db` has been audited and classified:

| # | Table Name | Current Database | Rows | Owning Application | Accessing Code Files | Read/Write Operations | Foreign Keys & Constraints | Proposed Destination DB |
|---|---|---|---|---|---|---|---|---|
| 1 | `workflows` | `agent_platform.db` | 11 | **Agent Platform** | `app/storage/repository.py`, `app/api/app.py`, `app/cli.py` | R/W (Insert or replace on manifest sync; read on run trigger) | PK: `workflow_id` | `agent_platform.db` |
| 2 | `workflow_versions` | `agent_platform.db` | 11 | **Agent Platform** | `app/storage/repository.py`, `app/api/app.py` | R/W (Versioned immutable workflow history) | PK: `(workflow_id, version)` | `agent_platform.db` |
| 3 | `runs` | `agent_platform.db` | 77 | **Agent Platform** | `app/storage/repository.py`, `app/api/app.py`, `app/cli.py` | R/W (Workflow run lifecycle, inputs/outputs JSON, status updates) | PK: `run_id` | `agent_platform.db` |
| 4 | `events` | `agent_platform.db` | 307 | **Agent Platform** | `app/storage/repository.py`, `app/api/app.py` | R/W (Step/node execution events, outputs, streaming payloads) | PK: `id` (Auto-increment), soft FK: `run_id` | `agent_platform.db` |
| 5 | `schedules` | `agent_platform.db` | 0 | **Agent Platform** | `app/storage/repository.py`, `app/temporal/schedules.py` | R/W (Cron and interval automated workflow triggers) | PK: `schedule_id` | `agent_platform.db` |
| 6 | `checkpoints` | `agent_platform_checkpoints.db` | 91 | **Agent Platform** | `app/api/app.py`, `app/storage/repository.py` | R/W (LangGraph execution thread state checkpoints) | PK: `(thread_id, checkpoint_ns, checkpoint_id)` | `agent_platform_checkpoints.db` |
| 7 | `writes` | `agent_platform_checkpoints.db` | 372 | **Agent Platform** | `app/api/app.py` | R/W (LangGraph channel writes per task execution) | PK: `(thread_id, checkpoint_ns, checkpoint_id, task_id, idx)` | `agent_platform_checkpoints.db` |
| 8 | `documents` | `agent_platform.db` | 42 | **GeoStrata** | `geostrata/backend/documents/repository.py`, `geostrata/backend/documents/service.py`, `geostrata/plugins/*/adapter.py` | R/W (PDF uploads, SHA256 hashes, status, project info metadata) | PK: `document_id`, Index: `(sha256_hash, project_id)` | `geostrata.db` |
| 9 | `document_pages` | `agent_platform.db` | 357 | **GeoStrata** | `geostrata/backend/documents/repository.py` | R/W (Page dimensions, raw extracted text, OCR scanned flags) | PK: `(document_id, page_index)` | `geostrata.db` |
| 10 | `document_tables` | `agent_platform.db` | 360 | **GeoStrata** | `geostrata/backend/documents/repository.py` | R/W (Defragmented engineering tables, headers, cell rows, bounding boxes) | PK: `table_id`, Index: `(document_id, page_index)` | `geostrata.db` |
| 11 | `document_evidence` | `agent_platform.db` | 3,705 | **GeoStrata** | `geostrata/backend/documents/repository.py` | R/W (Extracted bearing capacity, water table, SPT N-values, unit weights) | PK: `evidence_id`, Indexes: `(document_id, page_index)`, `property_type` | `geostrata.db` |
| 12 | `document_visual_evidence` | `agent_platform.db` | 13 | **GeoStrata** | `geostrata/backend/documents/repository.py`, `geostrata/backend/documents/vision/service.py` | R/W (VLM visual extraction, diagram crops, visual descriptions) | PK: `visual_evidence_id`, Index: `(document_id, page_index)` | `geostrata.db` |
| 13 | `document_visual_disagreements` | `agent_platform.db` | 0 | **GeoStrata** | `geostrata/backend/documents/repository.py` | R/W (Cross-modal discrepancy tracking between text and visual evidence) | PK: `disagreement_id`, Index: `(document_id, page_index)` | `geostrata.db` |
| 14 | `document_project_associations` | `agent_platform.db` | 58 | **GeoStrata** | `geostrata/backend/documents/repository.py`, `geostrata/plugins/project_document_validator/adapter.py` | R/W (Document-to-project matching confidence, user decisions, conflict reasons) | PK: `association_id`, Index: `(project_id, document_id)` | `geostrata.db` |
| 15 | `geotechnical_analysis_reports` | `agent_platform.db` | 134 | **GeoStrata** | `geostrata/backend/agents/geotechnical_analysis/repository.py` | R/W (Agent 1 synthesized geotechnical reports, JSON model, markdown) | PK: `report_id`, Indexes: `document_id`, `project_id` | `geostrata.db` |
| 16 | `geotechnical_analysis_reviews` | `agent_platform.db` | 1 | **GeoStrata** | `geostrata/backend/agents/geotechnical_analysis/repository.py` | R/W (P.E. human review decisions and comments) | PK: `review_id`, FK: `report_id -> geotechnical_analysis_reports(report_id)` | `geostrata.db` |
| 17 | `foundation_research_reports` | `agent_platform.db` | 101 | **GeoStrata** | `geostrata/backend/agents/foundation_research/repository.py` | R/W (Agent 2 foundation market research, code analysis, cost evaluations) | PK: `report_id`, Indexes: `(project_id, created_at)`, `(document_id, created_at)` | `geostrata.db` |
| 18 | `vendor_requirement_reports` | `agent_platform.db` | 222 | **GeoStrata** | `geostrata/backend/agents/requirement_agent/repository.py` | R/W (Agent 3 vendor requirement documents, specifications, bill of quantities) | PK: `report_id`, Indexes: `(project_id, created_at)`, `(document_id, created_at)`, `(geotechnical_report_id, foundation_research_report_id)` | `geostrata.db` |
| 19 | `vendor_requirement_reviews` | `agent_platform.db` | 37 | **GeoStrata** | `geostrata/backend/agents/requirement_agent/repository.py` | R/W (Human engineering review and approval records for requirement documents) | PK: `review_id` | `geostrata.db` |
| 20 | `project_workflows` | `agent_platform.db` | 1 | **GeoStrata (Legacy)** | None in active codebase (early prototype record) | Read-only historical data | PK: `workflow_id` | `geostrata.db` (for archival integrity) |

---

## 3. Cross-Application Dependency Inventory

### 3.1 SQL Joins
- **Result:** **0 Cross-Domain Joins.**
- **Verification:** An exhaustive regex and AST scan across all Python files identified only 1 SQL join in the entire repository: `app/storage/repository.py:498` (`LEFT JOIN runs r ON e.run_id = r.run_id`), which joins two internal Agent Platform tables (`events` and `runs`).

### 3.2 Direct Repository Imports
- **Result:** **0 Cross-Domain Repository Imports.**
- **Verification:**
  - `app/` contains 0 imports from `geostrata/` or GeoStrata repositories.
  - `geostrata/` contains 0 imports from `app/storage/` or `ExecutionRepository`.

### 3.3 Shared SQLite Connections
- **Current State:** Both applications share `agent_platform.db` because:
  - `geostrata/backend/api/app.py:91` falls back to `AGENT_PLATFORM_DB_PATH` or `"agent_platform.db"` when `GEOSTRATA_DB_PATH` is unset.
  - `geostrata/plugins/*/adapter.py` default to `os.getenv("AGENT_PLATFORM_DB_PATH", "agent_platform.db")`.
  - Fallback routines in `geotechnical_analysis/graph.py` (line 118) and `foundation_research/graph.py` (lines 99, 123) hardcode `"agent_platform.db"`.
- **Target Resolution:** Each application connects to its own independent file:
  - Agent Platform -> `AGENT_PLATFORM_DB_PATH` (default: `agent_platform.db`)
  - GeoStrata -> `GEOSTRATA_DB_PATH` (default: `geostrata.db`)

### 3.4 Cross-Domain Transactions
- **Result:** **0 Cross-Domain Transactions.**
- Every repository manages its own SQLite transaction boundary using `with self._lock:` and `self._conn.commit()`. There are no distributed or cross-table multi-repository transactions.

### 3.5 Workflow Dataflow & Execution Dependencies
In the workflow `geotechnical_foundation_investigation` ([`geostrata/workflow_definitions/geotechnical_foundation_investigation.yaml`](file:///c:/Users/PrathamRShetty/Documents/agent_platform/geostrata/workflow_definitions/geotechnical_foundation_investigation.yaml)):
- Agent Platform's `WorkflowBuilder` compiles the execution graph and manages state transitions between 4 activity nodes:
  1. `project_document_validator`
  2. `geotechnical_analysis`
  3. `foundation_research`
  4. `requirement_agent`
- **Data Exchange Mechanism:** Nodes exchange data exclusively through **declarative input/output mappings**:
  - `workflow_input.project_id`
  - `workflow_input.confirmed_document_ids`
  - `node_outputs.geotechnical_analysis_node.report_id`
  - `node_outputs.foundation_research_node.report_id`
- **Storage Boundary:** Agent Platform stores string IDs and output dictionaries as generic JSON in `runs.payload` and `events.payload`. Agent Platform never queries the contents of `geotechnical_analysis_reports`, `documents`, or `vendor_requirement_reports`. The domain agents query and persist their own data in GeoStrata's database.
- **Post-Separation Compatibility:** Because Agent Platform treats node outputs as opaque JSON payloads conforming to the `AgentRequest` / `AgentResult` SDK contract, splitting the databases has **zero impact** on workflow orchestration.

---

## 4. Existing Repository and Connection Architecture

### 4.1 Agent Platform Application Factory (`app/api/app.py`)
```python
# app/api/app.py lines 75-80
repository_path = Path(repo.path if hasattr(repo, "path") else os.getenv("AGENT_PLATFORM_DB_PATH", "agent_platform.db")).resolve()
```
- Accepts an `ExecutionRepository` instance.
- Initializes companion checkpoint database path:
  `checkpoint_path = str(repository_path.with_name(repository_path.stem + "_checkpoints" + (repository_path.suffix or ".db")))`
- Exposes `app.state.repository = repo`.

### 4.2 GeoStrata Application Factory (`geostrata/backend/api/app.py`)
```python
# geostrata/backend/api/app.py lines 82-101
resolved_path = os.getenv("GEOSTRATA_DB_PATH", os.getenv("AGENT_PLATFORM_DB_PATH", "agent_platform.db"))
conn = sqlite3.connect(str(db_file), check_same_thread=False)
conn.execute("PRAGMA busy_timeout = 5000")
conn.execute("PRAGMA journal_mode = WAL")
```
- Passes `conn` and `db_lock` directly to:
  - `DocumentRepository(conn, db_lock)`
  - `GeotechnicalAnalysisRepository(conn, db_lock)`
  - `FoundationResearchRepository(conn, db_lock)`
  - `RequirementAgentRepository(conn, db_lock)`
- Exposes `_RepositoryShim(conn, db_lock)` on `app.state.repository` for backward compatibility with router fallback dependency functions.

### 4.3 GeoStrata Plugin Adapters (`geostrata/plugins/*/adapter.py`)
Currently, when invoked in-process by `AgentRunner`, each of the 4 GeoStrata adapters opens its own database connection:
- `geostrata/plugins/project_document_validator/adapter.py:28`
- `geostrata/plugins/geotechnical_analysis/adapter.py:97`
- `geostrata/plugins/foundation_research/adapter.py:77`
- `geostrata/plugins/requirement_agent/adapter.py:31`

All 4 currently evaluate:
```python
db_path = inputs.get("db_path") or os.getenv("AGENT_PLATFORM_DB_PATH", "agent_platform.db")
conn = sqlite3.connect(db_path, check_same_thread=False)
```

In Phase 2B, this line will be updated across all 4 adapters to prioritize `GEOSTRATA_DB_PATH`:
```python
db_path = inputs.get("db_path") or os.getenv("GEOSTRATA_DB_PATH") or os.getenv("AGENT_PLATFORM_DB_PATH", "geostrata.db")
conn = sqlite3.connect(db_path, check_same_thread=False)
```

---

## 5. Proposed Independent Database Architecture

```
                                WORKSPACE
                                    │
           ┌────────────────────────┴────────────────────────┐
           ▼                                                 ▼
    AGENT PLATFORM                                       GEOSTRATA
  (Port 8000 / FastAPI)                             (Port 8001 / FastAPI)
           │                                                 │
  AGENT_PLATFORM_DB_PATH                              GEOSTRATA_DB_PATH
  (default: agent_platform.db)                       (default: geostrata.db)
           │                                                 │
           ▼                                                 ▼
┌─────────────────────────────┐                    ┌─────────────────────────────┐
│      agent_platform.db      │                    │         geostrata.db        │
│                             │                    │                             │
│  - workflows                │                    │  - documents                │
│  - workflow_versions        │                    │  - document_pages           │
│  - runs                     │                    │  - document_tables          │
│  - events                   │                    │  - document_evidence        │
│  - schedules                │                    │  - document_visual_evidence │
│                             │                    │  - document_visual_disagree.│
│  (Companion Checkpointer:)  │                    │  - document_project_assoc.  │
│  agent_platform_            │                    │  - geotechnical_reports     │
│    checkpoints.db           │                    │  - geotechnical_reviews     │
│    - checkpoints            │                    │  - foundation_res_reports   │
│    - writes                 │                    │  - vendor_req_reports       │
│                             │                    │  - vendor_req_reviews       │
│                             │                    │  - project_workflows (leg.) │
└─────────────────────────────┘                    └─────────────────────────────┘
```

### 5.1 Environment Configuration Conventions

| Variable | Default Value | Owning Service | Purpose |
|---|---|---|---|
| `AGENT_PLATFORM_DB_PATH` | `agent_platform.db` | Agent Platform | Path to generic platform SQLite database. |
| `GEOSTRATA_DB_PATH` | `geostrata.db` | GeoStrata | Path to domain geotechnical SQLite database. |
| `AGENT_PLATFORM_URL` | `http://127.0.0.1:8000` | GeoStrata Proxy | HTTP endpoint GeoStrata proxies `/v1/runs` and `/v1/workflows` to. |

---

## 6. Migration Strategy (Phase 2B Roadmap)

### Step 1: Pre-Migration Safe Snapshot (Byte-for-Byte Backup)
Before running any migration:
```bash
# Automated copy of the live production database
cp agent_platform.db agent_platform.db.bak_phase2a
if (Test-Path agent_platform_checkpoints.db) { cp agent_platform_checkpoints.db agent_platform_checkpoints.db.bak_phase2a }
```
- The original `agent_platform.db` remains completely untouched during the extraction process.
- No files are deleted or modified until extraction and verification are 100% complete and validated.

### Step 2: Automated Schema & Data Extraction Script (`scripts/migrate_database_separation.py`)
A dedicated Python migration script will:
1. Connect to destination `geostrata.db` (enabling WAL mode and busy timeout).
2. Instantiate each of the 4 GeoStrata domain repositories (`DocumentRepository`, `GeotechnicalAnalysisRepository`, `FoundationResearchRepository`, `RequirementAgentRepository`) against `geostrata.db` to create all 12 tables and their indexes cleanly.
3. Attach `agent_platform.db` using SQLite's native `ATTACH DATABASE 'agent_platform.db' AS source_db;`.
4. Copy all records in atomic batches:
   ```sql
   INSERT INTO documents SELECT * FROM source_db.documents;
   INSERT INTO document_pages SELECT * FROM source_db.document_pages;
   INSERT INTO document_tables SELECT * FROM source_db.document_tables;
   INSERT INTO document_evidence SELECT * FROM source_db.document_evidence;
   INSERT INTO document_visual_evidence SELECT * FROM source_db.document_visual_evidence;
   INSERT INTO document_visual_disagreements SELECT * FROM source_db.document_visual_disagreements;
   INSERT INTO document_project_associations SELECT * FROM source_db.document_project_associations;
   INSERT INTO geotechnical_analysis_reports SELECT * FROM source_db.geotechnical_analysis_reports;
   INSERT INTO geotechnical_analysis_reviews SELECT * FROM source_db.geotechnical_analysis_reviews;
   INSERT INTO foundation_research_reports SELECT * FROM source_db.foundation_research_reports;
   INSERT INTO vendor_requirement_reports SELECT * FROM source_db.vendor_requirement_reports;
   INSERT INTO vendor_requirement_reviews SELECT * FROM source_db.vendor_requirement_reviews;
   -- Legacy table
   CREATE TABLE project_workflows AS SELECT * FROM source_db.project_workflows;
   ```
5. Commit transactions and detach `source_db`.

### Step 3: Record Count & Checksum Reconciliation
The script will perform automated verification:
```python
for table in GEOSTRATA_TABLES:
    src_count = src_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    dst_count = dst_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    assert src_count == dst_count, f"Mismatch in {table}: source={src_count}, dest={dst_count}"
```
Expected row counts to verify:
- `documents`: 42
- `document_pages`: 357
- `document_tables`: 360
- `document_evidence`: 3,705
- `document_visual_evidence`: 13
- `document_visual_disagreements`: 0
- `document_project_associations`: 58
- `geotechnical_analysis_reports`: 134
- `geotechnical_analysis_reviews`: 1
- `foundation_research_reports`: 101
- `vendor_requirement_reports`: 222
- `vendor_requirement_reviews`: 37
- `project_workflows`: 1

### Step 4: Verification of Specific Entity Relationships
Verify key known entities in `geostrata.db`:
- White Oak primary soil document: ID `7d500784-af45-4a86-a437-e90c3f7b54f2`
- White Oak site plan document: ID `58e1ebc4-b70c-401e-b2c1-a842cadd764a`
- White Oak geotechnical report: ID `geo_rep_8b4818e4b427`

### Step 5: Agent Platform Database Pruning & Vacuum (Phase 2B)
Once `geostrata.db` is verified:
1. Drop the 13 GeoStrata tables from `agent_platform.db`.
2. Execute `VACUUM;` on `agent_platform.db` to reclaim space (shrinking it from 66MB down to generic platform size).
3. `agent_platform.db` now contains exclusively: `workflows`, `workflow_versions`, `runs`, `events`, `schedules`.

### Step 6: Rollback Strategy
If any step fails or verification raises an assertion:
1. Remove `geostrata.db`.
2. Restore `agent_platform.db` from `agent_platform.db.bak_phase2a`.
3. System is immediately returned to exact Phase 1.1 state with zero data loss.

---

## 7. Risks and Mitigation

| Risk | Impact | Likelihood | Mitigation Strategy |
|---|---|---|---|
| **Data Loss during Migration** | Critical | Very Low | Byte-for-byte pre-migration backup (`agent_platform.db.bak_phase2a`). Migration script reads from original and writes to new file without altering original until 100% verified. |
| **Hardcoded Database Paths in Code** | High | Low | Full codebase audit already identified all 3 hardcoded graph fallbacks and 4 adapter routines. All will be updated to check `GEOSTRATA_DB_PATH`. |
| **Foreign Key Constraints Broken** | Medium | None | Audited schema reveals only 1 foreign key exists: `geotechnical_analysis_reviews.report_id -> geotechnical_analysis_reports(report_id)`. Both tables reside in GeoStrata; constraint is 100% preserved. |
| **Database Lock Contention** | Medium | Low | Migration runs offline while servers are stopped, or using WAL mode read transactions. |
| **Test Fixtures Expecting Shared Database** | Medium | Medium | Update test fixtures in `tests/conftest.py` and test suites to configure `GEOSTRATA_DB_PATH="geostrata.db"` alongside `AGENT_PLATFORM_DB_PATH`. |

---

## 8. Required Code Changes for Phase 2B (Grouped by Module)

### Module 1: GeoStrata Application Entrypoint (`geostrata_app.py`)
- Add default environment configuration:
  ```python
  os.environ.setdefault("GEOSTRATA_DB_PATH", "geostrata.db")
  ```

### Module 2: GeoStrata App Factory (`geostrata/backend/api/app.py`)
- Update line 91 default:
  ```python
  resolved_path = os.getenv("GEOSTRATA_DB_PATH", "geostrata.db")
  ```

### Module 3: GeoStrata Plugin Adapters (`geostrata/plugins/*/adapter.py`)
Update the connection string in all 4 adapters:
1. `geostrata/plugins/project_document_validator/adapter.py:28`
2. `geostrata/plugins/geotechnical_analysis/adapter.py:97`
3. `geostrata/plugins/foundation_research/adapter.py:77`
4. `geostrata/plugins/requirement_agent/adapter.py:31`

Change:
```python
db_path = inputs.get("db_path") or os.getenv("GEOSTRATA_DB_PATH") or os.getenv("AGENT_PLATFORM_DB_PATH", "geostrata.db")
```

### Module 4: LangGraph Graph Node Fallback Connections
Update hardcoded `"agent_platform.db"` fallbacks:
1. `geostrata/backend/agents/geotechnical_analysis/graph.py:118`:
   ```python
   db_path = os.getenv("GEOSTRATA_DB_PATH", "geostrata.db")
   conn = sqlite3.connect(db_path, check_same_thread=False)
   ```
2. `geostrata/backend/agents/foundation_research/graph.py:99`:
   ```python
   db_path = os.getenv("GEOSTRATA_DB_PATH", "geostrata.db")
   conn = sqlite3.connect(db_path, check_same_thread=False)
   ```
3. `geostrata/backend/agents/foundation_research/graph.py:123`:
   ```python
   db_path = os.getenv("GEOSTRATA_DB_PATH", "geostrata.db")
   conn = sqlite3.connect(db_path, check_same_thread=False)
   ```

### Module 5: Environment & Test Configuration
1. `.env.example`:
   ```bash
   AGENT_PLATFORM_DB_PATH=agent_platform.db
   GEOSTRATA_DB_PATH=geostrata.db
   ```
2. `tests/conftest.py`:
   ```python
   os.environ.setdefault("GEOSTRATA_DB_PATH", "geostrata.db")
   ```

---

## 9. Testing and Verification Plan

In Phase 2B, verification will follow this rigorous 4-step sequence:

1. **Migration Verification:**
   - Execute verification script comparing row counts across all 18 tables.
   - Assert `geostrata.db` contains 100% of domain rows.
   - Assert `agent_platform.db` contains 100% of platform rows.
2. **Application Startup Verification:**
   - Start `uvicorn app.main:app --port 8000`: verify connection to `agent_platform.db`.
   - Start `uvicorn geostrata_app:app --port 8001`: verify connection to `geostrata.db`.
3. **Domain Route Verification:**
   - Query `GET http://127.0.0.1:8001/v1/documents`: verify documents are retrieved from `geostrata.db`.
   - Query `GET http://127.0.0.1:8001/v1/requirements/reports/latest`: verify report data is retrieved from `geostrata.db`.
4. **Automated Test Suites:**
   - Run `tests/test_generic_discovery.py` (9 tests).
   - Run `tests/test_document_pipeline.py` (13 tests).
   - Run `tests/test_requirement_agent.py` (10 tests).
   - Run `tests/test_geotechnical_analysis_agent.py` (6 tests).
   - Run `tests/test_foundation_research.py` (5 tests).
   - Run `tests/test_multi_document_matching.py` (3 tests).
   - Run `tests/test_geotechnical_workflow_integration.py` (3 tests).

---

## 10. Recommended Implementation Sequence for Phase 2B

```
  Step 1: Backup agent_platform.db -> agent_platform.db.bak_phase2a
     │
  Step 2: Create scripts/migrate_database_separation.py
     │
  Step 3: Run migration script to populate geostrata.db
     │
  Step 4: Execute automated count and data reconciliation check
     │
  Step 5: Update GeoStrata code (geostrata_app.py, app.py, adapters, graphs)
     │
  Step 6: Update .env.example and tests/conftest.py
     │
  Step 7: Prune GeoStrata tables from agent_platform.db and VACUUM
     │
  Step 8: Run all test suites and verify both applications start independently
     │
  Step 9: Compile PHASE_2B_DATABASE_SEPARATION_REPORT.md
```

---

## Sign-Off and Hold

This audit and plan is strictly **read-only**. No code or database files have been altered.  
We await user review and explicit approval before initiating Phase 2B implementation.

