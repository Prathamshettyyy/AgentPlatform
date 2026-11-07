export type DocumentReadinessStatus =
  | 'UPLOADED'
  | 'PROCESSING'
  | 'READY_FOR_REVIEW'
  | 'READY_FOR_ANALYSIS'
  | 'FAILED';

export type MatchStatus =
  | 'MATCHED'
  | 'POSSIBLE_MATCH'
  | 'MISMATCH'
  | 'PENDING_CONFIRMATION';

export type UserDecision = 'PENDING' | 'CONFIRMED' | 'REJECTED';

export type PortalStageStatus =
  | 'WAITING'
  | 'RUNNING'
  | 'SUCCEEDED'
  | 'FAILED'
  | 'BLOCKED'
  | 'NEEDS_REVIEW';

export interface ProjectInfo {
  project_name?: string | null;
  project_number?: string | null;
  client_name?: string | null;
  site_location?: string | null;
  report_date?: string | null;
  engineering_firm?: string | null;
  legal_description?: string | null;
  lot?: string | null;
  block?: string | null;
  subdivision?: string | null;
}

export interface DocumentMetadata {
  document_id: string;
  project_id: string;
  filename: string;
  sha256_hash: string;
  file_size_bytes: number;
  page_count: number;
  storage_path: string;
  status: 'uploaded' | 'processing' | 'completed' | 'failed' | 'duplicate';
  readiness_status?: DocumentReadinessStatus;
  error_message?: string | null;
  project_info: ProjectInfo;
  created_at: string;
  updated_at: string;
}

export interface ProjectProfile {
  project_id: string;
  project_name: string;
  project_number?: string | null;
  client_name?: string | null;
  site_address?: string | null;
  legal_description?: string | null;
  subdivision?: string | null;
  block_number?: string | null;
  lot_number?: string | null;
}

export interface FieldComparison {
  field_name: string;
  project_value?: string | null;
  document_value?: string | null;
  is_match: boolean;
  note: string;
}

export interface DocumentProjectAssociation {
  association_id: string;
  project_id: string;
  document_id: string;
  filename: string;
  match_status: MatchStatus;
  confidence_score: number;
  match_reasons: string[];
  conflict_reasons: string[];
  field_comparisons: FieldComparison[];
  user_decision: UserDecision;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  notes?: string | null;
  created_at?: string;
}

export interface DocumentReadinessResponse {
  document_id: string;
  project_id: string;
  filename: string;
  document_status: string;
  readiness_status: DocumentReadinessStatus;
  sha256_hash: string;
  error_message?: string | null;
}

export interface PageClassificationResult {
  document_id: string;
  page_number: number;
  page_type: string;
  confidence: number;
  reasoning: string;
  has_raster_images: boolean;
  vector_drawing_density: number;
  requires_vlm: boolean;
  suggested_labels?: string[];
}

export interface VisualEvidenceRecord {
  visual_evidence_id: string;
  document_id: string;
  page_number: number;
  page_type: string;
  summary: string;
  confidence: number;
  model_used: string;
  extracted_entities: Record<string, unknown>;
  detected_labels: string[];
  key_findings: string[];
  regions?: Array<Record<string, unknown>>;
  review_status: string;
  reviewed_by?: string | null;
  review_notes?: string | null;
  created_at: string;
}

export interface EvidenceRecord {
  evidence_id: string;
  document_id: string;
  category: string;
  title: string;
  value: string;
  unit?: string | null;
  page_number: number;
  section_title?: string | null;
  raw_quote: string;
  confidence: number;
  extraction_method: string;
  verification_status: string;
  metadata?: Record<string, unknown>;
}

export interface ExtractedTable {
  table_id: string;
  document_id: string;
  page_number: number;
  table_index: number;
  caption?: string | null;
  headers: string[];
  rows: string[][];
  row_count: number;
  col_count: number;
}

export interface BoringLogReference {
  boring_id: string;
  document_id: string;
  page_numbers: number[];
  total_depth_ft?: number | null;
  groundwater_depth_ft?: number | null;
  groundwater_notes?: string | null;
  strata_summary: string[];
  raw_excerpt?: string;
}

export interface ProjectDocumentValidationResult {
  project_id: string;
  is_valid: boolean;
  status: string;
  validated_document_ids: string[];
  primary_document_id?: string | null;
  document_versions: Record<string, unknown>;
  snapshot?: {
    snapshot_id: string;
    project_id: string;
    primary_geotechnical_document_id: string;
    confirmed_document_ids: string[];
    validation_status: string;
    created_at: string;
  } | null;
  validation_errors: string[];
  message: string;
}

export interface WorkflowRun {
  run_id: string;
  workflow_id: string;
  workflow_version?: string;
  status:
    | 'running'
    | 'succeeded'
    | 'partially_succeeded'
    | 'failed'
    | 'waiting_for_approval'
    | 'cancelled';
  owner_id?: string;
  execution_backend?: string;
  created_at?: string;
  updated_at?: string;
  inputs?: Record<string, unknown>;
  payload?: {
    run_id?: string;
    workflow_id?: string;
    workflow_input?: Record<string, unknown>;
    node_outputs?: Record<string, Record<string, unknown>>;
    agent_outputs?: Record<string, Record<string, unknown>>;
    error?: string;
    traceback?: string;
    retry_count?: number;
    [key: string]: unknown;
  };
  output?: {
    run_id?: string;
    workflow_id?: string;
    workflow_input?: Record<string, unknown>;
    node_outputs?: Record<string, Record<string, unknown>>;
    agent_outputs?: Record<string, Record<string, unknown>>;
    error?: string;
    traceback?: string;
    retry_count?: number;
    [key: string]: unknown;
  };
}

export interface WorkflowRunEvent {
  id?: number;
  run_id: string;
  node_id: string;
  status: string;
  payload: Record<string, unknown>;
  created_at?: string;
}

export interface CitationRef {
  document_id: string;
  filename?: string;
  page_numbers: number[];
  section_title?: string | null;
  table_id?: string | null;
  evidence_id?: string | null;
  raw_quote?: string | null;
}

export interface SoilClassificationRecord {
  stratum_name: string;
  uscs_symbol?: string | null;
  depth_range_ft?: string | null;
  description: string;
  plasticity_classification?: string | null;
  swell_potential?: string | null;
  boring_ids: string[];
  citations: CitationRef[];
}

export interface LaboratoryFindings {
  liquid_limit_range?: string | null;
  plasticity_index_range?: string | null;
  moisture_content_range_pct?: string | null;
  dry_unit_weight_pcf_range?: string | null;
  undrained_shear_strength_ksf_range?: string | null;
  percent_passing_no_200_range?: string | null;
  notable_test_results: string[];
  citations: CitationRef[];
}

export interface GroundwaterAssessment {
  groundwater_observed: boolean;
  encountered_depth_ft?: string | null;
  stabilized_depth_ft?: string | null;
  boring_observations: string[];
  seepage_and_seasonal_notes: string;
  citations: CitationRef[];
}

export interface FoundationSystemReportRecord {
  system_name: string;
  structure_applicability?: string | null;
  bearing_stratum?: string | null;
  minimum_depth_ft?: number | null;
  allowable_bearing_pressure_psf?: number | null;
  Drilled_pier_skin_friction_psf?: number | null;
  end_bearing_pressure_psf?: number | null;
  uplift_resistance_notes?: string | null;
  settlement_estimate_in?: string | null;
  design_notes: string[];
  citations: CitationRef[];
}

export interface BearingParameterRecord {
  parameter_name: string;
  value: string;
  unit?: string | null;
  applicable_depth_or_stratum?: string | null;
  foundation_type?: string | null;
  citations: CitationRef[];
}

export interface SitePreparationReportRecord {
  topic: string;
  requirement_summary: string;
  specifications: string[];
  citations: CitationRef[];
}

export interface GeotechnicalRiskRecord {
  risk_category: string;
  severity: 'HIGH' | 'MODERATE' | 'LOW';
  description: string;
  engineering_implication: string;
  mitigation_mentioned_in_report?: string | null;
  citations: CitationRef[];
}

export interface GeotechnicalAnalysisReport {
  report_id: string;
  project_id: string;
  primary_document_id: string;
  confirmed_document_ids: string[];
  excluded_document_ids: string[];
  project_summary: Record<string, unknown>;
  executive_overview: string;
  soil_classifications: SoilClassificationRecord[];
  laboratory_findings: LaboratoryFindings;
  groundwater_conditions: GroundwaterAssessment;
  potential_vertical_rise_pvr?: {
    pvr_value_in?: string | null;
    assumed_moisture_condition?: string | null;
    affected_depth_zone_ft?: string | null;
    mitigation_options: string[];
    citations: CitationRef[];
  };
  foundation_systems_in_report: FoundationSystemReportRecord[];
  bearing_parameters: BearingParameterRecord[];
  site_preparation_requirements: SitePreparationReportRecord[];
  geotechnical_risks: GeotechnicalRiskRecord[];
  missing_or_unclear_information: string[];
  questions_for_engineers: string[];
  cross_document_notes: string[];
  model_used: string;
  confidence_score: number;
  review_status: string;
  reviewed_by?: string | null;
  review_notes?: string | null;
  created_at: string;
}

export interface ResearchSourceCitation {
  source_id: string;
  title: string;
  organization_or_author: string;
  publication_or_standard?: string | null;
  year?: string | null;
  url?: string | null;
  relevance_note?: string | null;
  source_type?: string;
}

export interface FoundationTechnologyResearchRecord {
  technology_id?: string;
  name: string;
  category: 'SHALLOW' | 'DEEP' | string;
  mentioned_in_geotechnical_report: boolean;
  technical_explanation: string;
  load_transfer_mechanism: string;
  applicable_soil_conditions: string;
  constructability_considerations: string[];
  advantages: string[];
  limitations_and_risks: string[];
  expansive_clay_performance: string;
  citations: ResearchSourceCitation[];
}

export interface FoundationComparisonItem {
  foundation_name: string;
  category: string;
  mentioned_in_report: boolean;
  expansive_soil_suitability: string;
  relative_settlement_control: string;
  relative_construction_complexity: string;
  typical_depth_range: string;
  key_tradeoff: string;
}

export interface ProjectRelevanceItem {
  foundation_name: string;
  relevance_classification: string;
  alignment_with_site_conditions: string;
  geotechnical_report_parameters_referenced: string[];
  engineering_verification_needed: string[];
}

export interface FoundationResearchReport {
  research_report_id: string;
  project_id: string;
  geotechnical_report_id: string;
  primary_document_id: string;
  confirmed_document_ids: string[];
  site_condition_context: Record<string, unknown>;
  executive_research_summary: string;
  foundation_technologies: FoundationTechnologyResearchRecord[];
  comparison_matrix: FoundationComparisonItem[];
  project_relevance_analysis: ProjectRelevanceItem[];
  research_sources: ResearchSourceCitation[];
  research_gaps: string[];
  questions_for_foundation_engineers: string[];
  disclaimer: string;
  model_used: string;
  confidence_score: number;
  review_status: string;
  reviewed_by?: string | null;
  review_notes?: string | null;
  created_at: string;
}

export type RequirementSourceType =
  | 'GEOTECHNICAL_SOURCE_REQUIREMENT'
  | 'EXTERNAL_RESEARCH_REFERENCE'
  | 'PROPOSED_VENDOR_SUBMITTAL'
  | 'AI_DRAFTED_SCOPE'
  | 'ENGINEER_CONFIRMATION_REQUIRED';

export interface VendorRequirementItem {
  requirement_id: string;
  category: string;
  title: string;
  specification_text: string;
  numerical_value?: string | null;
  units?: string | null;
  conditions_or_load_case?: string | null;
  factor_of_safety?: string | null;
  standard_reference?: string | null;
  source_classification: RequirementSourceType;
  supporting_report_id: string;
  pdf_page_reference?: string | null;
  evidence_ids: string[];
  external_source_url?: string | null;
  requires_engineer_confirmation: boolean;
}

export interface VendorScopeItemRecord {
  scope_id: string;
  activity_category: string;
  title: string;
  description: string;
  applicable_foundation_systems: string[];
  requires_confirmation_before_contractual: boolean;
  confirmation_notes?: string | null;
  source_classification: RequirementSourceType;
  supporting_report_id: string;
  pdf_page_reference?: string | null;
  evidence_ids: string[];
}

export interface VendorSubmittalRecord {
  submittal_id: string;
  category: string;
  title: string;
  description: string;
  submission_stage: string;
  is_source_specified: boolean;
  source_classification: RequirementSourceType;
  supporting_report_id: string;
  pdf_page_reference?: string | null;
  evidence_ids: string[];
}

export interface VendorChecklistItemRecord {
  checklist_id: string;
  section_reference: string;
  requirement_summary: string;
  verification_prompt: string;
  mandatory_in_proposal: boolean;
  source_classification: RequirementSourceType;
  linked_requirement_ids: string[];
  supporting_report_id: string;
}

export interface RequirementGapRecord {
  gap_id: string;
  required_from_role: string;
  title: string;
  description: string;
  why_needed: string;
  blocks_final_vendor_specification: boolean;
  source_classification: RequirementSourceType;
  supporting_report_id: string;
}

export interface RequirementDocument {
  report_id: string;
  project_id: string;
  document_id: string;
  geotechnical_report_id: string;
  geotechnical_report_review_status: string;
  foundation_research_report_id: string;
  foundation_research_report_review_status: string;
  confirmed_document_ids: string[];
  snapshot_id?: string | null;
  document_versions: Record<string, string>;
  created_at: string;
  updated_at: string;
  review_status: string;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_notes?: string | null;
  is_preliminary_draft: boolean;
  suitable_for_contractual_issuance: boolean;
  issuance_status_banner: string;
  section_1_project_overview: {
    project_name: string;
    project_number?: string | null;
    site_address?: string | null;
    legal_description?: string | null;
    client?: string | null;
    geotechnical_consultant?: string | null;
    associated_source_documents: string[];
    confirmed_document_ids: string[];
    document_snapshot_id?: string | null;
    report_generation_date: string;
    geotechnical_report_id: string;
    geotechnical_report_review_status: string;
    foundation_research_report_id: string;
    foundation_research_report_review_status: string;
  };
  section_2_geotechnical_conditions: {
    dominant_soil_description: string;
    uscs_classification: string;
    boring_summary: string;
    laboratory_properties_summary: string;
    liquid_limit_range: string;
    plasticity_index_range: string;
    moisture_content_range: string;
    passing_no_200_range: string;
    pocket_penetrometer_range_tsf: string;
    spt_status: string;
    groundwater_summary: string;
    groundwater_depth_range_ft: string;
    pvr_value_inches: number;
    shrink_swell_potential: string;
    pvr_implications_for_vendors: string;
    site_conditions_and_constraints: string[];
    supporting_report_id: string;
    evidence_ids: string[];
  };
  section_3_foundation_systems: Array<{
    system_id: string;
    system_name: string;
    category: string;
    origin: 'GEOTECHNICAL_CONSULTANT_REPORT' | 'EXTERNAL_FOUNDATION_RESEARCH' | string;
    is_consultant_recommended: boolean;
    approval_status_note: string;
    description: string;
    why_considered: string;
    relevant_site_conditions: string;
    advantages: string[];
    limitations: string[];
    additional_engineering_info_required: string[];
    source_classification: RequirementSourceType;
    supporting_report_id: string;
    pdf_page_references: string[];
    evidence_ids: string[];
    external_source_urls: string[];
  }>;
  section_4_vendor_scope_of_work: VendorScopeItemRecord[];
  section_5_technical_requirements: VendorRequirementItem[];
  section_6_quality_and_documentation: VendorSubmittalRecord[];
  section_7_vendor_proposal_requirements: Array<{
    proposal_item_id: string;
    topic: string;
    required_information: string;
    engineering_rationale: string;
    source_classification: RequirementSourceType;
    supporting_report_id: string;
  }>;
  section_8_risks_and_precautions: Array<{
    risk_id: string;
    title: string;
    severity: string;
    project_risk_summary: string;
    vendor_proposal_expectation: string;
    is_unconditional_mandate: boolean;
    source_classification: RequirementSourceType;
    supporting_report_id: string;
    pdf_page_reference?: string | null;
    evidence_ids: string[];
  }>;
  section_9_missing_information: RequirementGapRecord[];
  section_10_vendor_response_checklist: VendorChecklistItemRecord[];
  section_11_references_and_evidence: Array<{
    reference_id: string;
    statement_summary: string;
    source_classification: RequirementSourceType;
    geotechnical_report_id?: string | null;
    original_pdf_page?: string | null;
    evidence_id?: string | null;
    foundation_research_report_id?: string | null;
    external_source_url?: string | null;
    external_source_title?: string | null;
  }>;
  section_12_limitations_and_approval: {
    is_preliminary_unapproved_draft: boolean;
    suitable_for_construction_or_contractual_issuance: boolean;
    upstream_reports_review_summary: string;
    statutory_disclaimer: string;
    required_professional_approvals: string[];
  };
  provenance_summary: Record<string, number>;
  markdown_content: string;
}

export interface PortalStage {
  id:
    | 'upload'
    | 'extract'
    | 'vision'
    | 'validate'
    | 'geotechnical_agent'
    | 'foundation_agent'
    | 'requirement_agent'
    | 'reports';
  number: number;
  title: string;
  subtitle: string;
  status: PortalStageStatus;
  detail?: string;
  nodeId?: string;
}

export interface ProjectSession {
  projectId: string;
  projectName: string;
  projectAddress: string;
  documentIds: string[];
  confirmedDocumentIds: string[];
  runId?: string | null;
  geotechnicalReportId?: string | null;
  foundationResearchReportId?: string | null;
  requirementReportId?: string | null;
  snapshotId?: string | null;
  stageStatuses: Record<string, PortalStageStatus>;
  errorMessage?: string | null;
  failedStageId?: string | null;
  createdAt: string;
  updatedAt: string;
}

