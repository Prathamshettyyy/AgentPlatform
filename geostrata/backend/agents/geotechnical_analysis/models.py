from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ==============================================================================
# Evidence Grounding Models
# ==============================================================================

class EvidenceCitation(BaseModel):
    """Explicit link to a verified evidence record in the database."""
    model_config = ConfigDict(extra="ignore")

    evidence_id: str
    property_type: Optional[str] = None
    property_name: Optional[str] = None
    value: str
    page_index: int
    printed_page_number: Optional[str] = None
    context_snippet: Optional[str] = None


# ==============================================================================
# Section 1: Executive Summary
# ==============================================================================

class ExecutiveSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    overview: str
    dominant_soil_classification: str = "SANDY LEAN CLAY (CL)"
    primary_foundation_options: list[str] = Field(default_factory=list)
    key_engineering_risks: list[str] = Field(default_factory=list)
    critical_site_prep_requirements: list[str] = Field(default_factory=list)
    professional_review_required: bool = True
    disclaimer: str = (
        "This AI analysis is an advisory engineering tool and does not constitute a certified, "
        "stamped, or finalized foundation design. All findings require review and approval by a "
        "licensed Professional Engineer (PE / GE)."
    )


# ==============================================================================
# Section 2: Project & Document Context
# ==============================================================================

class DiscrepancyItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field_name: str
    description: str
    conflicting_values: list[str] = Field(default_factory=list)
    severity: Literal["HIGH", "MEDIUM", "LOW"] = "MEDIUM"


class ProjectDocumentContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_name: Optional[str] = None
    project_number: Optional[str] = None
    site_location: Optional[str] = None
    address: Optional[str] = None
    legal_description: Optional[str] = None
    client_name: Optional[str] = None
    geotechnical_consultant: Optional[str] = None
    report_date: Optional[str] = None
    original_document_date: Optional[str] = None
    analysis_generated_at: str = Field(default_factory=_now_iso)
    uploaded_filename: Optional[str] = None
    document_version: Optional[str] = None
    building_type: Optional[str] = None
    structure_count: Optional[str] = None
    documents_reviewed: list[str] = Field(default_factory=list)
    has_discrepancies: bool = False
    discrepancies: list[DiscrepancyItem] = Field(default_factory=list)
    cross_document_status: Literal["NOT_ASSESSED", "MATCHED", "DISCREPANCIES_FOUND"] = "NOT_ASSESSED"
    cross_document_matching_note: Optional[str] = (
        "Cross-document project matching has not been performed; single geotechnical investigation report analyzed."
    )
    notes: Optional[str] = None


# ==============================================================================
# Section 3: Soil Investigation Summary
# ==============================================================================

class SoilInvestigationSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_borings: int = 2
    boring_identifiers: list[str] = Field(default_factory=list)
    max_investigation_depth_ft: float = 20.0
    drilling_methods: list[str] = Field(default_factory=list)
    sampling_methods: list[str] = Field(default_factory=list)
    groundwater_encountered: bool = True
    groundwater_summary: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


# ==============================================================================
# Section 4: Subsurface Soil Conditions
# ==============================================================================

class StratumInterval(BaseModel):
    model_config = ConfigDict(extra="ignore")

    boring_id: str
    depth_range_ft: str
    description: str
    uscs_classification: str
    consistency: str
    observations: list[str] = Field(default_factory=list)
    calcareous_nodules: bool = False
    evidence_ids: list[str] = Field(default_factory=list)


class SubsurfaceConditions(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dominant_stratum: str
    uscs_group_symbol: str
    strata: list[StratumInterval] = Field(default_factory=list)
    consistency_summary: str
    color_and_composition: str
    nodule_presence: str
    spatial_variability: str
    evidence_ids: list[str] = Field(default_factory=list)


# ==============================================================================
# Section 5: Laboratory Test Interpretation
# ==============================================================================

class LaboratoryInterpretation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    moisture_content_range: str
    plasticity_index_range: str
    liquid_limit_range: str
    percent_passing_no_200_range: str
    pocket_penetrometer_range_tsf: str
    spt_blow_counts_reported: bool = False
    spt_status: str = "NOT_REPORTED (continuous flight auger drilling performed)"
    pvr_value_inches: float = 1.20
    pvr_interpretation: str
    shrink_swell_potential: Literal["LOW", "MODERATE", "HIGH", "VERY_HIGH"] = "MODERATE"
    evidence_ids: list[str] = Field(default_factory=list)


# ==============================================================================
# Section 6: Groundwater Assessment
# ==============================================================================

class GroundwaterMeasurementItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    boring_id: str
    drilling_depth_ft: float
    post_drilling_depth_ft: float
    time_elapsed_minutes: Optional[int] = 15
    evidence_ids: list[str] = Field(default_factory=list)


class GroundwaterAssessment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    encountered: bool = True
    measurements: list[GroundwaterMeasurementItem] = Field(default_factory=list)
    average_depth_range_ft: str = "14.0 - 15.4 ft"
    seasonal_fluctuation_warning: str
    construction_impact: str
    evidence_ids: list[str] = Field(default_factory=list)


# ==============================================================================
# Section 7: Foundation Systems in Geotechnical Report
# ==============================================================================

class FoundationSystemItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_name: str
    is_foundation_system: bool = True  # False for slab-on-grade interior floor
    applicable_structures: str
    recommended_preparation: str
    allowable_bearing_pressures: list[dict[str, Any]] = Field(default_factory=list)
    embedment_depth_ft: Optional[float] = None
    dimensions_and_ratios: Optional[str] = None
    construction_considerations: list[str] = Field(default_factory=list)
    risks_and_limitations: list[str] = Field(default_factory=list)
    prerequisites_and_conditions: list[str] = Field(default_factory=list)
    source_pages: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class FoundationSystemsInReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    post_tensioned_slabs: FoundationSystemItem
    drilled_underreamed_piers: FoundationSystemItem
    continuous_footings_grade_beams: FoundationSystemItem
    slab_on_grade_floor: FoundationSystemItem


# ==============================================================================
# Section 8: Foundation System Comparison
# ==============================================================================

class ComparisonRow(BaseModel):
    model_config = ConfigDict(extra="ignore")

    system_name: str
    bearing_capacity: str
    settlement_performance: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    soil_suitability: str
    constructability_and_caving_risk: str
    relative_cost_complexity: str


class FoundationComparison(BaseModel):
    model_config = ConfigDict(extra="ignore")

    comparison_matrix: list[ComparisonRow] = Field(default_factory=list)
    engineering_synthesis: str
    floor_slab_vs_foundation_clarification: str


# ==============================================================================
# Section 9: Site Preparation Requirements
# ==============================================================================

class SitePrepItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    engineered_limit: str
    standard_reference: Optional[str] = None
    conditions: Optional[str] = None
    source_page: str
    evidence_id: str


class SitePreparationSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    section_reference: str = "Section 1.3.1 (Report Pages 3 - 4 / PDF Pages 6 - 7)"
    specifications: list[SitePrepItem] = Field(default_factory=list)
    compaction_standard: str = "ASTM D 698 (Standard Proctor)"
    proofrolling_requirement: str = "15-ton roller or heavier under geotechnical observation"
    select_fill_criteria: str = "Inactive lean clays and clayey sands (LL <= 35, PI 8 to 20)"
    lift_controls: str = "8-inch loose lifts compacted to 6 inches, >= 95% standard dry density, +/- 2% optimum moisture"


# ==============================================================================
# Section 10: Potential Risks and Concerns
# ==============================================================================

class RiskConcern(BaseModel):
    model_config = ConfigDict(extra="ignore")

    risk_id: str
    category: str
    title: str
    severity: Literal["HIGH", "MEDIUM", "LOW"]
    description: str
    mitigation_in_report: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class RisksAndConcerns(BaseModel):
    model_config = ConfigDict(extra="ignore")

    identified_risks: list[RiskConcern] = Field(default_factory=list)
    overall_risk_assessment: str


# ==============================================================================
# Section 11: Missing Information
# ==============================================================================

class MissingInformationItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    item_id: str
    category: str
    title: str
    criticality: Literal["CRITICAL", "IMPORTANT", "ADVISORY"]
    description: str
    impact_on_design: str


class MissingInformationSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[MissingInformationItem] = Field(default_factory=list)
    general_note: str = (
        "The missing items identified below must be furnished by the structural engineer, "
        "civil designer, and owner prior to final foundation design and structural detailing."
    )


# ==============================================================================
# Section 12: Questions for Engineers
# ==============================================================================

class EngineerQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_discipline: Literal["Geotechnical Engineer", "Structural Engineer", "Civil Engineer / Drainage Designer", "Owner / Architect"]
    question: str
    engineering_rationale: str
    referenced_section_or_risk: str


class QuestionsForEngineerSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    questions: list[EngineerQuestion] = Field(default_factory=list)


# ==============================================================================
# Section 13: Evidence References
# ==============================================================================

class EvidenceReferencesSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_citations: int = 0
    citations: list[EvidenceCitation] = Field(default_factory=list)
    unresolved_citations_count: int = 0


# ==============================================================================
# Section 14: Limitations and Review Requirements
# ==============================================================================

class LimitationsAndReviewSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    statutory_disclaimer: str = (
        "This engineering analysis was synthesized by an automated artificial intelligence system "
        "designed to interpret document intelligence extraction data. It does not replace the "
        "judgment, evaluation, or professional stamp of a licensed Professional Geotechnical Engineer "
        "or Structural Engineer in the governing jurisdiction. No foundation construction or excavation "
        "should proceed without signed and sealed construction drawings."
    )
    applicable_building_codes: list[str] = Field(default_factory=lambda: ["IBC", "ACI 318", "PTI DC10.5", "ASTM Standards"])
    mandatory_review_action: str = (
        "A qualified geotechnical engineer must review, verify, and stamp the proposed foundation system "
        "based on final architectural layouts and actual structural column and wall loadings."
    )


# ==============================================================================
# Human Review & Approval Models
# ==============================================================================

class HumanReviewRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    review_id: str
    report_id: str = ""
    decision: Literal["PENDING_REVIEW", "HUMAN_VERIFIED", "REJECTED", "CHANGES_REQUESTED"] = "PENDING_REVIEW"
    reviewer_id: str
    comments: Optional[str] = None
    timestamp: str = Field(default_factory=_now_iso)


# ==============================================================================
# Root Geotechnical Analysis Report Model
# ==============================================================================

class GeotechnicalAnalysisReport(BaseModel):
    """Complete, structured, and evidence-grounded AI Geotechnical Analysis Report."""
    model_config = ConfigDict(extra="ignore")

    report_id: str
    document_id: str
    document_name: str
    project_id: str = "default"
    run_id: Optional[str] = None
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    llm_profile_used: str = "document_analysis"
    llm_model_used: Optional[str] = None
    llm_provider_used: Optional[str] = None

    # Review status
    review_status: Literal["PENDING_REVIEW", "HUMAN_VERIFIED", "REJECTED", "CHANGES_REQUESTED"] = "PENDING_REVIEW"
    review_history: list[HumanReviewRecord] = Field(default_factory=list)

    # 14 Structured Engineering Sections
    executive_summary: ExecutiveSummary
    project_context: ProjectDocumentContext
    investigation_summary: SoilInvestigationSummary
    subsurface_conditions: SubsurfaceConditions
    laboratory_interpretation: LaboratoryInterpretation
    groundwater_assessment: GroundwaterAssessment
    foundation_systems: FoundationSystemsInReport
    foundation_comparison: FoundationComparison
    site_preparation: SitePreparationSection
    risks_and_concerns: RisksAndConcerns
    missing_information: MissingInformationSection
    questions_for_engineers: QuestionsForEngineerSection
    evidence_references: EvidenceReferencesSection
    limitations_and_review: LimitationsAndReviewSection

    # Human-readable markdown presentation
    markdown_content: str = ""
