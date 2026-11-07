import {
  AgentMetadata,
  ToolMetadata,
  WorkflowDefinition,
  RunRecord,
  ExecutionEvent,
  OverviewStats,
  HealthStatus,
  WorkflowDeletePreview,
  AgentDeletePreview,
  DocumentMetadata,
  DocumentPage,
  ExtractedTable,
  EvidenceRecord,
  FoundationSystemRecommendation,
  BoringLogReference,
  SitePreparationRequirement,
  GeotechnicalAnalysisReport,
  PageClassificationResult,
  VisualEvidence,
  CrossModalDisagreement,
  FoundationResearchReport,
} from './types';

// In-memory token storage (never written to localStorage or bundled as secret)
let inMemoryToken: string = '';
let apiBaseUrl: string = 'http://127.0.0.1:8000';

export function getAuthToken(): string {
  return inMemoryToken;
}

export function setAuthToken(token: string): void {
  inMemoryToken = token.trim();
}

export function getBaseUrl(): string {
  return apiBaseUrl;
}

export function setBaseUrl(url: string): void {
  let cleaned = url.trim();
  if (cleaned.endsWith('/')) {
    cleaned = cleaned.slice(0, -1);
  }
  apiBaseUrl = cleaned;
}

export class ApiError extends Error {
  status: number;
  details: any;

  constructor(status: number, message: string, details?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${apiBaseUrl}${path}`;
  const headers = new Headers(options.headers || {});

  if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }

  const token = getAuthToken();
  if (token && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers,
    });
  } catch (err: any) {
    throw new ApiError(0, `Network error: Could not connect to API server at ${apiBaseUrl}. Ensure the backend is running.`, err);
  }

  if (!response.ok) {
    let errorDetail = response.statusText;
    let errorJson: any = null;
    try {
      errorJson = await response.json();
      if (typeof errorJson?.detail === 'string') {
        errorDetail = errorJson.detail;
      } else if (errorJson?.detail && typeof errorJson.detail === 'object') {
        errorDetail = JSON.stringify(errorJson.detail);
      } else if (errorJson?.message) {
        errorDetail = errorJson.message;
      }
    } catch {
      // not JSON
    }

    if (response.status === 401) {
      throw new ApiError(401, `Authentication required (HTTP 401). Please configure your API token in Settings or start the server with development mode enabled.`, errorJson);
    }
    if (response.status === 403) {
      throw new ApiError(403, `Permission denied (HTTP 403): ${errorDetail}`, errorJson);
    }
    if (response.status === 404) {
      throw new ApiError(404, `Resource not found (HTTP 404): ${errorDetail}`, errorJson);
    }
    throw new ApiError(response.status, `API Error (${response.status}): ${errorDetail}`, errorJson);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

export const api = {
  // Health & Connectivity
  checkHealth: () => request<HealthStatus>('/v1/health'),
  getOverview: () => request<OverviewStats>('/v1/overview'),

  // Agents
  listAgents: () => request<AgentMetadata[]>('/v1/agents'),
  getAgent: (id: string) => request<AgentMetadata>(`/v1/agents/${encodeURIComponent(id)}`),
  runAgent: (id: string, inputs: Record<string, any>, task = 'direct agent execution') =>
    request<RunRecord>(`/v1/agents/${encodeURIComponent(id)}/runs`, {
      method: 'POST',
      body: JSON.stringify({ inputs, task }),
    }),
  deleteAgent: (id: string) =>
    request<{ deleted: boolean; agent_id: string; purged_records: any }>(`/v1/agents/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),
  previewDeleteAgent: (id: string) =>
    request<AgentDeletePreview>(`/v1/agents/${encodeURIComponent(id)}/preview-delete`),

  // Tools
  listTools: () => request<ToolMetadata[]>('/v1/tools'),

  // Workflows
  listWorkflows: (includeDrafts = true) =>
    request<WorkflowDefinition[]>(`/v1/workflows?include_drafts=${includeDrafts}`),
  getWorkflow: async (id: string) => {
    try {
      return await request<WorkflowDefinition>(`/v1/workflows/${encodeURIComponent(id)}`);
    } catch (err: any) {
      if (err.status === 404) {
        const drafts = await api.listWorkflows(true);
        const match = drafts.find((w) => w.id === id);
        if (match) {
          return match;
        }
      }
      throw err;
    }
  },
  createWorkflow: (workflow: WorkflowDefinition) => {
    const { id, version = '1.0.0', nodes = [], edges = [], max_steps } = workflow as any;
    const cleanNodes = (nodes || []).map((node: any) => ({
      id: node.id,
      type: node.type,
      agent_id: node.agent_id,
      status: node.status || 'available',
      input_mappings: node.input_mappings || {},
      ...(node.approval_payload_path ? { approval_payload_path: node.approval_payload_path } : {}),
      ...(node.approval_options ? { approval_options: node.approval_options } : {}),
    }));
    const cleanEdges = (edges || []).map((edge: any) => ({
      from: edge.from,
      to: edge.to,
      ...(edge.condition ? { condition: edge.condition } : {}),
    }));
    const payload: Record<string, any> = {
      id,
      version,
      nodes: cleanNodes,
      edges: cleanEdges,
    };
    if (typeof max_steps === 'number') {
      payload.max_steps = max_steps;
    }
    return request<WorkflowDefinition>('/v1/workflows', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },
  registerWorkflow: async (id: string, fallbackWorkflow?: WorkflowDefinition) => {
    try {
      return await request<WorkflowDefinition>(`/v1/workflows/${encodeURIComponent(id)}/register`, {
        method: 'POST',
      });
    } catch (err: any) {
      if (fallbackWorkflow && err.status === 404) {
        return await api.createWorkflow(fallbackWorkflow);
      }
      throw err;
    }
  },
  createDraft: (payload: { id: string; version?: string; nodes?: any[]; edges?: any[]; max_steps?: number }) =>
    request<{ id: string; status: string; saved: boolean; workflow_file: string }>('/v1/workflows/draft', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateWorkflow: (id: string, workflow: WorkflowDefinition) => {
    const { version = '1.0.0', nodes = [], edges = [], max_steps } = workflow as any;
    const payload: Record<string, any> = {
      id,
      version,
      nodes,
      edges,
    };
    if (typeof max_steps === 'number') {
      payload.max_steps = max_steps;
    }
    return request<WorkflowDefinition>(`/v1/workflows/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  },
  addAgentToWorkflow: (
    id: string,
    payload: {
      agent_id: string;
      node_id?: string;
      after?: string;
      before?: string;
      input_mappings?: Record<string, any>;
    }
  ) =>
    request<WorkflowDefinition>(`/v1/workflows/${encodeURIComponent(id)}/add-agent`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  removeNodeFromWorkflow: (id: string, nodeId: string) =>
    request<WorkflowDefinition>(
      `/v1/workflows/${encodeURIComponent(id)}/nodes/${encodeURIComponent(nodeId)}`,
      {
        method: 'DELETE',
      }
    ),
  disconnectWorkflow: (id: string) =>
    request<{ disconnected: boolean; workflow_id: string; registered: boolean; registration_status: string }>(
      `/v1/workflows/${encodeURIComponent(id)}/disconnect`,
      { method: 'POST' }
    ),
  previewDeleteWorkflow: (id: string) =>
    request<WorkflowDeletePreview>(`/v1/workflows/${encodeURIComponent(id)}/preview-delete`),
  deleteWorkflow: (id: string) =>
    request<{
      deleted: boolean;
      workflow_id: string;
      deleted_runs: number;
      deleted_events: number;
      deleted_checkpoints: number;
    }>(`/v1/workflows/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  // Runs
  listRuns: (status?: string, workflowId?: string) => {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (workflowId) params.append('workflow_id', workflowId);
    const qs = params.toString() ? `?${params.toString()}` : '';
    return request<RunRecord[]>(`/v1/runs${qs}`);
  },
  getRun: (runId: string) => request<RunRecord>(`/v1/runs/${encodeURIComponent(runId)}`),
  startRun: (workflowId: string, inputs: Record<string, any> = {}, allowPartial = true) =>
    request<RunRecord>('/v1/runs', {
      method: 'POST',
      body: JSON.stringify({ workflow_id: workflowId, inputs, allow_partial: allowPartial }),
    }),
  deleteRun: (runId: string) =>
    request<{ deleted: boolean; run_id: string }>(`/v1/runs/${encodeURIComponent(runId)}`, {
      method: 'DELETE',
    }),

  // Events & Logs
  listEvents: (runId?: string, limit = 100, offset = 0) => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (runId) params.append('run_id', runId);
    return request<ExecutionEvent[]>(`/v1/events?${params.toString()}`);
  },
  getRunEvents: (runId: string) =>
    request<ExecutionEvent[]>(`/v1/runs/${encodeURIComponent(runId)}/events`),

  // Approvals
  listApprovals: () => request<RunRecord[]>('/v1/approvals'),
  resumeApproval: (runId: string, decision: string) =>
    request<RunRecord>(`/v1/runs/${encodeURIComponent(runId)}/resume`, {
      method: 'POST',
      body: JSON.stringify({ decision }),
    }),

  // Document Intelligence (Phase 1)
  uploadDocuments: async (files: File[], projectId = 'default'): Promise<DocumentMetadata[]> => {
    const url = `${apiBaseUrl}/v1/documents/upload`;
    const formData = new FormData();
    formData.append('project_id', projectId);
    files.forEach((file) => {
      formData.append('files', file);
    });

    const headers = new Headers();
    const token = getAuthToken();
    if (token) {
      headers.set('Authorization', `Bearer ${token}`);
    }

    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: formData,
    });

    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errJson = await response.json();
        detail = errJson.detail || detail;
      } catch {}
      throw new ApiError(response.status, detail);
    }
    return response.json();
  },

  listDocuments: (projectId = 'default') =>
    request<DocumentMetadata[]>(`/v1/documents?project_id=${encodeURIComponent(projectId)}`),

  getDocument: (documentId: string) =>
    request<DocumentMetadata>(`/v1/documents/${encodeURIComponent(documentId)}`),

  getDocumentPages: (documentId: string) =>
    request<DocumentPage[]>(`/v1/documents/${encodeURIComponent(documentId)}/pages`),

  getDocumentPage: (documentId: string, pageIndex: number) =>
    request<DocumentPage>(`/v1/documents/${encodeURIComponent(documentId)}/pages/${pageIndex}`),

  getPageImageUrl: (documentId: string, pageIndex: number) =>
    `${apiBaseUrl}/v1/documents/${encodeURIComponent(documentId)}/pages/${pageIndex}/image`,

  getDocumentTables: (documentId: string) =>
    request<ExtractedTable[]>(`/v1/documents/${encodeURIComponent(documentId)}/tables`),

  getDocumentEvidence: (documentId: string, propertyType?: string, pageIndex?: number) => {
    const params = new URLSearchParams();
    if (propertyType) params.append('property_type', propertyType);
    if (pageIndex !== undefined) params.append('page_index', String(pageIndex));
    const qs = params.toString() ? `?${params.toString()}` : '';
    return request<EvidenceRecord[]>(`/v1/documents/${encodeURIComponent(documentId)}/evidence${qs}`);
  },

  getFoundationRecommendations: (documentId: string) =>
    request<FoundationSystemRecommendation[]>(`/v1/documents/${encodeURIComponent(documentId)}/foundation-recommendations`),

  getSitePreparation: (documentId: string) =>
    request<SitePreparationRequirement[]>(`/v1/documents/${encodeURIComponent(documentId)}/site-preparation`),

  getBoringLogs: (documentId: string) =>
    request<BoringLogReference[]>(`/v1/documents/${encodeURIComponent(documentId)}/boring-logs`),

  updateEvidenceStatus: (
    evidenceId: string,
    verificationStatus: 'PENDING_REVIEW' | 'HUMAN_VERIFIED' | 'REJECTED' | 'unverified' | 'verified' | 'flagged'
  ) =>
    request<{ evidence_id: string; verification_status: string }>(
      `/v1/documents/evidence/${encodeURIComponent(evidenceId)}?verification_status=${encodeURIComponent(verificationStatus)}`,
      { method: 'PATCH' }
    ),

  reprocessDocument: (documentId: string) =>
    request<{ document_id: string; status: string; pages_count: number; tables_count: number; evidence_count: number }>(
      `/v1/documents/${encodeURIComponent(documentId)}/reprocess`,
      { method: 'POST' }
    ),

  deleteDocument: (documentId: string) =>
    request<{ document_id: string; deleted: boolean }>(
      `/v1/documents/${encodeURIComponent(documentId)}`,
      { method: 'DELETE' }
    ),

  // Geotechnical Analysis Agent (Phase 2)
  runGeotechnicalAnalysis: (documentId: string, projectId = 'default', llmProfile = 'document_analysis') =>
    request<GeotechnicalAnalysisReport>('/v1/geotechnical-analysis/runs', {
      method: 'POST',
      body: JSON.stringify({
        document_id: documentId,
        project_id: projectId,
        llm_profile: llmProfile,
      }),
    }),

  getGeotechnicalReport: (reportId: string) =>
    request<GeotechnicalAnalysisReport>(`/v1/geotechnical-analysis/reports/${encodeURIComponent(reportId)}`),

  getLatestGeotechnicalReport: async (documentId: string) => {
    try {
      return await request<GeotechnicalAnalysisReport>(
        `/v1/geotechnical-analysis/documents/${encodeURIComponent(documentId)}/latest`
      );
    } catch (err: any) {
      if (err.status === 404) return null;
      throw err;
    }
  },

  listGeotechnicalReports: (projectId = 'default', documentId?: string) => {
    const params = new URLSearchParams();
    params.append('project_id', projectId);
    if (documentId) params.append('document_id', documentId);
    return request<Array<{ report_id: string; document_id: string; status: string; created_at: string }>>(
      `/v1/geotechnical-analysis/reports?${params.toString()}`
    );
  },

  submitGeotechnicalReview: (
    reportId: string,
    decision: 'PENDING_REVIEW' | 'HUMAN_VERIFIED' | 'REJECTED' | 'CHANGES_REQUESTED',
    reviewerId = 'licensed_engineer',
    comments?: string
  ) =>
    request<GeotechnicalAnalysisReport>(`/v1/geotechnical-analysis/reports/${encodeURIComponent(reportId)}/review`, {
      method: 'POST',
      body: JSON.stringify({
        decision,
        reviewer_id: reviewerId,
        comments,
      }),
    }),

  // Multimodal Vision Understanding
  getPageClassifications: (documentId: string) =>
    request<PageClassificationResult[]>(`/v1/documents/${encodeURIComponent(documentId)}/pages/classification`),

  analyzePageVisual: (documentId: string, pageIndex: number, modelOverride?: string, forceReanalyze = false) => {
    const params = new URLSearchParams();
    if (modelOverride) params.append('model_override', modelOverride);
    if (forceReanalyze) params.append('force_reanalyze', 'true');
    const qs = params.toString() ? `?${params.toString()}` : '';
    return request<VisualEvidence>(
      `/v1/documents/${encodeURIComponent(documentId)}/pages/${pageIndex}/analyze-visual${qs}`,
      { method: 'POST' }
    );
  },

  getVisualEvidence: (documentId: string, pageIndex?: number) => {
    const params = new URLSearchParams();
    if (pageIndex !== undefined) params.append('page_index', String(pageIndex));
    const qs = params.toString() ? `?${params.toString()}` : '';
    return request<VisualEvidence[]>(`/v1/documents/${encodeURIComponent(documentId)}/visual-evidence${qs}`);
  },

  reviewVisualEvidence: (
    evidenceId: string,
    reviewStatus: 'PENDING_REVIEW' | 'HUMAN_VERIFIED' | 'REJECTED' | 'CHANGES_REQUESTED',
    notes?: string,
    verifiedBy = 'lead_engineer'
  ) =>
    request<{ visual_evidence_id: string; review_status: string; status: string }>(
      `/v1/documents/visual-evidence/${encodeURIComponent(evidenceId)}/review`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          review_status: reviewStatus,
          human_notes: notes,
          verified_by: verifiedBy,
        }),
      }
    ),

  getVisualDisagreements: (documentId: string, status?: string) => {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    const qs = params.toString() ? `?${params.toString()}` : '';
    return request<CrossModalDisagreement[]>(
      `/v1/documents/${encodeURIComponent(documentId)}/visual-disagreements${qs}`
    );
  },

  resolveVisualDisagreement: (disagreementId: string, status: 'RESOLVED' | 'IGNORED', resolutionNotes?: string) =>
    request<{ disagreement_id: string; status: string; updated: boolean }>(
      `/v1/documents/visual-disagreements/${encodeURIComponent(disagreementId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify({
          status,
          resolution_notes: resolutionNotes,
        }),
      }
    ),

  // Foundation Research Agent (Phase 4)
  runFoundationResearch: (documentId: string, projectId = 'default', foundationTypes?: string[], searchProvider?: string) =>
    request<FoundationResearchReport>('/v1/foundation-research/runs', {
      method: 'POST',
      body: JSON.stringify({
        document_id: documentId,
        project_id: projectId,
        foundation_types_to_research: foundationTypes,
        search_provider_name: searchProvider,
      }),
    }),

  getFoundationResearchReport: (reportId: string) =>
    request<FoundationResearchReport>(`/v1/foundation-research/reports/${encodeURIComponent(reportId)}`),

  getLatestFoundationResearchForDocument: async (documentId: string) => {
    try {
      return await request<FoundationResearchReport>(
        `/v1/foundation-research/documents/${encodeURIComponent(documentId)}/latest`
      );
    } catch {
      return null;
    }
  },

  getLatestFoundationResearchForProject: async (projectId: string) => {
    try {
      return await request<FoundationResearchReport>(
        `/v1/foundation-research/projects/${encodeURIComponent(projectId)}/latest`
      );
    } catch {
      return null;
    }
  },

  listFoundationResearchReports: (projectId = 'default') =>
    request<FoundationResearchReport[]>(
      `/v1/foundation-research/projects/${encodeURIComponent(projectId)}/reports`
    ),

  submitFoundationResearchReview: (
    reportId: string,
    decision: 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED',
    reviewerId = 'licensed_engineer',
    comments?: string
  ) =>
    request<FoundationResearchReport>(
      `/v1/foundation-research/reports/${encodeURIComponent(reportId)}/review`,
      {
        method: 'POST',
        body: JSON.stringify({ decision, reviewer_id: reviewerId, comments }),
      }
    ),
};

