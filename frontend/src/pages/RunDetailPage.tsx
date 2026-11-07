import React, { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import {
  ArrowLeft,
  PlayCircle,
  Clock,
  CheckCircle2,
  XCircle,
  FileText,
  Trash2,
  Code2,
  AlertCircle,
  Layers,
  ChevronDown,
  ChevronRight,
  Terminal,
  GitBranch,
  Sparkles,
  Building,
  Search,
  Eye,
  MapPin,
  ExternalLink,
} from 'lucide-react';
import { StatusBadge } from '../components/common/StatusBadge';
import { Skeleton } from '../components/common/Skeleton';
import { ConfirmModal } from '../components/common/ConfirmModal';
import { WorkflowGraph } from '../components/workflows/WorkflowGraph';

/* ── collapsible node output card ── */
const NodeOutputCard: React.FC<{ nodeId: string; output: any; docId?: string }> = ({ nodeId, output, docId }) => {
  const [expanded, setExpanded] = useState(true);
  const targetDocId = output?.document_id || output?.primary_document_id || docId;

  const getQuickAction = () => {
    if (!targetDocId) return null;
    if (nodeId === 'geotechnical_analysis_node') {
      return (
        <Link
          to={`/documents/${encodeURIComponent(targetDocId)}?tab=ai_analysis`}
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-semibold text-indigo-300 bg-indigo-500/15 hover:bg-indigo-500/25 border border-indigo-500/30 rounded-lg transition-colors"
        >
          <Sparkles className="w-3 h-3 text-indigo-400" />
          View Geotechnical Report UI ↗
        </Link>
      );
    }
    if (nodeId === 'foundation_research_node') {
      return (
        <Link
          to={`/documents/${encodeURIComponent(targetDocId)}?tab=foundation_research`}
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-semibold text-teal-300 bg-teal-500/15 hover:bg-teal-500/25 border border-teal-500/30 rounded-lg transition-colors"
        >
          <Search className="w-3 h-3 text-teal-400" />
          View Foundation Research UI ↗
        </Link>
      );
    }
    if (nodeId === 'validate_project_documents_node') {
      return (
        <Link
          to={`/documents/${encodeURIComponent(targetDocId)}?tab=viewer`}
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-semibold text-cyan-300 bg-cyan-500/15 hover:bg-cyan-500/25 border border-cyan-500/30 rounded-lg transition-colors"
        >
          <Eye className="w-3 h-3 text-cyan-400" />
          Inspect Document in Viewer ↗
        </Link>
      );
    }
    return null;
  };

  return (
    <div className="rounded-xl border border-slate-800/80 overflow-hidden">
      <div
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 bg-slate-900/60 hover:bg-slate-800/40 transition-colors text-left cursor-pointer"
      >
        <div className="flex items-center gap-2.5">
          <Terminal className="w-3.5 h-3.5 text-blue-400 shrink-0" />
          <span className="font-mono text-sm font-semibold text-slate-200">{nodeId}</span>
          <span className="badge bg-emerald-500/10 border-emerald-500/20 text-emerald-400 text-[10px]">Succeeded</span>
        </div>
        <div className="flex items-center gap-2">
          {getQuickAction()}
          {expanded ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
        </div>
      </div>
      {expanded && (
        <pre className="p-4 bg-[#080c14] text-xs font-mono text-slate-300 overflow-x-auto max-h-72 leading-relaxed">
          {JSON.stringify(output, null, 2)}
        </pre>
      )}
    </div>
  );
};

/* ── Tab button ── */
const TabBtn: React.FC<{
  active: boolean;
  onClick: () => void;
  icon: React.ElementType;
  label: string;
  count?: number;
}> = ({ active, onClick, icon: Icon, label, count }) => (
  <button
    onClick={onClick}
    className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-all ${
      active
        ? 'border-blue-500 text-blue-400'
        : 'border-transparent text-slate-500 hover:text-slate-300 hover:border-slate-700'
    }`}
  >
    <Icon className="w-3.5 h-3.5" />
    {label}
    {count !== undefined && (
      <span className={`px-1.5 py-0.5 rounded-md text-[10px] font-bold ${active ? 'bg-blue-500/20 text-blue-400' : 'bg-slate-800 text-slate-500'}`}>
        {count}
      </span>
    )}
  </button>
);

/* ── Main ── */
export const RunDetailPage: React.FC = () => {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState<'outputs' | 'graph' | 'events' | 'raw'>('outputs');
  const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
  const [approvalError, setApprovalError] = useState<string | null>(null);

  const { data: run, isLoading, error } = useQuery({
    queryKey: ['run', runId],
    queryFn: () => api.getRun(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === 'running' || status === 'resuming' ? 2000 : false;
    },
  });

  const { data: workflows = [] } = useQuery({
    queryKey: ['workflows'],
    queryFn: () => api.listWorkflows(true),
  });

  const workflow = workflows.find((w) => w.id === run?.workflow_id);

  const { data: events = [] } = useQuery({
    queryKey: ['run-events', runId],
    queryFn: () => api.getRunEvents(runId!),
    enabled: Boolean(runId),
    refetchInterval: () => {
      const status = run?.status;
      return status === 'running' || status === 'resuming' ? 2000 : false;
    },
  });

  const resumeMutation = useMutation({
    mutationFn: (decision: string) => api.resumeApproval(runId!, decision),
    onSuccess: (updated) => {
      queryClient.setQueryData(['run', runId], updated);
      queryClient.invalidateQueries({ queryKey: ['run-events', runId] });
      queryClient.invalidateQueries({ queryKey: ['runs'] });
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
      setApprovalError(null);
    },
    onError: (err: any) => { setApprovalError(err.message || 'Approval action failed'); },
  });

  const deleteMutation = useMutation({
    mutationFn: () => api.deleteRun(runId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['runs'] });
      navigate('/runs');
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-36 w-full rounded-xl" />
        <Skeleton className="h-64 w-full rounded-xl" />
      </div>
    );
  }

  if (error || !run) {
    return (
      <div className="flex items-center gap-3 p-5 rounded-xl bg-rose-500/8 border border-rose-500/25 text-rose-400">
        <AlertCircle className="w-5 h-5 shrink-0" />
        <span>Failed to load run: {(error as any)?.message || 'Not found'}</span>
      </div>
    );
  }

  const isWaitingApproval = run.status === 'waiting_for_approval';
  const nodeOutputs = run.payload?.node_outputs || {};
  const finalOutput = run.payload?.final_output;
  const executionError = run.payload?.error;

  const validationOutput = nodeOutputs['validate_project_documents_node'];
  const geotechOutput = nodeOutputs['geotechnical_analysis_node'];
  const researchOutput = nodeOutputs['foundation_research_node'];

  // Resolve target document ID
  const primaryDocId = (
    geotechOutput?.document_id ||
    validationOutput?.primary_document_id ||
    researchOutput?.document_id ||
    finalOutput?.document_id ||
    run.payload?.inputs?.document_id ||
    run.payload?.inputs?.primary_document_id ||
    (run.payload?.inputs?.confirmed_document_ids && run.payload?.inputs?.confirmed_document_ids[0])
  );

  const geotechReportId = (
    geotechOutput?.report_id ||
    finalOutput?.geotechnical_report_id ||
    (typeof finalOutput?.report_id === 'string' && finalOutput.report_id.startsWith('geo_') ? finalOutput.report_id : undefined)
  );

  const researchReportId = (
    researchOutput?.foundation_research_report_id ||
    researchOutput?.report_id ||
    finalOutput?.foundation_research_report_id ||
    (typeof finalOutput?.report_id === 'string' && finalOutput.report_id.startsWith('fnd_') ? finalOutput.report_id : undefined)
  );

  const isGeotechnicalFlow = Boolean(
    geotechReportId ||
    researchReportId ||
    validationOutput ||
    run.workflow_id === 'geotechnical_foundation_investigation'
  );

  return (
    <div className="space-y-5">
      {/* Breadcrumb */}
      <Link to="/runs" className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-200 font-medium transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to Runs
      </Link>

      {/* Header card */}
      <div className="rounded-xl bg-slate-900/50 border border-slate-800/80 overflow-hidden">
        <div className="px-6 py-5">
          <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="p-3 rounded-xl bg-blue-500/10 border border-blue-500/20 text-blue-400 shrink-0">
                <PlayCircle className="w-6 h-6" />
              </div>
              <div>
                <div className="flex items-center gap-2.5 flex-wrap">
                  <h2 className="font-mono text-base font-bold text-slate-100">{run.run_id}</h2>
                  <StatusBadge status={run.status} />
                </div>
                <p className="text-xs text-slate-500 font-mono mt-1.5 space-x-2">
                  <span className="text-violet-400 font-semibold">
                    {run.workflow_id
                      ? `Workflow: ${run.workflow_id} (v${run.workflow_version || '1.0.0'})`
                      : `Agent: ${run.payload?.agent_id || 'direct'}`}
                  </span>
                  <span className="text-slate-700">·</span>
                  <span>Owner: {run.owner_id || 'development'}</span>
                  {run.created_at && (
                    <>
                      <span className="text-slate-700">·</span>
                      <span>{new Date(run.created_at).toLocaleString()}</span>
                    </>
                  )}
                </p>
              </div>
            </div>

            <button
              onClick={() => setIsDeleteModalOpen(true)}
              className="btn-ghost text-rose-500/70 hover:text-rose-400 hover:bg-rose-500/10 self-start sm:self-auto border border-transparent hover:border-rose-500/15"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Delete Run
            </button>
          </div>
        </div>

        {/* Approval bar */}
        {isWaitingApproval && (
          <div className="px-6 py-4 bg-amber-500/8 border-t border-amber-500/25">
            <div className="flex items-center gap-2 mb-2">
              <Clock className="w-4 h-4 text-amber-400" />
              <span className="text-xs font-semibold text-amber-400 uppercase tracking-wider">Human Approval Required</span>
            </div>
            <p className="text-xs text-amber-300/80 mb-3">
              This workflow is paused at a human checkpoint. Choose a decision to resume or terminate execution.
            </p>
            {approvalError && (
              <div className="mb-3 px-3 py-2 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs">
                {approvalError}
              </div>
            )}
            <div className="flex gap-2">
              <button
                onClick={() => resumeMutation.mutate('approve')}
                disabled={resumeMutation.isPending}
                className="btn-primary bg-emerald-600 hover:bg-emerald-500"
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                Approve & Resume
              </button>
              <button
                onClick={() => resumeMutation.mutate('reject')}
                disabled={resumeMutation.isPending}
                className="btn-danger"
              >
                <XCircle className="w-3.5 h-3.5" />
                Reject & Stop
              </button>
            </div>
          </div>
        )}

        {/* Error notice */}
        {executionError && (
          <div className="px-6 py-4 bg-rose-500/8 border-t border-rose-500/25 flex items-start gap-3">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold text-rose-400 mb-0.5">Execution Failure</p>
              <p className="text-xs text-rose-400/70">{executionError.message || JSON.stringify(executionError)}</p>
            </div>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800/60 gap-0 -mb-1">
        <TabBtn
          active={activeTab === 'outputs'}
          onClick={() => setActiveTab('outputs')}
          icon={Layers}
          label="Node Outputs"
          count={Object.keys(nodeOutputs).length}
        />
        {workflow && (
          <TabBtn
            active={activeTab === 'graph'}
            onClick={() => setActiveTab('graph')}
            icon={GitBranch}
            label="Execution Graph"
          />
        )}
        <TabBtn
          active={activeTab === 'events'}
          onClick={() => setActiveTab('events')}
          icon={FileText}
          label="Events"
          count={events.length}
        />
        <TabBtn
          active={activeTab === 'raw'}
          onClick={() => setActiveTab('raw')}
          icon={Code2}
          label="Raw JSON"
        />
      </div>

      {/* Tab: Graph */}
      {activeTab === 'graph' && workflow && (
        <div className="pt-2">
          <WorkflowGraph
            workflow={workflow}
            runRecord={run}
            events={events}
          />
        </div>
      )}

      {/* Tab: Outputs */}
      {activeTab === 'outputs' && (
        <div className="space-y-4 pt-1">
          {/* Dedicated Investigation Flow Results Dashboard */}
          {isGeotechnicalFlow && primaryDocId && (
            <div className="rounded-xl border border-indigo-500/30 bg-slate-900/80 p-5 space-y-4 shadow-xl backdrop-blur-sm">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-slate-800/80 pb-3">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-xl bg-indigo-500/15 text-indigo-400 border border-indigo-500/30">
                    <Sparkles className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                      Investigation Flow Results Hub
                      <span className="badge bg-emerald-500/15 border-emerald-500/30 text-emerald-400 text-[10px]">
                        Available in UI
                      </span>
                    </h3>
                    <p className="text-xs text-slate-400">
                      View fully rendered geotechnical findings, foundation systems, and visual maps in the dedicated engineering interface.
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-wrap">
                  <Link
                    to={`/documents/${encodeURIComponent(primaryDocId)}?tab=visual_intelligence`}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/90 hover:bg-slate-700 text-xs font-medium text-slate-200 transition-colors"
                  >
                    <MapPin className="w-3.5 h-3.5 text-amber-400" />
                    Boring Map & Logs
                  </Link>
                  <Link
                    to={`/documents/${encodeURIComponent(primaryDocId)}?tab=viewer`}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/90 hover:bg-slate-700 text-xs font-medium text-slate-200 transition-colors"
                  >
                    <Eye className="w-3.5 h-3.5 text-cyan-400" />
                    PDF Viewer
                  </Link>
                </div>
              </div>

              {/* Stage result cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                {/* Geotechnical Analysis Card */}
                <div className="p-4 rounded-xl border border-indigo-500/25 bg-indigo-950/20 hover:border-indigo-500/40 transition-all flex flex-col justify-between space-y-3">
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-[11px] font-bold text-indigo-400 uppercase tracking-wider flex items-center gap-1.5">
                        <Building className="w-3.5 h-3.5" />
                        Stage 2: Geotechnical Analysis Agent
                      </span>
                      {geotechReportId && (
                        <span className="badge bg-indigo-500/20 text-indigo-300 border-indigo-500/30 text-[10px] font-mono">
                          {geotechReportId.slice(0, 16)}...
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed line-clamp-2">
                      {geotechOutput?.executive_summary || 'Subsurface stratigraphy, soil mechanics, bearing capacity, and foundation comparison matrix.'}
                    </p>
                  </div>
                  <Link
                    to={`/documents/${encodeURIComponent(primaryDocId)}?tab=ai_analysis`}
                    className="inline-flex items-center justify-center gap-2 w-full py-2 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow transition-colors"
                  >
                    <Sparkles className="w-3.5 h-3.5" />
                    Open Geotechnical Analysis Report UI →
                  </Link>
                </div>

                {/* Foundation Research Card */}
                <div className="p-4 rounded-xl border border-teal-500/25 bg-teal-950/20 hover:border-teal-500/40 transition-all flex flex-col justify-between space-y-3">
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="text-[11px] font-bold text-teal-400 uppercase tracking-wider flex items-center gap-1.5">
                        <Search className="w-3.5 h-3.5" />
                        Stage 3: Foundation Research Agent
                      </span>
                      {researchReportId && (
                        <span className="badge bg-teal-500/20 text-teal-300 border-teal-500/30 text-[10px] font-mono">
                          {researchReportId.slice(0, 16)}...
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-300 leading-relaxed line-clamp-2">
                      External deep/shallow foundation research, USACE/PTI/FHWA parameters, and authoritative safety standards.
                    </p>
                  </div>
                  <Link
                    to={`/documents/${encodeURIComponent(primaryDocId)}?tab=foundation_research`}
                    className="inline-flex items-center justify-center gap-2 w-full py-2 px-3 rounded-lg bg-teal-600 hover:bg-teal-500 text-white text-xs font-semibold shadow transition-colors"
                  >
                    <Search className="w-3.5 h-3.5" />
                    Open Foundation Research Report UI →
                  </Link>
                </div>
              </div>
            </div>
          )}

          {/* Legacy single report banner if not geotech flow */}
          {!isGeotechnicalFlow && finalOutput?.report_id && finalOutput?.document_id && (
            <div className="p-4 bg-indigo-950/40 border border-indigo-800/60 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-3">
              <div>
                <span className="text-xs font-bold text-indigo-300 flex items-center gap-1.5">
                  <CheckCircle2 className="w-3.5 h-3.5 text-indigo-400" />
                  AI Analysis Report Ready
                </span>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  Report ID: <code className="text-slate-200">{finalOutput.report_id}</code> • Review Status: <span className="font-semibold text-amber-300">{finalOutput.review_status || 'PENDING_REVIEW'}</span>
                </p>
              </div>
              <Link
                to={`/documents/${encodeURIComponent(finalOutput.document_id)}`}
                className="btn-primary inline-flex items-center gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-500 text-white px-3 py-1.5 rounded-lg shrink-0 self-start md:self-auto"
              >
                <FileText className="w-3.5 h-3.5" />
                Open Document & AI Report
              </Link>
            </div>
          )}

          {/* Final output */}
          {finalOutput && (
            <div className="rounded-xl border border-emerald-500/25 overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-3 bg-emerald-500/8 border-b border-emerald-500/20">
                <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                <span className="text-sm font-semibold text-emerald-400">Final Output</span>
              </div>
              <pre className="p-4 bg-[#080c14] text-xs font-mono text-emerald-300/90 overflow-x-auto max-h-80 leading-relaxed">
                {JSON.stringify(finalOutput, null, 2)}
              </pre>
            </div>
          )}

          {/* Per-node cards */}
          {Object.keys(nodeOutputs).length === 0 ? (
            <div className="py-12 text-center">
              <Layers className="w-8 h-8 text-slate-700 mx-auto mb-3" />
              <p className="text-sm text-slate-500">No node outputs generated yet</p>
            </div>
          ) : (
            <div className="space-y-3">
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Per-Node Outputs ({Object.keys(nodeOutputs).length})
              </h3>
              {Object.entries(nodeOutputs).map(([nodeId, output]) => (
                <NodeOutputCard key={nodeId} nodeId={nodeId} output={output} docId={primaryDocId} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab: Events */}
      {activeTab === 'events' && (
        <div className="pt-1">
          {events.length === 0 ? (
            <div className="py-12 text-center">
              <FileText className="w-8 h-8 text-slate-700 mx-auto mb-3" />
              <p className="text-sm text-slate-500">No recorded events for this run</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {events.map((ev, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between px-4 py-3 rounded-xl bg-slate-900/50 border border-slate-800/60 hover:border-slate-700/60 transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <StatusBadge status={ev.status} />
                    <span className="font-mono text-sm text-slate-200">{ev.node_id}</span>
                  </div>
                  <span className="font-mono text-[11px] text-slate-500">
                    {ev.created_at ? new Date(ev.created_at).toLocaleTimeString() : '—'}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tab: Raw */}
      {activeTab === 'raw' && (
        <div className="pt-1 rounded-xl border border-slate-800/80 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 bg-slate-900/60 border-b border-slate-800/60">
            <Code2 className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-sm font-semibold text-slate-200">Serialized Execution State</span>
          </div>
          <pre className="p-5 bg-[#080c14] text-xs font-mono text-slate-400 overflow-x-auto max-h-[600px] leading-relaxed">
            {JSON.stringify(run, null, 2)}
          </pre>
        </div>
      )}

      {/* Delete modal */}
      {isDeleteModalOpen && (
        <ConfirmModal
          isOpen={true}
          title="Delete Run Record"
          message={`Permanently delete run '${run.run_id.slice(0, 8)}…' and all associated execution events?`}
          confirmText="Delete Run"
          cancelText="Cancel"
          isDanger={true}
          isLoading={deleteMutation.isPending}
          onConfirm={() => deleteMutation.mutate()}
          onCancel={() => setIsDeleteModalOpen(false)}
        />
      )}
    </div>
  );
};
