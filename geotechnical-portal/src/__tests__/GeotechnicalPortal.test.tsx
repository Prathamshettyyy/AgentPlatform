import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { App } from '../App';
import { portalApi } from '../api/client';
import type {
  DocumentMetadata,
  DocumentProjectAssociation,
  FoundationResearchReport,
  GeotechnicalAnalysisReport,
  RequirementDocument,
  WorkflowRun,
} from '../api/types';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return {
    ...actual,
    portalApi: {
      checkHealth: vi.fn(),
      uploadDocuments: vi.fn(),
      listProjectDocuments: vi.fn(),
      getDocument: vi.fn(),
      getDocumentReadiness: vi.fn(),
      classifyDocumentPages: vi.fn(),
      analyzeVisualPage: vi.fn(),
      getVisualEvidence: vi.fn(),
      matchProjectDocuments: vi.fn(),
      getProjectAssociations: vi.fn(),
      updateAssociationDecision: vi.fn(),
      getConfirmedDocuments: vi.fn(),
      validateProjectDocuments: vi.fn(),
      startGeotechnicalWorkflow: vi.fn(),
      getWorkflowRun: vi.fn(),
      getWorkflowRunEvents: vi.fn(),
      retryWorkflowRun: vi.fn(),
      listWorkflowRuns: vi.fn(),
      getGeotechnicalReportById: vi.fn(),
      getProjectGeotechnicalReport: vi.fn(),
      reviewGeotechnicalReport: vi.fn(),
      getFoundationResearchReportById: vi.fn(),
      getProjectFoundationResearchReport: vi.fn(),
      reviewFoundationResearchReport: vi.fn(),
      getRequirementReportById: vi.fn(),
      getProjectRequirementReport: vi.fn(),
      reviewRequirementReport: vi.fn(),
      getDocumentEvidence: vi.fn(),
      getDocumentTables: vi.fn(),
      getDocumentBoringLogs: vi.fn(),
      getPageImageUrl: vi.fn(
        (docId: string, page: number) => `http://127.0.0.1:8001/v1/documents/${docId}/pages/${page}/image`
      ),
      getOriginalFileUrl: vi.fn(
        (docId: string) => `http://127.0.0.1:8001/v1/documents/${docId}/file`
      ),
    },
  };
});

const MOCK_DOCS: DocumentMetadata[] = [
  {
    document_id: 'doc-soil-25-0117',
    project_id: 'proj_test',
    filename: 'Soil report 25-0117 v1.pdf',
    sha256_hash: 'aaa111222333',
    file_size_bytes: 512000,
    page_count: 22,
    storage_path: 'storage/documents/doc-soil-25-0117/original.pdf',
    status: 'completed',
    readiness_status: 'READY_FOR_ANALYSIS',
    project_info: {
      project_name: 'White Oak Residence',
      site_location: '2432 & 2434 White Oak Drive',
      subdivision: 'White Oak Terrace',
      block: '1',
      lot: '11 & 12',
    },
    created_at: '2026-04-16T10:00:00Z',
    updated_at: '2026-04-16T10:00:00Z',
  },
  {
    document_id: 'doc-site-2436',
    project_id: 'proj_test',
    filename: 'SITE PLAN 2436 White Oak 2026.04.16.pdf',
    sha256_hash: 'bbb444555666',
    file_size_bytes: 256000,
    page_count: 1,
    storage_path: 'storage/documents/doc-site-2436/original.pdf',
    status: 'completed',
    readiness_status: 'READY_FOR_REVIEW',
    project_info: {
      site_location: '2436 White Oak Drive',
      subdivision: 'White Oak Terrace',
      block: '1',
      lot: '11',
    },
    created_at: '2026-04-16T10:00:00Z',
    updated_at: '2026-04-16T10:00:00Z',
  },
  {
    document_id: 'doc-site-2434-mismatch',
    project_id: 'proj_test',
    filename: 'SITE PLAN 2434 WHITE OAK 2026.06.04.pdf',
    sha256_hash: 'ccc777888999',
    file_size_bytes: 240000,
    page_count: 1,
    storage_path: 'storage/documents/doc-site-2434-mismatch/original.pdf',
    status: 'completed',
    readiness_status: 'READY_FOR_REVIEW',
    project_info: {
      site_location: '2434 White Oak Drive',
      subdivision: 'Norhill Park',
      block: '2',
      lot: '8',
    },
    created_at: '2026-04-16T10:00:00Z',
    updated_at: '2026-04-16T10:00:00Z',
  },
];

const INITIAL_ASSOCIATIONS: DocumentProjectAssociation[] = [
  {
    association_id: 'assoc-1',
    project_id: 'proj_test',
    document_id: 'doc-soil-25-0117',
    filename: 'Soil report 25-0117 v1.pdf',
    match_status: 'MATCHED',
    confidence_score: 0.95,
    match_reasons: ['Subdivision White Oak Terrace matches', 'Lots 11 & 12 match'],
    conflict_reasons: [],
    field_comparisons: [],
    user_decision: 'CONFIRMED',
  },
  {
    association_id: 'assoc-2',
    project_id: 'proj_test',
    document_id: 'doc-site-2436',
    filename: 'SITE PLAN 2436 White Oak 2026.04.16.pdf',
    match_status: 'POSSIBLE_MATCH',
    confidence_score: 0.7,
    match_reasons: ['Same subdivision White Oak Terrace and Block 1'],
    conflict_reasons: ['Street number 2436 vs 2432 & 2434'],
    field_comparisons: [],
    user_decision: 'PENDING',
  },
  {
    association_id: 'assoc-3',
    project_id: 'proj_test',
    document_id: 'doc-site-2434-mismatch',
    filename: 'SITE PLAN 2434 WHITE OAK 2026.06.04.pdf',
    match_status: 'MISMATCH',
    confidence_score: 0.15,
    match_reasons: [],
    conflict_reasons: ['Subdivision conflict: Norhill Park vs White Oak Terrace'],
    field_comparisons: [],
    user_decision: 'PENDING',
  },
];

const MOCK_GEOTECH_REPORT: GeotechnicalAnalysisReport = {
  report_id: 'geotech_rpt_white_oak_001',
  project_id: 'proj_test',
  primary_document_id: 'doc-soil-25-0117',
  confirmed_document_ids: ['doc-soil-25-0117', 'doc-site-2436'],
  excluded_document_ids: ['doc-site-2434-mismatch'],
  project_summary: {},
  executive_overview:
    'Subsurface exploration encountered expansive fat clay (CH) and lean clay (CL) to 15 ft.',
  soil_classifications: [
    {
      stratum_name: 'Stratum I — Fat Clay',
      uscs_symbol: 'CH',
      depth_range_ft: '0 - 8 ft',
      description: 'Dark gray highly plastic expansive clay',
      plasticity_classification: 'High (PI 34-42)',
      swell_potential: 'High',
      boring_ids: ['B-1', 'B-2'],
      citations: [{ document_id: 'doc-soil-25-0117', page_numbers: [5, 11] }],
    },
  ],
  laboratory_findings: {
    liquid_limit_range: '52% - 68%',
    plasticity_index_range: '34 - 42',
    moisture_content_range_pct: '18% - 26%',
    undrained_shear_strength_ksf_range: '1.2 - 2.4 ksf',
    notable_test_results: ['High plasticity CH clay in upper 8 ft active zone'],
    citations: [],
  },
  groundwater_conditions: {
    groundwater_observed: false,
    encountered_depth_ft: 'Not encountered to 15 ft',
    stabilized_depth_ft: 'None',
    boring_observations: ['Dry during drilling'],
    seepage_and_seasonal_notes: 'Perched water possible during wet seasons.',
    citations: [],
  },
  potential_vertical_rise_pvr: {
    pvr_value_in: '2.5 to 3.2 inches',
    assumed_moisture_condition: 'Dry to Wet seasonal fluctuation',
    affected_depth_zone_ft: '0 to 10 ft',
    mitigation_options: ['Underreamed drilled piers', 'Post-tensioned slab with moisture barrier'],
    citations: [],
  },
  foundation_systems_in_report: [
    {
      system_name: 'Underreamed Drilled Piers',
      bearing_stratum: 'Stiff Sandy Clay below 10 ft',
      minimum_depth_ft: 10,
      allowable_bearing_pressure_psf: 3500,
      design_notes: ['Provide 6-inch void boxes beneath grade beams'],
      citations: [],
    },
  ],
  bearing_parameters: [
    {
      parameter_name: 'Net Allowable End Bearing Pressure',
      value: '3500',
      unit: 'psf',
      applicable_depth_or_stratum: '10 ft depth',
      foundation_type: 'Underreamed Drilled Piers',
      citations: [],
    },
  ],
  site_preparation_requirements: [
    {
      topic: 'Subgrade Stripping & Drainage',
      requirement_summary: 'Strip top 6 inches of organic topsoil and provide positive drainage.',
      specifications: ['Minimum 5% slope away from building perimeter for 10 ft'],
      citations: [],
    },
  ],
  geotechnical_risks: [
    {
      risk_category: 'Expansive Soil Swell / Shrinkage',
      severity: 'HIGH',
      description: 'High PI fat clay (CH) causes differential movement.',
      engineering_implication: 'Requires isolation or stiffened foundation system.',
      citations: [],
    },
  ],
  missing_or_unclear_information: ['Final structural column loads not specified on site plan.'],
  questions_for_engineers: ['Will void forms be used under residential grade beams?'],
  cross_document_notes: [],
  model_used: 'deterministic+qwen3',
  confidence_score: 0.94,
  review_status: 'PENDING_REVIEW',
  created_at: '2026-04-16T10:05:00Z',
};

const MOCK_FOUNDATION_REPORT: FoundationResearchReport = {
  research_report_id: 'found_res_white_oak_001',
  project_id: 'proj_test',
  geotechnical_report_id: 'geotech_rpt_white_oak_001',
  primary_document_id: 'doc-soil-25-0117',
  confirmed_document_ids: ['doc-soil-25-0117', 'doc-site-2436'],
  site_condition_context: {},
  executive_research_summary:
    'Comparative evaluation of underreamed drilled piers and PTI post-tensioned slabs on expansive clay.',
  foundation_technologies: [
    {
      technology_id: 'tech-1',
      name: 'Underreamed Belled Drilled Shafts',
      category: 'DEEP',
      mentioned_in_geotechnical_report: true,
      technical_explanation: 'Bears below the active moisture fluctuation zone.',
      load_transfer_mechanism: 'End bearing in stable stratum + uplift bell anchorage.',
      applicable_soil_conditions: 'Cohesive stiff clays capable of standing open during belling.',
      constructability_considerations: ['Verify no caving seams at bell depth'],
      advantages: ['Minimizes differential seasonal movement'],
      limitations_and_risks: ['Higher cost and requires carton void forms'],
      expansive_clay_performance: 'Excellent when founded below active zone.',
      citations: [],
    },
  ],
  comparison_matrix: [
    {
      foundation_name: 'Underreamed Belled Drilled Shafts',
      category: 'DEEP',
      mentioned_in_report: true,
      expansive_soil_suitability: 'High',
      relative_settlement_control: 'Superior (< 0.5 in)',
      relative_construction_complexity: 'Moderate-High',
      typical_depth_range: '10 - 15 ft',
      key_tradeoff: 'Higher cost vs superior swell isolation',
    },
  ],
  project_relevance_analysis: [
    {
      foundation_name: 'Underreamed Belled Drilled Shafts',
      relevance_classification: 'PRIMARY_CANDIDATE',
      alignment_with_site_conditions: 'Directly isolates structure from 2.5+ in PVR clay.',
      geotechnical_report_parameters_referenced: ['3,500 psf net allowable bearing at 10 ft'],
      engineering_verification_needed: ['Verify bell stability during test shaft'],
    },
  ],
  research_sources: [
    {
      source_id: 'src-fhwa',
      title: 'FHWA GEC 10 — Drilled Shafts: Construction Procedures and Design Methods',
      organization_or_author: 'Federal Highway Administration (FHWA)',
      publication_or_standard: 'FHWA-NHI-10-016',
      year: '2018',
      url: 'https://www.fhwa.dot.gov/engineering/geotech/',
    },
  ],
  research_gaps: ['Site-specific swell pressure consolidation test not performed.'],
  questions_for_foundation_engineers: ['Confirm minimum pier spacing and void form height.'],
  disclaimer:
    'AI-generated engineering reports require qualified professional review and are not approved construction designs.',
  model_used: 'deterministic+qwen3',
  confidence_score: 0.93,
  review_status: 'PENDING_REVIEW',
  created_at: '2026-04-16T10:06:00Z',
};

const MOCK_REQUIREMENT_REPORT: RequirementDocument = {
  report_id: 'req_white_oak_001',
  project_id: 'proj_test',
  document_id: 'doc-soil-25-0117',
  geotechnical_report_id: 'geotech_rpt_white_oak_001',
  geotechnical_report_review_status: 'PENDING_REVIEW',
  foundation_research_report_id: 'found_res_white_oak_001',
  foundation_research_report_review_status: 'PENDING_REVIEW',
  confirmed_document_ids: ['doc-soil-25-0117', 'doc-site-2436'],
  snapshot_id: 'snap_white_oak_001',
  document_versions: {},
  created_at: '2026-04-16T10:07:00Z',
  updated_at: '2026-04-16T10:07:00Z',
  review_status: 'PENDING_REVIEW',
  is_preliminary_draft: true,
  suitable_for_contractual_issuance: false,
  issuance_status_banner:
    'UNAPPROVED PRELIMINARY DRAFT — NOT SUITABLE FOR CONSTRUCTION OR CONTRACTUAL ISSUANCE WITHOUT P.E. APPROVAL',
  section_1_project_overview: {
    project_name: '2436 White Oak Residence',
    project_number: '25-0117',
    site_address: '2436 White Oak Drive, Houston, TX',
    associated_source_documents: ['Soil report 25-0117 v1.pdf'],
    confirmed_document_ids: ['doc-soil-25-0117', 'doc-site-2436'],
    report_generation_date: '2026-04-16T10:07:00Z',
    geotechnical_report_id: 'geotech_rpt_white_oak_001',
    geotechnical_report_review_status: 'PENDING_REVIEW',
    foundation_research_report_id: 'found_res_white_oak_001',
    foundation_research_report_review_status: 'PENDING_REVIEW',
  },
  section_2_geotechnical_conditions: {
    dominant_soil_description: 'SANDY LEAN CLAY (CL)',
    uscs_classification: 'CL',
    boring_summary: '2 borings to 20.0 ft',
    laboratory_properties_summary: 'LL 29-47%, PI 12-29',
    liquid_limit_range: '29% - 47%',
    plasticity_index_range: '12 - 29',
    moisture_content_range: '9.9% - 22.8%',
    passing_no_200_range: '57% - 76%',
    pocket_penetrometer_range_tsf: '1.0 - 4.5 tsf',
    spt_status: 'NOT_REPORTED',
    groundwater_summary: 'Encountered at 14.0 - 15.4 ft',
    groundwater_depth_range_ft: '14.0 - 15.4 ft',
    pvr_value_inches: 1.2,
    shrink_swell_potential: 'MODERATE',
    pvr_implications_for_vendors: 'Requires select fill or voided grade beams',
    site_conditions_and_constraints: [],
    supporting_report_id: 'geotech_rpt_white_oak_001',
    evidence_ids: [],
  },
  section_3_foundation_systems: [],
  section_4_vendor_scope_of_work: [],
  section_5_technical_requirements: [
    {
      requirement_id: 'REQ-TECH-03',
      category: 'SELECT_FILL_CRITERIA',
      title: 'Select Fill Plasticity Index (PI) and Liquid Limit (LL) Specification',
      specification_text: 'Inactive lean clays or clayey sands (LL <= 35, PI 8 to 20).',
      numerical_value: 'LL <= 35, PI 8 to 20',
      units: '%',
      source_classification: 'GEOTECHNICAL_SOURCE_REQUIREMENT',
      supporting_report_id: 'geotech_rpt_white_oak_001',
      pdf_page_reference: 'PDF Pages 6-7',
      evidence_ids: ['ev_01'],
      requires_engineer_confirmation: false,
    },
  ],
  section_6_quality_and_documentation: [],
  section_7_vendor_proposal_requirements: [],
  section_8_risks_and_precautions: [],
  section_9_missing_information: [],
  section_10_vendor_response_checklist: [],
  section_11_references_and_evidence: [],
  section_12_limitations_and_approval: {
    is_preliminary_unapproved_draft: true,
    suitable_for_construction_or_contractual_issuance: false,
    upstream_reports_review_summary: 'Preliminary draft',
    statutory_disclaimer: 'Preliminary draft requiring licensed P.E. review.',
    required_professional_approvals: [],
  },
  provenance_summary: {
    GEOTECHNICAL_SOURCE_REQUIREMENT: 12,
    EXTERNAL_RESEARCH_REFERENCE: 3,
    PROPOSED_VENDOR_SUBMITTAL: 16,
    AI_DRAFTED_SCOPE: 2,
    ENGINEER_CONFIRMATION_REQUIRED: 9,
  },
  markdown_content: '# VENDOR FOUNDATION REQUIREMENT DOCUMENT',
};

describe('Standalone Geotechnical Analysis Web Application', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    window.history.replaceState({}, '', '/');

    vi.mocked(portalApi.checkHealth).mockResolvedValue({
      status: 'healthy',
      service: 'agent-platform',
      auth_mode: 'development',
      version: '1.0.0',
    });
  });

  it('validates file uploads, pauses for human confirmation on POSSIBLE_MATCH / MISMATCH, executes workflow, and renders final reports', async () => {
    vi.mocked(portalApi.uploadDocuments).mockResolvedValue(MOCK_DOCS);
    vi.mocked(portalApi.classifyDocumentPages).mockResolvedValue([
      {
        document_id: 'doc-site-2436',
        page_number: 1,
        page_type: 'SITE_PLAN',
        confidence: 0.96,
        reasoning: 'Site plan drawing',
        has_raster_images: true,
        vector_drawing_density: 0.8,
        requires_vlm: true,
      },
    ]);
    vi.mocked(portalApi.analyzeVisualPage).mockResolvedValue({
      visual_evidence_id: 'vis-1',
      document_id: 'doc-site-2436',
      page_number: 1,
      page_type: 'SITE_PLAN',
      summary: 'Proposed two-story residence on Lot 11 Block 1 White Oak Terrace',
      confidence: 0.95,
      model_used: 'ollama/qwen3-vl:2b',
      extracted_entities: {},
      detected_labels: ['SITE_PLAN'],
      key_findings: ['Lot 11 Block 1'],
      review_status: 'PENDING_REVIEW',
      created_at: '2026-04-16T10:01:00Z',
    });

    vi.mocked(portalApi.matchProjectDocuments).mockResolvedValue({
      project_id: 'proj_test',
      total_evaluated: 3,
      matched_count: 1,
      possible_match_count: 1,
      mismatch_count: 1,
      associations: INITIAL_ASSOCIATIONS,
    });

    vi.mocked(portalApi.getDocumentReadiness).mockImplementation(async (docId) => ({
      document_id: docId,
      project_id: 'proj_test',
      filename: docId,
      document_status: 'completed',
      readiness_status:
        docId === 'doc-soil-25-0117' ? 'READY_FOR_ANALYSIS' : 'READY_FOR_REVIEW',
      sha256_hash: 'hash123',
    }));

    render(<App />);

    // Enter project details
    fireEvent.change(screen.getByLabelText(/Project Name/i), {
      target: { value: '2436 White Oak Residence' },
    });
    fireEvent.change(screen.getByLabelText(/Project Location/i), {
      target: { value: '2436 White Oak Drive, Houston, TX' },
    });

    // Add 3 files via file input
    const fileInput = screen.getByTestId('file-input');
    const f1 = new File(['%PDF-1.4 soil'], 'Soil report 25-0117 v1.pdf', {
      type: 'application/pdf',
    });
    const f2 = new File(['%PDF-1.4 site2436'], 'SITE PLAN 2436 White Oak 2026.04.16.pdf', {
      type: 'application/pdf',
    });
    const f3 = new File(['%PDF-1.4 site2434'], 'SITE PLAN 2434 WHITE OAK 2026.06.04.pdf', {
      type: 'application/pdf',
    });

    fireEvent.change(fileInput, { target: { files: [f1, f2, f3] } });

    expect(screen.getByText('Soil report 25-0117 v1.pdf')).toBeInTheDocument();
    expect(screen.getByText('SITE PLAN 2436 White Oak 2026.04.16.pdf')).toBeInTheDocument();
    expect(screen.getByText('SITE PLAN 2434 WHITE OAK 2026.06.04.pdf')).toBeInTheDocument();

    // Click Start Project Analysis
    fireEvent.click(screen.getByTestId('start-analysis-button'));

    // Wait for Processing screen & Human Confirmation Gate
    await waitFor(() => {
      expect(screen.getByTestId('human-confirmation-gate')).toBeInTheDocument();
    });

    // Stage 4 should be NEEDS_REVIEW and Stage 5 should be BLOCKED
    expect(screen.getByTestId('stage-status-validate')).toHaveTextContent('NEEDS_REVIEW');
    expect(screen.getByTestId('stage-status-geotechnical_agent')).toHaveTextContent('BLOCKED');

    // Confirm 2436 Site Plan and Reject 2434 Site Plan
    const updatedAssocs: DocumentProjectAssociation[] = INITIAL_ASSOCIATIONS.map((a) => {
      if (a.document_id === 'doc-site-2436') return { ...a, user_decision: 'CONFIRMED' };
      if (a.document_id === 'doc-site-2434-mismatch') return { ...a, user_decision: 'REJECTED' };
      return a;
    });

    vi.mocked(portalApi.updateAssociationDecision).mockResolvedValue(updatedAssocs[1]);
    vi.mocked(portalApi.getProjectAssociations).mockResolvedValue(updatedAssocs);

    fireEvent.click(screen.getByTestId('confirm-assoc-doc-site-2436'));

    await waitFor(() => {
      expect(screen.getByTestId('proceed-workflow-btn')).not.toBeDisabled();
    });

    // Set up mocks for workflow execution & report retrieval
    vi.mocked(portalApi.getConfirmedDocuments).mockResolvedValue({
      project_id: 'proj_test',
      confirmed_count: 2,
      confirmed_document_ids: ['doc-soil-25-0117', 'doc-site-2436'],
    });
    vi.mocked(portalApi.validateProjectDocuments).mockResolvedValue({
      project_id: 'proj_test',
      is_valid: true,
      status: 'succeeded',
      validated_document_ids: ['doc-soil-25-0117', 'doc-site-2436'],
      primary_document_id: 'doc-soil-25-0117',
      document_versions: {},
      snapshot: {
        snapshot_id: 'snap_white_oak_001',
        project_id: 'proj_test',
        primary_geotechnical_document_id: 'doc-soil-25-0117',
        confirmed_document_ids: ['doc-soil-25-0117', 'doc-site-2436'],
        validation_status: 'VALID',
        created_at: '2026-04-16T10:02:00Z',
      },
      validation_errors: [],
      message: 'All project documents validated successfully.',
    });

    const completedRun: WorkflowRun = {
      run_id: 'run-white-oak-12345',
      workflow_id: 'geotechnical_foundation_investigation',
      status: 'succeeded',
      output: {
        node_outputs: {
          validate_project_documents_node: {
            snapshot: { snapshot_id: 'snap_white_oak_001' },
          },
          geotechnical_analysis_node: {
            geotechnical_report_id: 'geotech_rpt_white_oak_001',
          },
          foundation_research_node: {
            foundation_research_report_id: 'found_res_white_oak_001',
          },
          requirement_agent_node: {
            report_id: 'req_white_oak_001',
          },
        },
      },
    };

    vi.mocked(portalApi.startGeotechnicalWorkflow).mockResolvedValue(completedRun);
    vi.mocked(portalApi.getWorkflowRun).mockResolvedValue(completedRun);
    vi.mocked(portalApi.getWorkflowRunEvents).mockResolvedValue([
      {
        run_id: 'run-white-oak-12345',
        node_id: 'validate_project_documents_node',
        status: 'succeeded',
        payload: {},
      },
      {
        run_id: 'run-white-oak-12345',
        node_id: 'geotechnical_analysis_node',
        status: 'succeeded',
        payload: { report_id: 'geotech_rpt_white_oak_001' },
      },
      {
        run_id: 'run-white-oak-12345',
        node_id: 'foundation_research_node',
        status: 'succeeded',
        payload: { research_report_id: 'found_res_white_oak_001' },
      },
      {
        run_id: 'run-white-oak-12345',
        node_id: 'requirement_agent_node',
        status: 'succeeded',
        payload: { report_id: 'req_white_oak_001' },
      },
    ]);
    vi.mocked(portalApi.getGeotechnicalReportById).mockResolvedValue(MOCK_GEOTECH_REPORT);
    vi.mocked(portalApi.getFoundationResearchReportById).mockResolvedValue(MOCK_FOUNDATION_REPORT);
    vi.mocked(portalApi.getRequirementReportById).mockResolvedValue(MOCK_REQUIREMENT_REPORT);
    vi.mocked(portalApi.getProjectRequirementReport).mockResolvedValue(MOCK_REQUIREMENT_REPORT);
    vi.mocked(portalApi.getDocumentEvidence).mockResolvedValue([]);
    vi.mocked(portalApi.getDocumentBoringLogs).mockResolvedValue([]);
    vi.mocked(portalApi.getVisualEvidence).mockResolvedValue([]);

    // Proceed into workflow
    fireEvent.click(screen.getByTestId('proceed-workflow-btn'));

    await waitFor(() => {
      expect(screen.getByTestId('view-final-results-btn')).toBeInTheDocument();
    });

    // Open Final Results page — displays Vendor Foundation Requirement Document as the primary deliverable
    fireEvent.click(screen.getByTestId('view-final-results-btn'));

    // Verify Statutory Disclaimer & Vendor Requirement Deliverable
    expect(screen.getByTestId('engineering-disclaimer-banner')).toBeInTheDocument();
    expect(screen.getByTestId('vendor-requirement-section')).toBeInTheDocument();
    expect(screen.getAllByText('Vendor Foundation Requirement Summary').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/LL <= 35, PI 8 to 20/i).length).toBeGreaterThan(0);
    expect(screen.getByTestId('download-requirement-markdown')).toBeInTheDocument();
    expect(screen.getByTestId('download-requirement-json')).toBeInTheDocument();

    // Verify Upstream Agent Audit Traceability (Agent 1 & Agent 2) can be inspected via audit drawer
    const auditToggle = screen.getByText(/Internal Agent Audit Traceability/i);
    fireEvent.click(auditToggle);
    expect(screen.getByTestId('geotechnical-analysis-section')).toBeInTheDocument();
    expect(screen.getByText('Stratum I — Fat Clay')).toBeInTheDocument();
    expect(screen.getByText('2.5 to 3.2 inches')).toBeInTheDocument();

    // Inspect Agent 2 Foundation Research in the audit drawer
    fireEvent.click(screen.getByTestId('tab-foundation'));
    expect(screen.getByTestId('foundation-research-section')).toBeInTheDocument();
    expect(screen.getAllByText('Underreamed Belled Drilled Shafts').length).toBeGreaterThan(0);
  });

  it('rejects unsupported file types and allows removing staged files before submitting', async () => {
    render(<App />);

    const fileInput = screen.getByTestId('file-input');
    const badFile = new File(['bad'], 'malware.exe', { type: 'application/octet-stream' });
    const validImg = new File(['\x89PNG\r\n\x1a\n'], 'site_photo.png', { type: 'image/png' });

    fireEvent.change(fileInput, { target: { files: [badFile, validImg] } });

    expect(screen.getByRole('alert')).toHaveTextContent(/unsupported format/i);
    expect(screen.getByText('site_photo.png')).toBeInTheDocument();

    // Remove the staged file
    fireEvent.click(screen.getByLabelText('Remove site_photo.png'));
    expect(screen.queryByText('site_photo.png')).not.toBeInTheDocument();
  });

  it('displays failed stage error details and supports retrying via workflow retry endpoint', async () => {
    vi.mocked(portalApi.uploadDocuments).mockResolvedValue([MOCK_DOCS[0]]);
    vi.mocked(portalApi.classifyDocumentPages).mockResolvedValue([]);
    vi.mocked(portalApi.matchProjectDocuments).mockResolvedValue({
      project_id: 'proj_retry',
      total_evaluated: 1,
      matched_count: 1,
      possible_match_count: 0,
      mismatch_count: 0,
      associations: [INITIAL_ASSOCIATIONS[0]],
    });
    vi.mocked(portalApi.getDocumentReadiness).mockResolvedValue({
      document_id: 'doc-soil-25-0117',
      project_id: 'proj_retry',
      filename: 'Soil report 25-0117 v1.pdf',
      document_status: 'completed',
      readiness_status: 'READY_FOR_ANALYSIS',
      sha256_hash: 'aaa111222333',
    });
    vi.mocked(portalApi.getConfirmedDocuments).mockResolvedValue({
      project_id: 'proj_retry',
      confirmed_count: 1,
      confirmed_document_ids: ['doc-soil-25-0117'],
    });
    vi.mocked(portalApi.validateProjectDocuments).mockResolvedValue({
      project_id: 'proj_retry',
      is_valid: true,
      status: 'succeeded',
      validated_document_ids: ['doc-soil-25-0117'],
      primary_document_id: 'doc-soil-25-0117',
      document_versions: {},
      validation_errors: [],
      message: 'Valid',
    });

    const failedRun: WorkflowRun = {
      run_id: 'run-failed-99',
      workflow_id: 'geotechnical_foundation_investigation',
      status: 'failed',
      output: {
        error: 'Simulated agent runtime timeout on geotechnical_analysis_node',
        node_outputs: {
          validate_project_documents_node: { status: 'succeeded' },
        },
      },
    };
    vi.mocked(portalApi.startGeotechnicalWorkflow).mockResolvedValue(failedRun);
    vi.mocked(portalApi.getWorkflowRun).mockResolvedValue(failedRun);
    vi.mocked(portalApi.getWorkflowRunEvents).mockResolvedValue([]);

    render(<App />);

    fireEvent.change(screen.getByLabelText(/Project Name/i), {
      target: { value: 'Retry Test Project' },
    });
    fireEvent.change(screen.getByLabelText(/Project Location/i), {
      target: { value: '2432 White Oak Drive' },
    });
    fireEvent.change(screen.getByTestId('file-input'), {
      target: {
        files: [new File(['%PDF-1.4 soil'], 'Soil report 25-0117 v1.pdf', { type: 'application/pdf' })],
      },
    });
    fireEvent.click(screen.getByTestId('start-analysis-button'));

    await waitFor(() => {
      expect(screen.getByTestId('stage-failure-banner')).toBeInTheDocument();
    });
    expect(screen.getByTestId('stage-failure-banner')).toHaveTextContent(
      /Simulated agent runtime timeout/i
    );

    // Trigger retry
    const retriedRun: WorkflowRun = {
      run_id: 'run-failed-99',
      workflow_id: 'geotechnical_foundation_investigation',
      status: 'succeeded',
      output: {
        retry_count: 1,
        node_outputs: {
          validate_project_documents_node: { status: 'succeeded' },
          geotechnical_analysis_node: { geotechnical_report_id: 'geotech_rpt_white_oak_001' },
          foundation_research_node: { foundation_research_report_id: 'found_res_white_oak_001' },
        },
      },
    };
    vi.mocked(portalApi.retryWorkflowRun).mockResolvedValue(retriedRun);
    vi.mocked(portalApi.getGeotechnicalReportById).mockResolvedValue(MOCK_GEOTECH_REPORT);
    vi.mocked(portalApi.getFoundationResearchReportById).mockResolvedValue(MOCK_FOUNDATION_REPORT);

    fireEvent.click(screen.getByTestId('retry-workflow-btn'));

    await waitFor(() => {
      expect(portalApi.retryWorkflowRun).toHaveBeenCalledWith('run-failed-99');
      expect(screen.getByTestId('view-final-results-btn')).toBeInTheDocument();
    });
  });

  it('auto-detects project name and site address from the uploaded soil report when left blank', async () => {
    vi.mocked(portalApi.uploadDocuments).mockResolvedValue([MOCK_DOCS[0]]);
    vi.mocked(portalApi.classifyDocumentPages).mockResolvedValue([]);
    vi.mocked(portalApi.matchProjectDocuments).mockResolvedValue({
      project_id: 'proj_auto',
      total_evaluated: 1,
      matched_count: 1,
      possible_match_count: 0,
      mismatch_count: 0,
      associations: [INITIAL_ASSOCIATIONS[0]],
    });
    vi.mocked(portalApi.getDocumentReadiness).mockResolvedValue({
      document_id: 'doc-soil-25-0117',
      project_id: 'proj_auto',
      filename: 'Soil report 25-0117 v1.pdf',
      document_status: 'completed',
      readiness_status: 'READY_FOR_ANALYSIS',
      sha256_hash: 'aaa111222333',
    });
    vi.mocked(portalApi.getConfirmedDocuments).mockResolvedValue({
      project_id: 'proj_auto',
      confirmed_count: 1,
      confirmed_document_ids: ['doc-soil-25-0117'],
    });
    vi.mocked(portalApi.validateProjectDocuments).mockResolvedValue({
      project_id: 'proj_auto',
      is_valid: true,
      status: 'succeeded',
      validated_document_ids: ['doc-soil-25-0117'],
      primary_document_id: 'doc-soil-25-0117',
      document_versions: {},
      validation_errors: [],
      message: 'Valid',
    });
    vi.mocked(portalApi.startGeotechnicalWorkflow).mockResolvedValue({
      run_id: 'run-auto-1',
      workflow_id: 'geotechnical_foundation_investigation',
      status: 'running',
    });
    vi.mocked(portalApi.getWorkflowRun).mockResolvedValue({
      run_id: 'run-auto-1',
      workflow_id: 'geotechnical_foundation_investigation',
      status: 'running',
    });
    vi.mocked(portalApi.getWorkflowRunEvents).mockResolvedValue([]);

    render(<App />);

    // Do NOT type Project Name or Project Location — only attach the Soil Report
    fireEvent.change(screen.getByTestId('file-input'), {
      target: {
        files: [
          new File(['%PDF-1.4 soil'], 'Soil report 25-0117 v1.pdf', {
            type: 'application/pdf',
          }),
        ],
      },
    });

    fireEvent.click(screen.getByTestId('start-analysis-button'));

    await waitFor(() => {
      expect(portalApi.matchProjectDocuments).toHaveBeenCalledWith(
        expect.objectContaining({
          project_name: 'White Oak Residence (2432 & 2434 White Oak Drive)',
          site_address: '2432 & 2434 White Oak Drive',
          subdivision: 'White Oak Terrace',
          block_number: '1',
          lot_number: '11 & 12',
        })
      );
    });
  });
});
