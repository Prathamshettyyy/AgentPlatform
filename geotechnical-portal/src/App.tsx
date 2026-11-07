import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Compass,
  Settings,
  CheckCircle2,
  AlertCircle,
  Upload,
  Cpu,
  FileSpreadsheet,
  X,
} from 'lucide-react';
import {
  getApiBaseUrl,
  getAuthToken,
  portalApi,
  setApiBaseUrl,
  setAuthToken,
} from './api/client';
import type {
  DocumentMetadata,
  DocumentProjectAssociation,
  DocumentReadinessResponse,
  FoundationResearchReport,
  GeotechnicalAnalysisReport,
  PortalStage,
  PortalStageStatus,
  ProjectSession,
  RequirementDocument,
  UserDecision,
  WorkflowRun,
  WorkflowRunEvent,
} from './api/types';
import { UploadView } from './components/UploadView';
import { ProcessingView } from './components/ProcessingView';
import { ResultsView } from './components/ResultsView';

type ActiveView = 'upload' | 'processing' | 'results';

const SESSIONS_STORAGE_KEY = 'geostrata_project_sessions_v1';

const DEFAULT_STAGES: PortalStage[] = [
  {
    id: 'upload',
    number: 1,
    title: 'Uploading project files',
    subtitle: 'Saving your soil report and site drawings',
    status: 'WAITING',
  },
  {
    id: 'extract',
    number: 2,
    title: 'Reading soil report & boring logs',
    subtitle: 'Extracting project address, soil layers, and laboratory test tables',
    status: 'WAITING',
  },
  {
    id: 'vision',
    number: 3,
    title: 'Inspecting site drawings & images',
    subtitle: 'Reading site plan layouts, lot numbers, and building footprint details',
    status: 'WAITING',
  },
  {
    id: 'validate',
    number: 4,
    title: 'Checking site location match',
    subtitle: 'Verifying that uploaded site drawings match the location in your Soil Report',
    status: 'WAITING',
    nodeId: 'validate_project_documents_node',
  },
  {
    id: 'geotechnical_agent',
    number: 5,
    title: 'Generating Geotechnical Analysis',
    subtitle: 'Analyzing soil conditions, PVR swell potential, groundwater, and bearing capacity',
    status: 'WAITING',
    nodeId: 'geotechnical_analysis_node',
  },
  {
    id: 'foundation_agent',
    number: 6,
    title: 'Researching Foundation Options',
    subtitle: 'Comparing shallow and deep foundation systems suitable for this site',
    status: 'WAITING',
    nodeId: 'foundation_research_node',
  },
  {
    id: 'requirement_agent',
    number: 7,
    title: 'Preparing Vendor Requirement Document',
    subtitle: 'Building contractor scope of work, technical specs, and proposal checklist',
    status: 'WAITING',
    nodeId: 'requirement_agent_node',
  },
  {
    id: 'reports',
    number: 8,
    title: 'Finalizing engineering reports',
    subtitle: 'Saving all three deliverables for review',
    status: 'WAITING',
  },
];

function loadSavedSessions(): ProjectSession[] {
  try {
    const raw = window.localStorage.getItem(SESSIONS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveSessionToStorage(session: ProjectSession): ProjectSession[] {
  const existing = loadSavedSessions().filter((s) => s.projectId !== session.projectId);
  const updated = [session, ...existing].slice(0, 15);
  try {
    window.localStorage.setItem(SESSIONS_STORAGE_KEY, JSON.stringify(updated));
  } catch {
    // ignore storage quota errors
  }
  return updated;
}

function syncUrlParams(projectId?: string | null, runId?: string | null, view?: ActiveView) {
  if (typeof window === 'undefined') return;
  const url = new URL(window.location.href);
  if (projectId) {
    url.searchParams.set('project_id', projectId);
  } else {
    url.searchParams.delete('project_id');
  }
  if (runId) {
    url.searchParams.set('run_id', runId);
  } else {
    url.searchParams.delete('run_id');
  }
  if (view) {
    url.searchParams.set('view', view);
  } else {
    url.searchParams.delete('view');
  }
  window.history.replaceState({}, '', url.toString());
}

export const App: React.FC = () => {
  const [activeView, setActiveView] = useState<ActiveView>('upload');
  const [recentSessions, setRecentSessions] = useState<ProjectSession[]>(() => loadSavedSessions());
  const [currentSession, setCurrentSession] = useState<ProjectSession | null>(null);

  const [stages, setStages] = useState<PortalStage[]>(DEFAULT_STAGES);
  const [documents, setDocuments] = useState<DocumentMetadata[]>([]);
  const [readinessMap, setReadinessMap] = useState<Record<string, DocumentReadinessResponse>>({});
  const [associations, setAssociations] = useState<DocumentProjectAssociation[]>([]);
  const [workflowRun, setWorkflowRun] = useState<WorkflowRun | null>(null);
  const [workflowEvents, setWorkflowEvents] = useState<WorkflowRunEvent[]>([]);
  const [geotechReport, setGeotechReport] = useState<GeotechnicalAnalysisReport | null>(null);
  const [foundationReport, setFoundationReport] = useState<FoundationResearchReport | null>(null);
  const [requirementReport, setRequirementReport] = useState<RequirementDocument | null>(null);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isActionBusy, setIsActionBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Backend health & settings modal
  const [backendHealthy, setBackendHealthy] = useState<boolean | null>(null);
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [apiUrlInput, setApiUrlInput] = useState(() => getApiBaseUrl());
  const [authTokenInput, setAuthTokenInput] = useState(() => getAuthToken());

  const pollTimerRef = useRef<number | null>(null);

  const checkBackend = useCallback(async () => {
    try {
      const res = await portalApi.checkHealth();
      setBackendHealthy(res.status === 'healthy');
    } catch {
      setBackendHealthy(false);
    }
  }, []);

  useEffect(() => {
    checkBackend();
  }, [checkBackend]);

  const updateSession = useCallback((patch: Partial<ProjectSession>) => {
    setCurrentSession((prev) => {
      if (!prev) return prev;
      const next: ProjectSession = {
        ...prev,
        ...patch,
        updatedAt: new Date().toISOString(),
      };
      setRecentSessions(saveSessionToStorage(next));
      return next;
    });
  }, []);

  const updateStage = useCallback(
    (
      stageId: PortalStage['id'],
      status: PortalStageStatus,
      detail?: string
    ) => {
      setStages((prev) =>
        prev.map((s) =>
          s.id === stageId ? { ...s, status, detail: detail ?? s.detail } : s
        )
      );
    },
    []
  );

  const fetchFinalReports = useCallback(
    async (
      projectId: string,
      geoReportId?: string | null,
      foundReportId?: string | null,
      reqReportId?: string | null
    ): Promise<{
      geo: GeotechnicalAnalysisReport | null;
      found: FoundationResearchReport | null;
      req: RequirementDocument | null;
    }> => {
      const [geo, found, req] = await Promise.all([
        geoReportId
          ? portalApi
              .getGeotechnicalReportById(geoReportId)
              .catch(() => portalApi.getProjectGeotechnicalReport(projectId).catch(() => null))
          : portalApi.getProjectGeotechnicalReport(projectId).catch(() => null),
        foundReportId
          ? portalApi
              .getFoundationResearchReportById(foundReportId)
              .catch(() => portalApi.getProjectFoundationResearchReport(projectId).catch(() => null))
          : portalApi.getProjectFoundationResearchReport(projectId).catch(() => null),
        reqReportId
          ? portalApi
              .getRequirementReportById(reqReportId)
              .catch(() => portalApi.getProjectRequirementReport(projectId).catch(() => null))
          : portalApi.getProjectRequirementReport(projectId).catch(() => null),
      ]);
      if (geo) setGeotechReport(geo);
      if (found) setFoundationReport(found);
      if (req) setRequirementReport(req);
      return { geo, found, req };
    },
    []
  );

  // Sync stage statuses from live WorkflowRun + WorkflowRunEvents
  const syncStagesFromRun = useCallback(
    async (run: WorkflowRun, events: WorkflowRunEvent[], projectId: string) => {
      const runPayload = run.payload || run.output || {};
      const nodeOutputs = runPayload.node_outputs || {};
      const eventMap: Record<string, string> = {};
      events.forEach((ev) => {
        eventMap[ev.node_id] = ev.status;
      });

      const valDone =
        Boolean(nodeOutputs.validate_project_documents_node) ||
        eventMap.validate_project_documents_node === 'succeeded';
      const geoDone =
        Boolean(nodeOutputs.geotechnical_analysis_node) ||
        eventMap.geotechnical_analysis_node === 'succeeded';
      const foundDone =
        Boolean(nodeOutputs.foundation_research_node) ||
        eventMap.foundation_research_node === 'succeeded';
      const reqDone =
        Boolean(nodeOutputs.requirement_agent_node) ||
        eventMap.requirement_agent_node === 'succeeded';

      const valOut = (nodeOutputs.validate_project_documents_node || {}) as Record<string, unknown>;
      const geoOut = (nodeOutputs.geotechnical_analysis_node || {}) as Record<string, unknown>;
      const foundOut = (nodeOutputs.foundation_research_node || {}) as Record<string, unknown>;
      const reqOut = (nodeOutputs.requirement_agent_node || {}) as Record<string, unknown>;

      const geoId =
        (geoOut.geotechnical_report_id as string) ||
        (geoOut.report_id as string) ||
        (runPayload.geotechnical_report_id as string) ||
        null;
      const foundId =
        (foundOut.foundation_research_report_id as string) ||
        (foundOut.research_report_id as string) ||
        (foundOut.report_id as string) ||
        (runPayload.foundation_research_report_id as string) ||
        null;
      const reqId =
        (reqOut.report_id as string) ||
        (runPayload.requirement_report_id as string) ||
        null;
      const snapId =
        (valOut.snapshot_id as string) ||
        ((valOut.snapshot as Record<string, unknown>)?.snapshot_id as string) ||
        null;

      if (run.status === 'failed') {
        const errMsg = runPayload.error || 'Workflow execution failed';
        setStages((prev) =>
          prev.map((st) => {
            if (st.id === 'upload' || st.id === 'extract' || st.id === 'vision') {
              return { ...st, status: 'SUCCEEDED' };
            }
            if (st.id === 'validate') {
              return { ...st, status: valDone ? 'SUCCEEDED' : 'FAILED', detail: valDone ? st.detail : errMsg };
            }
            if (st.id === 'geotechnical_agent') {
              return {
                ...st,
                status: geoDone ? 'SUCCEEDED' : valDone ? 'FAILED' : 'BLOCKED',
                detail: !geoDone && valDone ? errMsg : st.detail,
              };
            }
            if (st.id === 'foundation_agent') {
              return {
                ...st,
                status: foundDone ? 'SUCCEEDED' : geoDone ? 'FAILED' : 'BLOCKED',
                detail: !foundDone && geoDone ? errMsg : st.detail,
              };
            }
            if (st.id === 'requirement_agent') {
              return {
                ...st,
                status: reqDone ? 'SUCCEEDED' : foundDone ? 'FAILED' : 'BLOCKED',
                detail: !reqDone && foundDone ? errMsg : st.detail,
              };
            }
            return { ...st, status: 'BLOCKED' };
          })
        );
        updateSession({
          runId: run.run_id,
          errorMessage: errMsg,
        });
        return;
      }

      if (run.status === 'succeeded' || run.status === 'partially_succeeded') {
        const { geo, found, req } = await fetchFinalReports(projectId, geoId, foundId, reqId);
        setStages((prev) =>
          prev.map((st) => {
            if (st.id === 'validate') {
              return {
                ...st,
                status: 'SUCCEEDED',
                detail: snapId ? `Snapshot verified (${snapId})` : 'All documents validated',
              };
            }
            if (st.id === 'geotechnical_agent') {
              return {
                ...st,
                status: 'SUCCEEDED',
                detail: `Geotechnical Report: ${geo?.report_id || geoId || 'Generated'}`,
              };
            }
            if (st.id === 'foundation_agent') {
              return {
                ...st,
                status: 'SUCCEEDED',
                detail: `Foundation Research Report: ${
                  found?.research_report_id || foundId || 'Generated'
                }`,
              };
            }
            if (st.id === 'requirement_agent') {
              return {
                ...st,
                status: 'SUCCEEDED',
                detail: `Vendor Requirement Document: ${
                  req?.report_id || reqId || 'Generated'
                }`,
              };
            }
            if (st.id === 'reports') {
              return {
                ...st,
                status: 'SUCCEEDED',
                detail: 'Reports persisted and ready for engineering review',
              };
            }
            return { ...st, status: 'SUCCEEDED' };
          })
        );
        updateSession({
          runId: run.run_id,
          geotechnicalReportId: geo?.report_id || geoId,
          foundationResearchReportId: found?.research_report_id || foundId,
          requirementReportId: req?.report_id || reqId,
          snapshotId: snapId,
          errorMessage: null,
        });
        return;
      }

      // Run is currently RUNNING
      setStages((prev) =>
        prev.map((st) => {
          if (st.id === 'upload' || st.id === 'extract' || st.id === 'vision') {
            return { ...st, status: 'SUCCEEDED' };
          }
          if (st.id === 'validate') {
            return {
              ...st,
              status: valDone ? 'SUCCEEDED' : 'RUNNING',
              detail: valDone
                ? snapId
                  ? `Snapshot verified (${snapId})`
                  : 'Confirmed documents validated'
                : 'Executing validate_project_documents_node...',
            };
          }
          if (st.id === 'geotechnical_agent') {
            return {
              ...st,
              status: geoDone ? 'SUCCEEDED' : valDone ? 'RUNNING' : 'WAITING',
              detail: geoDone
                ? `Geotechnical Report: ${geoId}`
                : valDone
                ? 'Executing Geotechnical Analysis Agent...'
                : undefined,
            };
          }
          if (st.id === 'foundation_agent') {
            return {
              ...st,
              status: foundDone ? 'SUCCEEDED' : geoDone ? 'RUNNING' : 'WAITING',
              detail: foundDone
                ? `Foundation Research Report: ${foundId}`
                : geoDone
                ? 'Executing Foundation Research Agent...'
                : undefined,
            };
          }
          if (st.id === 'requirement_agent') {
            return {
              ...st,
              status: reqDone ? 'SUCCEEDED' : foundDone ? 'RUNNING' : 'WAITING',
              detail: reqDone
                ? `Vendor Requirement Document: ${reqId}`
                : foundDone
                ? 'Executing Vendor Requirement Agent...'
                : undefined,
            };
          }
          if (st.id === 'reports') {
            return {
              ...st,
              status: reqDone ? 'RUNNING' : 'WAITING',
            };
          }
          return st;
        })
      );
    },
    [fetchFinalReports, updateSession]
  );

  // Poll active workflow run
  useEffect(() => {
    const runId = currentSession?.runId;
    const projectId = currentSession?.projectId;
    if (!runId || !projectId) return;

    let cancelled = false;

    const pollOnce = async () => {
      try {
        const [run, events] = await Promise.all([
          portalApi.getWorkflowRun(runId),
          portalApi.getWorkflowRunEvents(runId).catch(() => []),
        ]);
        if (cancelled) return;
        setWorkflowRun(run);
        setWorkflowEvents(events);
        await syncStagesFromRun(run, events, projectId);

        if (
          run.status === 'succeeded' ||
          run.status === 'partially_succeeded' ||
          run.status === 'failed' ||
          run.status === 'cancelled'
        ) {
          if (pollTimerRef.current) {
            window.clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
        }
      } catch {
        // transient network error while polling
      }
    };

    pollOnce();
    pollTimerRef.current = window.setInterval(pollOnce, 1500);

    return () => {
      cancelled = true;
      if (pollTimerRef.current) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [currentSession?.runId, currentSession?.projectId, syncStagesFromRun]);

  // Execute workflow once confirmed documents are READY_FOR_ANALYSIS
  const executeWorkflowWithConfirmedDocs = useCallback(
    async (projectId: string, confirmedDocIds: string[]) => {
      updateStage(
        'validate',
        'RUNNING',
        `Validating ${confirmedDocIds.length} confirmed project document(s)...`
      );
      const valResult = await portalApi.validateProjectDocuments(projectId, confirmedDocIds);
      if (!valResult.is_valid) {
        const msg = valResult.validation_errors.join('; ') || valResult.message;
        updateStage('validate', 'FAILED', msg);
        updateSession({ errorMessage: msg, failedStageId: 'validate' });
        return;
      }

      const snapId = valResult.snapshot?.snapshot_id || null;
      updateStage(
        'validate',
        'SUCCEEDED',
        snapId ? `Validated snapshot ${snapId}` : 'Documents validated for analysis'
      );
      updateStage('geotechnical_agent', 'RUNNING', 'Dispatching Geotechnical Analysis Agent...');
      updateStage('foundation_agent', 'WAITING');
      updateStage('requirement_agent', 'WAITING');
      updateStage('reports', 'WAITING');

      try {
        const run = await portalApi.startGeotechnicalWorkflow(projectId, confirmedDocIds, false);
        setWorkflowRun(run);
        const events = await portalApi.getWorkflowRunEvents(run.run_id).catch(() => []);
        setWorkflowEvents(events);
        updateSession({
          confirmedDocumentIds: confirmedDocIds,
          runId: run.run_id,
          snapshotId: snapId,
          errorMessage: null,
        });
        syncUrlParams(projectId, run.run_id, 'processing');
        await syncStagesFromRun(run, events, projectId);
      } catch (wfErr) {
        const msg = wfErr instanceof Error ? wfErr.message : String(wfErr);
        updateStage('geotechnical_agent', 'FAILED', msg);
        updateStage('foundation_agent', 'BLOCKED');
        updateStage('requirement_agent', 'BLOCKED');
        updateStage('reports', 'BLOCKED');
        updateSession({ errorMessage: msg, failedStageId: 'geotechnical_agent' });
      }
    },
    [syncStagesFromRun, updateSession, updateStage]
  );

  // Refresh readiness map for a list of documents
  const refreshReadinessMap = useCallback(
    async (docs: DocumentMetadata[], projectId: string) => {
      const entries = await Promise.all(
        docs.map((d) =>
          portalApi
            .getDocumentReadiness(d.document_id, projectId)
            .then((r) => [d.document_id, r] as const)
            .catch(() => null)
        )
      );
      const nextMap: Record<string, DocumentReadinessResponse> = {};
      entries.forEach((entry) => {
        if (entry) nextMap[entry[0]] = entry[1];
      });
      setReadinessMap(nextMap);
      return nextMap;
    },
    []
  );

  // Phase 4: Full Automatic Background Processing after Upload
  const handleStartAnalysis = async (params: {
    projectName: string;
    projectAddress: string;
    subdivision?: string;
    blockNumber?: string;
    lotNumber?: string;
    files: File[];
  }) => {
    setIsSubmitting(true);
    setSubmitError(null);
    setGeotechReport(null);
    setFoundationReport(null);
    setRequirementReport(null);
    setWorkflowRun(null);
    setWorkflowEvents([]);

    const rawSeed =
      params.projectName.trim() ||
      params.files.find((f) => /soil|geotech|report/i.test(f.name))?.name.replace(/\.[^.]+$/, '') ||
      params.files[0]?.name.replace(/\.[^.]+$/, '') ||
      'geotech';
    const slug = rawSeed
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_|_$/g, '')
      .slice(0, 24);
    const projectId = `proj_${slug || 'geotech'}_${Date.now().toString(36).slice(-5)}`;

    const initialSession: ProjectSession = {
      projectId,
      projectName: params.projectName.trim() || 'Identifying Project from Soil Report...',
      projectAddress: params.projectAddress.trim() || 'Extracting site location & parcel metadata...',
      documentIds: [],
      confirmedDocumentIds: [],
      runId: null,
      stageStatuses: {},
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };

    setCurrentSession(initialSession);
    setRecentSessions(saveSessionToStorage(initialSession));
    setStages(
      DEFAULT_STAGES.map((s) =>
        s.id === 'upload'
          ? { ...s, status: 'RUNNING', detail: `Uploading ${params.files.length} file(s)...` }
          : { ...s, status: 'WAITING', detail: undefined }
      )
    );
    setActiveView('processing');
    syncUrlParams(projectId, null, 'processing');

    try {
      // 1. Upload and associate documents with project
      const uploadedDocs = await portalApi.uploadDocuments(params.files, projectId);
      setDocuments(uploadedDocs);
      updateStage(
        'upload',
        'SUCCEEDED',
        `Uploaded ${uploadedDocs.length} document(s) to project ${projectId}`
      );

      // Auto-identify project name, address, and parcel metadata from Soil Report if left blank
      const primarySoilDoc =
        uploadedDocs.find((d) => /soil|geotech|report|boring/i.test(d.filename)) ||
        uploadedDocs.find((d) => d.project_info?.site_location || d.project_info?.project_name) ||
        uploadedDocs[0];
      const extractedInfo = primarySoilDoc?.project_info || {};

      const resolvedProjectName =
        params.projectName.trim() ||
        (extractedInfo.project_name && extractedInfo.site_location
          ? `${extractedInfo.project_name} (${extractedInfo.site_location.split(',')[0]})`
          : extractedInfo.project_name) ||
        extractedInfo.site_location ||
        (primarySoilDoc?.filename
          ? primarySoilDoc.filename.replace(/\.[^.]+$/, '')
          : 'Geotechnical Investigation Project');

      const resolvedProjectAddress =
        params.projectAddress.trim() ||
        extractedInfo.site_location ||
        uploadedDocs.map((d) => d.project_info?.site_location).find(Boolean) ||
        extractedInfo.legal_description ||
        'Site location extracted from Geotechnical Report';

      const resolvedSubdivision = params.subdivision || extractedInfo.subdivision || null;
      const resolvedBlock = params.blockNumber || extractedInfo.block || null;
      const resolvedLot = params.lotNumber || extractedInfo.lot || null;

      updateSession({
        projectName: resolvedProjectName,
        projectAddress: resolvedProjectAddress,
        documentIds: uploadedDocs.map((d) => d.document_id),
      });

      // 2. Document Intelligence Extraction check
      updateStage(
        'extract',
        'RUNNING',
        'Verifying text, table, and boring log extraction...'
      );
      const failedDoc = uploadedDocs.find((d) => d.status === 'failed');
      if (failedDoc) {
        const msg = `Extraction failed for "${failedDoc.filename}": ${
          failedDoc.error_message || 'Unreadable document'
        }`;
        updateStage('extract', 'FAILED', msg);
        updateSession({
          documentIds: uploadedDocs.map((d) => d.document_id),
          errorMessage: msg,
          failedStageId: 'extract',
        });
        setIsSubmitting(false);
        return;
      }
      updateStage(
        'extract',
        'SUCCEEDED',
        `Identified "${resolvedProjectName}" at ${resolvedProjectAddress} across ${uploadedDocs.reduce(
          (acc, d) => acc + (d.page_count || 1),
          0
        )} page(s)`
      );

      // 3. Visual Understanding on relevant drawing / map pages
      updateStage(
        'vision',
        'RUNNING',
        'Classifying page layouts and checking drawing annotations...'
      );
      let analyzedDrawingPages = 0;
      // Focus visual inspection on actual drawings/site plans, or up to 2 docs max
      const drawingDocs = uploadedDocs.filter(
        (d) =>
          !d.filename.toLowerCase().includes('soil') &&
          !d.filename.toLowerCase().includes('geotech')
      );
      const docsToInspect = drawingDocs.length > 0 ? drawingDocs : uploadedDocs.slice(0, 2);

      try {
        await Promise.race([
          Promise.allSettled(
            docsToInspect.map(async (doc) => {
              try {
                const classifications = await portalApi.classifyDocumentPages(doc.document_id);
                const relevantPages = classifications.filter(
                  (c) =>
                    c.requires_vlm ||
                    ['SITE_PLAN', 'SUBSURFACE_PROFILE', 'FOUNDATION_DETAIL', 'BORING_LOG'].includes(
                      c.page_type
                    )
                );
                analyzedDrawingPages += relevantPages.length || classifications.length;
                // Dispatch VLM in the background without blocking the pipeline
                const targetPages =
                  relevantPages.length > 0 ? relevantPages.slice(0, 1) : classifications.slice(0, 1);
                targetPages.forEach((page) => {
                  portalApi
                    .analyzeVisualPage(doc.document_id, page.page_number, false)
                    .catch(() => null);
                });
              } catch {
                // non-fatal
              }
            })
          ),
          new Promise((resolve) => setTimeout(resolve, 2500)),
        ]);
      } catch {
        // non-fatal
      }

      updateStage(
        'vision',
        'SUCCEEDED',
        analyzedDrawingPages > 0
          ? `Verified layout structure across ${analyzedDrawingPages} drawing/log page(s)`
          : 'Page layout classification completed'
      );

      // 4. Execute project-document matching & readiness verification
      updateStage(
        'validate',
        'RUNNING',
        'Checking if uploaded site drawings match the Soil Report location...'
      );
      const matchRes = await portalApi.matchProjectDocuments({
        project_id: projectId,
        project_name: resolvedProjectName,
        site_address: resolvedProjectAddress,
        subdivision: resolvedSubdivision,
        block_number: resolvedBlock,
        lot_number: resolvedLot,
      });
      setAssociations(matchRes.associations);
      await refreshReadinessMap(uploadedDocs, projectId);

      updateSession({
        documentIds: uploadedDocs.map((d) => d.document_id),
      });

      const needsConfirmation = matchRes.associations.some(
        (a) =>
          (a.match_status === 'POSSIBLE_MATCH' ||
            a.match_status === 'MISMATCH' ||
            a.match_status === 'PENDING_CONFIRMATION') &&
          a.user_decision === 'PENDING'
      );

      if (needsConfirmation) {
        updateStage(
          'validate',
          'NEEDS_REVIEW',
          'Please review the site location check above before continuing'
        );
        updateStage('geotechnical_agent', 'BLOCKED', 'Waiting for site location confirmation');
        updateStage('foundation_agent', 'BLOCKED', 'Waiting for site location confirmation');
        updateStage('requirement_agent', 'BLOCKED', 'Waiting for site location confirmation');
        updateStage('reports', 'BLOCKED', 'Waiting for site location confirmation');
        setIsSubmitting(false);
        return;
      }

      // All documents matched cleanly — proceed automatically into workflow
      const confirmedRes = await portalApi.getConfirmedDocuments(projectId);
      const confirmedIds =
        confirmedRes.confirmed_document_ids.length > 0
          ? confirmedRes.confirmed_document_ids
          : uploadedDocs.map((d) => d.document_id);

      await executeWorkflowWithConfirmedDocs(projectId, confirmedIds);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setSubmitError(message);
      updateSession({ errorMessage: message });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Human confirmation handler for POSSIBLE_MATCH / MISMATCH documents
  const handleAssociationDecision = async (
    associationId: string,
    decision: UserDecision,
    notes?: string
  ) => {
    if (!currentSession) return;
    setIsActionBusy(true);
    try {
      await portalApi.updateAssociationDecision(
        associationId,
        decision,
        'Licensed Project Engineer',
        notes
      );
      const updatedAssocs = await portalApi.getProjectAssociations(currentSession.projectId);
      setAssociations(updatedAssocs);
      await refreshReadinessMap(documents, currentSession.projectId);
    } finally {
      setIsActionBusy(false);
    }
  };

  // Proceed after human review of uncertain documents
  const handleProceedAfterReview = async () => {
    if (!currentSession) return;
    setIsActionBusy(true);
    try {
      const confirmedRes = await portalApi.getConfirmedDocuments(currentSession.projectId);
      const confirmedIds = confirmedRes.confirmed_document_ids;
      await executeWorkflowWithConfirmedDocs(currentSession.projectId, confirmedIds);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      updateStage('validate', 'FAILED', msg);
      updateSession({ errorMessage: msg });
    } finally {
      setIsActionBusy(false);
    }
  };

  // Retry failed workflow or stage
  const handleRetryWorkflow = async () => {
    if (!currentSession) return;
    setIsActionBusy(true);
    try {
      if (currentSession.runId) {
        const retriedRun = await portalApi.retryWorkflowRun(currentSession.runId);
        setWorkflowRun(retriedRun);
        const events = await portalApi.getWorkflowRunEvents(retriedRun.run_id).catch(() => []);
        setWorkflowEvents(events);
        await syncStagesFromRun(retriedRun, events, currentSession.projectId);
      } else {
        const confirmedRes = await portalApi.getConfirmedDocuments(currentSession.projectId);
        const confirmedIds =
          confirmedRes.confirmed_document_ids.length > 0
            ? confirmedRes.confirmed_document_ids
            : currentSession.confirmedDocumentIds;
        await executeWorkflowWithConfirmedDocs(currentSession.projectId, confirmedIds);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      updateSession({ errorMessage: msg });
    } finally {
      setIsActionBusy(false);
    }
  };

  // Restore session from recent list or URL parameters
  const restoreProjectSession = useCallback(
    async (sessionToRestore: ProjectSession, preferredView?: ActiveView) => {
      setCurrentSession(sessionToRestore);
      setActiveView(preferredView || 'processing');
      setStages(
        DEFAULT_STAGES.map((s) =>
          s.id === 'upload' || s.id === 'extract' || s.id === 'vision'
            ? { ...s, status: 'SUCCEEDED' }
            : { ...s, status: 'WAITING' }
        )
      );

      try {
        const [projDocs, assocs] = await Promise.all([
          portalApi.listProjectDocuments(sessionToRestore.projectId).catch(() => []),
          portalApi.getProjectAssociations(sessionToRestore.projectId).catch(() => []),
        ]);

        let activeDocs = projDocs;
        if (activeDocs.length === 0 && sessionToRestore.documentIds.length > 0) {
          const fetched = await Promise.all(
            sessionToRestore.documentIds.map((id) => portalApi.getDocument(id).catch(() => null))
          );
          activeDocs = fetched.filter((d): d is DocumentMetadata => Boolean(d));
        }
        setDocuments(activeDocs);
        setAssociations(assocs);
        await refreshReadinessMap(activeDocs, sessionToRestore.projectId);

        if (sessionToRestore.runId) {
          const [run, events] = await Promise.all([
            portalApi.getWorkflowRun(sessionToRestore.runId),
            portalApi.getWorkflowRunEvents(sessionToRestore.runId).catch(() => []),
          ]);
          setWorkflowRun(run);
          setWorkflowEvents(events);
          await syncStagesFromRun(run, events, sessionToRestore.projectId);
        } else {
          const { geo, found } = await fetchFinalReports(
            sessionToRestore.projectId,
            sessionToRestore.geotechnicalReportId,
            sessionToRestore.foundationResearchReportId,
            sessionToRestore.requirementReportId
          );
          if (geo && found) {
            setStages((prev) => prev.map((s) => ({ ...s, status: 'SUCCEEDED' })));
            if (preferredView === 'results') {
              setActiveView('results');
            }
          } else {
            const unresolved = assocs.some(
              (a) =>
                (a.match_status === 'POSSIBLE_MATCH' ||
                  a.match_status === 'MISMATCH' ||
                  a.match_status === 'PENDING_CONFIRMATION') &&
                a.user_decision === 'PENDING'
            );
            if (unresolved) {
              updateStage('validate', 'NEEDS_REVIEW');
              updateStage('geotechnical_agent', 'BLOCKED');
              updateStage('foundation_agent', 'BLOCKED');
              updateStage('requirement_agent', 'BLOCKED');
              updateStage('reports', 'BLOCKED');
            }
          }
        }
      } catch {
        // ignore restore error
      }
    },
    [fetchFinalReports, refreshReadinessMap, syncStagesFromRun, updateStage]
  );

  // Restore state on initial browser load / refresh from URL params
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlProjectId = params.get('project_id');
    const urlRunId = params.get('run_id');
    const urlView = (params.get('view') as ActiveView) || undefined;

    if (!urlProjectId) return;

    const saved = loadSavedSessions().find((s) => s.projectId === urlProjectId);
    const sessionObj: ProjectSession = saved || {
      projectId: urlProjectId,
      projectName: urlProjectId,
      projectAddress: 'Restored Project Session',
      documentIds: [],
      confirmedDocumentIds: [],
      runId: urlRunId,
      stageStatuses: {},
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    };
    if (urlRunId) {
      sessionObj.runId = urlRunId;
    }
    restoreProjectSession(sessionObj, urlView);
  }, [restoreProjectSession]);

  // Load White Oak Reference Project
  const handleLoadDemoProject = async () => {
    setIsSubmitting(true);
    try {
      const allDocs = await portalApi.listProjectDocuments();
      const whiteOakDocs = allDocs.filter((d) =>
        /white oak|25-0117/i.test(d.filename)
      );
      const projectId = 'proj_white_oak_residence';

      await portalApi.matchProjectDocuments({
        project_id: projectId,
        project_name: '2436 White Oak Residence Investigation',
        site_address: '2432 & 2434 White Oak Drive, Houston, TX 77009',
        subdivision: 'White Oak Terrace',
        block_number: '1',
        lot_number: '11 & 12',
      });

      const runs = await portalApi.listWorkflowRuns().catch(() => []);
      const existingRun = runs.find(
        (r) =>
          r.workflow_id === 'geotechnical_foundation_investigation' &&
          r.status === 'succeeded' &&
          ((r.output?.workflow_input as Record<string, unknown>)?.project_id === projectId ||
            (r.inputs as Record<string, unknown>)?.project_id === projectId)
      );

      const demoSession: ProjectSession = {
        projectId,
        projectName: '2436 White Oak Residence Investigation',
        projectAddress: '2432 & 2434 White Oak Drive, Houston, TX 77009',
        documentIds: whiteOakDocs.map((d) => d.document_id),
        confirmedDocumentIds: [],
        runId: existingRun?.run_id || null,
        stageStatuses: {},
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
      };
      setRecentSessions(saveSessionToStorage(demoSession));
      syncUrlParams(projectId, demoSession.runId, 'processing');
      await restoreProjectSession(demoSession, 'processing');
    } finally {
      setIsSubmitting(false);
    }
  };

  const canOpenResults = Boolean(geotechReport && foundationReport);

  return (
    <div className="min-h-screen flex flex-col bg-slate-950 text-slate-100 print:min-h-0 print:bg-white print:text-slate-900 print:m-0 print:p-0">
      {/* Standalone Top Header — Full-Width Fluid Layout */}
      <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-slate-950/90 backdrop-blur-xl print:hidden">
        <div className="w-full px-5 sm:px-8 lg:px-10 xl:px-12 h-16 flex items-center justify-between gap-4">
          {/* Brand Logo */}
          <div
            onClick={() => {
              setActiveView('upload');
              syncUrlParams(null, null, 'upload');
            }}
            className="cursor-pointer flex items-center gap-3 group"
          >
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 via-amber-500 to-orange-600 flex items-center justify-center text-slate-950 shadow-lg shadow-amber-500/25 group-hover:scale-105 transition-transform">
              <Compass className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2.5">
                <span className="font-bold text-lg tracking-tight text-white">
                  GeoStrata
                </span>
                <span className="text-[11px] font-medium px-2.5 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30">
                  Soil &amp; Foundation Intelligence
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Automated Geotechnical Analysis, Foundation Options &amp; Vendor Bid Packages
              </p>
            </div>
          </div>

          {/* Workflow Stepper Navigation */}
          <nav className="hidden md:flex items-center gap-1.5 bg-slate-900/90 p-1.5 rounded-2xl border border-slate-800/90 shadow-inner">
            <button
              type="button"
              onClick={() => {
                setActiveView('upload');
                syncUrlParams(currentSession?.projectId, currentSession?.runId, 'upload');
              }}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition-all ${
                activeView === 'upload'
                  ? 'bg-gradient-to-r from-amber-500 to-orange-500 text-slate-950 font-semibold shadow-md shadow-amber-500/20'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
              }`}
            >
              <Upload className="w-3.5 h-3.5" />
              1. Upload Documents
            </button>

            <button
              type="button"
              disabled={!currentSession}
              onClick={() => {
                setActiveView('processing');
                syncUrlParams(currentSession?.projectId, currentSession?.runId, 'processing');
              }}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition-all disabled:opacity-40 ${
                activeView === 'processing'
                  ? 'bg-gradient-to-r from-amber-500 to-orange-500 text-slate-950 font-semibold shadow-md shadow-amber-500/20'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
              }`}
            >
              <Cpu className="w-3.5 h-3.5" />
              2. Analysis Progress
            </button>

            <button
              type="button"
              disabled={!canOpenResults}
              onClick={() => {
                setActiveView('results');
                syncUrlParams(currentSession?.projectId, currentSession?.runId, 'results');
              }}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-medium transition-all disabled:opacity-40 ${
                activeView === 'results'
                  ? 'bg-gradient-to-r from-amber-500 to-orange-500 text-slate-950 font-semibold shadow-md shadow-amber-500/20'
                  : 'text-slate-300 hover:text-white hover:bg-slate-800/60'
              }`}
            >
              <FileSpreadsheet className="w-3.5 h-3.5" />
              3. Engineering Reports
            </button>
          </nav>

          {/* Backend Status & API Settings */}
          <div className="flex items-center gap-2.5">
            <div
              title={`Connected to ${getApiBaseUrl()}`}
              className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-full bg-slate-900/90 border border-slate-800 text-xs"
            >
              {backendHealthy === true ? (
                <>
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-slate-200 font-medium">System Online</span>
                </>
              ) : backendHealthy === false ? (
                <>
                  <AlertCircle className="w-3.5 h-3.5 text-red-400" />
                  <span className="text-red-300">Offline</span>
                </>
              ) : (
                <span className="text-slate-400">Connecting...</span>
              )}
            </div>

            <button
              type="button"
              onClick={() => setShowSettingsModal(true)}
              aria-label="API Connection Settings"
              className="p-2 rounded-xl bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-300 transition-colors"
            >
              <Settings className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1">
        {activeView === 'upload' && (
          <UploadView
            onStartAnalysis={handleStartAnalysis}
            recentSessions={recentSessions}
            onSelectSession={(sess) => {
              syncUrlParams(sess.projectId, sess.runId, 'processing');
              restoreProjectSession(sess, 'processing');
            }}
            onLoadDemoProject={handleLoadDemoProject}
            isSubmitting={isSubmitting}
            submitError={submitError}
          />
        )}

        {activeView === 'processing' && currentSession && (
          <ProcessingView
            session={currentSession}
            stages={stages}
            documents={documents}
            readinessMap={readinessMap}
            associations={associations}
            workflowRun={workflowRun}
            workflowEvents={workflowEvents}
            onAssociationDecision={handleAssociationDecision}
            onProceedAfterReview={handleProceedAfterReview}
            onRetryWorkflow={handleRetryWorkflow}
            onOpenResults={() => {
              setActiveView('results');
              syncUrlParams(currentSession.projectId, currentSession.runId, 'results');
            }}
            onBackToUpload={() => {
              setActiveView('upload');
              syncUrlParams(null, null, 'upload');
            }}
            isActionBusy={isActionBusy}
          />
        )}

        {activeView === 'results' &&
          currentSession &&
          geotechReport &&
          foundationReport && (
            <ResultsView
              session={currentSession}
              documents={documents}
              workflowRun={workflowRun}
              geotechReport={geotechReport}
              foundationReport={foundationReport}
              requirementReport={requirementReport}
              onBackToProgress={() => {
                setActiveView('processing');
                syncUrlParams(currentSession.projectId, currentSession.runId, 'processing');
              }}
              onNewProject={() => {
                setActiveView('upload');
                syncUrlParams(null, null, 'upload');
              }}
              onReportsUpdated={(geo, found, req) => {
                setGeotechReport(geo);
                setFoundationReport(found);
                if (req !== undefined) setRequirementReport(req);
              }}
            />
          )}

        {activeView === 'results' &&
          currentSession &&
          (!geotechReport || !foundationReport) && (
            <div className="max-w-4xl mx-auto px-4 sm:px-6 py-16">
              <div className="rounded-2xl border border-slate-800 bg-slate-900/90 p-8 text-center space-y-4">
                <div className="w-10 h-10 rounded-full border-2 border-amber-500 border-t-transparent animate-spin mx-auto" />
                <h2 className="text-lg font-bold text-white">
                  Loading Project Engineering Reports...
                </h2>
                <p className="text-xs text-slate-400">
                  Synchronizing Geotechnical Analysis, Foundation Research, and Vendor Requirement deliverables for{' '}
                  <span className="font-mono text-amber-300">{currentSession.projectId}</span>
                </p>
                <div className="pt-2">
                  <button
                    type="button"
                    onClick={() => {
                      setActiveView('processing');
                      syncUrlParams(currentSession.projectId, currentSession.runId, 'processing');
                    }}
                    className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 border border-slate-700"
                  >
                    Switch to Processing View
                  </button>
                </div>
              </div>
            </div>
          )}
      </main>

      {/* API Connection Settings Modal */}
      {showSettingsModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="text-base font-bold text-white">
                GeoStrata API Connection Settings
              </h3>
              <button
                type="button"
                onClick={() => setShowSettingsModal(false)}
                className="p-1 text-slate-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="block text-slate-300 font-medium mb-1">
                  GeoStrata Backend Base URL (Port 8001)
                </label>
                <input
                  type="text"
                  value={apiUrlInput}
                  onChange={(e) => setApiUrlInput(e.target.value)}
                  placeholder="http://127.0.0.1:8001"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-white font-mono"
                />
              </div>

              <div>
                <label className="block text-slate-300 font-medium mb-1">
                  Bearer Auth Token (Optional)
                </label>
                <input
                  type="password"
                  value={authTokenInput}
                  onChange={(e) => setAuthTokenInput(e.target.value)}
                  placeholder="Leave blank in development mode"
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-white font-mono"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowSettingsModal(false)}
                className="px-4 py-2 rounded-xl bg-slate-800 text-xs text-slate-300"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  setApiBaseUrl(apiUrlInput);
                  setAuthToken(authTokenInput);
                  setShowSettingsModal(false);
                  checkBackend();
                }}
                className="px-4 py-2 rounded-xl bg-amber-500 text-slate-950 font-semibold text-xs"
              >
                Save &amp; Reconnect
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
export default App;

