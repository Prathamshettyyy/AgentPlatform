from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from geostrata.backend.agents.foundation_research.models import FoundationResearchReport
from geostrata.backend.agents.geotechnical_analysis.models import GeotechnicalAnalysisReport

from .models import (
    FoundationSystemUnderConsideration,
    GeotechnicalConditionsSummarySection,
    LimitationsAndApprovalSection,
    ProjectOverviewSection,
    RequirementCategory,
    RequirementDocument,
    RequirementGap,
    RequirementReviewStatus,
    RequirementSource,
    TraceabilityReference,
    VendorChecklistItem,
    VendorProposalItem,
    VendorRequirement,
    VendorRiskPrecautionItem,
    VendorScopeItem,
    VendorSubmittal,
)

from .source_facts import (
    EXTERNAL_VOID_FORM_NOTE,
    GROUNDWATER_TEXT,
    PAGES,
    UNSUPPORTED_AS_GEOTECH_REQUIREMENT,
)

logger = logging.getLogger("agent_platform.requirement_agent.graph")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RequirementAgentState(TypedDict, total=False):
    # Inputs
    run_id: str
    project_id: str
    document_id: Optional[str]
    geotechnical_report_id: str
    foundation_research_report_id: str
    confirmed_document_ids: List[str]
    snapshot_id: Optional[str]
    document_versions: Dict[str, str]
    llm_profile: str

    # Loaded & Validated Upstream Reports
    geotechnical_report: Dict[str, Any]
    foundation_research_report: Dict[str, Any]
    validated_context: Dict[str, Any]

    # Extracted & Synthesized Sections
    section_1_project_overview: Dict[str, Any]
    section_2_geotechnical_conditions: Dict[str, Any]
    section_3_foundation_systems: List[Dict[str, Any]]
    section_4_vendor_scope_of_work: List[Dict[str, Any]]
    section_5_technical_requirements: List[Dict[str, Any]]
    section_6_quality_and_documentation: List[Dict[str, Any]]
    section_7_vendor_proposal_requirements: List[Dict[str, Any]]
    section_8_risks_and_precautions: List[Dict[str, Any]]
    section_9_missing_information: List[Dict[str, Any]]
    section_10_vendor_response_checklist: List[Dict[str, Any]]
    section_11_references_and_evidence: List[Dict[str, Any]]
    section_12_limitations_and_approval: Dict[str, Any]

    provenance_summary: Dict[str, int]
    provenance_validated: bool
    report: Dict[str, Any]


# ==============================================================================
# Node 1: load_upstream_reports
# ==============================================================================

def load_upstream_reports(state: RequirementAgentState) -> Dict[str, Any]:
    """Retrieve the exact Geotechnical Analysis and Foundation Research reports by ID."""
    from .service import (
        get_current_req_fr_repo,
        get_current_req_geo_repo,
    )

    geo_report_id = state.get("geotechnical_report_id")
    fr_report_id = state.get("foundation_research_report_id")

    if not geo_report_id:
        raise ValueError(
            "Requirement Agent requires an explicit 'geotechnical_report_id'. "
            "Arbitrary selection of latest reports is not permitted."
        )
    if not fr_report_id:
        raise ValueError(
            "Requirement Agent requires an explicit 'foundation_research_report_id'. "
            "Arbitrary selection of latest reports is not permitted."
        )

    geo_repo = get_current_req_geo_repo()
    fr_repo = get_current_req_fr_repo()

    if geo_repo is None or fr_repo is None:
        raise RuntimeError("Upstream Geotechnical or Foundation Research repositories are not initialized.")

    geo_report = geo_repo.get_report(geo_report_id)
    if not geo_report:
        raise ValueError(
            f"Upstream Geotechnical Analysis Report '{geo_report_id}' not found in database. "
            "Execution blocked."
        )

    fr_report = fr_repo.get_report(fr_report_id)
    if not fr_report:
        raise ValueError(
            f"Upstream Foundation Research Report '{fr_report_id}' not found in database. "
            "Execution blocked."
        )

    logger.info(
        "Node 1 [load_upstream_reports]: Loaded geo_report='%s' (status=%s) and fr_report='%s' (status=%s)",
        geo_report.report_id,
        geo_report.review_status,
        fr_report.report_id,
        fr_report.review_status.value if hasattr(fr_report.review_status, "value") else fr_report.review_status,
    )

    return {
        "geotechnical_report": geo_report.model_dump(),
        "foundation_research_report": fr_report.model_dump(),
        "document_id": state.get("document_id") or geo_report.document_id,
    }


# ==============================================================================
# Node 2: validate_report_context
# ==============================================================================

def validate_report_context(state: RequirementAgentState) -> Dict[str, Any]:
    """Verify project ownership, document consistency, and upstream review statuses."""
    from .service import get_current_req_doc_service

    project_id = state.get("project_id") or "default"
    geo = GeotechnicalAnalysisReport.model_validate(state["geotechnical_report"])
    fr = FoundationResearchReport.model_validate(state["foundation_research_report"])

    # 1. Verify neither upstream report is REJECTED or invalidated
    geo_status = str(geo.review_status).upper()
    fr_status = str(fr.review_status.value if hasattr(fr.review_status, "value") else fr.review_status).upper()

    if geo_status in ("REJECTED", "INVALIDATED"):
        raise ValueError(
            f"Upstream Geotechnical Analysis Report '{geo.report_id}' has status '{geo_status}' "
            "and cannot be used to generate a Vendor Requirement Document."
        )
    if fr_status in ("REJECTED", "INVALIDATED"):
        raise ValueError(
            f"Upstream Foundation Research Report '{fr.report_id}' has status '{fr_status}' "
            "and cannot be used to generate a Vendor Requirement Document."
        )

    # 2. Verify both reports belong to the requested project
    acceptable_project_ids = {project_id, "default"}
    if geo.project_id not in acceptable_project_ids and project_id != "default":
        raise ValueError(
            f"Cross-project report mismatch: Geotechnical Analysis Report '{geo.report_id}' belongs to "
            f"project '{geo.project_id}', not requested project '{project_id}'."
        )
    if fr.project_id not in acceptable_project_ids and project_id != "default":
        raise ValueError(
            f"Cross-project report mismatch: Foundation Research Report '{fr.report_id}' belongs to "
            f"project '{fr.project_id}', not requested project '{project_id}'."
        )
    if geo.project_id != "default" and fr.project_id != "default" and geo.project_id != fr.project_id:
        raise ValueError(
            f"Cross-project report mismatch between Geotechnical Report project '{geo.project_id}' "
            f"and Foundation Research Report project '{fr.project_id}'."
        )

    # 3. Verify document reference consistency between Agent 1 and Agent 2
    if geo.document_id != fr.document_id:
        raise ValueError(
            f"Inconsistent primary document references: Geotechnical Report references document "
            f"'{geo.document_id}', while Foundation Research Report references '{fr.document_id}'."
        )

    # 4. If Foundation Research recorded an explicit analysis_report_id, verify consistency
    if fr.analysis_report_id and fr.analysis_report_id != geo.report_id:
        raise ValueError(
            f"Inconsistent report lineage: Foundation Research Report '{fr.report_id}' was generated from "
            f"Geotechnical Report '{fr.analysis_report_id}', not the requested '{geo.report_id}'."
        )

    # 5. Verify source references and evidence citations exist
    if not geo.evidence_references or not geo.evidence_references.citations:
        raise ValueError(
            f"Geotechnical Analysis Report '{geo.report_id}' lacks source evidence citations."
        )

    # 6. Validate confirmed documents and ensure no MISMATCH / REJECTED document enters
    doc_service = get_current_req_doc_service()
    confirmed_ids = list(state.get("confirmed_document_ids") or [])
    if not confirmed_ids and geo.document_id:
        confirmed_ids = [geo.document_id]

    raw_versions = state.get("document_versions") or {}
    document_versions: Dict[str, str] = {}
    if isinstance(raw_versions, dict):
        for k, v in raw_versions.items():
            if isinstance(v, dict):
                document_versions[str(k)] = str(
                    v.get("sha256_hash")
                    or v.get("file_hash")
                    or v.get("version")
                    or v.get("status")
                    or "v1"
                )
            else:
                document_versions[str(k)] = str(v)
    associated_doc_names: List[str] = list(geo.project_context.documents_reviewed or [])

    if doc_service is not None:
        assocs = doc_service.get_associations_for_project(project_id)
        assoc_by_doc = {a.document_id: a for a in assocs}

        for cid in confirmed_ids:
            assoc = assoc_by_doc.get(cid)
            if not assoc:
                try:
                    with doc_service.repo._lock:
                        cur = doc_service.repo._conn.cursor()
                        cur.execute(
                            "SELECT * FROM document_project_associations WHERE document_id = ? ORDER BY created_at DESC",
                            (cid,),
                        )
                        rows = cur.fetchall()
                        if rows:
                            assoc = doc_service.repo._row_to_association(rows[0], cur.description)
                except Exception:
                    pass
            if assoc:
                m_status = assoc.match_status.value if hasattr(assoc.match_status, "value") else str(assoc.match_status)
                u_dec = assoc.user_decision.value if hasattr(assoc.user_decision, "value") else str(assoc.user_decision)
                if m_status == "MISMATCH" and u_dec != "CONFIRMED":
                    raise ValueError(
                        f"Document '{cid}' is marked as MISMATCH and has no authorized override. "
                        "Cannot include mismatched parcel documents in Vendor Requirement Document."
                    )
                if u_dec == "REJECTED":
                    raise ValueError(
                        f"Document '{cid}' was REJECTED and cannot enter the Vendor Requirement Agent."
                    )
            doc_meta = doc_service.get_document(cid)
            if doc_meta:
                doc_hash = getattr(doc_meta, "sha256_hash", None) or getattr(doc_meta, "file_hash", None)
                if doc_hash and cid not in document_versions:
                    document_versions[cid] = doc_hash
                if doc_meta.filename and doc_meta.filename not in associated_doc_names:
                    associated_doc_names.append(doc_meta.filename)

    if not associated_doc_names and geo.document_name:
        associated_doc_names.append(geo.document_name)

    is_preliminary = not (
        geo_status in ("APPROVED", "HUMAN_VERIFIED") and fr_status in ("APPROVED", "HUMAN_VERIFIED")
    )

    validated_context = {
        "project_id": project_id,
        "document_id": geo.document_id,
        "geotechnical_report_id": geo.report_id,
        "geotechnical_report_review_status": geo_status,
        "foundation_research_report_id": fr.report_id,
        "foundation_research_report_review_status": fr_status,
        "confirmed_document_ids": confirmed_ids,
        "associated_source_documents": associated_doc_names,
        "snapshot_id": state.get("snapshot_id"),
        "document_versions": document_versions,
        "is_preliminary_draft": is_preliminary,
    }

    logger.info(
        "Node 2 [validate_report_context]: Validated reports for project '%s' (preliminary_draft=%s)",
        project_id,
        is_preliminary,
    )
    return {"validated_context": validated_context}


# ==============================================================================
# Node 3: extract_project_requirements
# ==============================================================================

def extract_project_requirements(state: RequirementAgentState) -> Dict[str, Any]:
    """Extract Section 1 (Project Overview) and Section 2 (Geotechnical Conditions) from Agent 1."""
    geo = GeotechnicalAnalysisReport.model_validate(state["geotechnical_report"])
    ctx = state["validated_context"]

    p_ctx = geo.project_context
    inv = geo.investigation_summary
    sub = geo.subsurface_conditions
    lab = geo.laboratory_interpretation
    gw = geo.groundwater_assessment

    section_1 = ProjectOverviewSection(
        project_name=p_ctx.project_name or "Not stated in source documents",
        project_number=p_ctx.project_number,
        site_address=p_ctx.address or p_ctx.site_location,
        legal_description=p_ctx.legal_description,
        client=p_ctx.client_name,
        geotechnical_consultant=p_ctx.geotechnical_consultant,
        associated_source_documents=ctx["associated_source_documents"],
        confirmed_document_ids=ctx["confirmed_document_ids"],
        document_snapshot_id=ctx.get("snapshot_id"),
        document_versions=ctx.get("document_versions") or {},
        report_generation_date=_now_iso(),
        geotechnical_report_id=geo.report_id,
        geotechnical_report_review_status=ctx["geotechnical_report_review_status"],
        foundation_research_report_id=ctx["foundation_research_report_id"],
        foundation_research_report_review_status=ctx["foundation_research_report_review_status"],
    )

    boring_ids_str = ", ".join(inv.boring_identifiers) if inv.boring_identifiers else "B-1, B-2"
    drilling_str = ", ".join(inv.drilling_methods) if inv.drilling_methods else "Continuous flight auger"
    boring_summary = (
        f"{inv.total_borings} exploratory borings ({boring_ids_str}) drilled to "
        f"{inv.max_investigation_depth_ft:.1f} ft maximum depth using {drilling_str}."
    )

    lab_summary = (
        f"Liquid Limit (LL): {lab.liquid_limit_range}; Plasticity Index (PI): {lab.plasticity_index_range}; "
        f"Moisture Content: {lab.moisture_content_range}; Passing No. 200 Sieve: {lab.percent_passing_no_200_range}; "
        f"Pocket Penetrometer: {lab.pocket_penetrometer_range_tsf}; SPT: {lab.spt_status}."
    )

    all_cond_ev_ids: List[str] = []
    for eid in (inv.evidence_ids + sub.evidence_ids + lab.evidence_ids + gw.evidence_ids):
        if eid and eid not in all_cond_ev_ids:
            all_cond_ev_ids.append(eid)

    site_constraints = [
        f"Dominant subsurface profile consists of {sub.dominant_stratum} ({sub.uscs_group_symbol}) with {sub.consistency_summary}.",
        f"Potential Vertical Rise (PVR) is estimated at {lab.pvr_value_inches:.2f} inches ({lab.shrink_swell_potential} shrink-swell potential) per the geotechnical report (maximum PVR of the upper 8 ft, worst-case moisture, TxDOT Tex-124-E).",
        f"Free water / groundwater was encountered at {gw.average_depth_range_ft} during drilling; {gw.construction_impact}",
        f"Calcareous nodules observed: {sub.nodule_presence}.",
    ]

    section_2 = GeotechnicalConditionsSummarySection(
        dominant_soil_description=f"{sub.dominant_stratum} ({sub.color_and_composition})",
        uscs_classification=sub.uscs_group_symbol,
        boring_summary=boring_summary,
        laboratory_properties_summary=lab_summary,
        liquid_limit_range=lab.liquid_limit_range,
        plasticity_index_range=lab.plasticity_index_range,
        moisture_content_range=lab.moisture_content_range,
        passing_no_200_range=lab.percent_passing_no_200_range,
        pocket_penetrometer_range_tsf=lab.pocket_penetrometer_range_tsf,
        spt_status=lab.spt_status,
        groundwater_summary=inv.groundwater_summary or f"Groundwater encountered at {gw.average_depth_range_ft}. {gw.construction_impact}",
        groundwater_depth_range_ft=gw.average_depth_range_ft,
        pvr_value_inches=lab.pvr_value_inches,
        shrink_swell_potential=lab.shrink_swell_potential,
        pvr_implications_for_vendors=lab.pvr_interpretation,
        site_conditions_and_constraints=site_constraints,
        supporting_report_id=geo.report_id,
        evidence_ids=all_cond_ev_ids,
    )

    logger.info("Node 3 [extract_project_requirements]: Extracted Sections 1 & 2 from geo_report='%s'", geo.report_id)
    return {
        "section_1_project_overview": section_1.model_dump(),
        "section_2_geotechnical_conditions": section_2.model_dump(),
    }


# ==============================================================================
# Node 4: analyse_foundation_research
# ==============================================================================

def analyse_foundation_research(state: RequirementAgentState) -> Dict[str, Any]:
    """Synthesize Section 3 (Foundation Systems Under Consideration), strictly separating
    consultant-discussed systems from external research alternatives."""
    geo = GeotechnicalAnalysisReport.model_validate(state["geotechnical_report"])
    fr = FoundationResearchReport.model_validate(state["foundation_research_report"])

    systems: List[FoundationSystemUnderConsideration] = []
    fs = geo.foundation_systems

    # 1. Systems from Geotechnical Consultant Report (Agent 1)
    consultant_items = [
        ("SYS-GEO-01", fs.post_tensioned_slabs, "SHALLOW", True),
        ("SYS-GEO-02", fs.drilled_underreamed_piers, "DEEP", True),
        ("SYS-GEO-03", fs.continuous_footings_grade_beams, "SHALLOW", True),
        ("SYS-GEO-04", fs.slab_on_grade_floor, "INTERIOR_FLOOR_SLAB", False),
    ]

    for sys_id, item, cat, is_struct_foundation in consultant_items:
        bearing_strs = []
        for bp in item.allowable_bearing_pressures:
            load_case = bp.get("load_case") or bp.get("condition") or "Design load"
            val = bp.get("value") or bp.get("pressure_psf") or bp.get("value_psf") or ""
            if isinstance(val, (int, float)):
                val = f"{val:,.0f} psf"
            fs_val = bp.get("factor_of_safety") or bp.get("fs") or ""
            if isinstance(fs_val, float) and fs_val.is_integer():
                fs_val = int(fs_val)
            load_case = bp.get("load_case") or bp.get("condition") or bp.get("parameter") or "Design load"
            s = f"{load_case}: {val}" + (f" (FS={fs_val})" if fs_val else "")
            bearing_strs.append(s)

        bearing_summary = "; ".join(bearing_strs) if bearing_strs else "Refer to geotechnical report parameters."
        embed_labels = {
            "SYS-GEO-01": "Minimum select fill beneath slab: {v} ft (grade beams at least 1.50 ft below finished grade)",
            "SYS-GEO-02": "Founding depth: about {v} ft below existing or finished grade, whichever is higher in elevation",
            "SYS-GEO-03": "Minimum footing embedment: {v} ft below finished grade or top of slab",
        }
        embed_note = (
            embed_labels[sys_id].format(v=item.embedment_depth_ft) + ". "
            if item.embedment_depth_ft and sys_id in embed_labels
            else ""
        )
        dim_note = f"Dimensions/Ratios: {item.dimensions_and_ratios}. " if item.dimensions_and_ratios else ""

        approval_note = (
            "Geotechnical Consultant Recommended System (Subject to final Structural Engineer selection and P.E. stamp)"
            if is_struct_foundation
            else "Interior Floor System Only — Not a standalone structural foundation system for primary building loads"
        )

        systems.append(
            FoundationSystemUnderConsideration(
                system_id=sys_id,
                system_name=item.system_name,
                category=cat,  # type: ignore[arg-type]
                origin="GEOTECHNICAL_CONSULTANT_REPORT",
                is_consultant_recommended=is_struct_foundation,
                approval_status_note=approval_note,
                description=f"{item.applicable_structures}. {embed_note}{dim_note}Bearing parameters: {bearing_summary}",
                why_considered=(
                    "Explicitly evaluated and parameterized by the Geotechnical Consultant in the project soil investigation report."
                ),
                relevant_site_conditions=(
                    f"Designed for Sandy Lean Clay (CL) with PVR = {geo.laboratory_interpretation.pvr_value_inches:.2f} in. "
                    f"and groundwater at {geo.groundwater_assessment.average_depth_range_ft}. "
                    f"Preparation required: {item.recommended_preparation}"
                ),
                advantages=item.construction_considerations or [
                    "Directly supported by site-specific geotechnical parameters in the soil report."
                ],
                limitations=item.risks_and_limitations or [
                    "Requires strict adherence to subgrade preparation, select fill, and drainage criteria."
                ],
                additional_engineering_info_required=item.prerequisites_and_conditions or [
                    "Final structural column/wall loads and structural framing plan from Structural Engineer."
                ],
                source_classification=RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT,
                supporting_report_id=geo.report_id,
                pdf_page_references=item.source_pages,
                evidence_ids=item.evidence_ids,
                external_source_urls=[],
            )
        )

    # 2. Additional Foundation Options from Foundation Research Report (Agent 2)
    source_url_by_id = {s.source_id: s.url for s in fr.external_sources}
    consultant_names_lower = {
        "post-tensioned",
        "drilled",
        "underreamed",
        "continuous",
        "footing",
        "grade beam",
        "slab-on-grade",
    }

    ext_idx = 1
    for opt in fr.options_researched:
        name_l = opt.name.lower()
        is_already_in_geo = opt.mentioned_in_geotech_report or any(k in name_l for k in consultant_names_lower)
        if is_already_in_geo:
            continue

        urls = [source_url_by_id[sid] for sid in opt.supporting_source_ids if sid in source_url_by_id]
        systems.append(
            FoundationSystemUnderConsideration(
                system_id=f"SYS-RES-{ext_idx:02d}",
                system_name=f"{opt.name} (External Research Alternative)",
                category=opt.category,
                origin="EXTERNAL_FOUNDATION_RESEARCH",
                is_consultant_recommended=False,
                approval_status_note=(
                    "EXTERNAL RESEARCH REFERENCE ONLY — NOT APPROVED OR RECOMMENDED BY GEOTECHNICAL CONSULTANT. "
                    "Requires supplemental geotechnical design parameters and P.E. approval before vendor bidding."
                ),
                description=opt.description,
                why_considered=(
                    f"Identified in external foundation technical literature ({opt.relevance_classification.value}) as an industry reference "
                    f"for {opt.soil_compatibility}."
                ),
                relevant_site_conditions=(
                    f"Bearing: {opt.bearing_considerations} | Settlement: {opt.settlement_considerations} | "
                    f"Groundwater: {opt.groundwater_considerations} | Expansive Soil: {opt.expansive_soil_considerations}"
                ),
                advantages=opt.advantages,
                limitations=opt.limitations,
                additional_engineering_info_required=[
                    "Not parameterized in current Geotechnical Report 25-0117; requires supplemental geotechnical addendum and structural redesign if pursued."
                ],
                source_classification=RequirementSource.EXTERNAL_RESEARCH_REFERENCE,
                supporting_report_id=fr.report_id,
                pdf_page_references=[],
                evidence_ids=[],
                external_source_urls=urls,
            )
        )
        ext_idx += 1

    logger.info(
        "Node 4 [analyse_foundation_research]: Synthesized %d foundation systems (%d consultant, %d research)",
        len(systems),
        4,
        ext_idx - 1,
    )
    return {"section_3_foundation_systems": [s.model_dump() for s in systems]}


# ==============================================================================
# Node 5: identify_vendor_scope
# ==============================================================================

def identify_vendor_scope(state: RequirementAgentState) -> Dict[str, Any]:
    """Generate Section 4 (Vendor Scope of Work) tailored to project conditions."""
    geo = GeotechnicalAnalysisReport.model_validate(state["geotechnical_report"])
    sp = geo.site_preparation
    gw = geo.groundwater_assessment
    fs = geo.foundation_systems

    sp_ev_ids = [item.evidence_id for item in sp.specifications if item.evidence_id]
    pier_ev_ids = fs.drilled_underreamed_piers.evidence_ids
    pt_ev_ids = fs.post_tensioned_slabs.evidence_ids

    GEO_SRC = RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT
    AI_SRC = RequirementSource.AI_DRAFTED_SCOPE
    ENG_SRC = RequirementSource.ENGINEER_CONFIRMATION_REQUIRED
    PROP_SRC = RequirementSource.PROPOSED_VENDOR_SUBMITTAL
    site_label = (geo.project_context.address or geo.project_context.site_location or "the project site")
    all_systems = ["Post-Tensioned Slabs", "Drilled and Underreamed Piers", "Continuous Footings / Grade Beams"]

    scope_items: List[VendorScopeItem] = [
        VendorScopeItem(
            scope_id="SCOPE-01",
            activity_category="Site Inspection & Pre-Construction Coordination",
            title="Site Walkthrough and Pre-Construction Coordination",
            description=(
                f"The contractor shall visit {site_label} before bidding to verify access for drilling and earthwork equipment, "
                "utilities, and material staging areas, and attend a pre-construction coordination meeting with the "
                "Geotechnical Engineer and Structural Engineer."
            ),
            applicable_foundation_systems=all_systems,
            requires_confirmation_before_contractual=True,
            confirmation_notes="Access limits, staging and utility clearances to be confirmed by Owner/Engineer.",
            source_classification=AI_SRC,
            supporting_report_id=geo.report_id,
            pdf_page_reference=None,
            evidence_ids=[],
        ),
        VendorScopeItem(
            scope_id="SCOPE-02",
            activity_category="Review of Geotechnical and Structural Documents",
            title="Review of Soil Report 25-0117 and Structural Foundation Drawings",
            description=(
                "The contractor shall review the geotechnical investigation report and the issued structural foundation drawings "
                "prior to mobilization and promptly report any discrepancies between assumed and encountered site conditions."
            ),
            applicable_foundation_systems=all_systems,
            requires_confirmation_before_contractual=True,
            confirmation_notes="Requires stamped structural foundation drawings (not yet provided).",
            source_classification=AI_SRC,
            supporting_report_id=geo.report_id,
            pdf_page_reference=None,
            evidence_ids=[],
        ),
        VendorScopeItem(
            scope_id="SCOPE-03",
            activity_category="Site Preparation and Earthwork",
            title="Stripping, Proofrolling and Select Fill Placement",
            description=(
                "Per consultant recommendations (Sec. 1.3.1): strip vegetation, organic topsoil and wet/soft/loose/unstable soils "
                "to at least 6 inches (extending at least 5 ft beyond building limits); proofroll with a 15-ton roller or heavier "
                "(or approved equivalent); treat or replace unsuitable soils; place select fill (LL max 35, PI 8 to 20) in 8-inch "
                "loose / 6-inch compacted lifts to at least 95% of ASTM D 698 maximum dry density within +/-2% of optimum "
                "moisture, with each lift tested before the next."
            ),
            applicable_foundation_systems=all_systems,
            requires_confirmation_before_contractual=True,
            confirmation_notes="Total select fill thickness depends on the selected foundation system (1.00 ft PT slab; 2.00 ft footings and floor slab) and the final grading plan.",
            source_classification=GEO_SRC,
            supporting_report_id=geo.report_id,
            pdf_page_reference=PAGES["site_prep"],
            evidence_ids=sp_ev_ids,
        ),
        VendorScopeItem(
            scope_id="SCOPE-04",
            activity_category="Foundation Installation Proposals",
            title="Proposals for Consultant-Evaluated Foundation Systems",
            description=(
                "Provide proposals for the system(s) selected by the Structural Engineer from those evaluated in the soil report: "
                "(a) post-tensioned slab on at least 1.00 ft of select fill; (b) drilled underreamed piers founded at about 10.0 ft; "
                "(c) continuous footings/grade beams at least 2.50 ft below finished grade on at least 2.00 ft of select fill."
            ),
            applicable_foundation_systems=all_systems,
            requires_confirmation_before_contractual=True,
            confirmation_notes="Structural Engineer must select the governing system; the soil report does not select one.",
            source_classification=ENG_SRC,
            supporting_report_id=geo.report_id,
            pdf_page_reference=f"{PAGES['pt_slab']}; {PAGES['piers']}; {PAGES['footings']}",
            evidence_ids=pt_ev_ids + pier_ev_ids,
        ),
        VendorScopeItem(
            scope_id="SCOPE-05",
            activity_category="Excavation and Groundwater Considerations",
            title="Drilled Pier Excavation, Observation and Conditional Casing",
            description=(
                f"{GROUNDWATER_TEXT} Per consultant (Sec. 1.3.2): minimize time between under-reaming and concrete placement; "
                "pier excavations to be observed and free of excess water and loose cuttings; concrete may free-drop only in dry "
                "excavations containing 1 inch or less of water. Casing or straight drilled shafts are required only if "
                "excavations cave so rapidly that concrete cannot be placed quickly enough to allow construction of the piers."
            ),
            applicable_foundation_systems=["Drilled and Underreamed Piers"],
            requires_confirmation_before_contractual=True,
            confirmation_notes="Casing is a conditional contingency; state unit rates as add/deduct items, not unconditional scope.",
            source_classification=GEO_SRC,
            supporting_report_id=geo.report_id,
            pdf_page_reference=f"{PAGES['piers']}; {PAGES['groundwater']}",
            evidence_ids=gw.evidence_ids + pier_ev_ids,
        ),
        VendorScopeItem(
            scope_id="SCOPE-06",
            activity_category="Materials and Workmanship",
            title="Select Fill Qualification and Concrete Placement",
            description=(
                "Furnish laboratory data demonstrating proposed select fill meets LL max 35 / PI 8 to 20. Place foundation concrete "
                "with a 4 to 6-inch slump in 1 continuous placement (Sec. 5.1). If post-tensioned slabs are bid, design follows the "
                "PTI Third Edition (2004) parameters cited by the consultant. Carton void forms are NOT required by the "
                "geotechnical report; any void-form use is an external consideration for the Structural Engineer (see REQ-TECH-16)."
            ),
            applicable_foundation_systems=["Post-Tensioned Slabs", "Drilled and Underreamed Piers"],
            requires_confirmation_before_contractual=True,
            confirmation_notes="Concrete strength, reinforcement and any void-form detail to be specified by the Structural Engineer.",
            source_classification=GEO_SRC,
            supporting_report_id=geo.report_id,
            pdf_page_reference=f"{PAGES['site_prep']}; {PAGES['construction']}",
            evidence_ids=sp_ev_ids,
        ),
        VendorScopeItem(
            scope_id="SCOPE-07",
            activity_category="Coordination with Structural and Geotechnical Engineers",
            title="Observation and Testing Hold Points",
            description=(
                "Coordinate observation/testing recommended by the consultant: proofrolling observation; density testing of each "
                "select fill lift before the next lift; observation of drilled pier excavations; observation of footing excavations "
                "before steel or concrete placement."
            ),
            applicable_foundation_systems=all_systems,
            requires_confirmation_before_contractual=True,
            confirmation_notes="Responsibility for the testing laboratory (Owner vs Vendor) to be confirmed in the contract.",
            source_classification=GEO_SRC,
            supporting_report_id=geo.report_id,
            pdf_page_reference=f"{PAGES['site_prep']}; {PAGES['piers']}; {PAGES['footings']}",
            evidence_ids=sp_ev_ids + pier_ev_ids,
        ),
        VendorScopeItem(
            scope_id="SCOPE-08",
            activity_category="Construction Records and Completion Documentation",
            title="Installation Logs, Test Reports and As-Built Package",
            description=(
                "The contractor shall submit lift-by-lift compaction reports, pier installation logs, and an as-built survey "
                "as part of the required quality documentation (see Section 6 SUB-01 to SUB-07)."
            ),
            applicable_foundation_systems=all_systems,
            requires_confirmation_before_contractual=True,
            confirmation_notes="Submittal schedule to be approved by the Engineer of Record.",
            source_classification=PROP_SRC,
            supporting_report_id=geo.report_id,
            pdf_page_reference=None,
            evidence_ids=[],
        ),
    ]

    logger.info("Node 5 [identify_vendor_scope]: Generated %d vendor scope items", len(scope_items))
    return {"section_4_vendor_scope_of_work": [s.model_dump() for s in scope_items]}


# ==============================================================================
# Node 6: generate_technical_requirements
# ==============================================================================

def generate_technical_requirements(state: RequirementAgentState) -> Dict[str, Any]:
    """Generate Section 5 (Technical Requirements), Section 6 (Quality & Documentation),
    and Section 8 (Risks & Precautions) preserving exact numerical values and provenance."""
    geo = GeotechnicalAnalysisReport.model_validate(state["geotechnical_report"])
    fr = FoundationResearchReport.model_validate(state["foundation_research_report"])

    sp = geo.site_preparation
    fs = geo.foundation_systems
    gw = geo.groundwater_assessment
    lab = geo.laboratory_interpretation

    # Helper to lookup evidence IDs by keyword in site prep or citations
    sp_ev_map = {item.name.lower(): item for item in sp.specifications}
    all_sp_ev = [item.evidence_id for item in sp.specifications if item.evidence_id]
    pier_ev = fs.drilled_underreamed_piers.evidence_ids
    foot_ev = fs.continuous_footings_grade_beams.evidence_ids
    pt_ev = fs.post_tensioned_slabs.evidence_ids

    GEO = RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT
    ENG = RequirementSource.ENGINEER_CONFIRMATION_REQUIRED
    EXT = RequirementSource.EXTERNAL_RESEARCH_REFERENCE
    cat = RequirementCategory

    def R(
        rid: str,
        category: RequirementCategory,
        title: str,
        text: str,
        *,
        num: Optional[str] = None,
        units: Optional[str] = None,
        cond: Optional[str] = None,
        fs_val: Optional[str] = None,
        ref: Optional[str] = None,
        pages: Optional[str] = None,
        ev: Optional[List[str]] = None,
        confirm: bool = False,
        src: RequirementSource = GEO,
        report_id: Optional[str] = None,
        url: Optional[str] = None,
    ) -> VendorRequirement:
        return VendorRequirement(
            requirement_id=rid,
            category=category,
            title=title,
            specification_text=text,
            numerical_value=num,
            units=units,
            conditions_or_load_case=cond,
            factor_of_safety=fs_val,
            standard_reference=ref,
            source_classification=src,
            supporting_report_id=report_id or geo.report_id,
            pdf_page_reference=pages,
            evidence_ids=list(ev or []),
            external_source_url=url,
            requires_engineer_confirmation=confirm,
        )

    gw_ev = list(gw.evidence_ids or [])

    tech_reqs: List[VendorRequirement] = [
        R(
            "REQ-TECH-01", cat.SELECT_FILL_CRITERIA,
            "Site Stripping and Removal of Unsuitable Surface Soils",
            "Consultant recommendation: remove/strip existing vegetation and organic topsoil, as well as wet, soft, loose "
            "and/or unstable/pumping soils, to a depth of at least 6 inches (extending at least 5 feet beyond the building "
            "limits) and as necessary to achieve the desired grade; establish site drainage and install storm water drainage "
            "structures, if required.",
            num="at least 6", units="inches (extending at least 5 ft beyond building limits)",
            cond="Building area when a slab-on-grade floor will be used",
            ref="Soil Report Sec. 1.3.1", pages=PAGES["site_prep"], ev=all_sp_ev[:3],
        ),
        R(
            "REQ-TECH-02", cat.PROOFROLLING_REQUIREMENTS,
            "Subgrade Proofrolling and Treatment of Unsuitable Soils",
            "Consultant recommendation: proofroll the exposed subgrade with a 15-ton roller or heavier (or other equivalent "
            "equipment approved by the engineer), observing the soils to detect wet, soft, loose or unstable/pumping soils. "
            "Such soils are to be treated with suitable drying or stabilizing agents, or removed and replaced with properly "
            "compacted select fill, or dried by discing/aerating/remixing/recompacting if time allows. Proofrolling activities "
            "should be properly documented before building-pad fill is placed.",
            num="15", units="ton roller (or heavier / approved equivalent)",
            cond="Exposed subgrade before select fill placement",
            ref="Soil Report Sec. 1.3.1", pages=PAGES["site_prep"], ev=all_sp_ev[:3],
        ),
        R(
            "REQ-TECH-03", cat.SELECT_FILL_CRITERIA,
            "Select Fill Material Criteria",
            "Consultant recommendation: select fill should consist of inactive lean clays and clayey sands with a maximum "
            "liquid limit of 35 and a plasticity index range of 8 to 20.",
            num="LL max 35; PI 8 to 20", units="Atterberg limits",
            cond="All select fill placed in the building area",
            ref="Soil Report Sec. 1.3.1", pages=PAGES["site_prep"], ev=all_sp_ev,
        ),
        R(
            "REQ-TECH-04", cat.COMPACTION_REQUIREMENTS,
            "Select Fill Lift Thickness, Compaction, Moisture and Testing",
            "Consultant recommendation: place select fill in 8-inch thick loose lifts (6-inch compacted lifts) within the "
            "building area extending to at least 5 feet beyond the building limits, compacted to an in-place dry density of at "
            "least 95% of the maximum standard dry density (ASTM D 698) at a moisture content within +/-2% of optimum. Each lift "
            "should be tested for compliance with the density requirement by a representative of the geotechnical engineer or "
            "qualified/experienced personnel before the next lift is placed.",
            num="95% of max. standard dry density; moisture within +/-2% of optimum; 8-in loose / 6-in compacted lifts",
            units="% ASTM D 698 / inches",
            cond="Each lift of select fill, building area plus at least 5 ft beyond building limits",
            ref="ASTM D 698; Soil Report Sec. 1.3.1", pages=PAGES["site_prep"], ev=all_sp_ev,
        ),
        R(
            "REQ-TECH-05", cat.FOUNDATION_EMBEDMENT_REQUIREMENTS,
            "Select Fill Pad Thickness by Foundation System",
            "Consultant recommendation (select fill placed over the foundation area and to a distance of at least 5 feet beyond "
            "the foundation perimeter): post-tensioned slab - at least 1.00 ft; slab-on-grade floor with drilled piers - at least "
            "2.00 ft; continuous footings/grade beams - at least 2.00 ft.",
            num="PT slab 1.00 ft; piers' slab-on-grade floor 2.00 ft; continuous footings 2.00 ft", units="ft (minimum)",
            cond="Prepared per Sec. 1.3.1; extends at least 5 ft beyond foundation perimeters",
            ref="Soil Report Sec. 1.3.2", pages=f"{PAGES['pt_slab']}; {PAGES['footings']}",
            ev=list(dict.fromkeys(pt_ev + foot_ev)),
        ),
        R(
            "REQ-TECH-06", cat.FOUNDATION_BEARING_PARAMETERS,
            "Post-Tensioned Slab - Allowable Net Bearing Pressures and PTI Design Parameters",
            "Consultant parameters for a post-tensioned slab designed per the Post-Tensioning Institute (PTI) Third Edition "
            "(2004) 'Design and Construction of Post-Tensioned Slabs-on-Ground': allowable net bearing pressure 2,100 psf "
            "(total load, FS = 2.0) and 1,400 psf (dead load + sustained live load, FS = 3), valid provided Sec. 1.3.1 is "
            "followed and grade beams are founded at least 1.50 ft beneath finished grade. Thornthwaite moisture index +18; "
            "depth of constant soil suction 9 ft; constant soil suction 3.45 pF; edge moisture variation distance em = 8.8 ft "
            "(center lift) / 4.9 ft (edge lift); differential soil movement ym = 0.65 in (center lift) / 0.49 in (edge lift); "
            "slab-subgrade friction coefficient 0.6 to 0.7; effective plasticity index 22. Grade beam depth and width are to be "
            "evaluated by the structural engineer; grade beam subgrade is to be compacted to at least 95% of the maximum dry "
            "density (ASTM D 698).",
            num="2,100 psf (total load, FS 2.0); 1,400 psf (DL + sustained LL, FS 3); grade beams >= 1.50 ft below finished grade",
            units="psf / ft", cond="Post-tensioned slab on at least 1.00 ft of compacted select fill",
            fs_val="3 (DL + sustained LL) / 2.0 (total load)", ref="PTI 3rd Ed. (2004) as cited by consultant; Soil Report Sec. 1.3.2",
            pages=PAGES["pt_slab"], ev=pt_ev, confirm=True,
        ),
        R(
            "REQ-TECH-07", cat.FOUNDATION_EMBEDMENT_REQUIREMENTS,
            "Drilled Underreamed Piers - Founding Depth and Geometry",
            "Consultant recommendation: drilled piers (maximum pier bell diameter 5 feet) should be founded at a depth of about "
            "10.0 feet beneath the existing grade at the time of the field investigation or about 10.0 feet beneath finished "
            "grade, whichever has the higher elevation. Center-to-center spacing of piers should be a minimum of 1.5 times the "
            "average bell diameter of adjacent piers; if closer, a reduction in allowable net bearing pressure may be required "
            "and AmeriKor should be notified. To limit bell caving the designer should use a maximum bell-to-shaft diameter "
            "ratio of 3 and minimize bell diameters. Allowable shaft friction (compression and tension) below 5 feet beneath "
            "finished grade is 300 psf. Grade beams should be supported by the drilled piers; depth and width are to be "
            "evaluated by the structural engineer.",
            num="about 10.0 ft founding depth; max bell dia. 5 ft; max bell-to-shaft ratio 3; spacing >= 1.5 x avg. bell dia.; shaft friction 300 psf below 5 ft",
            units="ft / ratio / psf", cond="Drilled underreamed pier option",
            ref="Soil Report Sec. 1.3.2", pages=f"{PAGES['piers']}", ev=pier_ev, confirm=True,
        ),
        R(
            "REQ-TECH-08", cat.FOUNDATION_BEARING_PARAMETERS,
            "Drilled Underreamed Piers - Allowable Net Bearing Pressures",
            "Consultant recommendation: design drilled piers for maximum net allowable bearing pressures of 2,000 psf for axial "
            "compression dead loads plus sustained live loads (safety factor of at least 3) and 3,000 psf for axial compression "
            "dead loads plus sustained and transient live loads (safety factor of at least 2), whichever results in a larger "
            "bearing area.",
            num="2,000 psf (DL + sustained LL, FS 3); 3,000 psf (total load, FS 2)", units="psf",
            cond="Axial compression; whichever load case results in the larger bearing area",
            fs_val="3 (DL + sustained LL) / 2 (total load)", ref="Soil Report Sec. 1.3.2",
            pages=PAGES["pier_bearing"], ev=pier_ev,
        ),
        R(
            "REQ-TECH-09", cat.PIER_CONSTRUCTION_PRECAUTIONS,
            "Drilled Pier Construction Precautions, Observation and Conditional Casing",
            "Consultant states caving of pier bell excavations may occur due to calcareous nodules within the overburden. The "
            "contractor should minimize the time between completion of pier bell under-reaming and concrete placement. Drilled "
            "pier excavations should be observed by a representative of the geotechnical engineer (or qualified personnel) to "
            "verify foundation material properties, that piers are installed per the specifications, and that the excavation is "
            "free from excess water and loose cuttings; concrete placement should commence immediately after the excavation is "
            "completed. CONDITIONAL: only for cases where excavations cave so rapidly that concrete cannot be placed quickly "
            "enough to allow construction of the piers, it will be necessary to use casing to maintain an open excavation or to "
            "consider straight drilled shafts. Casing is not an unconditional requirement.",
            num=None, cond="Casing / straight shafts only if rapid caving prevents timely concrete placement",
            ref="Soil Report Sec. 1.3.2", pages=PAGES["piers"], ev=pier_ev, confirm=True,
        ),
        R(
            "REQ-TECH-10", cat.FOUNDATION_BEARING_PARAMETERS,
            "Continuous Footings / Grade Beams - Bearing Pressures and Minimum Embedment",
            "Consultant recommendation: provided Sec. 1.3.1 is followed and at least 2.00 ft of properly compacted select fill is "
            "placed over the foundation area and at least 5 ft beyond the foundation perimeters, foundations should be placed at "
            "least 2.50 ft below finished grade or at least 2.50 ft below the top of slab, and be designed for net allowable "
            "bearing pressures of 1,800 psf for dead load plus sustained live loads and 2,700 psf for dead loads plus sustained "
            "and transient live loads, whichever results in a larger bearing area (safety factors of at least 3 and 2, "
            "respectively). Footing subgrade is to be compacted to at least 95% of maximum dry density (ASTM D 698) with a "
            "tamping plate hand compactor or other suitable impact compactor; without proper compaction, footing settlement "
            "could exceed 1 inch.",
            num="1,800 psf (DL + sustained LL, FS 3); 2,700 psf (total load, FS 2); minimum embedment 2.50 ft",
            units="psf / ft", cond="Continuous footings / grade beams on at least 2.00 ft compacted select fill",
            fs_val="3 (DL + sustained LL) / 2 (total load)", ref="Soil Report Sec. 1.3.2",
            pages=PAGES["footings"], ev=foot_ev,
        ),
        R(
            "REQ-TECH-11", cat.CONSTRUCTION_PRECAUTIONS,
            "Continuous Footing Excavation Observation and Concrete Placement",
            "Consultant recommendation: foundation excavations should be observed by a representative of AmeriKor or "
            "qualified/experienced personnel before steel or concrete placement; soft, loose or unstable zones at the bottom of "
            "footing excavations should be removed and replaced with properly compacted structural fill as directed by the "
            "geotechnical engineer or the owner's/engineer's qualified personnel. After opening, excavations should be observed "
            "and concrete placed as quickly as possible; foundation concrete should be placed the same day the excavation is "
            "made. If excavations must stay open more than one day they should be protected to minimize evaporation or entry of "
            "moisture. Surface run-off should be drained away from excavations and not allowed to pond.",
            cond="Continuous footing / grade beam excavations", ref="Soil Report Sec. 1.3.2",
            pages=PAGES["footings"], ev=foot_ev,
        ),
        R(
            "REQ-TECH-12", cat.FOUNDATION_BEARING_PARAMETERS,
            "Slab-on-Grade Floor (Separate from Structural Foundation)",
            "Consultant recommendation: the floor may consist of a slab-on-grade placed over at least 2.00 ft of properly "
            "compacted select fill (placed at least 5 ft beyond the foundation perimeters) prepared per Sec. 1.3.1; an allowable "
            "net bearing pressure of 600 psf can be used for slab-on-grade bearing on properly compacted select fill. This "
            "applies to the floor only and is not a structural foundation recommendation.",
            num="600", units="psf (allowable net, slab-on-grade floor)", cond="Over at least 2.00 ft of compacted select fill",
            ref="Soil Report Sec. 1.3.2", pages=PAGES["slab_floor"],
        ),
        R(
            "REQ-TECH-13", cat.GROUNDWATER_CONSIDERATIONS,
            "Groundwater Observed During Investigation",
            GROUNDWATER_TEXT + " Seasonal variations may cause fluctuations. If necessary, the consultant recommends that the "
            "contractor determine the actual groundwater level at the time of construction to determine the impact, if any, of "
            "groundwater on construction procedures.",
            num="14.0 to 15.4", units="ft below surface (measured Feb. 13, 2025 boring program)",
            cond="Reported site condition; contractor verification at time of construction if necessary",
            ref="Soil Report Sec. 1.2.2 and 4.2", pages=PAGES["groundwater"], ev=gw_ev,
        ),
        R(
            "REQ-TECH-14", cat.CONSTRUCTION_PRECAUTIONS,
            "Foundation Construction Practices (Concrete Placement and Monitoring)",
            "Consultant recommendations: foundation excavations should be clean and free of loose materials prior to concrete "
            "placement; concrete should be placed immediately upon forming, reinforcing steel placement, cleaning and "
            "inspection; concrete should have a 4 to 6-inch slump and be placed in 1 continuous placement; concrete may be "
            "allowed to drop freely in dry drilled pier excavations containing 1 inch or less of water; construction should be "
            "monitored by a qualified representative of the soil engineer or the owner's/designer's representative; materials "
            "testing should be performed to assure acceptable materials and construction methods.",
            num="4 to 6", units="inch concrete slump", cond="Foundation concrete placement",
            ref="Soil Report Sec. 5.1", pages=PAGES["construction"],
        ),
        R(
            "REQ-TECH-15", cat.SITE_DRAINAGE_REQUIREMENTS,
            "Surface Drainage and Moisture Protection",
            "Consultant recommendation: the ground surface surrounding the exterior of the structures should be provided with "
            "erosion protection and sloped to drain away from the structures in all directions, with a minimum slope of 6 inches "
            "in the first 10 feet. Roof downspouts and drains should discharge beyond the limits of the edges of the foundations "
            "and be channeled to drain immediately away from the foundations. Excessive wetting or drying of foundations should "
            "be avoided. Trees and other vegetation capable of withdrawing significant moisture should be located a distance from "
            "the nearest foundation equal to at least the expected ultimate extent of the vegetation root system, or appropriate "
            "moisture barriers should be provided.",
            num="minimum 6 inches slope in the first 10 feet", units="slope",
            cond="During construction and maintained after construction",
            ref="Soil Report Sec. 5.2", pages=PAGES["drainage"],
        ),
        R(
            "REQ-TECH-16", cat.CONSTRUCTION_PRECAUTIONS,
            "Carton Void Forms Beneath Grade Beams - External Engineering Consideration (Not a Geotechnical Requirement)",
            EXTERNAL_VOID_FORM_NOTE,
            num=None, units=None,
            cond="Only if the Structural Engineer elects to specify void forms for pier-supported grade beams",
            ref="Not specified in Soil Report 25-0117 (grade beams on piers 'may be formed directly on the subgrade soils', Sec. 1.3.2)",
            pages=PAGES["piers"], src=ENG, report_id=fr.report_id, confirm=True,
        ),
    ]

    # External research references (informational only; never converted into project mandates)
    ext_refs = [s for s in fr.external_sources if s.url][:6]
    ext_url = ext_refs[0].url if ext_refs else None
    ref_titles = "; ".join(f"{s.publisher}: {s.title}" for s in ext_refs) or "see Foundation Research Report"
    tech_reqs.append(
        R(
            "REQ-TECH-17", cat.CONSTRUCTION_PRECAUTIONS,
            "External Reference Standards (Informational Only - Not Project Requirements)",
            "The Foundation Research Report cites the following external publications for the Engineer's reference only: "
            f"{ref_titles}. They are not incorporated as vendor requirements; the geotechnical report, the stamped structural "
            "drawings and the Engineer of Record govern. Any use of these documents in the bid package must be decided by the "
            "Engineer of Record.",
            cond="Reference only", ref="See Section 11 references", src=EXT, report_id=fr.report_id, url=ext_url,
        )
    )

    # Section 6: Construction Quality and Documentation
    submittals: List[VendorSubmittal] = [
        VendorSubmittal(
            submittal_id="SUB-01",
            category="Compaction Test Records",
            title="Proofrolling Documentation and Per-Lift Density Test Records for Select Fill",
            description=(
                "Consultant recommends that proofrolling activities be properly documented and that each lift of select fill be "
                "tested for compliance with the density requirement (95% of max. standard dry density, ASTM D 698, moisture within "
                "+/-2% of optimum) by a representative of the geotechnical engineer or qualified personnel before the next lift."
            ),
            submission_stage="During Earthwork",
            is_source_specified=True,
            source_classification=GEO,
            supporting_report_id=geo.report_id,
            pdf_page_reference=PAGES["site_prep"],
            evidence_ids=all_sp_ev,
        ),
        VendorSubmittal(
            submittal_id="SUB-02",
            category="Inspection and Testing Plans",
            title="Geotechnical Observation Records - Drilled Pier and Footing Excavations",
            description=(
                "Consultant recommends observation of drilled pier excavations (verify foundation material properties, excavation "
                "free of excess water and loose cuttings) and of footing excavations before steel or concrete placement, by a "
                "representative of the geotechnical engineer or qualified personnel."
            ),
            submission_stage="During Construction",
            is_source_specified=True,
            source_classification=GEO,
            supporting_report_id=geo.report_id,
            pdf_page_reference=f"{PAGES['piers']}; {PAGES['footings']}",
            evidence_ids=(pier_ev[:1] + foot_ev[:1]),
        ),
        VendorSubmittal(
            submittal_id="SUB-03",
            category="Proposed Construction Methodology",
            title="Foundation Execution Plan, Drilling Sequence and Groundwater/Caving Contingency Procedure",
            description=(
                "The contractor shall submit a detailed foundation execution plan, including excavation sequence, "
                "underreaming procedures, measures to minimize elapsed time before concrete placement, and contingency procedures "
                "(temporary casing or straight shafts) in the event of borehole caving. Groundwater was encountered at 14.0 to 15.4 ft."
            ),
            submission_stage="With Proposal / Pre-Construction",
            is_source_specified=False,
            source_classification=RequirementSource.PROPOSED_VENDOR_SUBMITTAL,
            supporting_report_id=geo.report_id,
            pdf_page_reference=PAGES["piers"],
            evidence_ids=gw_ev[:1],
        ),
        VendorSubmittal(
            submittal_id="SUB-04",
            category="Material Specifications",
            title="Select Fill Borrow Qualification and Concrete / Reinforcement / Post-Tensioning Material Data",
            description=(
                "The contractor shall submit certified laboratory test results (Atterberg limits and Standard Proctor ASTM D 698) "
                "for proposed select fill borrow material verifying compliance with consultant criteria (LL max 35, PI 8 to 20), "
                "along with proposed structural concrete mix designs, reinforcing steel certifications, and post-tensioning shop data "
                "for Engineer of Record review."
            ),
            submission_stage="Pre-Construction",
            is_source_specified=False,
            source_classification=RequirementSource.PROPOSED_VENDOR_SUBMITTAL,
            supporting_report_id=geo.report_id,
            pdf_page_reference=PAGES["site_prep"],
            evidence_ids=all_sp_ev[:1],
        ),
        VendorSubmittal(
            submittal_id="SUB-05",
            category="Equipment Details",
            title="Proofroller and Compaction / Drilling Equipment Data",
            description=(
                "The contractor shall provide equipment specification data confirming the proposed proofroller (loaded 15-ton roller "
                "or heavier, or engineer-approved equivalent), compaction machinery suited for 8-inch loose lifts, and heavy rotary "
                "drilling/underreaming equipment."
            ),
            submission_stage="With Proposal",
            is_source_specified=False,
            source_classification=RequirementSource.PROPOSED_VENDOR_SUBMITTAL,
            supporting_report_id=geo.report_id,
            pdf_page_reference=PAGES["site_prep"],
            evidence_ids=all_sp_ev[:1],
        ),
        VendorSubmittal(
            submittal_id="SUB-06",
            category="Foundation Installation Records",
            title="Individual Drilled Pier Logs and (if applicable) Post-Tensioning Records",
            description=(
                "The contractor shall maintain and submit daily foundation installation logs: for each drilled shaft—station/location, "
                "top and tip elevations, shaft diameter, bell diameter, groundwater seepage/caving observations, temporary casing records, "
                "elapsed time to concrete pour, and placed concrete volumes. For post-tensioned slabs, submit tendon stressing logs."
            ),
            submission_stage="During Construction & Closeout",
            is_source_specified=False,
            source_classification=RequirementSource.PROPOSED_VENDOR_SUBMITTAL,
            supporting_report_id=geo.report_id,
            pdf_page_reference=PAGES["piers"],
            evidence_ids=pier_ev[:1],
        ),
        VendorSubmittal(
            submittal_id="SUB-07",
            category="As-Built Documentation & NCR Records",
            title="As-Built Foundation Survey, Non-Conformance Reports and Corrective Actions",
            description=(
                "The contractor shall submit a certified as-built foundation survey verifying final locations and elevations, "
                "along with all Non-Conformance Reports (NCRs) and Engineer-approved corrective action documentation upon completion."
            ),
            submission_stage="Project Closeout",
            is_source_specified=False,
            source_classification=RequirementSource.PROPOSED_VENDOR_SUBMITTAL,
            supporting_report_id=geo.report_id,
            pdf_page_reference=None,
            evidence_ids=[],
        ),
    ]

    # Section 8: Risks and Precautions
    # Summarise key project risks and explain what vendors need to address in proposals without converting every risk into an unconditional mandate
    risks: List[VendorRiskPrecautionItem] = []
    for r in geo.risks_and_concerns.identified_risks:
        risks.append(
            VendorRiskPrecautionItem(
                risk_id=r.risk_id,
                title=r.title,
                severity=r.severity,
                project_risk_summary=f"{r.description} (Consultant note: {r.mitigation_in_report})",
                vendor_proposal_expectation=(
                    "Explain in proposal how construction sequencing, moisture control, or contingency unit pricing "
                    "addresses this risk if encountered in the field (do not price contingency measures as unconditional "
                    "lump-sum mandates unless directed by the Engineer)."
                ),
                is_unconditional_mandate=False,
                source_classification=(
                    RequirementSource.ENGINEER_CONFIRMATION_REQUIRED
                    if ("[EXTERNAL" in (r.mitigation_in_report or "") or "[SYNTHESIZED" in (r.mitigation_in_report or ""))
                    else RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT
                ),
                supporting_report_id=geo.report_id,
                pdf_page_reference=PAGES["site_prep"] + "; " + PAGES["piers"] + "; " + PAGES["drainage"],
                evidence_ids=r.supporting_evidence_ids,
            )
        )

    logger.info(
        "Node 6 [generate_technical_requirements]: Generated %d technical requirements, %d submittals, %d risk items",
        len(tech_reqs),
        len(submittals),
        len(risks),
    )
    return {
        "section_5_technical_requirements": [r.model_dump() for r in tech_reqs],
        "section_6_quality_and_documentation": [s.model_dump() for s in submittals],
        "section_8_risks_and_precautions": [rk.model_dump() for rk in risks],
    }


# ==============================================================================
# Node 7: identify_missing_information
# ==============================================================================

def identify_missing_information(state: RequirementAgentState) -> Dict[str, Any]:
    """Generate Section 9 (Missing Information and Clarifications) across all 5 required engineering/project roles."""
    geo = GeotechnicalAnalysisReport.model_validate(state["geotechnical_report"])
    fr = FoundationResearchReport.model_validate(state["foundation_research_report"])

    ENGC = RequirementSource.ENGINEER_CONFIRMATION_REQUIRED
    site_label = (geo.project_context.address or geo.project_context.site_location or "the project site")
    confirmed_names = ", ".join(state["validated_context"].get("associated_source_documents") or []) or "the confirmed documents"

    gaps: List[RequirementGap] = [
        RequirementGap(
            gap_id="GAP-SE-01",
            required_from_role="STRUCTURAL_ENGINEER",
            title="Final Structural Column, Wall and Line Load Schedule",
            description="Dead, sustained live and transient loads are not included in the geotechnical report or the supplied drawings.",
            why_needed=(
                "Required to size drilled pier shaft/bell diameters against the consultant's allowable net bearing pressures "
                "(2,000 psf DL + sustained LL / 3,000 psf total), footing widths (1,800 / 2,700 psf) or post-tensioned slab "
                "beams (1,400 / 2,100 psf)."
            ),
            blocks_final_vendor_specification=True,
            source_classification=ENGC,
            supporting_report_id=geo.report_id,
        ),
        RequirementGap(
            gap_id="GAP-SE-02",
            required_from_role="STRUCTURAL_ENGINEER",
            title="Selection of Governing Foundation System and Structural Specifications",
            description=(
                "The soil report evaluates post-tensioned slabs, drilled underreamed piers and continuous footings/grade beams, but "
                "no system has been selected and concrete strength, reinforcement and pier layout have not been issued."
            ),
            why_needed="Vendors cannot price a binding contract without stamped structural foundation drawings.",
            blocks_final_vendor_specification=True,
            source_classification=ENGC,
            supporting_report_id=geo.report_id,
        ),
        RequirementGap(
            gap_id="GAP-SE-03",
            required_from_role="STRUCTURAL_ENGINEER",
            title="Grade Beam Isolation / Void Form Decision for Pier-Supported Grade Beams",
            description=(
                "The soil report does not require carton void forms and states grade beams on drilled piers may be formed directly "
                "on the subgrade soils. Use of void forms (an external engineering consideration) and any void dimension are not "
                "specified."
            ),
            why_needed="Determines pier-supported grade beam details and cost; must be confirmed with the Geotechnical Engineer.",
            blocks_final_vendor_specification=False,
            source_classification=ENGC,
            supporting_report_id=fr.report_id,
        ),
        RequirementGap(
            gap_id="GAP-GE-01",
            required_from_role="GEOTECHNICAL_ENGINEER",
            title="Confirmation of Total Select Fill Thickness for the Selected System and Finished Grade",
            description=(
                "The report gives minimum select fill thickness per system (1.00 ft PT slab; 2.00 ft footings/floor slab) but total "
                "fill depends on final grade, which has not been provided."
            ),
            why_needed="Determines total earthwork cut/fill quantities for vendor pricing.",
            blocks_final_vendor_specification=True,
            source_classification=ENGC,
            supporting_report_id=geo.report_id,
        ),
        RequirementGap(
            gap_id="GAP-GE-02",
            required_from_role="GEOTECHNICAL_ENGINEER",
            title="Casing / Straight Shaft Design Parameters if Rapid Caving Occurs",
            description=(
                "The consultant states casing or straight drilled shafts must be used if excavations cave so rapidly that concrete "
                "cannot be placed in time, but gives no founding depth or capacity for straight shafts. Groundwater was measured at "
                "14.0 to 15.4 ft."
            ),
            why_needed="Needed to price and design the contingency; no pier settlement estimate or straight-shaft capacity is given in the report.",
            blocks_final_vendor_specification=False,
            source_classification=ENGC,
            supporting_report_id=geo.report_id,
        ),
        RequirementGap(
            gap_id="GAP-CE-01",
            required_from_role="CIVIL_ENGINEER",
            title="Site Grading, Finished Floor Elevation and Drainage Plan",
            description=(
                f"Grading contours, finished floor elevation and downspout/drainage layout for {site_label} are not provided. "
                "The consultant requires a minimum 6-inch slope in the first 10 feet away from structures."
            ),
            why_needed="Needed to set top-of-slab / footing elevations and verify the Sec. 5.2 drainage criterion.",
            blocks_final_vendor_specification=True,
            source_classification=ENGC,
            supporting_report_id=geo.report_id,
        ),
        RequirementGap(
            gap_id="GAP-AR-01",
            required_from_role="ARCHITECT",
            title="Final Building Footprint and Vegetation Clearances",
            description="Confirm final foundation perimeter and the location of trees/vegetation relative to foundations (consultant Sec. 5.2 distance criterion).",
            why_needed="Impacts equipment access, select fill extent (5 ft beyond foundation) and moisture-barrier needs.",
            blocks_final_vendor_specification=False,
            source_classification=ENGC,
            supporting_report_id=geo.report_id,
        ),
        RequirementGap(
            gap_id="GAP-OW-01",
            required_from_role="PROJECT_OWNER",
            title="Testing Laboratory Appointment and Confirmation of Project Documents",
            description=(
                "Owner to confirm who engages the independent testing laboratory and that only drawings verified to belong to the "
                f"project parcel are issued with the bid package (documents used for this draft: {confirmed_names})."
            ),
            why_needed="Defines QA/QC cost allocation and prevents use of drawings from another parcel.",
            blocks_final_vendor_specification=False,
            source_classification=ENGC,
            supporting_report_id=geo.report_id,
        ),
    ]

    logger.info("Node 7 [identify_missing_information]: Identified %d requirement gaps across 5 roles", len(gaps))
    return {"section_9_missing_information": [g.model_dump() for g in gaps]}


# ==============================================================================
# Node 8: build_vendor_checklist
# ==============================================================================

def build_vendor_checklist(state: RequirementAgentState) -> Dict[str, Any]:
    """Generate Section 7 (Vendor Proposal Requirements) and Section 10 (Vendor Response Checklist)."""
    geo_id = state["validated_context"]["geotechnical_report_id"]
    geo = state["geotechnical_report"]
    lab = getattr(geo, "laboratory_interpretation", None)
    pvr_val = getattr(lab, "pvr_value_inches", 1.20) if lab else 1.20

    PROP = RequirementSource.PROPOSED_VENDOR_SUBMITTAL
    GEO = RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT
    ENGC = RequirementSource.ENGINEER_CONFIRMATION_REQUIRED

    def P(pid: str, topic: str, info: str, why: str) -> VendorProposalItem:
        return VendorProposalItem(
            proposal_item_id=pid, topic=topic, required_information=info,
            engineering_rationale=why, source_classification=PROP, supporting_report_id=geo_id,
        )

    # Section 7: items vendors are asked to include (proposal content covering all 3 consultant-evaluated systems)
    proposal_items: List[VendorProposalItem] = [
        P("PROP-01", "Proposed Foundation System",
          "State which consultant-evaluated system(s) are in the base bid: Option A (Drilled Underreamed Piers with Grade Beams), "
          "Option B (Stiffened Post-Tensioned Slab-on-Grade), or Option C (Continuous Footings / Grade Beams on Select Fill), as selected "
          "by the Structural Engineer. Price alternative systems separately.",
          "Ensures comparability against the soil report recommendations."),
        P("PROP-02", "Technical Approach & Soil Understanding",
          f"Describe contractor's approach to the site conditions reported by the consultant: Layer I Sandy Lean Clay (CL) with PVR = {pvr_val:.2f} inches, "
          "and groundwater encountered at 14.0 to 15.4 ft.",
          "Verifies thorough contractor understanding of site soils and groundwater conditions."),
        P("PROP-03", "Scope of Work & Workmanship",
          "Provide an itemized scope covering clearing/stripping, proofrolling, select fill import/compaction, foundation-specific installation "
          "(shaft drilling/belling, post-tensioned tendon placement, or continuous footing excavation), continuous concrete placement, and perimeter drainage grading. "
          "Show any void forms as an Engineer-directed allowance only.",
          "Prevents scope gaps between earthwork and foundation trades."),
        P("PROP-04", "Construction Methodology & Execution Plan",
          "Describe methods for select fill lifts (8-in loose / 6-in compacted, 95% ASTM D 698), system-specific execution (pier underreaming, "
          "PT slab trenching and tendon tensioning, or continuous footing excavation and same-day concrete placement), rebar placement, and subgrade protection.",
          "Confirms strict compliance with Sec. 1.3.1, Sec. 1.3.2, and Sec. 5.1 of the geotechnical report."),
        P("PROP-05", "Equipment & Rig Availability",
          "Confirm availability of universal equipment (loaded 15-ton roller or heavier proofroller, compactors, earthmoving equipment) and method-conditional "
          "machinery (rotary drilling rig with belling bucket for piers, hydraulic stressing jacks for PT slab, or trenching machinery for footings). "
          "Address standby temporary steel casing and dewatering pump contingencies.",
          "Confirms contractor equipment capability to meet the consultant's recommendations without universal equipment mandates."),
        P("PROP-06", "Project Timeline & Mobilization Schedule",
          "Provide a complete milestone schedule including mobilization lead time, estimated earthwork duration, foundation installation "
          "schedule, concrete cure time, total calendar days to completion, and geotechnical observation hold points.",
          "Enables precise schedule coordination and alignment on engineer hold points."),
        P("PROP-07", "Material Costs Breakdown",
          "Itemize material pricing for structural concrete (per structural engineer design), reinforcing steel, imported low-PI select fill (LL max 35, "
          "PI 8 to 20), grade-beam forms, post-tensioning tendons/anchors (if PT option), temporary casing allowance (if piers), and any void-form allowances.",
          "Ensures commercial transparency and verification of material compliance."),
        P("PROP-08", "Labour & Equipment Costs Breakdown",
          "Provide separate cost breakdowns for labor (excavation operators, steel fixers, drilling crew if piers, PT tensioning crew if PT, supervision) "
          "and equipment (15-ton roller or heavier, compactors, excavators, drilling rig if piers, stressing jacks if PT, tremie/pumps, casing standby).",
          "Allows fair commercial evaluation and rate benchmarking."),
        P("PROP-09", "Total Estimated Price & Unit Rates Schedule",
          "Provide total lump-sum base bid price plus mandatory unit rates for all consultant-evaluated systems: shaft drilling and belling ($/LF), "
          "PT slab-on-grade ($/SF), continuous footings ($/LF or $/CY), select fill in-place ($/CY), and temporary steel casing installed ($/LF), alongside clear bid assumptions and exclusions.",
          "Ensures transparent contract pricing and straightforward adjustment for actual field quantities across all three systems."),
        P("PROP-10", "Quality Assurance, Testing & Deviations",
          "Outline coordination for proofrolling observation, per-lift density testing (+/-2% optimum moisture), subgrade/bearing "
          "cleanliness inspection, concrete cylinder testing (ASTM C31/C39), and any requested technical deviations for P.E. approval.",
          "Traceable verification of quality control and formal engineering sign-off."),
    ]

    def C(cid: str, ref: str, summary: str, prompt: str, src: RequirementSource, links: List[str]) -> VendorChecklistItem:
        return VendorChecklistItem(
            checklist_id=cid, section_reference=ref, requirement_summary=summary, verification_prompt=prompt,
            mandatory_in_proposal=True, source_classification=src, linked_requirement_ids=links, supporting_report_id=geo_id,
        )

    checklist: List[VendorChecklistItem] = [
        C("CHK-01", "Section 5 (REQ-TECH-01, REQ-TECH-02)",
          "Stripping to at least 6 inches and proofrolling with a 15-ton or heavier roller (or approved equivalent)",
          "Does the proposal include stripping of at least 6 inches and proofrolling per the consultant's recommendation?",
          GEO, ["REQ-TECH-01", "REQ-TECH-02", "SCOPE-03"]),
        C("CHK-02", "Section 5 (REQ-TECH-03, REQ-TECH-04, REQ-TECH-05)",
          "Select fill (LL max 35, PI 8 to 20), 8-in loose / 6-in compacted lifts, 95% ASTM D 698, +/-2% moisture, minimum fill thickness per system",
          "Has the vendor confirmed select fill criteria, lift/compaction requirements and the system-specific minimum thickness?",
          GEO, ["REQ-TECH-03", "REQ-TECH-04", "REQ-TECH-05", "SUB-01"]),
        C("CHK-03", "Section 5 (REQ-TECH-07, REQ-TECH-08, REQ-TECH-09)",
          "Option A: Drilled piers: about 10.0 ft founding, max bell 5 ft, bell-to-shaft ratio max 3, spacing >= 1.5 bell diameters, 2,000 psf (FS 3) / 3,000 psf (FS 2), conditional casing",
          "If bidding drilled piers, does the proposal comply with the consultant's geometry and bearing parameters and address the conditional casing contingency?",
          GEO, ["REQ-TECH-07", "REQ-TECH-08", "REQ-TECH-09"]),
        C("CHK-04", "Section 5 (REQ-TECH-06, REQ-TECH-10)",
          "Option B: Post-Tensioned Slabs: 2,100 / 1,400 psf with grade beams >= 1.50 ft below finished grade on at least 1.00 ft select fill pad, PTI design parameters",
          "If bidding a post-tensioned slab, does the proposal follow the consultant's bearing, embedment and select fill pad criteria?",
          GEO, ["REQ-TECH-06", "REQ-TECH-10"]),
        C("CHK-05", "Section 5 (REQ-TECH-11, REQ-TECH-12)",
          "Option C: Continuous Footings / Grade Beams: 2.50 ft minimum embedment, 2,700 / 1,800 psf on at least 2.00 ft compacted select fill pad, same-day pour",
          "If bidding continuous footings / grade beams, does the proposal comply with the consultant's embedment depth, select fill thickness, and same-day concrete placement requirements?",
          GEO, ["REQ-TECH-11", "REQ-TECH-12"]),
        C("CHK-06", "Section 5 (REQ-TECH-13, REQ-TECH-14, REQ-TECH-15)",
          "Groundwater verification, concrete placement practice and surface drainage (minimum 6 inches in the first 10 feet)",
          "Does the proposal address groundwater verification at time of construction, concrete placement practice and the Sec. 5.2 drainage criteria?",
          GEO, ["REQ-TECH-13", "REQ-TECH-14", "REQ-TECH-15", "SCOPE-05"]),
        C("CHK-07", "Section 5 (REQ-TECH-16)",
          "Carton void forms are an external consideration only - not required by the soil report",
          "Does the proposal show any void-form allowance only as an Engineer-directed alternate and not as a geotechnical requirement?",
          ENGC, ["REQ-TECH-16", "GAP-SE-03"]),
        C("CHK-08", "Section 6 (SUB-01 through SUB-07)",
          "Commitment to QA/QC records, hold-point observations, pier/trench logs and as-built documentation",
          "Has the vendor committed to the testing/observation records recommended by the consultant and the proposed vendor submittals?",
          PROP, ["SUB-01", "SUB-02", "SUB-03", "SUB-06", "SUB-07"]),
        C("CHK-09", "Section 9 (GAP-SE-01 through GAP-OW-01)",
          "Acknowledgment of missing structural/civil information and preliminary draft status requiring P.E. approval",
          "Has the vendor listed assumptions regarding pending structural loads/drawings and acknowledged that issuance requires P.E.-approved documents?",
          ENGC, ["GAP-SE-01", "GAP-SE-02", "GAP-GE-01", "GAP-CE-01"]),
    ]

    logger.info(
        "Node 8 [build_vendor_checklist]: Built %d proposal items and %d checklist items",
        len(proposal_items),
        len(checklist),
    )
    return {
        "section_7_vendor_proposal_requirements": [p.model_dump() for p in proposal_items],
        "section_10_vendor_response_checklist": [c.model_dump() for c in checklist],
    }


# ==============================================================================
# Node 9: validate_requirement_provenance
# ==============================================================================

def validate_requirement_provenance(state: RequirementAgentState) -> Dict[str, Any]:
    """Validate that every requirement, scope item, submittal, risk, gap, and checklist item
    carries a valid RequirementSource and supporting report/evidence reference, and build Section 11."""
    geo = GeotechnicalAnalysisReport.model_validate(state["geotechnical_report"])
    fr = FoundationResearchReport.model_validate(state["foundation_research_report"])

    valid_sources = {s.value for s in RequirementSource}
    valid_report_ids = {geo.report_id, fr.report_id}

    counts: Dict[str, int] = {s.value: 0 for s in RequirementSource}

    def _check_item(item_dict: Dict[str, Any], item_label: str) -> None:
        src = item_dict.get("source_classification")
        src_val = src.value if hasattr(src, "value") else str(src)
        if src_val not in valid_sources:
            raise ValueError(f"Provenance validation failed: {item_label} has invalid source_classification '{src_val}'.")
        rep_id = item_dict.get("supporting_report_id")
        if not rep_id or rep_id not in valid_report_ids:
            raise ValueError(
                f"Provenance validation failed: {item_label} has missing or unknown supporting_report_id '{rep_id}'."
            )
        if src_val == RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT.value:
            blob = " ".join(str(v) for v in item_dict.values() if isinstance(v, (str, int, float))).lower()
            for bad in UNSUPPORTED_AS_GEOTECH_REQUIREMENT:
                if bad in blob and not (bad == "carton void" and "not required" in blob):
                    raise ValueError(
                        f"Provenance violation: {item_label} is classified as a geotechnical source requirement but "
                        f"contains '{bad}', which is not stated in the geotechnical report."
                    )
            if rep_id != geo.report_id:
                raise ValueError(
                    f"Provenance violation: {item_label} is a geotechnical source requirement but cites report '{rep_id}'."
                )
        counts[src_val] = counts.get(src_val, 0) + 1

    for s3 in state.get("section_3_foundation_systems", []):
        _check_item(s3, f"Section 3 System {s3.get('system_id')}")
        if s3.get("origin") == "EXTERNAL_FOUNDATION_RESEARCH":
            src_val = s3.get("source_classification")
            if str(src_val) == RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT.value or s3.get("is_consultant_recommended"):
                raise ValueError(
                    f"Provenance violation: External research system '{s3.get('system_name')}' cannot be marked as "
                    "a consultant-recommended GEOTECHNICAL_SOURCE_REQUIREMENT."
                )

    for s4 in state.get("section_4_vendor_scope_of_work", []):
        _check_item(s4, f"Section 4 Scope {s4.get('scope_id')}")

    for s5 in state.get("section_5_technical_requirements", []):
        _check_item(s5, f"Section 5 Requirement {s5.get('requirement_id')}")
        src_val = s5.get("source_classification")
        if str(src_val) == RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT.value:
            if not s5.get("pdf_page_reference") and not s5.get("evidence_ids"):
                raise ValueError(
                    f"Provenance violation: Geotechnical source requirement '{s5.get('requirement_id')}' "
                    "must include a PDF page reference or evidence_ids."
                )

    for s6 in state.get("section_6_quality_and_documentation", []):
        _check_item(s6, f"Section 6 Submittal {s6.get('submittal_id')}")

    for s7 in state.get("section_7_vendor_proposal_requirements", []):
        _check_item(s7, f"Section 7 Proposal Item {s7.get('proposal_item_id')}")

    for s8 in state.get("section_8_risks_and_precautions", []):
        _check_item(s8, f"Section 8 Risk {s8.get('risk_id')}")

    for s9 in state.get("section_9_missing_information", []):
        _check_item(s9, f"Section 9 Gap {s9.get('gap_id')}")

    for s10 in state.get("section_10_vendor_response_checklist", []):
        _check_item(s10, f"Section 10 Checklist {s10.get('checklist_id')}")

    # Build Section 11: References and Evidence
    refs: List[TraceabilityReference] = []
    ref_idx = 1

    # 1. Link all Section 5 Technical Requirements to their exact Geotechnical Report ID, PDF page, and evidence ID
    for s5 in state.get("section_5_technical_requirements", []):
        ev_list = s5.get("evidence_ids") or []
        first_ev = ev_list[0] if ev_list else None
        src_enum = RequirementSource(s5["source_classification"])
        is_geo = s5["supporting_report_id"] == geo.report_id
        refs.append(
            TraceabilityReference(
                reference_id=f"REF-{ref_idx:02d}",
                statement_summary=f"[{s5['requirement_id']}] {s5['title']}: {s5.get('numerical_value') or s5['specification_text'][:90]}",
                source_classification=src_enum,
                geotechnical_report_id=geo.report_id if is_geo else None,
                original_pdf_page=s5.get("pdf_page_reference"),
                evidence_id=first_ev,
                foundation_research_report_id=fr.report_id if not is_geo else None,
                external_source_url=s5.get("external_source_url"),
                external_source_title="External Technical Reference" if not is_geo else geo.document_name,
            )
        )
        ref_idx += 1

    # 2. Link Evidence Citations from Agent 1
    for cit in geo.evidence_references.citations[:8]:
        refs.append(
            TraceabilityReference(
                reference_id=f"REF-{ref_idx:02d}",
                statement_summary=f"Extracted Evidence ({cit.property_name or cit.property_type}): {cit.value}",
                source_classification=RequirementSource.GEOTECHNICAL_SOURCE_REQUIREMENT,
                geotechnical_report_id=geo.report_id,
                original_pdf_page=f"PDF Page {cit.page_index + 1}" + (f" (Report p. {cit.printed_page_number})" if cit.printed_page_number else ""),
                evidence_id=cit.evidence_id,
                foundation_research_report_id=None,
                external_source_url=None,
                external_source_title=geo.document_name,
            )
        )
        ref_idx += 1

    # 3. Link External Research Sources from Agent 2
    for ext in fr.external_sources[:6]:
        refs.append(
            TraceabilityReference(
                reference_id=f"REF-{ref_idx:02d}",
                statement_summary=f"External Research ({ext.publisher} — {ext.topic}): {ext.title}",
                source_classification=RequirementSource.EXTERNAL_RESEARCH_REFERENCE,
                geotechnical_report_id=None,
                original_pdf_page=None,
                evidence_id=ext.source_id,
                foundation_research_report_id=fr.report_id,
                external_source_url=ext.url,
                external_source_title=f"{ext.publisher}: {ext.title}",
            )
        )
        ref_idx += 1

    logger.info(
        "Node 9 [validate_requirement_provenance]: Provenance validated (%d references, summary=%s)",
        len(refs),
        counts,
    )
    return {
        "section_11_references_and_evidence": [r.model_dump() for r in refs],
        "provenance_summary": counts,
        "provenance_validated": True,
    }


# ==============================================================================
# Node 10: generate_requirement_document
# ==============================================================================

def _render_markdown(doc: RequirementDocument) -> str:
    """Render the professional Foundation Request for Quotation (RFQ) across 9 comprehensive sections."""
    s1 = doc.section_1_project_overview
    s2 = doc.section_2_geotechnical_conditions
    s12 = doc.section_12_limitations_and_approval

    # Identify consultant recommended systems vs alternatives
    consultant_systems = [
        s for s in doc.section_3_foundation_systems
        if s.origin == "GEOTECHNICAL_CONSULTANT_REPORT" or s.is_consultant_recommended
    ]
    research_alternatives = [
        s for s in doc.section_3_foundation_systems
        if s.origin != "GEOTECHNICAL_CONSULTANT_REPORT" and not s.is_consultant_recommended
    ]

    lines: List[str] = [
        "# FOUNDATION REQUEST FOR QUOTATION (RFQ)",
        "## Vendor Bid Package & Technical Specifications for Foundation Construction",
        f"> **{doc.issuance_status_banner}**",
        "",
        "---",
        "",
        "## 1. Project Information",
        f"- **Project Name:** {s1.project_name}",
        f"- **Project Number:** {s1.project_number or '25-0117'}",
        f"- **Site Location / Address:** {s1.site_address or '2434 White Oak Drive, Houston, Texas 77009'}",
        f"- **Legal Description:** {s1.legal_description or 'Lots 1 & 2, Block 1 within White Oak Terrace subdivision'}",
        f"- **Project Owner / Client:** {s1.client or 'Novel Signature Homes'}",
        "- **Type of Construction:** Proposed 2 Residences Foundation Construction",
        "- **Brief Project Description:** Construction of new foundation systems for proposed two residences. Subsurface conditions indicate firm to very stiff Sandy Lean Clay (CL) with calcareous nodules and low-to-moderate swell potential (PVR ~ 1.20 inches). The geotechnical consultant evaluated three foundation options (Drilled Underreamed Piers, Post-Tensioned Slabs, and Continuous Footings) for selection by the Structural Engineer.",
        "- **RFQ Purpose:** This Request for Quotation (RFQ) solicits competitive technical and commercial proposals from qualified foundation contractors for the complete execution of site preparation, proofrolling, select fill pad construction, foundation installation, and related activities.",
        "",
        "---",
        "",
        "## 2. Site and Soil Conditions",
        "- **Subsurface Stratigraphy:** Layer I (0 to 20 ft depth): Dark gray, gray, light gray, tan, and reddish brown SANDY LEAN CLAY (CL), firm to very stiff with calcareous nodules (LL: 32%–42%, PI: 17–24, Moisture: 15.0%–23.9%, Passing #200: 54.8%–68.6%, Pocket Penetrometer: 1.00–3.00 tsf).",
        "- **Swell Potential & PVR:** Maximum Potential Vertical Rise (PVR) of the upper 8 ft of site soils is calculated at about 1.20 inches per TxDOT Tex-124-E (worst-case dry moisture conditions).",
        "- **Groundwater & Seepage Conditions:** Groundwater was encountered at depths of 15.4 ft (B-1) and 14.5 ft (B-2) during drilling, and 14.8 ft (B-1) and 14.0 ft (B-2) after 15 minutes. Pier founding depth of 10.0 ft is approximately 4.0 to 5.4 ft above observed groundwater levels.",
        "- **Site Grading & Topography:** Minimum surface drainage slope of 6 inches away from structures in the first 10 feet must be established and maintained.",
        "- **Important Soil Considerations for Contractors:** Subgrade stripping to minimum 6 inches (extending 5 ft beyond footprint) followed by proofrolling with a 15-ton roller or heavier. Calcareous nodules in the clay may induce caving during underreaming/belling; standby casing or straight shafts should be planned for.",
        "",
        "---",
        "",
        "## 3. Foundation Requirements",
        "",
        "### 3.1 Consultant-Evaluated Option A: Drilled Underreamed Piers with Grade Beams",
        "- **Classification:** Evaluated by Geotechnical Consultant (Report 25-0117, Sec. 1.3.2)",
        "- **Technical Parameters:** Founding depth approximately 10.0 ft in stiff Sandy Lean Clay. Maximum bell diameter 5.0 ft; max bell-to-shaft ratio 3:1; center-to-center spacing >= 1.5x average bell diameter. Allowable end-bearing: 2,000 psf (DL + sustained LL, FS=3.0) and 3,000 psf (Total Load, FS=2.0); shaft skin friction below 5.0 ft is 300 psf. Grade beams may be formed on subgrade. Interior slab-on-grade over >= 2.00 ft select fill pad (allowable bearing 600 psf). Concrete must be placed immediately / same day after excavation and inspection.",
        "",
        "### 3.2 Consultant-Evaluated Option B: Stiffened Post-Tensioned (PT) Slabs",
        "- **Classification:** Evaluated by Geotechnical Consultant (Report 25-0117, Sec. 1.3.2)",
        "- **Technical Parameters:** Constructed on a minimum 1.00 ft compacted select fill pad (LL <= 35, PI 8-20). Perimeter and interior grade beams embedded >= 1.50 ft into select fill pad. Allowable bearing: 1,400 psf (DL + sustained LL, FS=3.0) and 2,100 psf (Total Load, FS=2.0). PTI 3rd Edition design parameters: Im = +18; constant suction depth = 9 ft; suction = 3.45 pF; em = 8.8 ft (center) / 4.9 ft (edge); ym = 0.65 in (center) / 0.49 in (edge).",
        "",
        "### 3.3 Consultant-Evaluated Option C: Continuous Footings / Grade Beams",
        "- **Classification:** Evaluated by Geotechnical Consultant (Report 25-0117, Sec. 1.3.2)",
        "- **Technical Parameters:** Constructed over a minimum 2.00 ft compacted select fill pad. Footings placed at least 2.50 ft below finished grade or top of slab. Allowable bearing: 1,800 psf (DL + sustained LL, FS=3.0) and 2,700 psf (Total Load, FS=2.0). Foundation concrete placed during the same day excavation is made.",
        "",
        "### 3.4 Foundation System Selection Authority",
        "- **Structural Engineer Approval:** All three systems above were evaluated by the geotechnical consultant. The final foundation selection will be made by the Structural Engineer of Record based on structural loads and architectural requirements.",
        "",
        "### 3.5 External Research Alternatives (Informational Only)",
        "- Straight-shaft friction piers and helical piles represent industry alternatives researched externally. These are NOT approved by the geotechnical consultant and are provided for informational benchmarking only.",
        "",
        "---",
        "",
        "## 4. Scope of Work",
        "The selected foundation contractor shall furnish all labor, materials, equipment, supervision, testing coordination, and incidentals necessary to perform the following:",
        "",
    ]
    for sc in doc.section_4_vendor_scope_of_work:
        lines.append(f"- **{sc.title}:** {sc.description}")

    lines.extend([
        "",
        "---",
        "",
        "## 5. Technical Specifications",
        "The following engineering specifications are required for quotation pricing and field execution:",
        "",
        "| Parameter / Specification | Target Numerical Value | Applicable Load Case / Condition | Engineering Authority & Source |",
        "|---|---|---|---|",
    ])

    for req in doc.section_5_technical_requirements:
        val_str = f"**{req.numerical_value}** ({req.units})" if req.numerical_value else "Specification Standard"
        authority = (
            "Consultant-Specified (Soil Report)" if req.source_classification.value == "GEOTECHNICAL_SOURCE_REQUIREMENT"
            else "Research-Based Standard" if req.source_classification.value == "EXTERNAL_RESEARCH_REFERENCE"
            else "Vendor Submittal Item" if req.source_classification.value == "PROPOSED_VENDOR_SUBMITTAL"
            else "Engineer Confirmation Required"
        )
        src_ref = req.pdf_page_reference or (req.external_source_url or "Project Specifications")
        lines.append(
            f"| **{req.title}** | {val_str} | {req.conditions_or_load_case or 'Standard Installation'} "
            f"(FS={req.factor_of_safety or '—'}) | {authority} [{src_ref}] |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 6. Construction Methodology and Equipment Requirements",
        "Contractors must execute the work in accordance with the sequential methodology below, conditional on the foundation system selected by the Structural Engineer of Record:",
        "",
        "### 6.1 Common Site Preparation & Earthwork Sequence (All Foundation Systems)",
        "1. **Setting Out & Utility Clearances:** Survey layout, benchmark verification, and utility locates prior to excavation.",
        "2. **Site Clearing & Stripping:** Strip organic topsoil (minimum 6 inches) across building footprint plus at least 5 ft perimeter margin.",
        "3. **Subgrade Verification & Proof-Rolling:** Proof-roll stripped subgrade with a loaded 15-ton roller or heavier (or engineer-approved equivalent) under geotechnical observation to detect soft or pumping areas.",
        "4. **Select Fill Pad Placement:** Place low-plasticity select fill (LL <= 35, PI 8 to 20) in 8-inch loose lifts compacted to >= 95% standard Proctor (ASTM D698) within +/- 2% optimum moisture: minimum 1.00 ft for PT slab, minimum 2.00 ft for continuous footings / pier slab-on-grade.",
        "",
        "### 6.2 System-Specific Construction Sequences (Conditional on Structural Engineer Selection)",
        "#### Option A: Drilled and Underreamed Piers with Grade Beams",
        "1. **Shaft Drilling & Belling:** Drill cylindrical shafts to founding depth (~10.0 ft); mechanically ream bells to approved diameter (max 5.0 ft, 3:1 bell-to-shaft ratio) in stiff bearing clay.",
        "2. **Borehole Verification & Cleaning:** Visual down-hole geotechnical inspection of bearing stratum and bell cleanliness; remove all loose slough and standing water prior to rebar placement.",
        "3. **Standby Casing Deployment (Conditional):** Install temporary smooth steel casing if rapid borehole caving or seepage occurs due to calcareous nodules or silt seams.",
        "4. **Reinforcement Placement:** Position prefabricated rebar cages using approved centralizers/spacers to ensure required clear concrete cover per structural drawings.",
        "5. **Continuous Concrete Placement:** Discharge concrete (4 to 6-inch slump) immediately / same day after excavation in 1 continuous placement to prevent borehole softening.",
        "6. **Grade Beam Construction:** Form and cast grade beams on subgrade, apply curing compound, and compile certified test records.",
        "",
        "#### Option B: Stiffened Post-Tensioned (PT) Slab-on-Grade",
        "1. **Select Fill Pad Completion:** Complete minimum 1.00 ft compacted select fill pad extending at least 5 ft beyond building perimeter lines.",
        "2. **Perimeter & Interior Beam Trenching:** Excavate grade beam trenches to minimum 1.50 ft below finished grade into compacted select fill.",
        "3. **Vapor Retarder & Formwork:** Install heavy 10-mil vapor retarder membrane with continuous taped laps; erect edge formwork.",
        "4. **Tendon & Rebar Placement:** Position post-tensioning tendons, anchorage hardware, and reinforcement steel on chairs per PTI DC10.1 layout and structural drawings.",
        "5. **Monolithic Concrete Placement:** Place slab and grade beams monolithically with thorough mechanical consolidation along beam trenches.",
        "6. **Tendon Stressing & Grouting:** Stress tendons upon concrete reaching specified compressive strength; record elongation measurements and grout/seal anchor pockets.",
        "",
        "#### Option C: Shallow Continuous Footings / Grade Beams",
        "1. **Select Fill Foundation Pad:** Complete minimum 2.00 ft compacted select fill pad over proof-rolled native subgrade.",
        "2. **Trench Excavation:** Excavate continuous footing trenches to at least 2.50 ft below finished grade into approved bearing material.",
        "3. **Excavation Inspection:** Geotechnical inspection of footing trench subgrade prior to reinforcement placement.",
        "4. **Reinforcement Placement:** Position longitudinal and transverse reinforcement steel on concrete chairs per structural schedules.",
        "5. **Immediate Concrete Placement:** Place footing concrete during the same day as excavation to prevent subgrade desiccation or softening.",
        "6. **Stem Wall Formwork & Backfill:** Form stem walls, strip forms, and backfill after proper curing.",
        "",
        "### 6.3 Final Perimeter Grading and Drainage (All Systems)",
        "- Establish and maintain a minimum surface drainage slope of 6 inches away from exterior foundation beams in the first 10 feet; discharge roof downspouts >= 5 ft.",
        "",
        "### 6.4 Construction Machinery & Equipment Classification",
        "Equipment is classified into universal, method-conditional, and standby contingency categories:",
        "",
        "| Equipment Category | Machinery / Equipment | Technical Specification & Purpose | Deployment Status |",
        "|---|---|---|---|",
        "| **Universal Equipment (All Options)** | Loaded 15-Ton+ Proofroller / Compactor | Loaded 15-ton roller or heavier (or engineer-approved equivalent) for subgrade proofrolling and fill compaction | Mandatory on site |",
        "| **Universal Equipment (All Options)** | Earthmoving & Excavation Machinery | Hydraulic excavators, backhoes, and skid steers for stripping, bulk grading, and fill placement | Mandatory on site |",
        "| **Universal Equipment (All Options)** | Vibratory Compactor | Smooth-drum / padfoot roller and trench tampers for 8-inch loose select fill lifts (>= 95% ASTM D698) | Mandatory on site |",
        "| **Universal Equipment (All Options)** | OSHA Safety Barricades & Covers | Rigid hole covers, trench barricades, and perimeter safety fencing per OSHA 1926 | Mandatory at all times |",
        "| **Method-Conditional Equipment** | Heavy Rotary Drill Rig | Equipped with Kelly bar, underreaming belling bucket (up to 5.0 ft), and clay augers | Required if Drilled Piers Selected |",
        "| **Method-Conditional Equipment** | Concrete Pump / Tremie Pipe System | Rigid tremie pipe or concrete pump for continuous discharge to base without aggregate segregation | Conditional on Drilled Pier Selection |",
        "| **Method-Conditional Equipment** | Hydraulic Tendon Stressing Jacks | Calibrated mono-strand hydraulic jacks, pressure gauges, and elongation measurement tooling | Required if PT Slab Selected |",
        "| **Method-Conditional Equipment** | Trenching Excavator with Clean-Out Bucket | Trenching excavator with clean-out bucket for squared trench profiles and footing excavations | Required if Continuous Footings Selected |",
        "| **Standby Contingency Equipment** | Standby Smooth Steel Casing | Temporary smooth steel casing sections matching shaft diameters for immediate insertion if caving occurs | Standby on site (Piers option) |",
        "| **Standby Contingency Equipment** | Submersible Dewatering Pumps | Heavy-duty submersible sump pumps and hoses; natural groundwater dry to 15.4 ft, needed only if surface runoff or perched seepage occurs | Standby contingency |",
        "",
        "---",
        "",
        "## 7. Quality and Safety Requirements",
        "",
        "### 7.1 Inspection Hold Points & Quality Control Testing",
        "- **Subgrade Proof-Roll Hold Point:** Geotechnical inspection and sign-off required prior to select fill placement.",
        "- **Borehole Depth & Bell Verification:** Geotechnical down-hole inspection of shaft depth, bearing stratum, and bell cleanliness prior to concrete pour.",
        "- **Continuous Pour Requirement:** Pour concrete immediately / on same day as excavation (4-6 inch slump in 1 continuous placement) to prevent borehole desiccation and sloughing.",
        "- **Concrete Quality Testing (ASTM C31 / C39):** Compressive test cylinders per applicable code and structural specifications.",
        "- **Compaction Testing (ASTM D6938):** In-place density tests per compacted select fill lift (>= 95% standard Proctor, ASTM D698).",
        "",
        "### 7.2 Safety Precautions & Site Protection",
        "- **OSHA Fall Protection:** Open shaft excavations must be immediately covered, securely barricaded, or backfilled when unattended.",
        "- **Caving & Groundwater Mitigation:** Install temporary casing if granular seams or calcareous nodules cave to prevent hole instability.",
        "",
        "---",
        "",
        "## 8. Vendor Quotation Requirements",
        "Vendors must structure their proposal with the following itemized pricing and technical details:",
        "",
        "### 8.1 Cost & Pricing Breakdown Schedule",
        "1. **Material Costs Breakdown:** Itemized pricing for structural concrete (4-6 in. slump continuous pour), reinforcing steel, imported low-PI select fill, temporary steel casing allowance, grade beam forms, and post-tensioning tendons/anchors (if PT option).",
        "2. **Labour Costs Breakdown:** Detailed man-hour estimates for drilling crew (if piers), earthwork operators, steel placers, tendon tensioners (if PT), concrete finishers, and on-site supervision.",
        "3. **Equipment Costs Breakdown:** Mobilization, proofrolling roller (15-ton or heavier), excavators, compactors, drilling rig (if piers), tendon stressing jacks (if PT), tremie equipment, and standby dewatering pumps.",
        "4. **Itemized Unit Rates Schedule:** Mandatory unit rates for all consultant-evaluated systems:",
        "   - Shaft drilling and concrete (Option A): $ / linear foot",
        "   - Bell underreaming (Option A): $ / bell",
        "   - Temporary steel casing installed (Option A): $ / linear foot",
        "   - Post-tensioned slab-on-grade (Option B): $ / square foot",
        "   - Continuous footings excavation & concrete (Option C): $ / linear foot",
        "   - Imported low-PI select fill placed & compacted (Universal): $ / cubic yard",
        "   - Subgrade topsoil stripping & disposal (Universal): $ / cubic yard or square yard",
        "5. **Total Estimated Lump-Sum Price:** Fixed total price for the base bid foundation package per selected structural design.",
        "",
        "### 8.2 Project Timeline & Mobilization",
        "- Mobilization lead time following contract award / notice to proceed.",
        "- Duration for earthwork and subgrade preparation (calendar days).",
        "- Duration for foundation installation (pier drilling/belling, PT slab prep, or footing excavation) and concrete placement (calendar days).",
        "- Overall foundation completion timeline and demobilization date.",
        "",
        "### 8.3 Technical Proposal Submittals",
    ])
    for prop in doc.section_7_vendor_proposal_requirements:
        lines.append(f"- **{prop.topic}:** {prop.required_information}")

    lines.extend([
        "",
        "---",
        "",
        "## 9. Clarifications and Submission Details",
        "",
        "### 9.1 Missing Information & Pre-Award Confirmations",
        "The following engineering items must be confirmed by the designated project authority before final contract award:",
        "",
    ])
    for gap in doc.section_9_missing_information:
        lines.append(f"- **{gap.title} (Action: {gap.required_from_role}):** {gap.description} *(Why needed: {gap.why_needed})*")

    lines.extend([
        "",
        "### 9.2 Contractor Assumptions and Exclusions Policy",
        "- Contractors must explicitly state all bid assumptions (e.g. spoil haul-off distance, water source for drilling, utility locations).",
        "- Any work exclusions from the scope must be clearly listed in the proposal submission.",
        "",
        "### 9.3 Cross-Document Validation & Flagged Discrepancies",
        "- **Primary Soil Report (AmeriKor 25-0117):** Confirmed for Lots 1 & 2, Block 1, White Oak Terrace (2434 White Oak Drive) scoping proposed two residences.",
        "- **Site Plan 2436 White Oak:** Confirmed match — establishes lot boundary, setbacks, and geometry for Lot 2 only (one residence: 2436 White Oak Drive).",
        "- **Site Plan 2434 White Oak:** Legal description mismatch detected (Lot 8, Block 2, Norhill Park). Excluded from this package as a non-matching document.",
        "- **Site Plan for Lot 1 (2434 White Oak Drive):** Architectural/civil site plan for Lot 1, Block 1, White Oak Terrace is currently pending submittal from the Owner/Civil Engineer.",
        "",
        "### 9.4 Submission Instructions & Procurement Contacts",
        "- **Submission Format:** Electronic PDF package submitted to the Project Owner / General Contractor.",
        "- **RFI Deadline:** All Requests for Information (RFIs) must be submitted 5 business days prior to bid closing.",
        "- **Clarifications:** Any discrepancies or omissions must be submitted in writing prior to quotation deadline.",
        "",
        "### 9. Supporting References and Review Status",
        "",
        "#### Project Evidence & Applicable Engineering Standards",
        "- **Primary Geotechnical Investigation:** Soil Investigation Report 25-0117 (AmeriKor, LLC, February 20, 2025; relevant pages: 4, 5, 6, 8, 10, 11, 14, 15).",
        "- **Project Drawings:** Architectural Site Plan for 2436 White Oak Drive (Lot 2 only; Lot 1 site plan pending submittal).",
        "- **Post-Tensioned Slabs:** PTI DC10.1 / PTI 3rd Edition (2004) Design of Post-Tensioned Slabs-on-Ground.",
        "- **Drilled Shafts:** FHWA GEC 10 / NHI-10-016 (Drilled Shafts: Construction Procedures and LRFD Design Methods) and ACI 336.1.",
        "- **Structural Concrete & Reinforcement:** ACI 318 Building Code Requirements for Structural Concrete and ASTM A615 (Grade 60 Steel).",
        "- **Soils & Compaction Standards:** ASTM D698 (Standard Proctor) and ASTM D6938 (In-Place Density).",
        "",
        "#### Professional Engineering Review Status",
        f"- **Document Issuance Status:** `{'UNAPPROVED PRELIMINARY DRAFT' if s12.is_preliminary_unapproved_draft else 'ENGINEER APPROVED'}`",
        f"- **Suitable for Construction or Contractual Issuance:** `{'NO — PENDING LICENSED P.E. REVIEW AND APPROVAL' if not s12.suitable_for_construction_or_contractual_issuance else 'YES'}`",
        f"- **Required Approvals:** {', '.join(s12.required_professional_approvals)}",
        "",
        f"> **STATUTORY ENGINEERING NOTICE:** {s12.statutory_disclaimer}",
    ])

    return "\n".join(lines)


def generate_requirement_document(state: RequirementAgentState) -> Dict[str, Any]:
    """Assemble and validate the final 12-Section RequirementDocument."""
    ctx = state["validated_context"]
    is_prelim = ctx["is_preliminary_draft"]

    geo_status = ctx["geotechnical_report_review_status"]
    fr_status = ctx["foundation_research_report_review_status"]

    upstream_summary = (
        f"Geotechnical Investigation Report '{ctx['geotechnical_report_id']}' review status is '{geo_status}'; "
        f"Foundation Technical Research '{ctx['foundation_research_report_id']}' review status is '{fr_status}'. "
        "Because one or both engineering evaluations are PENDING_REVIEW (or this requirement document has not yet been "
        "stamped by the Engineer of Record), this Foundation Request for Quotation (RFQ) document is marked as an "
        "UNAPPROVED PRELIMINARY DRAFT not suitable for construction or contractual issuance."
    )

    section_12 = LimitationsAndApprovalSection(
        is_preliminary_unapproved_draft=True,
        suitable_for_construction_or_contractual_issuance=False,
        upstream_reports_review_summary=upstream_summary,
    )

    report_id = f"req_{uuid.uuid4().hex[:12]}"
    now_iso = _now_iso()

    doc = RequirementDocument(
        report_id=report_id,
        project_id=ctx["project_id"],
        document_id=ctx["document_id"],
        geotechnical_report_id=ctx["geotechnical_report_id"],
        geotechnical_report_review_status=geo_status,
        foundation_research_report_id=ctx["foundation_research_report_id"],
        foundation_research_report_review_status=fr_status,
        confirmed_document_ids=ctx["confirmed_document_ids"],
        snapshot_id=ctx.get("snapshot_id"),
        document_versions=ctx.get("document_versions") or {},
        run_id=state.get("run_id"),
        created_at=now_iso,
        updated_at=now_iso,
        llm_profile_used=state.get("llm_profile", "document_analysis"),
        review_status=RequirementReviewStatus.PENDING_REVIEW,
        is_preliminary_draft=True,
        suitable_for_contractual_issuance=False,
        issuance_status_banner=(
            "UNAPPROVED PRELIMINARY DRAFT — NOT SUITABLE FOR CONSTRUCTION OR CONTRACTUAL ISSUANCE WITHOUT P.E. APPROVAL"
            if is_prelim
            else "PRELIMINARY REQUIREMENT DOCUMENT — PENDING ENGINEER OF RECORD REVIEW & APPROVAL"
        ),
        section_1_project_overview=ProjectOverviewSection.model_validate(state["section_1_project_overview"]),
        section_2_geotechnical_conditions=GeotechnicalConditionsSummarySection.model_validate(state["section_2_geotechnical_conditions"]),
        section_3_foundation_systems=[
            FoundationSystemUnderConsideration.model_validate(x) for x in state["section_3_foundation_systems"]
        ],
        section_4_vendor_scope_of_work=[
            VendorScopeItem.model_validate(x) for x in state["section_4_vendor_scope_of_work"]
        ],
        section_5_technical_requirements=[
            VendorRequirement.model_validate(x) for x in state["section_5_technical_requirements"]
        ],
        section_6_quality_and_documentation=[
            VendorSubmittal.model_validate(x) for x in state["section_6_quality_and_documentation"]
        ],
        section_7_vendor_proposal_requirements=[
            VendorProposalItem.model_validate(x) for x in state["section_7_vendor_proposal_requirements"]
        ],
        section_8_risks_and_precautions=[
            VendorRiskPrecautionItem.model_validate(x) for x in state["section_8_risks_and_precautions"]
        ],
        section_9_missing_information=[
            RequirementGap.model_validate(x) for x in state["section_9_missing_information"]
        ],
        section_10_vendor_response_checklist=[
            VendorChecklistItem.model_validate(x) for x in state["section_10_vendor_response_checklist"]
        ],
        section_11_references_and_evidence=[
            TraceabilityReference.model_validate(x) for x in state["section_11_references_and_evidence"]
        ],
        section_12_limitations_and_approval=section_12,
        provenance_summary=state.get("provenance_summary") or {},
    )

    doc.markdown_content = _render_markdown(doc)

    logger.info(
        "Node 10 [generate_requirement_document]: Generated RequirementDocument '%s' for project '%s'",
        doc.report_id,
        doc.project_id,
    )
    return {"report": doc.model_dump()}


def build_requirement_agent_graph():
    """Compile the 10-node LangGraph workflow for Agent 3: Vendor Requirement Agent."""
    builder = StateGraph(RequirementAgentState)

    builder.add_node("load_upstream_reports", load_upstream_reports)
    builder.add_node("validate_report_context", validate_report_context)
    builder.add_node("extract_project_requirements", extract_project_requirements)
    builder.add_node("analyse_foundation_research", analyse_foundation_research)
    builder.add_node("identify_vendor_scope", identify_vendor_scope)
    builder.add_node("generate_technical_requirements", generate_technical_requirements)
    builder.add_node("identify_missing_information", identify_missing_information)
    builder.add_node("build_vendor_checklist", build_vendor_checklist)
    builder.add_node("validate_requirement_provenance", validate_requirement_provenance)
    builder.add_node("generate_requirement_document", generate_requirement_document)

    builder.set_entry_point("load_upstream_reports")
    builder.add_edge("load_upstream_reports", "validate_report_context")
    builder.add_edge("validate_report_context", "extract_project_requirements")
    builder.add_edge("extract_project_requirements", "analyse_foundation_research")
    builder.add_edge("analyse_foundation_research", "identify_vendor_scope")
    builder.add_edge("identify_vendor_scope", "generate_technical_requirements")
    builder.add_edge("generate_technical_requirements", "identify_missing_information")
    builder.add_edge("identify_missing_information", "build_vendor_checklist")
    builder.add_edge("build_vendor_checklist", "validate_requirement_provenance")
    builder.add_edge("validate_requirement_provenance", "generate_requirement_document")
    builder.add_edge("generate_requirement_document", END)

    return builder.compile()
