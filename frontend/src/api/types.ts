export interface AgentMetadata {
  id: string;
  name: string;
  version: string;
  description?: string;
  status?: string;
  entrypoint?: string;
  adapter_type?: 'python_callable' | 'compiled_langgraph';
  capabilities?: string[];
  input_schema?: Record<string, any>;
  output_schema?: Record<string, any>;
  execution?: {
    allowed_tools?: string[];
    permissions?: string[];
    timeout_seconds?: number;
  };
}

export interface ToolMetadata {
  id: string;
  name: string;
  description?: string;
  version?: string;
  entrypoint?: string;
  adapter_type?: string;
  enabled?: boolean;
  input_schema?: Record<string, any>;
  output_schema?: Record<string, any>;
  execution?: {
    permissions?: string[];
    requires_approval?: boolean;
  };
}

export interface InputMapping {
  path?: string;
  literal?: any;
}

export interface WorkflowNode {
  id: string;
  type: 'agent' | 'human_approval' | 'trigger';
  agent_id?: string;
  trigger_type?: 'webhook' | 'schedule' | 'manual';
  trigger_config?: {
    webhook_path?: string;
    secret_token?: string;
    cron?: string;
    sample_payload?: Record<string, any>;
  };
  status?: string;
  input_mappings?: Record<string, InputMapping>;
  approval_payload_path?: string;
  approval_options?: string[];
  execute_in?: 'activity' | 'workflow';
  timeout_seconds?: number;
  max_retries?: number;
  retry_backoff_seconds?: number;
}

export interface WorkflowEdge {
  from: string;
  to: string;
  condition?: {
    path?: string;
    equals?: any;
    not_equals?: any;
    exists?: boolean;
    truthy?: boolean;
    [key: string]: any;
  } | null;
}

export interface WorkflowDefinition {
  id: string;
  version: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  max_steps?: number;
  registered?: boolean;
  registration_status?: 'registered' | 'disconnected' | 'draft';
  workflow_file?: string;
}

export interface RunRecord {
  run_id: string;
  workflow_id: string | null;
  workflow_version?: string;
  thread_id?: string;
  owner_id?: string;
  status: 'running' | 'succeeded' | 'failed' | 'waiting_for_approval' | 'partially_succeeded' | 'resuming';
  payload: {
    workflow_input?: Record<string, any>;
    inputs?: Record<string, any>;
    node_outputs?: Record<string, any>;
    final_output?: Record<string, any>;
    error?: {
      message?: string;
      details?: any;
      code?: string;
    };
    __interrupt__?: Record<string, any>;
    [key: string]: any;
  };
  created_at?: string;
}

export interface ExecutionEvent {
  id?: number;
  run_id: string;
  node_id: string;
  status: string;
  payload: Record<string, any>;
  created_at: string;
}

export interface OverviewStats {
  agents_count: number;
  workflows_total: number;
  workflows_registered: number;
  workflows_drafts: number;
  runs_total: number;
  runs_running: number;
  runs_succeeded: number;
  runs_failed: number;
  pending_approvals: number;
  tools_count: number;
}

export interface HealthStatus {
  status: string;
  service: string;
  auth_mode?: string;
  version?: string;
}

export interface WorkflowDeletePreview {
  workflow_id: string;
  registered: boolean;
  has_local_file: boolean;
  local_file: string | null;
  versions: string[];
  run_count: number;
  event_count: number;
  checkpoint_count: number;
}

export interface AgentDeletePreview {
  agent_id: string;
  direct_run_count: number;
  event_count: number;
  checkpoint_count: number;
  workflows_referencing: string[];
  has_manifest: boolean;
  has_adapter: boolean;
  has_catalog_entry: boolean;
}

// ==============================================================================
// Document Intelligence & Geotechnical Documents Types (Phase 1)
// ==============================================================================

export interface BoundingBox {
  x0: number;
  top: number;
  x1: number;
  bottom: number;
  page_width: number;
  page_height: number;
}

export interface FoundationParameter {
  parameter_name: string;
  value: string;
  numeric_value?: number | null;
  unit?: string | null;
  load_case?: string | null;
  factor_of_safety?: number | null;
  conditions?: string | null;
  page_index: number;
  printed_page_number?: string | null;
  evidence_id?: string | null;
}

export interface FoundationSystemRecommendation {
  system_name: string;
  applicable_structure: string;
  description: string;
  page_range: string;
  parameters: FoundationParameter[];
}

export interface SitePreparationRequirement {
  requirement_name: string;
  requirement_text: string;
  original_value: string;
  numeric_value?: number | null;
  unit?: string | null;
  conditions?: string | null;
  standard_reference?: string | null;
  page_index: number;
  printed_page_number?: string | null;
  evidence_id?: string | null;
}

export interface BoringObservation {
  depth_ft: number;
  depth_label: string;
  observation: string;
}

export interface BoringLogReference {
  boring_id: string;
  page_index: number;
  printed_page_number?: string | null;
  depth_range?: string | null;
  stratum_description?: string | null;
  observations: BoringObservation[];
  sample_depths: number[];
  termination_depth?: number | null;
  groundwater_drilling_depth?: number | null;
  groundwater_15min_depth?: number | null;
  groundwater_depth?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  gps_coordinates?: string | null;
  boring_type?: string;
  evidence_id?: string | null;
}

export interface EvidenceRecord {
  evidence_id: string;
  document_id: string;
  document_name: string;
  page_index: number;
  printed_page_number?: string | null;
  extracted_text: string;
  property_type?: string | null;
  property_name?: string | null;
  original_value?: string;
  numeric_value?: number | null;
  unit?: string | null;
  boring_id?: string | null;
  depth?: string | null;
  bounding_box?: BoundingBox | null;
  extraction_method: string;
  verification_status: 'PENDING_REVIEW' | 'HUMAN_VERIFIED' | 'REJECTED' | 'unverified' | 'verified' | 'flagged';
  confidence_category?: 'VERIFIED_TEXT' | 'VERIFIED_TABLE_CELL' | 'IMAGE_ONLY' | 'LOW_CONFIDENCE' | 'DISAGREEMENT';
  confidence_score: number;
  is_reported?: boolean;
  foundation_system?: string | null;
  load_case?: string | null;
  factor_of_safety?: number | null;
  conditions?: string | null;
  context_snippet?: string | null;
  created_at: string;
}

export interface ExtractedTable {
  table_id: string;
  document_id: string;
  page_index: number;
  printed_page_number?: string | null;
  table_name?: string | null;
  table_classification?:
    | 'engineering_data'
    | 'boring_log'
    | 'laboratory_summary'
    | 'foundation_design_parameters'
    | 'reference_legend'
    | 'figure_drawing_text'
    | 'fragmented_low_confidence';
  headers: string[];
  rows: string[][];
  bounding_box?: BoundingBox | null;
  caption?: string | null;
  cell_count: number;
  confidence_score?: number;
  is_fragment?: boolean;
  parent_table_id?: string | null;
}

export interface DocumentPage {
  page_index: number;
  printed_page_number?: string | null;
  width: number;
  height: number;
  is_scanned: boolean;
  char_count: number;
  word_count: number;
  raw_text: string;
  section_headings: string[];
  tables_count: number;
  evidence_count: number;
  status: 'extracted' | 'failed' | 'empty';
  error_message?: string | null;
}

export interface ProjectInfo {
  project_name?: string | null;
  project_number?: string | null;
  site_location?: string | null;
  client_name?: string | null;
  engineer_firm?: string | null;
  investigation_date?: string | null;
}

export interface DocumentMetadata {
  document_id: string;
  project_id: string;
  filename: string;
  sha256_hash: string;
  file_size_bytes: number;
  page_count: number;
  is_scanned: boolean;
  document_type: 'text_based' | 'scanned' | 'hybrid';
  pdf_metadata?: Record<string, any>;
  project_info?: ProjectInfo | null;
  storage_path?: string;
  status: 'uploaded' | 'processing' | 'completed' | 'partially_extracted' | 'failed' | 'duplicate';
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

// ==============================================================================
// AI Geotechnical Analysis Types (Phase 2)
// ==============================================================================

export interface EvidenceCitation {
  evidence_id: string;
  property_type?: string | null;
  property_name?: string | null;
  value: string;
  page_index: number;
  printed_page_number?: string | null;
  context_snippet?: string | null;
}

export interface ExecutiveSummary {
  overview: string;
  dominant_soil_classification: string;
  primary_foundation_options: string[];
  key_engineering_risks: string[];
  critical_site_prep_requirements: string[];
  professional_review_required: boolean;
  disclaimer: string;
}

export interface DiscrepancyItem {
  field_name: string;
  description: string;
  conflicting_values: string[];
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
}

export interface ProjectDocumentContext {
  project_name?: string | null;
  project_number?: string | null;
  site_location?: string | null;
  address?: string | null;
  legal_description?: string | null;
  client_name?: string | null;
  geotechnical_consultant?: string | null;
  report_date?: string | null;
  original_document_date?: string | null;
  analysis_generated_at?: string | null;
  uploaded_filename?: string | null;
  document_version?: string | null;
  building_type?: string | null;
  structure_count?: string | null;
  documents_reviewed: string[];
  has_discrepancies: boolean;
  discrepancies: DiscrepancyItem[];
  cross_document_status?: 'NOT_ASSESSED' | 'MATCHED' | 'DISCREPANCIES_FOUND';
  cross_document_matching_note?: string | null;
  notes?: string | null;
}

export interface SoilInvestigationSummary {
  total_borings: number;
  boring_identifiers: string[];
  max_investigation_depth_ft: number;
  drilling_methods: string[];
  sampling_methods: string[];
  groundwater_encountered: boolean;
  groundwater_summary: string;
  evidence_ids: string[];
}

export interface StratumInterval {
  boring_id: string;
  depth_range_ft: string;
  description: string;
  uscs_classification: string;
  consistency: string;
  observations: string[];
  calcareous_nodules: boolean;
  evidence_ids: string[];
}

export interface SubsurfaceConditions {
  dominant_stratum: string;
  uscs_group_symbol: string;
  strata: StratumInterval[];
  consistency_summary: string;
  color_and_composition: string;
  nodule_presence: string;
  spatial_variability: string;
  evidence_ids: string[];
}

export interface LaboratoryInterpretation {
  moisture_content_range: string;
  plasticity_index_range: string;
  liquid_limit_range: string;
  percent_passing_no_200_range: string;
  pocket_penetrometer_range_tsf: string;
  spt_blow_counts_reported: boolean;
  spt_status: string;
  pvr_value_inches: number;
  pvr_interpretation: string;
  shrink_swell_potential: 'LOW' | 'MODERATE' | 'HIGH' | 'VERY_HIGH';
  evidence_ids: string[];
}

export interface GroundwaterMeasurementItem {
  boring_id: string;
  drilling_depth_ft: number;
  post_drilling_depth_ft: number;
  time_elapsed_minutes?: number | null;
  evidence_ids: string[];
}

export interface GroundwaterAssessment {
  encountered: boolean;
  measurements: GroundwaterMeasurementItem[];
  average_depth_range_ft: string;
  seasonal_fluctuation_warning: string;
  construction_impact: string;
  evidence_ids: string[];
}

export interface FoundationSystemItem {
  system_name: string;
  is_foundation_system: boolean;
  applicable_structures: string;
  recommended_preparation: string;
  allowable_bearing_pressures: Array<{
    load_case?: string;
    pressure_psf?: number;
    factor_of_safety?: number;
    parameter?: string;
    value_psf?: number;
    notes?: string;
  }>;
  embedment_depth_ft?: number | null;
  dimensions_and_ratios?: string | null;
  construction_considerations: string[];
  risks_and_limitations: string[];
  prerequisites_and_conditions: string[];
  source_pages: string[];
  evidence_ids: string[];
}

export interface FoundationSystemsInReport {
  post_tensioned_slabs: FoundationSystemItem;
  drilled_underreamed_piers: FoundationSystemItem;
  continuous_footings_grade_beams: FoundationSystemItem;
  slab_on_grade_floor: FoundationSystemItem;
}

export interface ComparisonRow {
  system_name: string;
  bearing_capacity: string;
  settlement_performance: string;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH';
  soil_suitability: string;
  constructability_and_caving_risk: string;
  relative_cost_complexity: string;
}

export interface FoundationComparison {
  comparison_matrix: ComparisonRow[];
  engineering_synthesis: string;
  floor_slab_vs_foundation_clarification: string;
}

export interface SitePrepItem {
  name: string;
  engineered_limit: string;
  standard_reference?: string | null;
  conditions?: string | null;
  source_page: string;
  evidence_id: string;
}

export interface SitePreparationSection {
  section_reference: string;
  specifications: SitePrepItem[];
  compaction_standard: string;
  proofrolling_requirement: string;
  select_fill_criteria: string;
  lift_controls: string;
}

export interface RiskConcern {
  risk_id: string;
  category: string;
  title: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  description: string;
  mitigation_in_report: string;
  supporting_evidence_ids: string[];
}

export interface RisksAndConcerns {
  identified_risks: RiskConcern[];
  overall_risk_assessment: string;
}

export interface MissingInformationItem {
  item_id: string;
  category: string;
  title: string;
  criticality: 'CRITICAL' | 'IMPORTANT' | 'ADVISORY';
  description: string;
  impact_on_design: string;
}

export interface MissingInformationSection {
  items: MissingInformationItem[];
  general_note: string;
}

export interface EngineerQuestion {
  target_discipline: 'Geotechnical Engineer' | 'Structural Engineer' | 'Civil Engineer / Drainage Designer' | 'Owner / Architect';
  question: string;
  engineering_rationale: string;
  referenced_section_or_risk: string;
}

export interface QuestionsForEngineerSection {
  questions: EngineerQuestion[];
}

export interface EvidenceReferencesSection {
  total_citations: number;
  citations: EvidenceCitation[];
  unresolved_citations_count: number;
}

export interface LimitationsAndReviewSection {
  statutory_disclaimer: string;
  applicable_building_codes: string[];
  mandatory_review_action: string;
}

export interface HumanReviewRecord {
  review_id: string;
  decision: 'PENDING_REVIEW' | 'HUMAN_VERIFIED' | 'REJECTED' | 'CHANGES_REQUESTED';
  reviewer_id: string;
  comments?: string | null;
  timestamp: string;
}

export interface GeotechnicalAnalysisReport {
  report_id: string;
  document_id: string;
  document_name: string;
  project_id: string;
  run_id?: string | null;
  created_at: string;
  updated_at: string;
  llm_profile_used: string;
  llm_model_used?: string | null;
  llm_provider_used?: string | null;
  review_status: 'PENDING_REVIEW' | 'HUMAN_VERIFIED' | 'REJECTED' | 'CHANGES_REQUESTED';
  review_history: HumanReviewRecord[];
  executive_summary: ExecutiveSummary;
  project_context: ProjectDocumentContext;
  investigation_summary: SoilInvestigationSummary;
  subsurface_conditions: SubsurfaceConditions;
  laboratory_interpretation: LaboratoryInterpretation;
  groundwater_assessment: GroundwaterAssessment;
  foundation_systems: FoundationSystemsInReport;
  foundation_comparison: FoundationComparison;
  site_preparation: SitePreparationSection;
  risks_and_concerns: RisksAndConcerns;
  missing_information: MissingInformationSection;
  questions_for_engineers: QuestionsForEngineerSection;
  evidence_references: EvidenceReferencesSection;
  limitations_and_review: LimitationsAndReviewSection;
  markdown_content: string;
}

// ==============================================================================
// Multimodal Vision Understanding Types
// ==============================================================================

export type PageContentType =
  | 'TEXT_ONLY'
  | 'TEXT_WITH_TABLES'
  | 'IMAGE_ONLY'
  | 'MIXED_TEXT_AND_IMAGES'
  | 'ENGINEERING_DRAWING'
  | 'SITE_PLAN'
  | 'BORING_LOG_DRAWING'
  | 'CHART_OR_GRAPH'
  | 'MAP_OR_LOCATION_DIAGRAM'
  | 'PHOTOGRAPH'
  | 'UNKNOWN';

export interface PageClassificationResult {
  document_id: string;
  page_index: number;
  pdf_page_number: number;
  primary_content_type: PageContentType;
  confidence: number;
  secondary_types: PageContentType[];
  classification_method: string;
  reasoning: string;
  features: Record<string, any>;
}

export interface VisualRegion {
  region_id: string;
  label: string;
  region_type: string;
  bounding_box: BoundingBox;
  confidence: number;
  description?: string | null;
  metadata?: Record<string, any>;
}

export interface VisualEvidence {
  visual_evidence_id: string;
  document_id: string;
  page_index: number;
  pdf_page_number: number;
  printed_page_number?: string | null;
  content_type: PageContentType;
  title_or_caption?: string | null;
  visual_description: string;
  extracted_labels: string[];
  detected_entities: Array<Record<string, any>>;
  structured_findings: Record<string, any>;
  detected_regions: VisualRegion[];
  bounding_box?: BoundingBox | null;
  crop_coordinates?: Record<string, number> | null;
  extraction_method: string;
  vision_model?: string | null;
  confidence_category: 'HIGH' | 'MEDIUM' | 'LOW' | 'DISAGREEMENT';
  review_status: 'PENDING_REVIEW' | 'HUMAN_VERIFIED' | 'REJECTED' | 'CHANGES_REQUESTED';
  human_notes?: string | null;
  verified_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CrossModalDisagreement {
  disagreement_id: string;
  document_id: string;
  page_index: number;
  property_name: string;
  text_value?: string | null;
  table_value?: string | null;
  visual_value?: string | null;
  discrepancy_description: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  status: 'OPEN' | 'RESOLVED' | 'IGNORED';
  resolution_notes?: string | null;
  created_at: string;
  resolved_at?: string | null;
}

// ==============================================================================
// Foundation Research Agent Types (Phase 4)
// ==============================================================================

export type RelevanceClassification =
  | 'RELEVANT_FOR_FURTHER_EVALUATION'
  | 'POTENTIALLY_RELEVANT'
  | 'LIMITED_RELEVANCE'
  | 'INSUFFICIENT_INFORMATION'
  | 'NOT_EVALUATED';

export type AuthorityCategory =
  | 'GOVERNMENT_AGENCY'
  | 'STANDARDS_ORGANIZATION'
  | 'INDUSTRY_ASSOCIATION'
  | 'ACADEMIC_RESEARCH'
  | 'SPECIALTY_CONTRACTOR'
  | 'ENGINEERING_PRACTICE'
  | 'GENERAL_WEB';

export interface ResearchQuery {
  query_id: string;
  topic: string;
  foundation_type?: string;
  query_text: string;
  target_source_types?: string[];
  rationale: string;
}

export interface ResearchSource {
  source_id: string;
  title: string;
  url: string;
  publisher?: string | null;
  publication_date?: string | null;
  last_updated?: string | null;
  access_date?: string | null;
  snippet: string;
  topic?: string | null;
  authority_category: AuthorityCategory;
  claims_supported?: string[];
}

export interface ResearchFinding {
  finding_id: string;
  foundation_type: string;
  topic: string;
  finding_text: string;
  source_ids?: string[];
  confidence_score?: number;
}

export interface FoundationOption {
  name: string;
  category: 'SHALLOW' | 'DEEP';
  mentioned_in_geotech_report: boolean;
  description: string;
  typical_applications: string[];
  soil_compatibility: string;
  bearing_considerations: string;
  settlement_considerations: string;
  groundwater_considerations: string;
  expansive_soil_considerations: string;
  construction_methods: string[];
  equipment_requirements: string[];
  advantages: string[];
  limitations: string[];
  applicable_standards: string[];
  vendor_capabilities: string[];
  relevance_classification: RelevanceClassification;
  relevance_reasoning: string;
  supporting_source_ids: string[];
}

export interface FoundationComparisonItem {
  foundation_type: string;
  category: 'SHALLOW' | 'DEEP';
  typical_application?: string;
  soil_compatibility?: string;
  bearing_considerations: string;
  settlement_considerations: string;
  groundwater_considerations?: string;
  expansive_soil_considerations?: string;
  construction_complexity?: string;
  advantages: string[];
  limitations: string[];
  project_relevance: RelevanceClassification;
  relevance_explanation?: string;
  missing_inputs?: string[];
}

export interface ResearchGap {
  gap_id: string;
  category: string;
  description: string;
  impact: string;
  required_action: string;
}

export interface EngineerQuestionItem {
  question_id: string;
  target_role: string;
  question: string;
  context_reason: string;
}

export interface FoundationResearchReport {
  report_id: string;
  project_id: string;
  document_id: string;
  analysis_report_id?: string | null;
  created_at: string;
  updated_at: string;
  llm_profile_used: string;
  search_provider_used: string;
  review_status: 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED';
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  review_notes?: string | null;
  geotechnical_summary: Record<string, any>;
  confirmed_documents_reviewed: string[];
  research_queries: ResearchQuery[];
  options_researched: FoundationOption[];
  comparisons: FoundationComparisonItem[];
  external_sources: ResearchSource[];
  research_findings: ResearchFinding[];
  research_gaps: ResearchGap[];
  engineer_questions: EngineerQuestionItem[];
  markdown_content: string;
}





// ==============================================================================
// Project Workflow Orchestration Types (Phase 5)
// ==============================================================================

export type ProjectWorkflowStatus = 'PENDING' | 'RUNNING' | 'PAUSED' | 'FAILED' | 'COMPLETED' | 'CANCELLED';
export type ProjectStageStatus = 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'PAUSED' | 'SKIPPED';
export type ProjectStageName =
  | 'DOCUMENT_PROCESSING'
  | 'DOCUMENT_VALIDATION'
  | 'GEOTECHNICAL_ANALYSIS'
  | 'FOUNDATION_RESEARCH'
  | 'WORKFLOW_SUMMARY';

export interface ProjectStageError {
  code: string;
  message: string;
  details: Record<string, any>;
  at: string;
}

export interface ProjectStageRecord {
  name: ProjectStageName;
  label: string;
  status: ProjectStageStatus;
  attempts: number;
  started_at?: string | null;
  completed_at?: string | null;
  execution_id?: string | null;
  reused: boolean;
  output: Record<string, any>;
  error?: ProjectStageError | null;
}

export interface ProjectRetryEntry {
  retry_id: string;
  requested_at: string;
  requested_by: string;
  from_stage: ProjectStageName;
  previous_status: ProjectWorkflowStatus;
  previous_failure?: ProjectStageError | null;
}

export interface ProjectHistoryEvent {
  at: string;
  stage?: ProjectStageName | null;
  event: string;
  message: string;
}

export interface ProjectWorkflowRecord {
  workflow_id: string;
  project_id: string;
  status: ProjectWorkflowStatus;
  current_stage?: ProjectStageName | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at: string;
  search_provider?: string | null;
  confirmed_document_ids: string[];
  primary_document_id?: string | null;
  input_signature?: string | null;
  geotechnical_execution_id?: string | null;
  geotechnical_report_id?: string | null;
  geotechnical_report_reused: boolean;
  foundation_research_execution_id?: string | null;
  foundation_research_report_id?: string | null;
  stages: ProjectStageRecord[];
  failure?: ProjectStageError | null;
  retry_history: ProjectRetryEntry[];
  history: ProjectHistoryEvent[];
  cancel_requested: boolean;
  review_status: string;
  review_requirements: string[];
  summary?: Record<string, any> | null;
}
