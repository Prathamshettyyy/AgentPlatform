from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import pytest
import yaml
from fastapi.testclient import TestClient

from app.api.app import create_app
from geostrata.backend.documents import (
    DocumentMetadata,
    DocumentReadinessStatus,
    DocumentRepository,
    DocumentService,
    DocumentStorage,
    PDFExtractor,
)
from geostrata.backend.documents.matching_models import MatchStatus, UserDecision
from app.registry import AgentLoader, AgentRegistry
from app.runtime.runner import AgentRunner
from app.storage.repository import ExecutionRepository
from app.workflows.builder import WorkflowBuilder
from app.workflows.models import WorkflowDefinition
from app.workflows.validator import validate_workflow

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_YAML_PATH = WORKSPACE_ROOT / "geostrata" / "workflow_definitions" / "geotechnical_foundation_investigation.yaml"
MANIFESTS_DIR = WORKSPACE_ROOT / "geostrata" / "plugins" / "manifests"
REAL_SOIL_REPORT_PATH = Path("storage/documents/7d500784-af45-4a86-a437-e90c3f7b54f2/original.pdf")


@pytest.fixture
def agent_registry():
    """Build an AgentRegistry with all trusted manifests loaded."""
    reg = AgentRegistry()
    loader = AgentLoader(reg, MANIFESTS_DIR)
    loader.load_all()
    return reg


@pytest.fixture
def workflow_def():
    """Load the canonical geotechnical foundation investigation workflow definition."""
    assert WORKFLOW_YAML_PATH.is_file(), f"Workflow file not found: {WORKFLOW_YAML_PATH}"
    raw = yaml.safe_load(WORKFLOW_YAML_PATH.read_text(encoding="utf-8"))
    return WorkflowDefinition.model_validate(raw)


def test_stage1_document_readiness_statuses():
    """Stage 1: Verify document readiness status calculation across document scenarios."""
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    doc_service = DocumentService(repository=DocumentRepository(conn), storage=DocumentStorage())

    white_oak_project_id = "7d500784-af45-4a86-a437-e90c3f7b54f2"

    # 1. Soil Report is MATCHED -> READY_FOR_ANALYSIS
    soil_status = doc_service.get_document_readiness_status(
        "7d500784-af45-4a86-a437-e90c3f7b54f2",
        project_id=white_oak_project_id,
    )
    assert soil_status == DocumentReadinessStatus.READY_FOR_ANALYSIS

    # 2. 2436 Site Plan is POSSIBLE_MATCH and CONFIRMED -> READY_FOR_ANALYSIS
    site_plan_status = doc_service.get_document_readiness_status(
        "58e1ebc4-b70c-401e-b2c1-a842cadd764a",
        project_id=white_oak_project_id,
    )
    assert site_plan_status == DocumentReadinessStatus.READY_FOR_ANALYSIS

    # 3. 2434 Site Plan is MISMATCH and unconfirmed -> READY_FOR_REVIEW (cannot enter analysis)
    mismatch_status = doc_service.get_document_readiness_status(
        "ef3832f5-6364-4611-b259-c12a83338802",
        project_id=white_oak_project_id,
    )
    assert mismatch_status == DocumentReadinessStatus.READY_FOR_REVIEW

    # 4. Nonexistent document -> FAILED
    missing_status = doc_service.get_document_readiness_status("nonexistent-doc-uuid")
    assert missing_status == DocumentReadinessStatus.FAILED


def test_stage1_document_validation_and_version_integrity():
    """Stage 1: Verify validate_project_documents enforces confirmations and document version hashes."""
    conn = sqlite3.connect(os.getenv("GEOSTRATA_DB_PATH", "geostrata.db"), check_same_thread=False)
    doc_service = DocumentService(repository=DocumentRepository(conn), storage=DocumentStorage())

    white_oak_project_id = "7d500784-af45-4a86-a437-e90c3f7b54f2"
    valid_docs = [
        "7d500784-af45-4a86-a437-e90c3f7b54f2",
        "58e1ebc4-b70c-401e-b2c1-a842cadd764a",
    ]

    # Valid confirmed document set
    res = doc_service.validate_project_documents(
        project_id=white_oak_project_id,
        confirmed_document_ids=valid_docs,
    )
    assert res.is_valid is True
    assert res.status == "succeeded"
    assert res.primary_document_id == "7d500784-af45-4a86-a437-e90c3f7b54f2"
    assert res.snapshot is not None
    assert res.snapshot.snapshot_id.startswith("snap_")
    assert len(res.document_versions) == 2

    # Verify version hash checking guards against mid-run document modification
    expected_versions = {
        "7d500784-af45-4a86-a437-e90c3f7b54f2": "tampered_fake_hash_12345",
    }
    tampered_res = doc_service.validate_project_documents(
        project_id=white_oak_project_id,
        confirmed_document_ids=valid_docs,
        expected_versions=expected_versions,
    )
    assert tampered_res.is_valid is False
    assert any("Document version conflict" in e for e in tampered_res.validation_errors)

    # Empty document list rejected
    empty_res = doc_service.validate_project_documents(
        project_id=white_oak_project_id,
        confirmed_document_ids=[],
    )
    assert empty_res.is_valid is False

    # Mismatch unconfirmed document rejected
    mismatch_res = doc_service.validate_project_documents(
        project_id=white_oak_project_id,
        confirmed_document_ids=valid_docs + ["ef3832f5-6364-4611-b259-c12a83338802"],
    )
    assert mismatch_res.is_valid is False
    assert any("MISMATCH" in e for e in mismatch_res.validation_errors)


def test_geotechnical_workflow_definition_loads_and_validates(agent_registry, workflow_def):
    """Stage 2: Verify the 4-node sequential pipeline compiles, validates, and chains correctly."""
    assert workflow_def.id == "geotechnical_foundation_investigation"
    assert len(workflow_def.nodes) == 4
    assert len(workflow_def.edges) == 3

    node_val = workflow_def.nodes[0]
    node_geo = workflow_def.nodes[1]
    node_fnd = workflow_def.nodes[2]
    node_req = workflow_def.nodes[3]

    # Node 1: Validate Project Documents (service task node)
    assert node_val.id == "validate_project_documents_node"
    assert node_val.agent_id == "project_document_validator"
    assert "project_id" in node_val.input_mappings
    assert "confirmed_document_ids" in node_val.input_mappings

    # Node 2: Geotechnical Analysis Agent
    assert node_geo.id == "geotechnical_analysis_node"
    assert node_geo.agent_id == "geotechnical_analysis"
    assert node_geo.input_mappings["confirmed_document_ids"].path == "node_outputs.validate_project_documents_node.validated_document_ids"
    assert node_geo.input_mappings["document_id"].path == "node_outputs.validate_project_documents_node.primary_document_id"

    # Node 3: Foundation Research Agent
    assert node_fnd.id == "foundation_research_node"
    assert node_fnd.agent_id == "foundation_research"
    assert node_fnd.input_mappings["geotechnical_report_id"].path == "node_outputs.geotechnical_analysis_node.report_id"
    assert node_fnd.input_mappings["document_id"].path == "node_outputs.geotechnical_analysis_node.document_id"
    assert node_fnd.input_mappings["confirmed_document_ids"].path == "node_outputs.geotechnical_analysis_node.confirmed_document_ids"

    # Node 4: Vendor Requirement Agent
    assert node_req.id == "requirement_agent_node"
    assert node_req.agent_id == "requirement_agent"
    assert node_req.input_mappings["geotechnical_report_id"].path == "node_outputs.geotechnical_analysis_node.report_id"
    assert node_req.input_mappings["foundation_research_report_id"].path == "node_outputs.foundation_research_node.report_id"
    assert node_req.input_mappings["confirmed_document_ids"].path == "node_outputs.validate_project_documents_node.validated_document_ids"
    assert node_req.input_mappings["snapshot_id"].path == "node_outputs.validate_project_documents_node.snapshot_id"
    assert node_req.input_mappings["document_versions"].path == "node_outputs.validate_project_documents_node.document_versions"

    # Validate against registry
    validate_workflow(workflow_def, agent_registry)

    # Compile into executable LangGraph
    builder = WorkflowBuilder(agent_registry)
    compiled = builder.build(workflow_def)
    assert compiled is not None


@pytest.mark.asyncio
async def test_geotechnical_workflow_e2e_white_oak_execution(agent_registry, workflow_def):
    """Stage 3: Full end-to-end execution of 3-node sequence on White Oak project."""
    builder = WorkflowBuilder(agent_registry)
    compiled = builder.build(workflow_def)

    white_oak_project_id = "7d500784-af45-4a86-a437-e90c3f7b54f2"
    confirmed_docs = [
        "7d500784-af45-4a86-a437-e90c3f7b54f2",
        "58e1ebc4-b70c-401e-b2c1-a842cadd764a",
    ]

    run_id = "geo_wf_e2e_3node_run"
    state_input = {
        "run_id": run_id,
        "workflow_id": workflow_def.id,
        "workflow_version": workflow_def.version,
        "workflow_input": {
            "project_id": white_oak_project_id,
            "confirmed_document_ids": confirmed_docs,
        },
        "node_outputs": {},
        "agent_outputs": {},
    }

    result = await compiled.ainvoke(
        state_input,
        {"configurable": {"thread_id": run_id}},
    )

    assert result is not None
    node_outputs = result.get("node_outputs", {})

    # 1. Verify Node 1: Validate Project Documents Output
    assert "validate_project_documents_node" in node_outputs
    val_out = node_outputs["validate_project_documents_node"]
    assert val_out["status"] == "succeeded"
    assert val_out["primary_document_id"] == "7d500784-af45-4a86-a437-e90c3f7b54f2"
    assert len(val_out["validated_document_ids"]) == 2
    assert val_out["snapshot_id"].startswith("snap_")
    assert len(val_out["document_versions"]) == 2

    # 2. Verify Node 2: Geotechnical Analysis Output
    assert "geotechnical_analysis_node" in node_outputs
    geo_out = node_outputs["geotechnical_analysis_node"]
    assert geo_out["status"] == "succeeded"
    assert geo_out["report_id"].startswith("geo_rep_")
    assert geo_out["document_id"] == "7d500784-af45-4a86-a437-e90c3f7b54f2"
    assert geo_out["review_status"] == "PENDING_REVIEW"
    assert geo_out["project_context"]["project_number"] == "25-0117"

    # 3. Verify Node 3: Foundation Research Output
    assert "foundation_research_node" in node_outputs
    fnd_out = node_outputs["foundation_research_node"]
    assert fnd_out["status"] == "succeeded"
    assert fnd_out["report_id"].startswith("fnd_rep_")
    assert fnd_out["geotechnical_report_id"] == geo_out["report_id"]
    assert fnd_out["document_id"] == geo_out["document_id"]
    assert len(fnd_out["options_researched"]) >= 4

    # 4. Verify Node 4: Vendor Requirement Agent Output
    assert "requirement_agent_node" in node_outputs
    req_out = node_outputs["requirement_agent_node"]
    assert req_out["status"] == "succeeded"
    assert req_out["report_id"].startswith("req_")
    assert req_out["geotechnical_report_id"] == geo_out["report_id"]
    assert req_out["foundation_research_report_id"] == fnd_out["report_id"]
    assert req_out["review_status"] == "PENDING_REVIEW"
    assert req_out["is_preliminary_draft"] is True

    # 5. Verify no large PDF byte payloads were passed between nodes (only IDs and metadata)
    for node_name, out in node_outputs.items():
        assert "pdf_bytes" not in out
        assert "raw_pdf" not in out


@pytest.mark.asyncio
async def test_geotechnical_workflow_persists_in_execution_repository(tmp_path, agent_registry, workflow_def):
    """Test 4: Verify execution history, node outputs, and event capturing in repository."""
    repo = ExecutionRepository(str(tmp_path / "test_exec.db"))
    builder = WorkflowBuilder(agent_registry)
    compiled = builder.build(workflow_def)

    white_oak_project_id = "7d500784-af45-4a86-a437-e90c3f7b54f2"
    confirmed_docs = ["7d500784-af45-4a86-a437-e90c3f7b54f2"]
    run_id = "repo_persist_run_3node"
    inputs = {
        "project_id": white_oak_project_id,
        "confirmed_document_ids": confirmed_docs,
    }

    # Simulate direct execution flow in app.py
    repo.start_run(
        run_id=run_id,
        workflow_id=workflow_def.id,
        payload=inputs,
        workflow_version=workflow_def.version,
        thread_id=run_id,
        owner_id="test_user",
        execution_backend="direct",
    )

    result = await compiled.ainvoke(
        {
            "run_id": run_id,
            "workflow_id": workflow_def.id,
            "workflow_version": workflow_def.version,
            "workflow_input": inputs,
            "node_outputs": {},
            "agent_outputs": {},
        },
        {"configurable": {"thread_id": run_id}},
    )

    repo.update_run(run_id, "succeeded", result)
    for node_id, output in result.get("node_outputs", {}).items():
        repo.add_event(run_id, node_id, "succeeded", output)

    stored_run = repo.get_run(run_id)
    assert stored_run is not None
    assert stored_run["status"] == "succeeded"
    assert stored_run["workflow_id"] == workflow_def.id
    assert stored_run["agent_outputs"]["validate_project_documents_node"]["status"] == "succeeded"
    assert stored_run["agent_outputs"]["geotechnical_analysis_node"]["report_id"].startswith("geo_rep_")
    assert stored_run["agent_outputs"]["foundation_research_node"]["report_id"].startswith("fnd_rep_")

    events = repo.list_events(run_id)
    event_nodes = [e["node_id"] for e in events]
    assert "validate_project_documents_node" in event_nodes
    assert "geotechnical_analysis_node" in event_nodes
    assert "foundation_research_node" in event_nodes

    repo.close()


@pytest.mark.asyncio
async def test_geotechnical_workflow_rejects_mismatched_documents(agent_registry, workflow_def):
    """Test 5: Workflow immediately stops at Node 1 when mismatched document is provided."""
    builder = WorkflowBuilder(agent_registry)
    compiled = builder.build(workflow_def)

    white_oak_project_id = "7d500784-af45-4a86-a437-e90c3f7b54f2"
    mismatched_docs = [
        "7d500784-af45-4a86-a437-e90c3f7b54f2",
        "ef3832f5-6364-4611-b259-c12a83338802",  # Mismatch document
    ]

    run_id = "reject_mismatch_run"
    state_input = {
        "run_id": run_id,
        "workflow_id": workflow_def.id,
        "workflow_version": workflow_def.version,
        "workflow_input": {
            "project_id": white_oak_project_id,
            "confirmed_document_ids": mismatched_docs,
        },
        "node_outputs": {},
        "agent_outputs": {},
    }

    with pytest.raises(Exception) as exc_info:
        await compiled.ainvoke(
            state_input,
            {"configurable": {"thread_id": run_id}},
        )

    err_msg = str(exc_info.value)
    assert "MISMATCH" in err_msg or "REJECTED" in err_msg
    assert "ef3832f5-6364-4611-b259-c12a83338802" in err_msg


def test_api_pre_workflow_validation_blocks_invalid_runs():
    """Test 6: Verify API start_run endpoint blocks execution via pre-workflow validation."""
    app = create_app(manifests_dir=MANIFESTS_DIR)
    client = TestClient(app)

    # 1. Attempting to start run with mismatched document MUST return 400
    bad_resp = client.post(
        "/v1/runs",
        json={
            "workflow_id": "geotechnical_foundation_investigation",
            "inputs": {
                "project_id": "7d500784-af45-4a86-a437-e90c3f7b54f2",
                "confirmed_document_ids": [
                    "7d500784-af45-4a86-a437-e90c3f7b54f2",
                    "ef3832f5-6364-4611-b259-c12a83338802",  # Mismatch
                ],
            },
        },
    )
    assert bad_resp.status_code == 400
    assert "MISMATCH" in bad_resp.json()["detail"]

    # 2. Direct document validation endpoint
    val_resp = client.post(
        "/v1/documents/projects/7d500784-af45-4a86-a437-e90c3f7b54f2/validate-documents",
        json={
            "confirmed_document_ids": [
                "7d500784-af45-4a86-a437-e90c3f7b54f2",
                "58e1ebc4-b70c-401e-b2c1-a842cadd764a",
            ],
        },
    )
    assert val_resp.status_code == 200
    val_data = val_resp.json()
    assert val_data["is_valid"] is True
    assert val_data["primary_document_id"] == "7d500784-af45-4a86-a437-e90c3f7b54f2"
    assert len(val_data["document_versions"]) == 2

    # 3. Document readiness endpoint
    readiness_resp = client.get("/v1/documents/7d500784-af45-4a86-a437-e90c3f7b54f2/readiness")
    assert readiness_resp.status_code == 200
    assert readiness_resp.json()["readiness_status"] == "READY_FOR_ANALYSIS"


def test_portal_image_upload_and_workflow_retry(tmp_path):
    """Test 7: Verify PNG/JPEG upload support for the standalone portal and workflow retry history."""
    import io
    from PIL import Image

    repo = ExecutionRepository(str(tmp_path / "portal_test.db"))
    app = create_app(repository=repo, manifests_dir=MANIFESTS_DIR)
    client = TestClient(app)

    # Create a valid PNG image in memory
    img = Image.new("RGB", (400, 300), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    up_resp = client.post(
        "/v1/documents/upload",
        data={"project_id": "proj_img_test"},
        files=[("files", ("site_plan_drawing.png", png_bytes, "image/png"))],
    )
    assert up_resp.status_code == 200
    up_data = up_resp.json()
    assert isinstance(up_data, list)
    assert len(up_data) == 1
    doc_meta = up_data[0]
    assert doc_meta["filename"] == "site_plan_drawing.png"
    assert doc_meta["status"] == "completed"
    assert doc_meta["page_count"] == 1



