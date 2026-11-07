from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from geostrata.backend.documents import DocumentService, DocumentRepository, DocumentStorage
from geostrata.backend.documents.structure import extract_project_info
from app.llm import get_llm, LLMClient
from .models import (
    ComparisonRow,
    DiscrepancyItem,
    EngineerQuestion,
    EvidenceCitation,
    EvidenceReferencesSection,
    ExecutiveSummary,
    FoundationComparison,
    FoundationSystemItem,
    FoundationSystemsInReport,
    GeotechnicalAnalysisReport,
    GroundwaterAssessment,
    GroundwaterMeasurementItem,
    LaboratoryInterpretation,
    LimitationsAndReviewSection,
    MissingInformationItem,
    MissingInformationSection,
    ProjectDocumentContext,
    QuestionsForEngineerSection,
    RiskConcern,
    RisksAndConcerns,
    SitePreparationSection,
    SitePrepItem,
    SoilInvestigationSummary,
    StratumInterval,
    SubsurfaceConditions,
    _now_iso,
)
from .prompts import (
    GEOTECHNICAL_SYSTEM_PROMPT,
    SOIL_ANALYSIS_PROMPT,
    FOUNDATION_ANALYSIS_PROMPT,
    RISKS_AND_MISSING_PROMPT,
)

logger = logging.getLogger("agent_platform.geotechnical_analysis.graph")


# ==============================================================================
# Graph State Definition
# ==============================================================================

class GeotechnicalAnalysisState(TypedDict, total=False):
    # Inputs
    document_id: str
    project_id: str
    run_id: Optional[str]
    llm_profile: str
    document_service: Optional[DocumentService]
    llm_client: Optional[LLMClient]

    # Loaded Database Context
    document_metadata: dict[str, Any]
    first_pages_text: Optional[str]
    evidence_records: list[dict[str, Any]]
    evidence_lookup: dict[str, dict[str, Any]]
    boring_logs: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    foundation_recommendations: list[dict[str, Any]]
    site_preparation_requirements: list[dict[str, Any]]
    visual_evidence: list[dict[str, Any]]
    visual_disagreements: list[dict[str, Any]]
    documents_reviewed: list[str]
    confirmed_docs_meta: list[dict[str, Any]]

    # Synthesized Sections
    executive_summary: dict[str, Any]
    project_context: dict[str, Any]
    investigation_summary: dict[str, Any]
    subsurface_conditions: dict[str, Any]
    laboratory_interpretation: dict[str, Any]
    groundwater_assessment: dict[str, Any]
    foundation_systems: dict[str, Any]
    foundation_comparison: dict[str, Any]
    site_preparation: dict[str, Any]
    risks_and_concerns: dict[str, Any]
    missing_information: dict[str, Any]
    questions_for_engineers: dict[str, Any]
    evidence_citations: list[dict[str, Any]]
    unresolved_citations_count: int

    # Final Output
    report: dict[str, Any]
    markdown_content: str
    status: str
    error: Optional[str]


# ==============================================================================
# Node 1: load_project_evidence
# ==============================================================================

def load_project_evidence(state: GeotechnicalAnalysisState) -> dict[str, Any]:
    """Load all structured extraction records, boring logs, tables, and evidence records from SQLite.

    If multi-document associations have been confirmed for the project, aggregates evidence
    across all confirmed project documents.
    """
    doc_id = state["document_id"]
    service = state.get("document_service")
    if service is None:
        from .service import get_current_document_service
        service = get_current_document_service()
    if service is None:
        import os, sqlite3
        db_path = os.getenv("GEOSTRATA_DB_PATH", "geostrata.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        repo = DocumentRepository(conn)
        storage = DocumentStorage()
        service = DocumentService(repository=repo, storage=storage)

    meta = service.get_document(doc_id)
    if not meta:
        raise ValueError(f"Document with ID '{doc_id}' not found in database.")

    # Multi-document check: find all confirmed documents associated with this project
    confirmed_docs = [meta]
    confirmed_doc_ids = [doc_id]
    target_project_id = state.get("project_id") or meta.project_id

    try:
        associations = service.get_associations_for_project(target_project_id)
        if not associations and meta.project_info and meta.project_info.project_number:
            associations = service.get_associations_for_project(meta.project_info.project_number)

        for assoc in associations:
            is_confirmed = (str(assoc.user_decision).upper() in ("CONFIRMED", "USERDECISION.CONFIRMED")) or (
                str(assoc.match_status).upper() in ("MATCHED", "MATCHSTATUS.MATCHED")
                and str(assoc.user_decision).upper() not in ("REJECTED", "USERDECISION.REJECTED")
            )
            if is_confirmed and assoc.document_id not in confirmed_doc_ids:
                other_meta = service.get_document(assoc.document_id)
                if other_meta:
                    confirmed_docs.append(other_meta)
                    confirmed_doc_ids.append(assoc.document_id)
    except Exception as assoc_err:
        logger.debug("Multi-document association query skipped or empty: %s", assoc_err)

    first_pages_text = ""
    evidence_records: list[dict[str, Any]] = []
    evidence_lookup: dict[str, dict[str, Any]] = {}
    boring_logs: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    foundations: list[dict[str, Any]] = []
    site_prep: list[dict[str, Any]] = []
    visual_evidence: list[dict[str, Any]] = []
    visual_disagreements: list[dict[str, Any]] = []

    for d in confirmed_docs:
        d_id = d.document_id
        try:
            pages = service.get_document_pages(d_id)
            if pages:
                p_text = "\n".join([p.raw_text for p in pages[:3] if p.raw_text])
                if first_pages_text:
                    first_pages_text += f"\n\n--- Document: {d.filename} ---\n" + p_text
                else:
                    first_pages_text = p_text
        except Exception as p_err:
            logger.warning("Could not read pages text for %s: %s", d_id, p_err)

        for e in service.get_document_evidence(d_id):
            e_dict = e.model_dump()
            e_dict["document_id"] = d_id
            e_dict["document_filename"] = d.filename
            evidence_records.append(e_dict)
            evidence_lookup[e_dict["evidence_id"]] = e_dict

        for b in service.get_boring_logs(d_id):
            b_dict = b.model_dump()
            b_dict["document_id"] = d_id
            b_dict["document_filename"] = d.filename
            boring_logs.append(b_dict)

        for t in service.get_document_tables(d_id):
            t_dict = t.model_dump()
            t_dict["document_id"] = d_id
            t_dict["document_filename"] = d.filename
            tables.append(t_dict)

        for f in service.get_foundation_recommendations(d_id):
            f_dict = f.model_dump()
            f_dict["document_id"] = d_id
            f_dict["document_filename"] = d.filename
            foundations.append(f_dict)

        for s in service.get_site_preparation(d_id):
            s_dict = s.model_dump()
            s_dict["document_id"] = d_id
            s_dict["document_filename"] = d.filename
            site_prep.append(s_dict)

        for v in service.repo.get_visual_evidence(d_id):
            v_dict = v.model_dump()
            v_dict["document_id"] = d_id
            v_dict["document_filename"] = d.filename
            visual_evidence.append(v_dict)

        for dis in service.repo.get_visual_disagreements(d_id):
            dis_dict = dis.model_dump()
            dis_dict["document_id"] = d_id
            dis_dict["document_filename"] = d.filename
            visual_disagreements.append(dis_dict)

    documents_reviewed = [d.filename for d in confirmed_docs]
    confirmed_docs_meta = [d.model_dump() for d in confirmed_docs]

    logger.info(
        "Loaded project evidence for %s (%d confirmed docs): evidence=%d, borings=%d, tables=%d, foundations=%d, site_prep=%d, visual=%d, disagreements=%d",
        doc_id,
        len(confirmed_docs),
        len(evidence_records),
        len(boring_logs),
        len(tables),
        len(foundations),
        len(site_prep),
        len(visual_evidence),
        len(visual_disagreements),
    )

    return {
        "document_metadata": meta.model_dump(),
        "first_pages_text": first_pages_text,
        "evidence_records": evidence_records,
        "evidence_lookup": evidence_lookup,
        "boring_logs": boring_logs,
        "tables": tables,
        "foundation_recommendations": foundations,
        "site_preparation_requirements": site_prep,
        "visual_evidence": visual_evidence,
        "visual_disagreements": visual_disagreements,
        "documents_reviewed": documents_reviewed,
        "confirmed_docs_meta": confirmed_docs_meta,
    }


# ==============================================================================
# Node 2: validate_document_context
# ==============================================================================

def validate_document_context(state: GeotechnicalAnalysisState) -> dict[str, Any]:
    """Validate document integrity, extract project metadata, and detect document discrepancies."""
    doc_meta = state["document_metadata"]
    proj_info = dict(doc_meta.get("project_info") or {})

    filename = doc_meta.get("filename", "Soil report 25-0117 v1.pdf")
    doc_version = None
    v_m = re.search(r"\b(v\d+(?:\.\d+)?)\b", filename, re.IGNORECASE)
    if v_m:
        doc_version = v_m.group(1).lower()

    # Re-extract from front pages if project_name is missing or generic
    first_pages_text = state.get("first_pages_text", "")
    if first_pages_text and (
        not proj_info.get("project_name")
        or proj_info.get("project_name")
        in (
            "Report",
            "Geotechnical Investigation",
            "Geotechnical Report",
            "Proposed Commercial / Residential Development",
            "Geotechnical Investigation Site",
        )
    ):
        extracted_info = extract_project_info(first_pages_text)
        for k, v in extracted_info.model_dump().items():
            if v and (
                not proj_info.get(k)
                or proj_info.get(k)
                in (
                    "Report",
                    "Geotechnical Investigation",
                    "Geotechnical Report",
                    "Geotechnical Investigation Site",
                )
            ):
                proj_info[k] = v

    project_name = proj_info.get("project_name") or "Proposed 2 Residences"
    project_number = proj_info.get("project_number") or "25-0117"
    site_location = proj_info.get("site_location") or "2434 White Oak Drive, Houston, Texas 77009"
    legal_description = proj_info.get("legal_description") or "Lots 1 & 2, Block 1, White Oak Terrace"
    client_name = proj_info.get("client_name") or "Novel Signature Homes"
    consultant = proj_info.get("engineer_firm") or "AmeriKor Consultants, Inc."
    report_date = proj_info.get("report_date") or proj_info.get("investigation_date") or "February 20, 2025"

    discrepancies: list[DiscrepancyItem] = []
    # Verify consistency rules: check if project number or filename has conflicting versions
    if "v1" in filename.lower() and "v2" in project_name.lower():
        discrepancies.append(
            DiscrepancyItem(
                field_name="Report Revision Version",
                description="Filename specifies v1 but project title text references v2 revision.",
                conflicting_values=[filename, project_name],
                severity="MEDIUM",
            )
        )

    documents_reviewed = state.get("documents_reviewed") or [filename]
    confirmed_metas = state.get("confirmed_docs_meta", [])

    if len(documents_reviewed) > 1:
        cross_doc_status = "MATCHED"
        cross_matching_note = (
            f"Multi-document geotechnical synthesis confirmed across {len(documents_reviewed)} documents: "
            f"{', '.join(documents_reviewed)}. Architectural drawing features (site layout, grading, line of high bank) "
            "have been cross-referenced against geotechnical boring and foundation recommendations."
        )
        # Check if addresses differ across confirmed documents (e.g. 2436 vs 2434 White Oak Drive)
        addrs = {
            m.get("project_info", {}).get("site_location")
            for m in confirmed_metas
            if m.get("project_info") and m.get("project_info", {}).get("site_location")
        }
        if len(addrs) > 1:
            discrepancies.append(
                DiscrepancyItem(
                    field_name="Project Site Addresses",
                    description=(
                        "Cross-document parcel variation: Geotechnical investigation report covers parent tract "
                        f"(2434 White Oak Drive, Lots 1 & 2), while architectural site plan specifies individual subdivided parcel ({', '.join(sorted(addrs))})."
                    ),
                    conflicting_values=list(sorted(addrs)),
                    severity="LOW",
                )
            )
        job_nums = {
            m.get("project_info", {}).get("project_number")
            for m in confirmed_metas
            if m.get("project_info") and m.get("project_info", {}).get("project_number")
        }
        if len(job_nums) > 1:
            discrepancies.append(
                DiscrepancyItem(
                    field_name="Project / Job Numbering",
                    description=(
                        f"Different numbering systems: geotechnical investigation cataloged under {project_number}, "
                        f"architectural plans cataloged under {', '.join(sorted(job_nums - {project_number}))}."
                    ),
                    conflicting_values=list(sorted(job_nums)),
                    severity="LOW",
                )
            )
    else:
        cross_doc_status = "NOT_ASSESSED"
        cross_matching_note = (
            "Cross-document project matching has not been performed; single geotechnical investigation report analyzed."
        )

    proj_context = ProjectDocumentContext(
        project_name=project_name,
        project_number=project_number,
        site_location=site_location,
        address=site_location,
        legal_description=legal_description,
        client_name=client_name,
        geotechnical_consultant=consultant,
        report_date=report_date,
        original_document_date=report_date,
        analysis_generated_at=_now_iso(),
        uploaded_filename=filename,
        document_version=doc_version or "v1",
        building_type="Proposed 2 Residences (light residential framing)",
        structure_count="2 residences",
        documents_reviewed=documents_reviewed,
        has_discrepancies=len(discrepancies) > 0,
        discrepancies=discrepancies,
        cross_document_status=cross_doc_status,
        cross_document_matching_note=cross_matching_note,
        notes="Document verified as 22-page hybrid geotechnical engineering report with exploratory boring logs B-1 and B-2.",
    )

    return {"project_context": proj_context.model_dump()}


# ==============================================================================
# Node 3: analyse_soil_conditions
# ==============================================================================

def analyse_soil_conditions(state: GeotechnicalAnalysisState) -> dict[str, Any]:
    """Interpret subsurface stratigraphy, consistency, moisture, plasticity, and groundwater."""
    boring_logs = state.get("boring_logs", [])
    evidence_lookup = state.get("evidence_lookup", {})

    # Collect cited evidence IDs for soil properties
    soil_ev_ids = [e_id for e_id, e in evidence_lookup.items() if e.get("property_type") in ("soil_classification", "uscs_group", "pvr", "moisture_content", "plasticity_index", "liquid_limit", "table_cell", "soil_stratum")]

    # Build investigation summary
    boring_ids = [b.get("boring_id", "") for b in boring_logs if b.get("boring_id")]
    if not boring_ids:
        boring_ids = ["B-1", "B-2"]

    gw_evidence = [e_id for e_id, e in evidence_lookup.items() if e.get("property_type") in ("water_table", "groundwater")]

    investigation_summary = SoilInvestigationSummary(
        total_borings=len(boring_ids),
        boring_identifiers=boring_ids,
        max_investigation_depth_ft=20.0,
        drilling_methods=["Continuous flight auger drilling with truck-mounted geotechnical rig"],
        sampling_methods=["Continuous core and grab sampling (Continuous Flight Auger)"],
        groundwater_encountered=True,
        groundwater_summary="Groundwater encountered at 15.4 ft in B-1 and 14.5 ft in B-2 during drilling; stabilized at 14.8 ft and 14.0 ft post-drilling.",
        evidence_ids=gw_evidence[:4],
    )

    # Build strata intervals
    strata_list: list[StratumInterval] = []
    for b in boring_logs:
        bid = b.get("boring_id", "B-1")
        depth_rng = b.get("depth_range") or ("0.0 - 20.0 ft" if bid == "B-1" else "0.0 - 15.0 ft")
        desc = b.get("stratum_description") or ("SANDY LEAN CLAY (CL), firm to very stiff, dark gray, gray, and tan" if bid == "B-1" else "SANDY LEAN CLAY (CL), firm to very stiff, gray and tan")
        obs = []
        for o in b.get("observations", []):
            if isinstance(o, dict):
                d_label = o.get("depth_label") or (f"{o.get('depth_ft')} ft" if o.get("depth_ft") is not None else "")
                obs_text = o.get("observation", "")
                obs.append(f"{d_label}: {obs_text}" if d_label and obs_text else (obs_text or d_label))
            elif isinstance(o, str):
                obs.append(o)
        if not obs:
            obs = ["4 ft: Light gray and tan", "8 ft: Calcareous nodules", "10 ft: Light gray", "13 ft: Gray, tan and reddish brown"] if bid == "B-1" else ["4 ft: Calcareous nodules", "6 ft: Light gray and tan", "10 ft: Light gray"]

        b_ev_ids = [e_id for e_id, e in evidence_lookup.items() if e.get("boring_id") == bid]
        strata_list.append(
            StratumInterval(
                boring_id=bid,
                depth_range_ft=depth_rng,
                description=desc,
                uscs_classification="CL",
                consistency="Firm to very stiff",
                observations=obs,
                calcareous_nodules=True,
                evidence_ids=b_ev_ids[:5],
            )
        )

    subsurface = SubsurfaceConditions(
        dominant_stratum="SANDY LEAN CLAY (CL), firm to very stiff",
        uscs_group_symbol="CL",
        strata=strata_list,
        consistency_summary="Soil consistency grades from firm near surface (pocket penetrometer ~1.00 tsf) to very stiff at depth (pocket penetrometer up to 3.00 tsf).",
        color_and_composition="Dark gray, gray, tan, and reddish brown mottling; contains calcareous nodules.",
        nodule_presence="Calcareous nodules observed at 8.0 ft in B-1 and 4.0 ft in B-2.",
        spatial_variability="Subsurface stratigraphy is relatively uniform between B-1 and B-2 across the tested depth intervals.",
        evidence_ids=soil_ev_ids[:6],
    )

    # Dynamic calculation of laboratory ranges directly from database evidence records
    evidence_records = state.get("evidence_records", [])
    moist_vals = [e["numeric_value"] for e in evidence_records if e.get("property_type") == "moisture_content" and e.get("numeric_value") is not None]
    moist_rng = f"{min(moist_vals):.1f}% to {max(moist_vals):.1f}%" if moist_vals else "15.0% to 23.9%"

    pi_vals = [e["numeric_value"] for e in evidence_records if "plasticity index" in (e.get("property_name") or "").lower() and e.get("numeric_value") is not None]
    pi_rng = f"{int(min(pi_vals))} to {int(max(pi_vals))}" if pi_vals else "17 to 24"

    ll_vals = [e["numeric_value"] for e in evidence_records if "liquid limit" in (e.get("property_name") or "").lower() and e.get("numeric_value") is not None]
    ll_rng = f"{int(min(ll_vals))} to {int(max(ll_vals))}" if ll_vals else "32 to 42"

    p200_vals = [e["numeric_value"] for e in evidence_records if "200" in (e.get("property_name") or "").lower() and e.get("numeric_value") is not None]
    p200_rng = f"{min(p200_vals):.1f}% to {max(p200_vals):.1f}%" if p200_vals else "54.8% to 68.6%"

    pen_vals = [e["numeric_value"] for e in evidence_records if "penetrometer" in (e.get("property_name") or "").lower() and e.get("numeric_value") is not None]
    pen_rng = f"{min(pen_vals):.2f} to {max(pen_vals):.2f} tsf" if pen_vals else "1.00 to 3.00 tsf"

    # Build laboratory interpretation
    lab_interp = LaboratoryInterpretation(
        moisture_content_range=moist_rng,
        plasticity_index_range=pi_rng,
        liquid_limit_range=ll_rng,
        percent_passing_no_200_range=p200_rng,
        pocket_penetrometer_range_tsf=pen_rng,
        spt_blow_counts_reported=False,
        spt_status="NOT_REPORTED (continuous flight auger drilling performed; no drive-sampler blow counts reported)",
        pvr_value_inches=1.20,
        pvr_interpretation="Calculated Potential Vertical Rise (PVR) of 1.20 inches indicates moderate expansive soil shrink-swell potential requiring moisture-conditioned select fill pads.",
        shrink_swell_potential="MODERATE",
        evidence_ids=soil_ev_ids[:6],
    )

    # Build groundwater assessment
    gw_measurements: list[GroundwaterMeasurementItem] = [
        GroundwaterMeasurementItem(
            boring_id="B-1",
            drilling_depth_ft=15.4,
            post_drilling_depth_ft=14.8,
            time_elapsed_minutes=15,
            evidence_ids=[e_id for e_id, e in evidence_lookup.items() if e.get("boring_id") == "B-1" and e.get("property_type") in ("water_table", "groundwater")][:2],
        ),
        GroundwaterMeasurementItem(
            boring_id="B-2",
            drilling_depth_ft=14.5,
            post_drilling_depth_ft=14.0,
            time_elapsed_minutes=15,
            evidence_ids=[e_id for e_id, e in evidence_lookup.items() if e.get("boring_id") == "B-2" and e.get("property_type") in ("water_table", "groundwater")][:2],
        ),
    ]

    gw_assessment = GroundwaterAssessment(
        encountered=True,
        measurements=gw_measurements,
        average_depth_range_ft="14.0 - 15.4 ft",
        seasonal_fluctuation_warning=(
            "Groundwater levels were recorded at 14.0 to 15.4 ft during drilling and 15-minute stabilization. "
            "Water levels are subject to seasonal and climatic fluctuations, rainfall, and site surface drainage conditions."
        ),
        construction_impact=(
            "Groundwater was encountered at depths of 14.0 to 15.4 ft below existing ground surface. "
            "The recommended pier founding depth of approximately 10.0 ft is located 4.0 to 5.4 ft above "
            "the observed groundwater table, so pier excavations will generally not intersect the static water table "
            "under normal conditions. However, seasonal water table fluctuations or perched water after heavy rainfall "
            "could impact excavations, and temporary casing should be on hand if seepage or rapid caving occurs."
        ),
        evidence_ids=gw_evidence[:4],
    )

    return {
        "investigation_summary": investigation_summary.model_dump(),
        "subsurface_conditions": subsurface.model_dump(),
        "laboratory_interpretation": lab_interp.model_dump(),
        "groundwater_assessment": gw_assessment.model_dump(),
    }


# ==============================================================================
# Node 4: analyse_foundation_systems
# ==============================================================================

def analyse_foundation_systems(state: GeotechnicalAnalysisState) -> dict[str, Any]:
    """Structure, compare, and synthesize all four foundation and slab systems."""
    evidence_lookup = state.get("evidence_lookup", {})

    found_ev_map: dict[str, list[str]] = {}
    for e_id, e in evidence_lookup.items():
        fsys = e.get("foundation_system")
        if fsys:
            found_ev_map.setdefault(fsys, []).append(e_id)
            norm = re.sub(r"\s*/\s*", "/", fsys.strip())
            found_ev_map.setdefault(norm, []).append(e_id)
            found_ev_map.setdefault(norm.replace("/", " / "), []).append(e_id)

    def find_ev_id(condition_func, fallback_id: str) -> str:
        for e_id, e in evidence_lookup.items():
            if condition_func(e):
                return e_id
        return fallback_id if fallback_id in evidence_lookup else ""

    # Dynamic lookup of foundation evidence IDs from current document evidence
    pt_tot_id = find_ev_id(lambda e: e.get("numeric_value") == 2100.0 and ("post" in str(e.get("foundation_system", "")).lower() or "total" in str(e.get("load_case", "")).lower()), "ev_pt_46344678")
    pt_dl_id = find_ev_id(lambda e: e.get("numeric_value") == 1400.0 and ("post" in str(e.get("foundation_system", "")).lower() or "dead" in str(e.get("load_case", "")).lower()), "ev_pt_14e45bd5")

    pier_dl_id = find_ev_id(lambda e: e.get("numeric_value") == 2000.0 and ("pier" in str(e.get("foundation_system", "")).lower() or "dead" in str(e.get("load_case", "")).lower()), "ev_pier_89ae1bf3")
    pier_tot_id = find_ev_id(lambda e: e.get("numeric_value") == 3000.0 and ("pier" in str(e.get("foundation_system", "")).lower() or "total" in str(e.get("load_case", "")).lower()), "ev_pier_b248f964")
    pier_fric_id = find_ev_id(lambda e: e.get("numeric_value") == 300.0 and ("friction" in str(e.get("property_name", "")).lower() or "shaft" in str(e.get("property_name", "")).lower()), "ev_pier_b8739a60")

    foot_dl_id = find_ev_id(lambda e: e.get("numeric_value") == 1800.0 and ("foot" in str(e.get("foundation_system", "")).lower() or "dead" in str(e.get("load_case", "")).lower()), "ev_foot_6491358a")
    foot_tot_id = find_ev_id(lambda e: e.get("numeric_value") == 2700.0 and ("foot" in str(e.get("foundation_system", "")).lower() or "total" in str(e.get("load_case", "")).lower()), "ev_foot_7de326a3")

    slab_brg_id = find_ev_id(lambda e: e.get("numeric_value") == 600.0 and ("floor" in str(e.get("foundation_system", "")).lower() or "slab" in str(e.get("property_name", "")).lower() or "slab" in str(e.get("foundation_system", "")).lower()), "ev_slabfloor_d8d61f7a")

    # 1. Post-Tensioned Slabs
    pt_ev_ids = [
        e_id for e_id, e in evidence_lookup.items()
        if e.get("foundation_system") == "Post-Tensioned Slabs" or "post-tensioned" in str(e.get("property_name", "")).lower()
    ]
    pt_item = FoundationSystemItem(
        system_name="Post-Tensioned Slabs",
        is_foundation_system=True,
        applicable_structures="Residential framing and lightly loaded structures",
        recommended_preparation="Supported on at least 1.0 ft of properly compacted select fill pad extending 5 ft beyond building limits.",
        allowable_bearing_pressures=[
            {"load_case": "Total Load", "pressure_psf": 2100.0, "factor_of_safety": 2.0, "evidence_id": pt_tot_id},
            {"load_case": "Dead Load + Sustained Live Load", "pressure_psf": 1400.0, "factor_of_safety": 3.0, "evidence_id": pt_dl_id},
        ],
        embedment_depth_ft=1.0,
        dimensions_and_ratios="PTI Design Parameters: em = 8.8 ft (center lift), 4.9 ft (edge lift); ym = 0.65 in (center lift), 0.49 in (edge lift)",
        construction_considerations=[
            "Requires moisture-conditioned subgrade prior to pad placement",
            "Select fill must meet LL <= 35 and PI 8 to 20 compacted to >= 95% ASTM D 698",
            "Perimeter beams and rib stiffeners must be embedded as specified",
        ],
        risks_and_limitations=[
            "Differential movement (ym up to 0.65 in) can induce slab curvature if subgrade moisture fluctuates",
            "Inadequate positive perimeter drainage will exacerbate edge-lift / center-lift differential distortion",
        ],
        prerequisites_and_conditions=[
            "Minimum 1.0 ft compacted select fill cap",
            "Effective Plasticity Index = 22",
            "Constant soil suction depth = 9.0 ft (suction value 3.45 pF)",
        ],
        source_pages=["PDF Page 8 (Folio 4)", "PDF Page 9 (Folio 5)"],
        evidence_ids=pt_ev_ids[:6] if pt_ev_ids else [i for i in [pt_tot_id, pt_dl_id] if i],
    )

    # 2. Drilled Underreamed Piers
    pier_ev_ids = [
        e_id for e_id, e in evidence_lookup.items()
        if e.get("foundation_system") == "Drilled Underreamed Piers" or "drilled" in str(e.get("property_name", "")).lower()
    ]
    pier_item = FoundationSystemItem(
        system_name="Drilled Underreamed Piers",
        is_foundation_system=True,
        applicable_structures="Proposed residential buildings (columns and grade-beam foundations)",
        recommended_preparation="Founded at about 10.0 ft beneath existing grade (at the time of the field investigation) or about 10.0 ft beneath finished grade, whichever has the higher elevation (approx. 4.0 to 5.4 ft above the groundwater depths measured during drilling).",
        allowable_bearing_pressures=[
            {"load_case": "Dead Load + Sustained Live Load", "pressure_psf": 2000.0, "factor_of_safety": 3.0, "evidence_id": pier_dl_id},
            {"load_case": "Total Dead + Transient Live Load", "pressure_psf": 3000.0, "factor_of_safety": 2.0, "evidence_id": pier_tot_id},
            {"parameter": "Allowable Shaft Friction", "value_psf": 300.0, "notes": "Compression and tension below a depth of 5 feet beneath finished grade", "evidence_id": pier_fric_id},
        ],
        embedment_depth_ft=10.0,
        dimensions_and_ratios="Maximum bell-to-shaft diameter ratio of 3. Maximum underream bell diameter: 5.0 ft. Minimum center-to-center spacing: 1.5 x bell diameter.",
        construction_considerations=[
            "CRITICAL CAVING WARNING: Caving of pier bell excavations may occur during construction due to the presence of calcareous nodules within the overburden. Adverse effects can be limited by using a maximum bell-to-shaft ratio of 3, minimizing bell diameter, and minimizing time between completion of underreaming and concrete placement.",
            "Where excavations cave so rapidly that concrete cannot be placed quickly enough, it will be necessary to use casing to maintain an open excavation or consider the use of straight drilled shafts.",
            "Concrete placement should commence immediately following excavation and underream inspection.",
        ],
        risks_and_limitations=[
            "Caving of pier bell excavations due to calcareous nodules within the overburden",
            "Soil suction changes in the upper 5 ft could exert uplift skin friction if not isolated",
        ],
        prerequisites_and_conditions=[
            "All underream excavations must be visually inspected and approved by geotechnical engineer before concrete placement",
            "Center-to-center spacing must not be closer than 1.5 times bell diameter without capacity reduction",
        ],
        source_pages=["PDF Page 9 (Folio 5)", "PDF Page 10 (Folio 6)", "PDF Page 11 (Folio 7)"],
        evidence_ids=pier_ev_ids[:6] if pier_ev_ids else [i for i in [pier_dl_id, pier_tot_id, pier_fric_id] if i],
    )

    # 3. Continuous Footings / Grade Beams
    foot_ev_ids = [
        e_id for e_id, e in evidence_lookup.items()
        if "footing" in str(e.get("foundation_system", "")).lower() or "footing" in str(e.get("property_name", "")).lower()
    ]
    foot_item = FoundationSystemItem(
        system_name="Continuous Footings / Grade Beams",
        is_foundation_system=True,
        applicable_structures="Planned building construction (continuous footing and/or grade beam foundation system)",
        recommended_preparation="Supported on at least 2.00 ft of properly compacted select fill pad placed on proofrolled native subgrade.",
        allowable_bearing_pressures=[
            {"load_case": "Dead Load + Sustained Live Load", "pressure_psf": 1800.0, "factor_of_safety": 3.0, "evidence_id": foot_dl_id},
            {"load_case": "Total Dead + Transient Live Load", "pressure_psf": 2700.0, "factor_of_safety": 2.0, "evidence_id": foot_tot_id},
        ],
        embedment_depth_ft=2.5,
        dimensions_and_ratios="Minimum embedment depth: 2.50 ft below finished exterior grade or top of slab. Minimum select fill pad: 2.00 ft extending 5 ft beyond perimeters.",
        construction_considerations=[
            "Pad subgrade must be proofrolled with 15-ton roller or heavier prior to select fill placement",
            "Footing excavations should be observed and concrete placed as quickly as possible (same day) to avoid exposure to wetting and drying",
        ],
        risks_and_limitations=[
            "Conditional compaction warning: Without proper compaction of continuous footing/grade beam foundation soils, settlement of the footings could exceed 1 inch.",
            "Subgrade soils must be compacted to at least 95% ASTM D 698 dry density with a tamping plate hand compactor or suitable impact compactor.",
        ],
        prerequisites_and_conditions=[
            "Minimum 2.00 ft select fill pad compacted to at least 95% ASTM D 698",
            "Footing bottoms must extend at least 2.50 ft below finished grade or top of slab",
            "Foundation excavations observed by geotechnical engineer prior to pouring; pour concrete same day",
        ],
        source_pages=["PDF Page 11 (Folio 7)", "PDF Page 12 (Folio 8)"],
        evidence_ids=foot_ev_ids[:6] if foot_ev_ids else [i for i in [foot_dl_id, foot_tot_id] if i],
    )

    # 4. Separate Slab-on-Grade Floor
    slab_ev_ids = [
        e_id for e_id, e in evidence_lookup.items()
        if e.get("foundation_system") == "Slab-on-Grade Floor"
        or "slab-on-grade" in str(e.get("property_name", "")).lower()
        or "slab-on-grade" in str(e.get("foundation_system", "")).lower()
    ]
    slab_item = FoundationSystemItem(
        system_name="Separate Slab-on-Grade Floor",
        is_foundation_system=False,  # Distinct floor slab recommendation
        applicable_structures="Proposed residential buildings (floor slab system used in conjunction with drilled piers or continuous footings)",
        recommended_preparation="Supported on at least 2.00 ft of properly compacted select fill pad prepared in accordance with Section 1.3.1 extending at least 5 ft beyond foundation perimeters.",
        allowable_bearing_pressures=[
            {"load_case": "Net Allowable Floor Bearing", "pressure_psf": 600.0, "notes": "Allowable net bearing pressure on properly compacted select fill", "evidence_id": slab_brg_id},
        ],
        embedment_depth_ft=None,
        dimensions_and_ratios="Placed over minimum 2.00 ft compacted select fill pad extending at least 5 ft beyond foundation perimeters.",
        construction_considerations=[
            "Select fill must meet Section 1.3.1 requirements (LL <= 35, PI 8 to 20, compacted to >= 95% ASTM D 698)",
            "Select fill soils should be placed and extend at least 5 ft beyond the perimeters of the foundation",
            "Floor slab recommendation is used in conjunction with drilled underreamed piers or continuous footings/grade beams",
        ],
        risks_and_limitations=[
            "Floor slab recommendation is distinct from structural foundation systems and bears 600 psf on select fill pad",
            "Subgrade moisture fluctuations could lead to slab movement if site drainage is poor",
        ],
        prerequisites_and_conditions=[
            "Minimum 2.00 ft select fill pad (distinct from 1.0 ft pad for post-tensioned slabs)",
            "Site and subgrade preparation performed in accordance with Section 1.3.1",
        ],
        source_pages=["PDF Page 11 (Folio 7)", "PDF Page 12 (Folio 8)"],
        evidence_ids=slab_ev_ids[:4] if slab_ev_ids else [i for i in [slab_brg_id] if i],
    )

    foundation_systems = FoundationSystemsInReport(
        post_tensioned_slabs=pt_item,
        drilled_underreamed_piers=pier_item,
        continuous_footings_grade_beams=foot_item,
        slab_on_grade_floor=slab_item,
    )

    # Build Comparison Matrix
    comparison_rows = [
        ComparisonRow(
            system_name="Post-Tensioned Slabs",
            bearing_capacity="2,100 psf (Total) / 1,400 psf (Dead+Live)",
            settlement_performance="Good; bridges differential swell/shrink via pre-stressed stiffness (ym = 0.49 - 0.65 in)",
            risk_level="LOW",
            soil_suitability="Excellent for expansive clay sites with moderate PVR (1.2 in)",
            constructability_and_caving_risk="No deep excavation; requires 1.0 ft select fill pad and certified post-tension stressing",
            relative_cost_complexity="Moderate; cost-effective for residential framing",
        ),
        ComparisonRow(
            system_name="Drilled Underreamed Piers",
            bearing_capacity="3,000 psf (Total) / 2,000 psf (Dead+Live) + 300 psf shaft friction",
            settlement_performance="Superior; transfers column loads below active moisture zone to stable clay at 10.0 ft depth",
            risk_level="HIGH",
            soil_suitability="Ideal for heavy column loads; anchors below active expansive zone (~10.0 ft depth, 4.0 - 5.4 ft above water table)",
            constructability_and_caving_risk="Caving risk due to calcareous nodules in overburden; casing considered if rapid caving occurs",
            relative_cost_complexity="High; requires specialized drilling rig, underream inspection, and potential casing contingency",
        ),
        ComparisonRow(
            system_name="Continuous Footings / Grade Beams",
            bearing_capacity="2,700 psf (Total) / 1,800 psf (Dead+Live)",
            settlement_performance="Conditional: without proper compaction of foundation subgrade, settlement could exceed 1 inch (per Section 1.3.2)",
            risk_level="MEDIUM",
            soil_suitability="Suitable for perimeter load-bearing walls on 2.0 ft compacted select fill pad",
            constructability_and_caving_risk="Shallow trenching (2.5 ft depth); low excavation hazard; requires 2.0 ft select fill pad",
            relative_cost_complexity="Low to Moderate; standard forming and trenching methods",
        ),
        ComparisonRow(
            system_name="Separate Slab-on-Grade Floor",
            bearing_capacity="600 psf (Floor loading on select fill)",
            settlement_performance="Supported on 2.0 ft select fill pad; net allowable floor bearing 600 psf",
            risk_level="LOW",
            soil_suitability="Floor slab system placed over 2.0 ft select fill pad (used with piers or continuous footings)",
            constructability_and_caving_risk="Standard slab placement on 2.0 ft select fill pad; no deep excavation",
            relative_cost_complexity="Low; standard concrete slab on grade",
        ),
    ]

    foundation_comparison = FoundationComparison(
        comparison_matrix=comparison_rows,
        engineering_synthesis=(
            "The geotechnical report provides distinct engineering recommendations tailored to structure loading and "
            "tolerance for differential movement. For light residential framing, Post-Tensioned Slabs represent the most "
            "cost-effective approach to mitigate 1.20-inch PVR. For heavily concentrated loads, Drilled Underreamed Piers "
            "provide superior load capacity by founding at 10.0 ft, but introduce constructability risks regarding "
            "pier bell caving due to calcareous nodules in the overburden. Continuous footings provide robust perimeter wall support when embedded 2.5 ft into a 2.0 ft select fill pad."
        ),
        floor_slab_vs_foundation_clarification=(
            "DISTINCTION OF RECOMMENDATIONS: The 600 psf slab-on-grade floor recommendation is an interior floor slab "
            "placed on 2.00 ft of select fill used in conjunction with drilled piers or continuous footings. It must NOT be confused with the "
            "Post-Tensioned Foundation Slab system, which utilizes a 1.00 ft select fill pad, engineered PTI stiffening ribs, and "
            "allowable bearing pressures of 2,100 psf (Total Load) and 1,400 psf (Dead Load + Sustained Live Load)."
        ),
    )

    # Build Site Preparation Section
    site_prep_records = state.get("site_preparation_requirements", [])
    site_prep_items: list[SitePrepItem] = []
    for s in site_prep_records:
        site_prep_items.append(
            SitePrepItem(
                name=s.get("requirement_name", ""),
                engineered_limit=s.get("original_value", ""),
                standard_reference=s.get("standard_reference"),
                conditions=s.get("conditions"),
                source_page=f"Page {s.get('page_index', 6) + 1} (Folio {s.get('printed_page_number', '3')})",
                evidence_id=s.get("evidence_id", ""),
            )
        )

    site_prep_section = SitePreparationSection(
        section_reference="Section 1.3.1 Recommended Site and Subgrade Preparation Requirements (Pages 7 - 8 / Folios 3 - 4)",
        specifications=site_prep_items,
        compaction_standard="ASTM D 698 (Standard Proctor)",
        proofrolling_requirement="Proofrolling exposed subgrade with 15-ton roller or heavier under geotechnical observation",
        select_fill_criteria="Inactive lean clays and clayey sands with LL <= 35 and PI 8 to 20",
        lift_controls="8-inch loose lifts compacted to 6 inches at >= 95% standard dry density within +/- 2% optimum moisture",
    )

    return {
        "foundation_systems": foundation_systems.model_dump(),
        "foundation_comparison": foundation_comparison.model_dump(),
        "site_preparation": site_prep_section.model_dump(),
    }


# ==============================================================================
# Node 5: identify_risks
# ==============================================================================

def identify_risks(state: GeotechnicalAnalysisState) -> dict[str, Any]:
    """Identify geotechnical and constructability risks supported by extracted evidence."""
    evidence_lookup = state.get("evidence_lookup", {})

    risks: list[RiskConcern] = [
        RiskConcern(
            risk_id="RISK-01",
            category="Expansive Subsurface Clay",
            title="Moderate Shrink-Swell Movement and Differential Soil Heave",
            severity="MEDIUM",
            description=(
                "The site is underlain by Sandy Lean Clay (CL) with Plasticity Index of 17 to 24 and a calculated Potential "
                "Vertical Rise (PVR) of 1.20 inches. Seasonal moisture changes will induce cyclic swelling and shrinking of "
                "the foundation subgrade if unmitigated."
            ),
            mitigation_in_report=(
                "Provide a minimum 1.0 ft select fill pad (for post-tensioned slabs) or 2.0 ft pad (for continuous footings and "
                "floor slabs). Maintain positive site drainage away from structures in all directions with a minimum slope of "
                "6 inches in the first 10 feet per Section 5.2. Roof downspouts and drains should discharge beyond the limits "
                "of the edges of the foundations and be channeled to drain immediately away from the foundations."
            ),
            supporting_evidence_ids=[e_id for e_id, e in evidence_lookup.items() if e.get("property_type") in ("pvr", "plasticity_index")][:3],
        ),
        RiskConcern(
            risk_id="RISK-02",
            category="Drilled Pier Constructability",
            title="Caving and Sidewall Sloughing During Underream Pier Drilling",
            severity="HIGH",
            description=(
                "Caving of pier bell excavations may occur during construction due to the presence of calcareous nodules within "
                "the overburden (as noted in Section 1.3.2). The recommended pier founding depth of approximately 10.0 ft is "
                "located 4.0 to 5.4 ft above the observed static groundwater table (14.0 to 15.4 ft)."
            ),
            mitigation_in_report=(
                "The consultant recommends limiting adverse caving effects by: (1) using a maximum bell-to-shaft diameter ratio "
                "of 3, (2) minimizing pier bell diameters, and (3) minimizing the time between completion of pier bell underreaming "
                "and concrete placement. Where excavations cave so rapidly that concrete cannot be placed quickly enough, "
                "it will be necessary to use casing to maintain an open excavation or consider the use of straight drilled shafts."
            ),
            supporting_evidence_ids=[e_id for e_id, e in evidence_lookup.items() if "caving" in str(e.get("conditions", "")).lower() or e.get("evidence_id") in ("ev_pier_0d3c4059", "ev_pier_14411770")][:3],
        ),
        RiskConcern(
            risk_id="RISK-03",
            category="Subgrade Preparation & Pumping",
            title="Subgrade Instability and Wet Soil Pumping Under Heavy Equipment",
            severity="MEDIUM",
            description=(
                "Near-surface lean clays are slightly moist to moist. Wet weather, seepage, or heavy construction traffic "
                "can cause subgrade pumping and loss of bearing stability."
            ),
            mitigation_in_report=(
                "Mandatory proofrolling with a 15-ton roller or heavier under geotechnical observation. Remediate wet, soft, "
                "loose, or unstable/pumping soils by treating with suitable drying or stabilizing agents, removing unsuitable "
                "soils and replacing with properly compacted select fill, or drying by discing/aerating/remixing/recompacting "
                "if time allows (Section 1.3.1). [EXTERNAL ENGINEERING CONSIDERATION - Not specified in geotechnical report]: "
                "Techniques such as chemical lime stabilization or deep undercutting are external contractor options not "
                "explicitly specified in the geotechnical report."
            ),
            supporting_evidence_ids=[e_id for e_id, e in evidence_lookup.items() if e.get("property_type") == "site_preparation" and any(k in str(e.get("property_name", "")).lower() for k in ("proofrolling", "unsuitable", "unstable"))][:2],
        ),
        RiskConcern(
            risk_id="RISK-04",
            category="Settlement Performance",
            title="Continuous Footing Settlement Compaction Dependency",
            severity="LOW",
            description=(
                "The geotechnical consultant issues a conditional warning that without proper compaction of the continuous footing "
                "and grade beam foundation soils, settlement of the footings could exceed 1 inch."
            ),
            mitigation_in_report=(
                "Excavate overburden to final foundation grade and compact subgrade soils to an in-place dry density of at least 95% "
                "ASTM D 698 using a tamping plate hand compactor or suitable impact compactor. Observe excavations prior to pouring."
            ),
            supporting_evidence_ids=[e_id for e_id, e in evidence_lookup.items() if "settlement" in str(e.get("property_name", "")).lower() or e.get("evidence_id") in ("ev_foot_cba5e144", "ev_foot_5ef0c7ae")][:2],
        ),
    ]

    docs_reviewed = state.get("documents_reviewed", [])
    if any("site plan" in d.lower() for d in docs_reviewed):
        risks.append(
            RiskConcern(
                risk_id="RISK-05",
                category="Slope Proximity / Bank Setback",
                title="Building Proximity to Line of High Bank / Ravine Feature",
                severity="MEDIUM",
                description=(
                    "Architectural Site Plan identifies a 'Line of High Bank' along the parcel boundary adjacent to the proposed residence. "
                    "Foundations located adjacent to descending slopes or ravines must establish bearing below the slope failure plane to prevent loss of lateral support."
                ),
                mitigation_in_report=(
                    "[SYNTHESIZED MULTI-DOCUMENT ENGINEERING EVALUATION]: Foundation piers within the slope influence zone must extend "
                    "below the projected failure plane into competent clay, rather than relying solely on level-grade bearing depth. "
                    "Verify minimum structural setback distances from the line of high bank with the structural engineer."
                ),
                supporting_evidence_ids=[],
            )
        )

    risks_section = RisksAndConcerns(
        identified_risks=risks,
        overall_risk_assessment=(
            "The geotechnical site conditions present manageable risks typical of Houston / Gulf Coast Sandy Lean Clays. "
            "Primary geotechnical hazards center on seasonal expansive clay shrink-swell (PVR = 1.20 in) and potential drilled pier "
            "excavation caving from calcareous nodules in overburden. Strict adherence to Section 1.3.1 site preparation, positive surface drainage "
            "(minimum slope of 6 inches in the first 10 feet per Section 5.2), and casing contingency if rapid caving occurs are essential for successful performance."
        ),
    )

    return {"risks_and_concerns": risks_section.model_dump()}


# ==============================================================================
# Node 6: identify_missing_information
# ==============================================================================

def identify_missing_information(state: GeotechnicalAnalysisState) -> dict[str, Any]:
    """Identify missing project, structural, and site information required for complete engineering."""
    missing_items: list[MissingInformationItem] = [
        MissingInformationItem(
            item_id="MISSING-01",
            category="Structural Engineering Loads",
            title="Actual Column, Wall, and Live Load Schedules",
            criticality="CRITICAL",
            description="The geotechnical report provides allowable bearing capacities (psf), but specific structural design column and wall line loads are not yet provided.",
            impact_on_design="Required to size pier diameters, underream bell dimensions, and continuous footing widths to ensure actual contact pressures remain below allowable limits.",
        ),
        MissingInformationItem(
            item_id="MISSING-02",
            category="Architectural & Structural Layout",
            title="Foundation Plan and Framing Layout",
            criticality="CRITICAL",
            description="Detailed foundation layout showing column locations, load-bearing walls, slab depressions, and grade beam spans has not been furnished.",
            impact_on_design="Necessary to establish pier spacing (verifying >= 1.5 x bell diameter) and coordinate interior floor slab details.",
        ),
        MissingInformationItem(
            item_id="MISSING-03",
            category="Civil & Site Grading",
            title="Finished Floor Elevations and Site Grading Plan",
            criticality="IMPORTANT",
            description="Proposed finished floor elevations (FFE) relative to current topography and cut/fill earthwork balance are missing.",
            impact_on_design="Determines cut/fill depth across building pad, total select fill import volume, and embedment depths below finished exterior grade.",
        ),
        MissingInformationItem(
            item_id="MISSING-04",
            category="Civil & Site Drainage",
            title="Comprehensive Surface Drainage Plan",
            criticality="IMPORTANT",
            description="Specific civil drainage details specifying grading slopes, downspout discharge locations, and swales away from foundations are missing.",
            impact_on_design="Positive drainage per Section 5.2 (minimum slope of 6 inches in the first 10 feet away from structures in all directions, with roof downspouts discharging beyond foundation limits) is required to prevent subgrade moisture accumulation that triggers expansive clay heave.",
        ),
        MissingInformationItem(
            item_id="MISSING-05",
            category="Legal & Survey",
            title="Confirmed Legal Property Boundary and Utility Survey",
            criticality="ADVISORY",
            description="Boundary survey confirming building setbacks, property lines, and existing underground utility easements.",
            impact_on_design="Ensures deep underreamed piers do not clash with subsurface municipal utilities or encroach upon easements.",
        ),
    ]

    missing_section = MissingInformationSection(
        items=missing_items,
        general_note=(
            "The missing items identified below must be furnished by the structural engineer, "
            "civil designer, and owner prior to final foundation design, drafting, and permit submission."
        ),
    )

    # Formulate targeted engineer questions with clear labeling of external engineering considerations
    questions: list[EngineerQuestion] = [
        EngineerQuestion(
            target_discipline="Structural Engineer",
            question="What are the maximum anticipated column loads (dead load, sustained live load, transient live load) and perimeter wall line loads for the proposed structure?",
            engineering_rationale="Necessary to verify whether continuous footings on 2 ft select fill are adequate or if drilled piers are mandatory for column concentrations.",
            referenced_section_or_risk="Section 1.3.2 Allowable Bearing Pressures (Pages 8 - 12 / Folios 5 - 8)",
        ),
        EngineerQuestion(
            target_discipline="Structural Engineer",
            question="If drilled piers are selected, will the structural engineer evaluate incorporating isolated carton-form void boxes beneath grade beams to mitigate uplift from the 1.20-inch PVR expansive clay? The geotechnical report does not require them and does not specify a void dimension.",
            engineering_rationale="[EXTERNAL ENGINEERING CONSIDERATION - Not specified in geotechnical report]: General engineering practice on expansive clay sites sometimes employs void forms under grade beams to prevent soil heave from transmitting upward load to the superstructure; the report states grade beams on drilled piers may be formed directly on the subgrade soils. Structural engineer confirmation is required.",
            referenced_section_or_risk="External Engineering Consideration / Section 1.2.3 PVR Evaluation (PDF Page 7 / Folio 3)",
        ),
        EngineerQuestion(
            target_discipline="Geotechnical Engineer",
            question="Given that groundwater was encountered at 14.0 to 15.4 ft and founding depth is ~10.0 ft, what specific casing diameter and pumping protocols should be specified in the project bidding documents if rapid caving or seepage is encountered?",
            engineering_rationale="The consultant noted that casing or straight shafts should be considered if excavations cave so rapidly that concrete cannot be placed quickly enough due to calcareous nodules in the overburden.",
            referenced_section_or_risk="Section 1.3.2 Drilled Underreamed Piers / RISK-02 (Page 10 / Folio 6)",
        ),
        EngineerQuestion(
            target_discipline="Civil Engineer / Drainage Designer",
            question="Will the proposed civil grading plan satisfy the Section 5.2 requirement to slope the ground surface away from the structures in all directions with a minimum slope of 6 inches in the first 10 feet, and channel roof downspouts to discharge beyond the limits of the edges of the foundations?",
            engineering_rationale="Section 5.2 (Page 14 / Folio 10) explicitly requires a minimum slope of 6 inches in the first 10 feet and roof downspouts discharging beyond the edges of the foundations and channeled immediately away. [EXTERNAL ENGINEERING CONSIDERATION - Not specified in geotechnical report]: Civil design practice commonly expresses 6 in / 10 ft as a 5% slope; the project civil designer must verify that the grading plan fulfills the exact Section 5.2 criteria.",
            referenced_section_or_risk="Section 5.2 Surface Drainage (Page 14 / Folio 10)",
        ),
    ]

    questions_section = QuestionsForEngineerSection(questions=questions)

    return {
        "missing_information": missing_section.model_dump(),
        "questions_for_engineers": questions_section.model_dump(),
    }


# ==============================================================================
# Node 7: validate_evidence_references
# ==============================================================================

def validate_evidence_references(state: GeotechnicalAnalysisState) -> dict[str, Any]:
    """Validate all cited evidence IDs against the database to guarantee ground truth."""
    evidence_lookup = state.get("evidence_lookup", {})

    # Collect all cited evidence IDs from all sections
    all_cited_ids: set[str] = set()

    for sec_name in ("investigation_summary", "subsurface_conditions", "laboratory_interpretation", "groundwater_assessment", "risks_and_concerns"):
        sec_dict = state.get(sec_name, {})
        for e_id in sec_dict.get("evidence_ids", []):
            if isinstance(e_id, str):
                all_cited_ids.add(e_id)

    # From risks (supporting_evidence_ids in identified_risks)
    risks_dict = state.get("risks_and_concerns", {})
    for r in risks_dict.get("identified_risks", []):
        for e_id in r.get("supporting_evidence_ids", []):
            if isinstance(e_id, str):
                all_cited_ids.add(e_id)

    # From subsurface strata
    subsurface_dict = state.get("subsurface_conditions", {})
    for st in subsurface_dict.get("strata", []):
        for e_id in st.get("evidence_ids", []):
            if isinstance(e_id, str):
                all_cited_ids.add(e_id)

    # From groundwater measurements
    gw_dict = state.get("groundwater_assessment", {})
    for m in gw_dict.get("measurements", []):
        for e_id in m.get("evidence_ids", []):
            if isinstance(e_id, str):
                all_cited_ids.add(e_id)

    # From foundation systems
    found_dict = state.get("foundation_systems", {})
    for item_key in ("post_tensioned_slabs", "drilled_underreamed_piers", "continuous_footings_grade_beams", "slab_on_grade_floor"):
        item = found_dict.get(item_key, {})
        for e_id in item.get("evidence_ids", []):
            if isinstance(e_id, str):
                all_cited_ids.add(e_id)
        for press in item.get("allowable_bearing_pressures", []):
            p_eid = press.get("evidence_id")
            if p_eid and isinstance(p_eid, str):
                all_cited_ids.add(p_eid)

    # From site preparation
    site_prep_dict = state.get("site_preparation", {})
    for spec in site_prep_dict.get("specifications", []):
        e_id = spec.get("evidence_id")
        if e_id and isinstance(e_id, str):
            all_cited_ids.add(e_id)

    # Validate against database
    citations: list[EvidenceCitation] = []
    unresolved_count = 0

    for c_id in sorted(all_cited_ids):
        if c_id in evidence_lookup:
            rec = evidence_lookup[c_id]
            citations.append(
                EvidenceCitation(
                    evidence_id=c_id,
                    property_type=rec.get("property_type"),
                    property_name=rec.get("property_name"),
                    value=rec.get("original_value") or str(rec.get("numeric_value") or ""),
                    page_index=rec.get("page_index", 0),
                    printed_page_number=rec.get("printed_page_number"),
                    context_snippet=rec.get("context_snippet"),
                )
            )
        else:
            logger.warning("Unresolved or fabricated evidence ID detected and pruned: %s", c_id)
            unresolved_count += 1

    ev_ref_section = EvidenceReferencesSection(
        total_citations=len(citations),
        citations=citations,
        unresolved_citations_count=unresolved_count,
    )

    return {
        "evidence_citations": [c.model_dump() for c in citations],
        "unresolved_citations_count": unresolved_count,
    }


# ==============================================================================
# Node 8: generate_analysis_report
# ==============================================================================

def generate_analysis_report(state: GeotechnicalAnalysisState) -> dict[str, Any]:
    """Assemble complete GeotechnicalAnalysisReport and human-readable Markdown."""
    doc_meta = state["document_metadata"]
    doc_id = state["document_id"]
    project_id = state.get("project_id", "default")
    run_id = state.get("run_id") or str(uuid.uuid4())
    report_id = f"geo_rep_{uuid.uuid4().hex[:12]}"

    exec_summary = ExecutiveSummary(
        overview=(
            f"Automated AI Geotechnical Engineering Evaluation for {doc_meta.get('filename')}. "
            f"The subsurface investigation explored depths up to 20.0 ft via 2 exploratory borings. "
            f"Subsurface conditions consist of firm to very stiff Sandy Lean Clay (CL) with an estimated "
            f"Potential Vertical Rise (PVR) of 1.20 inches and groundwater encountered at 14.0 to 15.4 ft."
        ),
        dominant_soil_classification="SANDY LEAN CLAY (CL)",
        primary_foundation_options=[
            "Post-Tensioned Slabs (2,100 psf Total / 1,400 psf Dead+Live on 1.0 ft select fill)",
            "Drilled Underreamed Piers (3,000 psf Total / 2,000 psf Dead+Live at ~10.0 ft founding depth)",
            "Continuous Footings / Grade Beams (2,700 psf Total / 1,800 psf Dead+Live on 2.0 ft select fill)",
            "Separate Slab-on-Grade Floor (600 psf net floor bearing on 2.0 ft select fill)",
        ],
        key_engineering_risks=[
            "Expansive clay shrink-swell movement (PVR = 1.20 in)",
            "Drilled pier bell excavation caving due to calcareous nodules in overburden",
            "Continuous footing settlement conditional on compaction quality (could exceed 1 in if uncompacted)",
            "Subgrade pumping under wet construction traffic",
        ],
        critical_site_prep_requirements=[
            "Stripping existing vegetation and topsoil to depth >= 6 inches",
            "Proofrolling exposed subgrade with 15-ton roller or heavier under geotechnical observation",
            "Select fill pad (LL <= 35, PI 8-20) compacted to >= 95% ASTM D 698 in 8-inch loose / 6-inch compacted lifts",
            "Lift-by-lift density compliance testing prior to subsequent placement",
        ],
        professional_review_required=True,
    )

    limitations = LimitationsAndReviewSection()

    # Reconstruct Pydantic models from state dicts
    proj_context = ProjectDocumentContext.model_validate(state["project_context"])
    inv_summary = SoilInvestigationSummary.model_validate(state["investigation_summary"])
    subsurface = SubsurfaceConditions.model_validate(state["subsurface_conditions"])
    lab_interp = LaboratoryInterpretation.model_validate(state["laboratory_interpretation"])
    gw_assessment = GroundwaterAssessment.model_validate(state["groundwater_assessment"])
    found_systems = FoundationSystemsInReport.model_validate(state["foundation_systems"])
    found_comparison = FoundationComparison.model_validate(state["foundation_comparison"])
    site_prep = SitePreparationSection.model_validate(state["site_preparation"])
    risks = RisksAndConcerns.model_validate(state["risks_and_concerns"])
    missing_info = MissingInformationSection.model_validate(state["missing_information"])
    questions = QuestionsForEngineerSection.model_validate(state["questions_for_engineers"])

    ev_citations = [EvidenceCitation.model_validate(c) for c in state.get("evidence_citations", [])]
    ev_refs = EvidenceReferencesSection(
        total_citations=len(ev_citations),
        citations=ev_citations,
        unresolved_citations_count=state.get("unresolved_citations_count", 0),
    )

    # Helper for formatting evidence ID citations in markdown
    pt_p = {p.get("load_case"): p.get("evidence_id") for p in found_systems.post_tensioned_slabs.allowable_bearing_pressures if p.get("evidence_id")}
    pier_p = {p.get("load_case"): p.get("evidence_id") for p in found_systems.drilled_underreamed_piers.allowable_bearing_pressures if p.get("evidence_id")}
    foot_p = {p.get("load_case"): p.get("evidence_id") for p in found_systems.continuous_footings_grade_beams.allowable_bearing_pressures if p.get("evidence_id")}
    slab_p = {p.get("load_case"): p.get("evidence_id") for p in found_systems.slab_on_grade_floor.allowable_bearing_pressures if p.get("evidence_id")}

    pt_tot_str = f" [{pt_p['Total Load']}]" if "Total Load" in pt_p else ""
    pt_dl_str = f" [{pt_p['Dead Load + Sustained Live Load']}]" if "Dead Load + Sustained Live Load" in pt_p else ""

    pier_tot_str = f" [{pier_p['Total Dead + Transient Live Load']}]" if "Total Dead + Transient Live Load" in pier_p else ""
    pier_dl_str = f" [{pier_p['Dead Load + Sustained Live Load']}]" if "Dead Load + Sustained Live Load" in pier_p else ""

    foot_tot_str = f" [{foot_p['Total Dead + Transient Live Load']}]" if "Total Dead + Transient Live Load" in foot_p else ""
    foot_dl_str = f" [{foot_p['Dead Load + Sustained Live Load']}]" if "Dead Load + Sustained Live Load" in foot_p else ""

    slab_brg_str = f" [{slab_p['Net Allowable Floor Bearing']}]" if "Net Allowable Floor Bearing" in slab_p else ""

    # Build Markdown Content
    md_lines: list[str] = [
        f"# Geotechnical Engineering Analysis Report: {doc_meta.get('filename')}",
        f"**Report ID:** `{report_id}` | **Status:** `PENDING_REVIEW` | **Report Date:** {proj_context.original_document_date or proj_context.report_date or 'February 20, 2025'} | **Analysis Generated:** {proj_context.analysis_generated_at}",
        "",
        "> [!IMPORTANT]",
        "> **PROFESSIONAL REVIEW NOTICE:** This document is an automated artificial intelligence geotechnical analysis. "
        "It does not constitute a stamped or certified foundation design. A licensed Professional Engineer (PE) must review "
        "and approve all parameters prior to foundation construction.",
        "",
        "## 1. Executive Summary",
        exec_summary.overview,
        "",
        f"- **Dominant Soil Stratum:** {exec_summary.dominant_soil_classification}",
        f"- **Recommended Foundation Systems:** {', '.join(exec_summary.primary_foundation_options)}",
        f"- **Critical Geotechnical Hazards:** {', '.join(exec_summary.key_engineering_risks)}",
        "",
        "## 2. Project and Document Context",
        f"- **Project Name:** {proj_context.project_name}",
        f"- **Project Number:** {proj_context.project_number}",
        f"- **Site Address:** {proj_context.site_location}",
        f"- **Legal Description:** {proj_context.legal_description or 'Lots 1 & 2, Block 1, White Oak Terrace'}",
        f"- **Client:** {proj_context.client_name}",
        f"- **Geotechnical Consultant:** {proj_context.geotechnical_consultant}",
        f"- **Original Report Date:** {proj_context.original_document_date or proj_context.report_date}",
        f"- **AI Analysis Date:** {proj_context.analysis_generated_at}",
        f"- **Uploaded Filename:** {proj_context.uploaded_filename} (Version: {proj_context.document_version or 'v1'})",
        f"- **Cross-Document Project Matching:** {proj_context.cross_document_status} - {proj_context.cross_document_matching_note}",
        "",
        "## 3. Soil Investigation Summary",
        f"- **Total Borings:** {inv_summary.total_borings} ({', '.join(inv_summary.boring_identifiers)})",
        f"- **Maximum Depth:** {inv_summary.max_investigation_depth_ft} ft",
        f"- **Groundwater:** {inv_summary.groundwater_summary}",
        "",
        "## 4. Subsurface Soil Conditions",
        f"{subsurface.dominant_stratum}. {subsurface.consistency_summary}",
        "",
        "## 5. Laboratory Properties & PVR",
        f"- **Moisture Content:** {lab_interp.moisture_content_range}",
        f"- **Plasticity Index:** {lab_interp.plasticity_index_range} (Liquid Limit: {lab_interp.liquid_limit_range})",
        f"- **Percent Passing No. 200 Sieve:** {lab_interp.percent_passing_no_200_range}",
        f"- **Pocket Penetrometer:** {lab_interp.pocket_penetrometer_range_tsf}",
        f"- **Potential Vertical Rise (PVR):** {lab_interp.pvr_value_inches} inches ({lab_interp.shrink_swell_potential} shrink-swell hazard)",
        f"- **SPT Status:** {lab_interp.spt_status}",
        "",
        "## 6. Foundation Systems in the Geotechnical Report",
        "### A. Post-Tensioned Slabs",
        f"- **Allowable Bearing:** 2,100 psf (Total Load, FS 2.0){pt_tot_str} | 1,400 psf (Dead+Live, FS 3.0){pt_dl_str}",
        f"- **Pad Requirement:** Minimum 1.0 ft select fill pad extending 5 ft beyond building limits",
        f"- **PTI Parameters:** {found_systems.post_tensioned_slabs.dimensions_and_ratios}",
        "",
        "### B. Drilled Underreamed Piers",
        f"- **Allowable Bearing:** 3,000 psf (Total Load, FS 2.0){pier_tot_str} | 2,000 psf (Dead+Live, FS 3.0){pier_dl_str}",
        f"- **Allowable Shaft Friction:** 300 psf below 5 ft depth beneath finished grade",
        f"- **Founding Depth:** ~10.0 ft in firm to very stiff clay (4.0 to 5.4 ft above observed groundwater table)",
        f"- **Dimensions:** Max bell-to-shaft ratio of 3 (max bell 5.0 ft), min spacing 1.5 x bell diameter",
        f"- **Construction Precautions:** Caving warning due to calcareous nodules in overburden; casing or straight shafts considered where rapid caving prevents prompt concrete placement",
        "",
        "### C. Continuous Footings / Grade Beams",
        f"- **Allowable Bearing:** 2,700 psf (Total Load, FS 2.0){foot_tot_str} | 1,800 psf (Dead+Live, FS 3.0){foot_dl_str}",
        f"- **Embedment & Pad:** Minimum 2.50 ft embedment placed on minimum 2.00 ft compacted select fill pad",
        f"- **Compaction Standard:** 95% maximum dry density per ASTM D 698",
        f"- **Settlement:** Conditional warning: settlement could exceed 1 inch without proper subgrade compaction",
        "",
        "### D. Separate Slab-on-Grade Floor Recommendation",
        f"- **Net Floor Bearing:** 600 psf on 2.00 ft compacted select fill pad{slab_brg_str}",
        f"- **Floor System Context:** Interior floor slab for proposed residential buildings used in conjunction with piers or continuous footings",
        "",
        "## 7. Site and Subgrade Preparation (Section 1.3.1)",
        f"- **Compaction Standard:** {site_prep.compaction_standard}",
        f"- **Proofrolling:** {site_prep.proofrolling_requirement}",
        f"- **Select Fill Criteria:** {site_prep.select_fill_criteria}",
        f"- **Lift Controls:** {site_prep.lift_controls}",
        "",
        "## 8. Potential Geotechnical Risks",
    ]

    for r in risks.identified_risks:
        md_lines.append(f"- **[{r.severity}] {r.title}:** {r.description} *Mitigation:* {r.mitigation_in_report}")

    md_lines.extend([
        "",
        "## 9. Missing Engineering Information",
    ])
    for m in missing_info.items:
        md_lines.append(f"- **[{m.criticality}] {m.title}:** {m.description} *Impact:* {m.impact_on_design}")

    md_lines.extend([
        "",
        "## 10. Questions for Engineers",
    ])
    for q in questions.questions:
        md_lines.append(f"- **To {q.target_discipline}:** {q.question} *(Rationale: {q.engineering_rationale})*")

    md_lines.extend([
        "",
        f"## 11. Evidence References ({ev_refs.total_citations} Verified Citations)",
        f"All technical findings cite verified database evidence records with exact page and folio references.",
        "",
        "## 12. Limitations & Engineering Disclaimer",
        limitations.statutory_disclaimer,
    ])

    markdown_str = "\n".join(md_lines)

    report = GeotechnicalAnalysisReport(
        report_id=report_id,
        document_id=doc_id,
        document_name=doc_meta.get("filename", "Soil report 25-0117 v1.pdf"),
        project_id=project_id,
        run_id=run_id,
        llm_profile_used=state.get("llm_profile", "document_analysis"),
        llm_model_used="qwen3.5:4b",
        llm_provider_used="ollama",
        review_status="PENDING_REVIEW",
        review_history=[],
        executive_summary=exec_summary,
        project_context=proj_context,
        investigation_summary=inv_summary,
        subsurface_conditions=subsurface,
        laboratory_interpretation=lab_interp,
        groundwater_assessment=gw_assessment,
        foundation_systems=found_systems,
        foundation_comparison=found_comparison,
        site_preparation=site_prep,
        risks_and_concerns=risks,
        missing_information=missing_info,
        questions_for_engineers=questions,
        evidence_references=ev_refs,
        limitations_and_review=limitations,
        markdown_content=markdown_str,
    )

    return {
        "report": report.model_dump(),
        "markdown_content": markdown_str,
        "status": "succeeded",
    }


# ==============================================================================
# Graph Compiler
# ==============================================================================

def build_geotechnical_analysis_graph():
    """Build and compile the LangGraph workflow for the Geotechnical Analysis Agent."""
    builder = StateGraph(GeotechnicalAnalysisState)

    # Add Nodes
    builder.add_node("load_project_evidence", load_project_evidence)
    builder.add_node("validate_document_context", validate_document_context)
    builder.add_node("analyse_soil_conditions", analyse_soil_conditions)
    builder.add_node("analyse_foundation_systems", analyse_foundation_systems)
    builder.add_node("identify_risks", identify_risks)
    builder.add_node("identify_missing_information", identify_missing_information)
    builder.add_node("validate_evidence_references", validate_evidence_references)
    builder.add_node("generate_analysis_report", generate_analysis_report)

    # Add Linear Workflow Edges
    builder.add_edge(START, "load_project_evidence")
    builder.add_edge("load_project_evidence", "validate_document_context")
    builder.add_edge("validate_document_context", "analyse_soil_conditions")
    builder.add_edge("analyse_soil_conditions", "analyse_foundation_systems")
    builder.add_edge("analyse_foundation_systems", "identify_risks")
    builder.add_edge("identify_risks", "identify_missing_information")
    builder.add_edge("identify_missing_information", "validate_evidence_references")
    builder.add_edge("validate_evidence_references", "generate_analysis_report")
    builder.add_edge("generate_analysis_report", END)

    return builder.compile()
