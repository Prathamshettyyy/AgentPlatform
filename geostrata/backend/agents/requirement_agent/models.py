from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RequirementSource(str, Enum):
    """Mandatory provenance classification for every vendor requirement, scope item, and submittal."""
    GEOTECHNICAL_SOURCE_REQUIREMENT = "GEOTECHNICAL_SOURCE_REQUIREMENT"
    EXTERNAL_RESEARCH_REFERENCE = "EXTERNAL_RESEARCH_REFERENCE"
    PROPOSED_VENDOR_SUBMITTAL = "PROPOSED_VENDOR_SUBMITTAL"
    AI_DRAFTED_SCOPE = "AI_DRAFTED_SCOPE"
    ENGINEER_CONFIRMATION_REQUIRED = "ENGINEER_CONFIRMATION_REQUIRED"


class RequirementCategory(str, Enum):
    """Engineering categories for project-specific technical requirements."""
    SELECT_FILL_CRITERIA = "SELECT_FILL_CRITERIA"
    COMPACTION_REQUIREMENTS = "COMPACTION_REQUIREMENTS"
    PROOFROLLING_REQUIREMENTS = "PROOFROLLING_REQUIREMENTS"
    FOUNDATION_BEARING_PARAMETERS = "FOUNDATION_BEARING_PARAMETERS"
    FOUNDATION_EMBEDMENT_REQUIREMENTS = "FOUNDATION_EMBEDMENT_REQUIREMENTS"
    PIER_CONSTRUCTION_PRECAUTIONS = "PIER_CONSTRUCTION_PRECAUTIONS"
    GROUNDWATER_CONSIDERATIONS = "GROUNDWATER_CONSIDERATIONS"
    SITE_DRAINAGE_REQUIREMENTS = "SITE_DRAINAGE_REQUIREMENTS"
    CONSTRUCTION_PRECAUTIONS = "CONSTRUCTION_PRECAUTIONS"
    QUALITY_AND_DOCUMENTATION = "QUALITY_AND_DOCUMENTATION"


class RequirementReviewStatus(str, Enum):
    """Review status for Vendor Foundation Requirement Documents."""
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class RequirementReview(BaseModel):
    """Audit record for human engineering review of a RequirementDocument."""
    model_config = ConfigDict(extra="ignore")

    review_id: str
    report_id: str
    reviewer: str
    decision: RequirementReviewStatus
    reviewed_at: str = Field(default_factory=_now_iso)
    notes: Optional[str] = None


# ==============================================================================
# Section 1 — Project Overview
# ==============================================================================

class ProjectOverviewSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_name: str
    project_number: Optional[str] = None
    site_address: Optional[str] = None
    legal_description: Optional[str] = None
    client: Optional[str] = None
    geotechnical_consultant: Optional[str] = None
    associated_source_documents: List[str] = Field(default_factory=list)
    confirmed_document_ids: List[str] = Field(default_factory=list)
    document_snapshot_id: Optional[str] = None
    document_versions: Dict[str, str] = Field(default_factory=dict)
    report_generation_date: str = Field(default_factory=_now_iso)
    geotechnical_report_id: str
    geotechnical_report_review_status: str = "PENDING_REVIEW"
    foundation_research_report_id: str
    foundation_research_report_review_status: str = "PENDING_REVIEW"


# ==============================================================================
# Section 2 — Project and Geotechnical Conditions
# ==============================================================================

class GeotechnicalConditionsSummarySection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dominant_soil_description: str
    uscs_classification: str
    boring_summary: str
    laboratory_properties_summary: str
    liquid_limit_range: str
    plasticity_index_range: str
    moisture_content_range: str
    passing_no_200_range: str
    pocket_penetrometer_range_tsf: str
    spt_status: str
    groundwater_summary: str
    groundwater_depth_range_ft: str
    pvr_value_inches: float
    shrink_swell_potential: str
    pvr_implications_for_vendors: str
    site_conditions_and_constraints: List[str] = Field(default_factory=list)
    supporting_report_id: str
    evidence_ids: List[str] = Field(default_factory=list)


# ==============================================================================
# Section 3 — Foundation Systems Under Consideration
# ==============================================================================

class FoundationSystemUnderConsideration(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_id: str
    system_name: str
    category: Literal["SHALLOW", "DEEP", "INTERIOR_FLOOR_SLAB"] = "SHALLOW"
    origin: Literal["GEOTECHNICAL_CONSULTANT_REPORT", "EXTERNAL_FOUNDATION_RESEARCH"]
    is_consultant_recommended: bool
    approval_status_note: str
    description: str
    why_considered: str
    relevant_site_conditions: str
    advantages: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    additional_engineering_info_required: List[str] = Field(default_factory=list)
    source_classification: RequirementSource
    supporting_report_id: str
    pdf_page_references: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    external_source_urls: List[str] = Field(default_factory=list)


# ==============================================================================
# Section 4 — Vendor Scope of Work
# ==============================================================================

class VendorScopeItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scope_id: str
    activity_category: str
    title: str
    description: str
    applicable_foundation_systems: List[str] = Field(default_factory=list)
    requires_confirmation_before_contractual: bool = True
    confirmation_notes: Optional[str] = None
    source_classification: RequirementSource
    supporting_report_id: str
    pdf_page_reference: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)


# ==============================================================================
# Section 5 — Technical Requirements
# ==============================================================================

class VendorRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    requirement_id: str
    category: RequirementCategory
    title: str
    specification_text: str
    numerical_value: Optional[str] = None
    units: Optional[str] = None
    conditions_or_load_case: Optional[str] = None
    factor_of_safety: Optional[str] = None
    standard_reference: Optional[str] = None
    source_classification: RequirementSource
    supporting_report_id: str
    pdf_page_reference: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)
    external_source_url: Optional[str] = None
    requires_engineer_confirmation: bool = False


# ==============================================================================
# Section 6 — Construction Quality and Documentation
# ==============================================================================

class VendorSubmittal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    submittal_id: str
    category: str
    title: str
    description: str
    submission_stage: str = "With Proposal / Pre-Construction"
    is_source_specified: bool = False
    source_classification: RequirementSource
    supporting_report_id: str
    pdf_page_reference: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)


# ==============================================================================
# Section 7 — Vendor Proposal Requirements
# ==============================================================================

class VendorProposalItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    proposal_item_id: str
    topic: str
    required_information: str
    engineering_rationale: str
    source_classification: RequirementSource = RequirementSource.PROPOSED_VENDOR_SUBMITTAL
    supporting_report_id: str


# ==============================================================================
# Section 8 — Risks and Precautions
# ==============================================================================

class VendorRiskPrecautionItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    risk_id: str
    title: str
    severity: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"
    project_risk_summary: str
    vendor_proposal_expectation: str
    is_unconditional_mandate: bool = False
    source_classification: RequirementSource
    supporting_report_id: str
    pdf_page_reference: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)


# ==============================================================================
# Section 9 — Missing Information and Clarifications
# ==============================================================================

class RequirementGap(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gap_id: str
    required_from_role: Literal[
        "GEOTECHNICAL_ENGINEER",
        "STRUCTURAL_ENGINEER",
        "CIVIL_ENGINEER",
        "ARCHITECT",
        "PROJECT_OWNER",
    ]
    title: str
    description: str
    why_needed: str
    blocks_final_vendor_specification: bool = True
    source_classification: RequirementSource = RequirementSource.ENGINEER_CONFIRMATION_REQUIRED
    supporting_report_id: str


# ==============================================================================
# Section 10 — Vendor Response Checklist
# ==============================================================================

class VendorChecklistItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    checklist_id: str
    section_reference: str
    requirement_summary: str
    verification_prompt: str
    mandatory_in_proposal: bool = True
    source_classification: RequirementSource
    linked_requirement_ids: List[str] = Field(default_factory=list)
    supporting_report_id: str


# ==============================================================================
# Section 11 — References and Evidence
# ==============================================================================

class TraceabilityReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reference_id: str
    statement_summary: str
    source_classification: RequirementSource
    geotechnical_report_id: Optional[str] = None
    original_pdf_page: Optional[str] = None
    evidence_id: Optional[str] = None
    foundation_research_report_id: Optional[str] = None
    external_source_url: Optional[str] = None
    external_source_title: Optional[str] = None


# ==============================================================================
# Section 12 — Limitations and Approval
# ==============================================================================

class LimitationsAndApprovalSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    is_preliminary_unapproved_draft: bool = True
    suitable_for_construction_or_contractual_issuance: bool = False
    upstream_reports_review_summary: str
    statutory_disclaimer: str = (
        "PRELIMINARY FOUNDATION CONTRACTOR RFQ — PROFESSIONAL REVIEW REQUIRED: "
        "This document is a preliminary foundation contractor RFQ prepared using the available project documents "
        "and supporting technical references. It is subject to verification and approval by the licensed Engineer of Record "
        "before contractual issuance or construction use. It does not constitute a stamped foundation design, "
        "certified construction specification, engineering approval, or permission to begin construction or contractual "
        "procurement until formally reviewed, completed, and approved."
    )
    required_professional_approvals: List[str] = Field(
        default_factory=lambda: [
            "Licensed Geotechnical Engineer of Record (verification of soil, pier embedment, and earthwork parameters)",
            "Licensed Structural Engineer of Record (structural loads, PT slab design, pier sizes, bell diameters, and reinforcement)",
            "Licensed Civil Engineer (site grading, positive drainage away from foundation, and stormwater controls)",
            "Project Owner / Architect (final building footprint, finished floor elevation, and scope authorization)",
        ]
    )


# ==============================================================================
# Root Vendor Foundation Requirement Document Model
# ==============================================================================

class RequirementDocument(BaseModel):
    """Complete, traceable 12-Section Vendor Foundation Requirement Document produced by Agent 3."""
    model_config = ConfigDict(extra="ignore")

    report_id: str
    project_id: str
    document_id: str
    geotechnical_report_id: str
    geotechnical_report_review_status: str = "PENDING_REVIEW"
    foundation_research_report_id: str
    foundation_research_report_review_status: str = "PENDING_REVIEW"
    confirmed_document_ids: List[str] = Field(default_factory=list)
    snapshot_id: Optional[str] = None
    document_versions: Dict[str, str] = Field(default_factory=dict)
    run_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    llm_profile_used: str = "document_analysis"

    # Human Review & Approval Status
    review_status: RequirementReviewStatus = RequirementReviewStatus.PENDING_REVIEW
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    review_notes: Optional[str] = None
    review_history: List[RequirementReview] = Field(default_factory=list)

    # Draft / Issuance Controls
    is_preliminary_draft: bool = True
    suitable_for_contractual_issuance: bool = False
    issuance_status_banner: str = (
        "UNAPPROVED PRELIMINARY DRAFT — NOT SUITABLE FOR CONSTRUCTION OR CONTRACTUAL ISSUANCE WITHOUT P.E. APPROVAL"
    )

    # 12 Structured Sections
    section_1_project_overview: ProjectOverviewSection
    section_2_geotechnical_conditions: GeotechnicalConditionsSummarySection
    section_3_foundation_systems: List[FoundationSystemUnderConsideration] = Field(default_factory=list)
    section_4_vendor_scope_of_work: List[VendorScopeItem] = Field(default_factory=list)
    section_5_technical_requirements: List[VendorRequirement] = Field(default_factory=list)
    section_6_quality_and_documentation: List[VendorSubmittal] = Field(default_factory=list)
    section_7_vendor_proposal_requirements: List[VendorProposalItem] = Field(default_factory=list)
    section_8_risks_and_precautions: List[VendorRiskPrecautionItem] = Field(default_factory=list)
    section_9_missing_information: List[RequirementGap] = Field(default_factory=list)
    section_10_vendor_response_checklist: List[VendorChecklistItem] = Field(default_factory=list)
    section_11_references_and_evidence: List[TraceabilityReference] = Field(default_factory=list)
    section_12_limitations_and_approval: LimitationsAndApprovalSection

    # Provenance Audit Metrics
    provenance_summary: Dict[str, int] = Field(default_factory=dict)

    # Formatted Markdown Report
    markdown_content: str = ""

