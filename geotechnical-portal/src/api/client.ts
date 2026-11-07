import type {
  BoringLogReference,
  DocumentMetadata,
  DocumentProjectAssociation,
  DocumentReadinessResponse,
  EvidenceRecord,
  ExtractedTable,
  FoundationResearchReport,
  GeotechnicalAnalysisReport,
  PageClassificationResult,
  ProjectDocumentValidationResult,
  ProjectProfile,
  RequirementDocument,
  UserDecision,
  VisualEvidenceRecord,
  WorkflowRun,
  WorkflowRunEvent,
} from './types';

const STORAGE_API_URL_KEY = 'geostrata_api_base_url';
const STORAGE_AUTH_TOKEN_KEY = 'geostrata_api_auth_token';

export function getApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    const saved = window.localStorage.getItem(STORAGE_API_URL_KEY);
    if (saved && saved.trim()) {
      const cleanSaved = saved.trim().replace(/\/+$/, '');
      // Automatically migrate legacy pre-separation port 8000 to GeoStrata port 8001
      if (cleanSaved === 'http://127.0.0.1:8000' || cleanSaved === 'http://localhost:8000') {
        window.localStorage.setItem(STORAGE_API_URL_KEY, 'http://127.0.0.1:8001');
        return 'http://127.0.0.1:8001';
      }
      return cleanSaved;
    }
  }
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  if (envUrl && typeof envUrl === 'string' && envUrl.trim()) {
    return envUrl.trim().replace(/\/+$/, '');
  }
  return 'http://127.0.0.1:8001';
}

export function setApiBaseUrl(url: string): void {
  if (typeof window !== 'undefined') {
    if (url.trim()) {
      window.localStorage.setItem(STORAGE_API_URL_KEY, url.trim().replace(/\/+$/, ''));
    } else {
      window.localStorage.removeItem(STORAGE_API_URL_KEY);
    }
  }
}

export function getAuthToken(): string {
  if (typeof window !== 'undefined') {
    const saved = window.localStorage.getItem(STORAGE_AUTH_TOKEN_KEY);
    if (saved && saved.trim()) {
      return saved.trim();
    }
  }
  const envToken = import.meta.env.VITE_API_AUTH_TOKEN;
  if (envToken && typeof envToken === 'string' && envToken.trim()) {
    return envToken.trim();
  }
  return '';
}

export function setAuthToken(token: string): void {
  if (typeof window !== 'undefined') {
    if (token.trim()) {
      window.localStorage.setItem(STORAGE_AUTH_TOKEN_KEY, token.trim());
    } else {
      window.localStorage.removeItem(STORAGE_AUTH_TOKEN_KEY);
    }
  }
}

export function getAgentPlatformUiUrl(): string {
  const envUi = import.meta.env.VITE_AGENT_PLATFORM_UI_URL;
  if (envUi && typeof envUi === 'string' && envUi.trim()) {
    return envUi.trim().replace(/\/+$/, '');
  }
  return 'http://localhost:5173';
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}${path.startsWith('/') ? path : `/${path}`}`;
  const token = getAuthToken();

  const headers = new Headers(init.headers || {});
  if (!(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', token.startsWith('Bearer ') ? token : `Bearer ${token}`);
  }

  const response = await fetch(url, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const errBody = await response.json();
      detail = errBody.detail || errBody.message || errBody.error || JSON.stringify(errBody);
    } catch {
      const txt = await response.text().catch(() => '');
      if (txt) detail = txt;
    }
    throw new Error(`API Error (${response.status}): ${detail}`);
  }

  return response.json() as Promise<T>;
}

// Normalize backend GeotechnicalAnalysisReport schema into portal UI model
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function normalizeGeotechnicalReport(raw: any): GeotechnicalAnalysisReport {
  if (!raw) throw new Error('Empty geotechnical report response');
  if (Array.isArray(raw.soil_classifications) && raw.laboratory_findings) {
    return raw as GeotechnicalAnalysisReport;
  }

  const strata = Array.isArray(raw.subsurface_conditions?.strata)
    ? raw.subsurface_conditions.strata
    : [];
  const lab = raw.laboratory_interpretation || {};
  const gw = raw.groundwater_assessment || {};
  const fndSysObj = raw.foundation_systems || {};
  const fndList = [
    fndSysObj.post_tensioned_slabs,
    fndSysObj.drilled_underreamed_piers,
    fndSysObj.continuous_footings_grade_beams,
    fndSysObj.slab_on_grade_floor,
  ].filter(Boolean);

  // Extract bearing parameters across foundation systems
  const bearingParams: GeotechnicalAnalysisReport['bearing_parameters'] = [];
  fndList.forEach((sys) => {
    if (Array.isArray(sys.allowable_bearing_pressures)) {
      sys.allowable_bearing_pressures.forEach((bp: Record<string, unknown>) => {
        bearingParams.push({
          parameter_name: String(bp.parameter || bp.type || bp.name || sys.system_name),
          value: String(bp.value ?? bp.pressure ?? 'See report'),
          unit: bp.unit ? String(bp.unit) : undefined,
          applicable_depth_or_stratum: bp.conditions
            ? String(bp.conditions)
            : sys.embedment_depth_ft
            ? `${sys.embedment_depth_ft} ft depth`
            : undefined,
          foundation_type: sys.system_name,
          citations: [],
        });
      });
    }
  });

  const siteSpecs = Array.isArray(raw.site_preparation?.specifications)
    ? raw.site_preparation.specifications
    : [];
  const risks = Array.isArray(raw.risks_and_concerns?.identified_risks)
    ? raw.risks_and_concerns.identified_risks
    : [];
  const missingItems = Array.isArray(raw.missing_information?.items)
    ? raw.missing_information.items
    : [];
  const questions = Array.isArray(raw.questions_for_engineers?.questions)
    ? raw.questions_for_engineers.questions
    : [];

  return {
    report_id: raw.report_id,
    project_id: raw.project_id || 'default',
    primary_document_id: raw.document_id || '',
    confirmed_document_ids: Array.isArray(raw.project_context?.documents_reviewed)
      ? raw.project_context.documents_reviewed
      : [raw.document_id].filter(Boolean),
    excluded_document_ids: [],
    project_summary: raw.project_context || {},
    executive_overview:
      raw.executive_summary?.overview ||
      raw.subsurface_conditions?.consistency_summary ||
      'Geotechnical analysis completed.',
    soil_classifications: strata.map((s: Record<string, unknown>) => ({
      stratum_name: `${s.boring_id || 'Boring'} (${s.depth_range_ft || ''})`,
      uscs_symbol: String(
        s.uscs_classification || raw.subsurface_conditions?.uscs_group_symbol || 'CL'
      ),
      depth_range_ft: String(s.depth_range_ft || ''),
      description: String(s.description || ''),
      plasticity_classification: String(s.consistency || ''),
      swell_potential: String(lab.shrink_swell_potential || 'MODERATE'),
      boring_ids: [String(s.boring_id || 'B-1')],
      citations: [],
    })),
    laboratory_findings: {
      liquid_limit_range: lab.liquid_limit_range || 'N/A',
      plasticity_index_range: lab.plasticity_index_range || 'N/A',
      moisture_content_range_pct: lab.moisture_content_range || 'N/A',
      undrained_shear_strength_ksf_range: lab.pocket_penetrometer_range_tsf || 'N/A',
      percent_passing_no_200_range: lab.percent_passing_no_200_range || 'N/A',
      notable_test_results: [
        lab.pvr_interpretation,
        lab.spt_status,
        raw.subsurface_conditions?.nodule_presence,
      ].filter(Boolean),
      citations: [],
    },
    groundwater_conditions: {
      groundwater_observed: Boolean(gw.encountered),
      encountered_depth_ft: gw.average_depth_range_ft || 'Not encountered',
      stabilized_depth_ft:
        Array.isArray(gw.measurements) && gw.measurements[0]
          ? `${gw.measurements[0].post_drilling_depth_ft} ft`
          : gw.average_depth_range_ft || 'N/A',
      boring_observations: Array.isArray(gw.measurements)
        ? gw.measurements.map(
            (m: Record<string, unknown>) =>
              `${m.boring_id}: encountered at ${m.drilling_depth_ft} ft, ${m.post_drilling_depth_ft} ft after ${m.time_elapsed_minutes} min`
          )
        : [],
      seepage_and_seasonal_notes: [gw.seasonal_fluctuation_warning, gw.construction_impact]
        .filter(Boolean)
        .join(' '),
      citations: [],
    },
    potential_vertical_rise_pvr: {
      pvr_value_in:
        lab.pvr_value_inches != null ? `${lab.pvr_value_inches} inches` : '1.20 inches',
      assumed_moisture_condition: lab.shrink_swell_potential || 'MODERATE',
      affected_depth_zone_ft: 'Active seasonal zone',
      mitigation_options: raw.executive_summary?.critical_site_prep_requirements || [],
      citations: [],
    },
    foundation_systems_in_report: fndList.map((sys) => ({
      system_name: sys.system_name,
      structure_applicability: sys.applicable_structures,
      bearing_stratum: sys.recommended_preparation,
      minimum_depth_ft: sys.embedment_depth_ft,
      design_notes: [
        ...(sys.construction_considerations || []),
        ...(sys.prerequisites_and_conditions || []),
      ],
      citations: [],
    })),
    bearing_parameters: bearingParams,
    site_preparation_requirements: siteSpecs.map((sp: Record<string, unknown>) => ({
      topic: String(sp.name || 'Site Preparation'),
      requirement_summary: String(sp.engineered_limit || ''),
      specifications: [sp.standard_reference, sp.conditions, sp.source_page].filter(
        Boolean
      ) as string[],
      citations: [],
    })),
    geotechnical_risks: risks.map((r: Record<string, unknown>) => ({
      risk_category: String(r.title || r.category || 'Geotechnical Risk'),
      severity:
        r.severity === 'HIGH' ? 'HIGH' : r.severity === 'LOW' ? 'LOW' : ('MODERATE' as const),
      description: String(r.description || ''),
      engineering_implication: String(r.mitigation_in_report || ''),
      mitigation_mentioned_in_report: String(r.mitigation_in_report || ''),
      citations: [],
    })),
    missing_or_unclear_information: missingItems.map(
      (m: Record<string, unknown>) => `${m.title}: ${m.description} (${m.impact_on_design})`
    ),
    questions_for_engineers: questions.map(
      (q: Record<string, unknown>) => `[${q.target_discipline}] ${q.question}`
    ),
    cross_document_notes: raw.project_context?.cross_document_matching_note
      ? [raw.project_context.cross_document_matching_note]
      : [],
    model_used: raw.llm_model_used || raw.llm_profile_used || 'document_analysis',
    confidence_score: 0.94,
    review_status: raw.review_status || 'PENDING_REVIEW',
    created_at: raw.created_at || new Date().toISOString(),
  };
}

// Normalize backend FoundationResearchReport schema into portal UI model
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function normalizeFoundationResearchReport(raw: any): FoundationResearchReport {
  if (!raw) throw new Error('Empty foundation research report response');
  if (Array.isArray(raw.foundation_technologies) && Array.isArray(raw.comparison_matrix)) {
    return raw as FoundationResearchReport;
  }

  const options = Array.isArray(raw.options_researched) ? raw.options_researched : [];
  const comparisons = Array.isArray(raw.comparisons) ? raw.comparisons : [];
  const sources = Array.isArray(raw.external_sources) ? raw.external_sources : [];
  const gaps = Array.isArray(raw.research_gaps) ? raw.research_gaps : [];
  const questions = Array.isArray(raw.engineer_questions) ? raw.engineer_questions : [];

  return {
    research_report_id: raw.research_report_id || raw.report_id,
    project_id: raw.project_id || 'default',
    geotechnical_report_id: raw.geotechnical_report_id || raw.analysis_report_id || '',
    primary_document_id: raw.document_id || '',
    confirmed_document_ids: Array.isArray(raw.confirmed_documents_reviewed)
      ? raw.confirmed_documents_reviewed
      : [raw.document_id].filter(Boolean),
    site_condition_context: raw.geotechnical_summary || {},
    executive_research_summary:
      raw.geotechnical_summary?.overview ||
      `Evaluated ${options.length} shallow and deep foundation technologies against site subsurface conditions and ${sources.length} authoritative technical references.`,
    foundation_technologies: options.map((opt: Record<string, unknown>, idx: number) => ({
      technology_id: `tech_${idx + 1}`,
      name: String(opt.name || ''),
      category: String(opt.category || 'SHALLOW'),
      mentioned_in_geotechnical_report: Boolean(opt.mentioned_in_geotech_report),
      technical_explanation: String(opt.description || ''),
      load_transfer_mechanism: String(opt.bearing_considerations || ''),
      applicable_soil_conditions: String(opt.soil_compatibility || ''),
      constructability_considerations: Array.isArray(opt.construction_methods)
        ? (opt.construction_methods as string[])
        : [],
      advantages: Array.isArray(opt.advantages) ? (opt.advantages as string[]) : [],
      limitations_and_risks: Array.isArray(opt.limitations) ? (opt.limitations as string[]) : [],
      expansive_clay_performance: String(opt.expansive_soil_considerations || ''),
      citations: [],
    })),
    comparison_matrix: comparisons.map((c: Record<string, unknown>) => ({
      foundation_name: String(c.foundation_type || ''),
      category: String(c.category || ''),
      mentioned_in_report: true,
      expansive_soil_suitability: String(c.expansive_soil_considerations || ''),
      relative_settlement_control: String(c.settlement_considerations || ''),
      relative_construction_complexity: String(c.construction_complexity || ''),
      typical_depth_range: String(c.typical_application || ''),
      key_tradeoff: String(c.relevance_explanation || ''),
    })),
    project_relevance_analysis: comparisons.map((c: Record<string, unknown>) => ({
      foundation_name: String(c.foundation_type || ''),
      relevance_classification: String(c.project_relevance || 'RELEVANT_FOR_FURTHER_EVALUATION'),
      alignment_with_site_conditions: String(c.relevance_explanation || ''),
      geotechnical_report_parameters_referenced: [String(c.bearing_considerations || '')].filter(
        Boolean
      ),
      engineering_verification_needed: Array.isArray(c.missing_inputs)
        ? (c.missing_inputs as string[])
        : [],
    })),
    research_sources: sources.map((s: Record<string, unknown>) => ({
      source_id: String(s.source_id || ''),
      title: String(s.title || ''),
      organization_or_author: String(s.publisher || ''),
      publication_or_standard: String(s.topic || ''),
      year: s.publication_date ? String(s.publication_date) : undefined,
      url: s.url ? String(s.url) : undefined,
      relevance_note: s.snippet ? String(s.snippet) : undefined,
    })),
    research_gaps: gaps.map(
      (g: Record<string, unknown>) => `${g.category}: ${g.description} (${g.required_action})`
    ),
    questions_for_foundation_engineers: questions.map(
      (q: Record<string, unknown>) => `[${q.target_role}] ${q.question}`
    ),
    disclaimer: String(raw.disclaimer || ''),
    model_used: String(raw.llm_profile_used || 'foundation_research'),
    confidence_score: 0.92,
    review_status: String(raw.review_status || 'PENDING_REVIEW'),
    reviewed_by: raw.reviewed_by ? String(raw.reviewed_by) : null,
    review_notes: raw.review_notes ? String(raw.review_notes) : null,
    created_at: String(raw.created_at || new Date().toISOString()),
  };
}

export const portalApi = {
  // Health & Platform Check
  checkHealth: () =>
    request<{ status: string; service: string; auth_mode: string; version: string }>('/v1/health'),

  // Stage 1: Document Upload & Extraction
  uploadDocuments: async (files: File[], projectId: string): Promise<DocumentMetadata[]> => {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));
    formData.append('project_id', projectId);
    const res = await request<
      DocumentMetadata[] | { uploaded_count: number; documents: DocumentMetadata[] }
    >('/v1/documents/upload', {
      method: 'POST',
      body: formData,
    });
    return Array.isArray(res) ? res : res.documents;
  },

  listProjectDocuments: (projectId?: string) => {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    return request<DocumentMetadata[]>(`/v1/documents${query}`);
  },

  getDocument: (documentId: string) =>
    request<DocumentMetadata>(`/v1/documents/${encodeURIComponent(documentId)}`),

  getDocumentReadiness: (documentId: string, projectId?: string) => {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    return request<DocumentReadinessResponse>(
      `/v1/documents/${encodeURIComponent(documentId)}/readiness${query}`
    );
  },

  // Visual Understanding & Page Classification
  classifyDocumentPages: async (documentId: string): Promise<PageClassificationResult[]> => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const list = await request<any[]>(
      `/v1/documents/${encodeURIComponent(documentId)}/pages/classification`
    );
    if (!Array.isArray(list)) return [];
    return list.map((c) => {
      const pageType = String(c.page_type || c.primary_content_type || 'TEXT_ONLY');
      return {
        document_id: String(c.document_id || documentId),
        page_number: Number(
          c.page_number ?? c.pdf_page_number ?? (c.page_index != null ? Number(c.page_index) + 1 : 1)
        ),
        page_type: pageType,
        confidence: Number(c.confidence ?? 0.9),
        reasoning: String(c.reasoning || ''),
        has_raster_images: Boolean(c.has_raster_images ?? c.features?.has_raster_images),
        vector_drawing_density: Number(c.vector_drawing_density ?? 0),
        requires_vlm: Boolean(
          c.requires_vlm ??
            [
              'SITE_PLAN',
              'ENGINEERING_DRAWING',
              'BORING_LOG_DRAWING',
              'MAP_OR_LOCATION_DIAGRAM',
              'BORING_LOG',
              'SUBSURFACE_PROFILE',
              'FOUNDATION_DETAIL',
            ].includes(pageType)
        ),
        suggested_labels: Array.isArray(c.suggested_labels) ? c.suggested_labels : [],
      };
    });
  },

  analyzeVisualPage: (documentId: string, pageNumber: number, force = false) => {
    const pageIndex = Math.max(0, Number(pageNumber || 1) - 1);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 6000);
    return request<VisualEvidenceRecord>(
      `/v1/documents/${encodeURIComponent(documentId)}/pages/${pageIndex}/analyze-visual?force_reanalyze=${force}`,
      {
        method: 'POST',
        body: JSON.stringify({ force }),
        signal: controller.signal,
      }
    ).finally(() => clearTimeout(timeoutId));
  },

  getVisualEvidence: async (documentId: string): Promise<VisualEvidenceRecord[]> => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const list = await request<any[]>(
      `/v1/documents/${encodeURIComponent(documentId)}/visual-evidence`
    );
    if (!Array.isArray(list)) return [];
    return list.map((ve, idx) => ({
      visual_evidence_id: String(ve.visual_evidence_id || ve.evidence_id || `ve_${idx}`),
      document_id: String(ve.document_id || documentId),
      page_number: Number(ve.page_number ?? (ve.page_index != null ? Number(ve.page_index) + 1 : 1)),
      page_type: ve.page_type || 'ENGINEERING_DRAWING',
      extracted_entities:
        typeof ve.extracted_entities === 'object' && !Array.isArray(ve.extracted_entities)
          ? ve.extracted_entities
          : {},
      detected_labels: Array.isArray(ve.detected_labels) ? ve.detected_labels : [],
      key_findings: Array.isArray(ve.key_findings) ? ve.key_findings : [],
      summary: String(ve.summary || 'Visual drawing analysis record'),
      confidence: Number(ve.confidence ?? ve.confidence_score ?? 0.9),
      review_status: ve.review_status || 'PENDING_REVIEW',
      model_used: String(ve.model_used || ve.vlm_model || 'VLM'),
      created_at: String(ve.created_at || new Date().toISOString()),
    }));
  },

  // Project-Document Matching & Human Confirmation
  matchProjectDocuments: async (projectProfile: ProjectProfile) => {
    const res = await request<
      | DocumentProjectAssociation[]
      | {
          project_id: string;
          total_evaluated: number;
          matched_count: number;
          possible_match_count: number;
          mismatch_count: number;
          associations: DocumentProjectAssociation[];
        }
    >(`/v1/documents/projects/${encodeURIComponent(projectProfile.project_id)}/match`, {
      method: 'POST',
      body: JSON.stringify(projectProfile),
    });
    const associations = Array.isArray(res) ? res : res.associations;
    return {
      project_id: projectProfile.project_id,
      total_evaluated: associations.length,
      matched_count: associations.filter((a) => a.match_status === 'MATCHED').length,
      possible_match_count: associations.filter((a) => a.match_status === 'POSSIBLE_MATCH').length,
      mismatch_count: associations.filter((a) => a.match_status === 'MISMATCH').length,
      associations,
    };
  },

  getProjectAssociations: (projectId: string) =>
    request<DocumentProjectAssociation[]>(
      `/v1/documents/projects/${encodeURIComponent(projectId)}/associations`
    ),

  updateAssociationDecision: (
    associationId: string,
    decision: UserDecision,
    reviewedBy = 'Project Engineer',
    notes?: string
  ) =>
    request<DocumentProjectAssociation>(
      `/v1/documents/associations/${encodeURIComponent(associationId)}/decision`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          decision,
          reviewed_by: reviewedBy,
          notes: notes || null,
        }),
      }
    ),

  getConfirmedDocuments: async (projectId: string) => {
    const res = await request<
      string[] | { project_id: string; confirmed_count: number; confirmed_document_ids: string[] }
    >(`/v1/documents/projects/${encodeURIComponent(projectId)}/confirmed-documents`);
    const ids = Array.isArray(res) ? res : res.confirmed_document_ids;
    return {
      project_id: projectId,
      confirmed_count: ids.length,
      confirmed_document_ids: ids,
    };
  },

  validateProjectDocuments: (projectId: string, confirmedDocumentIds: string[]) =>
    request<ProjectDocumentValidationResult>(
      `/v1/documents/projects/${encodeURIComponent(projectId)}/validate-documents`,
      {
        method: 'POST',
        body: JSON.stringify({
          confirmed_document_ids: confirmedDocumentIds,
        }),
      }
    ),

  // Stage 2: Existing Workflow Execution & Monitoring
  startGeotechnicalWorkflow: (
    projectId: string,
    confirmedDocumentIds: string[],
    wait = false
  ) =>
    request<WorkflowRun>('/v1/runs', {
      method: 'POST',
      body: JSON.stringify({
        workflow_id: 'geotechnical_foundation_investigation',
        execution_backend: 'direct',
        inputs: {
          project_id: projectId,
          confirmed_document_ids: confirmedDocumentIds,
        },
        wait,
      }),
    }),

  getWorkflowRun: (runId: string) =>
    request<WorkflowRun>(`/v1/runs/${encodeURIComponent(runId)}`),

  getWorkflowRunEvents: (runId: string) =>
    request<WorkflowRunEvent[]>(`/v1/runs/${encodeURIComponent(runId)}/events`),

  retryWorkflowRun: (runId: string) =>
    request<WorkflowRun>(`/v1/runs/${encodeURIComponent(runId)}/retry`, {
      method: 'POST',
    }),

  listWorkflowRuns: () => request<WorkflowRun[]>('/v1/runs'),

  // Stage 3: Final Reports & Technical Evidence Retrieval
  getGeotechnicalReportById: async (reportId: string): Promise<GeotechnicalAnalysisReport> => {
    const raw = await request<unknown>(
      `/v1/geotechnical-analysis/reports/${encodeURIComponent(reportId)}`
    );
    return normalizeGeotechnicalReport(raw);
  },

  getProjectGeotechnicalReport: async (projectId: string): Promise<GeotechnicalAnalysisReport> => {
    const list = await request<Array<{ report_id: string }>>(
      `/v1/geotechnical-analysis/reports?project_id=${encodeURIComponent(projectId)}`
    );
    if (!Array.isArray(list) || list.length === 0) {
      throw new Error(`No geotechnical report found for project ${projectId}`);
    }
    const raw = await request<unknown>(
      `/v1/geotechnical-analysis/reports/${encodeURIComponent(list[0].report_id)}`
    );
    return normalizeGeotechnicalReport(raw);
  },

  reviewGeotechnicalReport: async (
    reportId: string,
    reviewStatus: string,
    reviewedBy: string,
    reviewNotes?: string
  ): Promise<GeotechnicalAnalysisReport> => {
    const decision = reviewStatus === 'VERIFIED' ? 'HUMAN_VERIFIED' : reviewStatus;
    const raw = await request<unknown>(
      `/v1/geotechnical-analysis/reports/${encodeURIComponent(reportId)}/review`,
      {
        method: 'POST',
        body: JSON.stringify({
          decision,
          reviewer_id: reviewedBy,
          comments: reviewNotes || null,
        }),
      }
    );
    return normalizeGeotechnicalReport(raw);
  },

  getFoundationResearchReportById: async (
    researchReportId: string
  ): Promise<FoundationResearchReport> => {
    const raw = await request<unknown>(
      `/v1/foundation-research/reports/${encodeURIComponent(researchReportId)}`
    );
    return normalizeFoundationResearchReport(raw);
  },

  getProjectFoundationResearchReport: async (
    projectId: string
  ): Promise<FoundationResearchReport> => {
    const raw = await request<unknown>(
      `/v1/foundation-research/projects/${encodeURIComponent(projectId)}/latest`
    );
    return normalizeFoundationResearchReport(raw);
  },

  reviewFoundationResearchReport: async (
    researchReportId: string,
    reviewStatus: string,
    reviewedBy: string,
    reviewNotes?: string
  ): Promise<FoundationResearchReport> => {
    const decision = reviewStatus === 'VERIFIED' ? 'APPROVED' : 'REJECTED';
    const raw = await request<unknown>(
      `/v1/foundation-research/reports/${encodeURIComponent(researchReportId)}/review`,
      {
        method: 'POST',
        body: JSON.stringify({
          decision,
          reviewer_id: reviewedBy,
          comments: reviewNotes || null,
        }),
      }
    );
    return normalizeFoundationResearchReport(raw);
  },

  getRequirementReportById: (reportId: string) =>
    request<RequirementDocument>(
      `/v1/requirements/reports/${encodeURIComponent(reportId)}`
    ),

  getProjectRequirementReport: (projectId: string) =>
    request<RequirementDocument>(
      `/v1/requirements/projects/${encodeURIComponent(projectId)}/latest`
    ),

  reviewRequirementReport: (
    reportId: string,
    reviewStatus: string,
    reviewedBy: string,
    reviewNotes?: string
  ) => {
    const decision =
      reviewStatus === 'VERIFIED'
        ? 'APPROVED'
        : reviewStatus === 'CHANGES_REQUESTED'
        ? 'CHANGES_REQUESTED'
        : reviewStatus;
    return request<RequirementDocument>(
      `/v1/requirements/reports/${encodeURIComponent(reportId)}/review`,
      {
        method: 'POST',
        body: JSON.stringify({
          decision,
          reviewer_id: reviewedBy,
          comments: reviewNotes || null,
        }),
      }
    );
  },

  // Supporting Evidence & Original Document Links
  getDocumentEvidence: async (documentId: string): Promise<EvidenceRecord[]> => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const list = await request<any[]>(`/v1/documents/${encodeURIComponent(documentId)}/evidence`);
    if (!Array.isArray(list)) return [];
    return list.map((ev, idx) => ({
      evidence_id: String(ev.evidence_id || `ev_${idx}`),
      document_id: String(ev.document_id || documentId),
      category: String(ev.category || ev.evidence_type || ev.property_type || 'TECHNICAL_PROPERTY'),
      title: String(
        ev.title || ev.property_name || ev.property_type || 'Extracted Engineering Parameter'
      ),
      value: String(ev.value ?? ''),
      unit: ev.unit ? String(ev.unit) : null,
      page_number: Number(
        ev.page_number ??
          ev.printed_page_number ??
          (ev.page_index != null ? Number(ev.page_index) + 1 : 1)
      ),
      section_title: ev.section_title || ev.section_reference || null,
      raw_quote: String(ev.raw_quote || ev.context_snippet || ''),
      confidence: Number(ev.confidence ?? ev.confidence_score ?? 0.9),
      extraction_method: String(ev.extraction_method || 'DOCUMENT_INTELLIGENCE'),
      verification_status: String(ev.verification_status || ev.review_status || 'EXTRACTED'),
    }));
  },

  getDocumentTables: (documentId: string) =>
    request<ExtractedTable[]>(`/v1/documents/${encodeURIComponent(documentId)}/tables`),

  getDocumentBoringLogs: async (documentId: string): Promise<BoringLogReference[]> => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const list = await request<any[]>(
      `/v1/documents/${encodeURIComponent(documentId)}/boring-logs`
    );
    if (!Array.isArray(list)) return [];
    return list.map((bl, idx) => {
      const pageNum = Number(
        bl.printed_page_number ?? (bl.page_index != null ? Number(bl.page_index) + 1 : 1)
      );
      return {
        boring_id: String(bl.boring_id || `B-${idx + 1}`),
        document_id: String(bl.document_id || documentId),
        page_numbers: Array.isArray(bl.page_numbers)
          ? bl.page_numbers.map(Number)
          : [Number.isFinite(pageNum) && pageNum > 0 ? pageNum : 1],
        total_depth_ft:
          bl.total_depth_ft != null
            ? Number(bl.total_depth_ft)
            : bl.max_depth_ft != null
            ? Number(bl.max_depth_ft)
            : null,
        groundwater_depth_ft:
          bl.groundwater_depth_ft != null
            ? Number(bl.groundwater_depth_ft)
            : bl.groundwater_depth_drilling_ft != null
            ? Number(bl.groundwater_depth_drilling_ft)
            : bl.groundwater_depth_post_ft != null
            ? Number(bl.groundwater_depth_post_ft)
            : null,
        strata_summary: Array.isArray(bl.strata_summary)
          ? bl.strata_summary.map(String)
          : bl.stratum_description
          ? [`${bl.depth_range_ft || ''}: ${bl.stratum_description}`.trim()]
          : [],
      };
    });
  },

  getPageImageUrl: (documentId: string, pageNumber: number, dpi = 150) => {
    const pageIndex = Math.max(0, Number(pageNumber || 1) - 1);
    return `${getApiBaseUrl()}/v1/documents/${encodeURIComponent(documentId)}/pages/${pageIndex}/image?dpi=${dpi}`;
  },

  getOriginalFileUrl: (documentId: string) =>
    `${getApiBaseUrl()}/v1/documents/${encodeURIComponent(documentId)}/file`,
};
