import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { CheckSquare, CheckCircle2, XCircle, Clock, AlertCircle, RefreshCw } from 'lucide-react';
import { Link } from 'react-router-dom';
import { StatusBadge } from '../components/common/StatusBadge';
import { TableSkeleton } from '../components/common/Skeleton';
import { EmptyState } from '../components/common/EmptyState';

export const ApprovalsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data: approvals = [], isLoading, error, refetch } = useQuery({
    queryKey: ['approvals'],
    queryFn: api.listApprovals,
    refetchInterval: 5000,
  });

  const resumeMutation = useMutation({
    mutationFn: ({ runId, decision }: { runId: string; decision: string }) =>
      api.resumeApproval(runId, decision),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['approvals'] });
      queryClient.invalidateQueries({ queryKey: ['runs'] });
      queryClient.invalidateQueries({ queryKey: ['overview-stats'] });
      setErrorMsg(null);
    },
    onError: (err: any) => { setErrorMsg(err.message || 'Failed to submit decision'); },
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="page-header">
        <div>
          <h2 className="section-title">Human Approvals</h2>
          <p className="section-subtitle">Workflow executions currently paused awaiting human review</p>
        </div>
        <button onClick={() => refetch()} className="btn-secondary">
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* Error */}
      {errorMsg && (
        <div className="flex items-center gap-3 p-3 rounded-xl bg-rose-500/8 border border-rose-500/25 text-rose-400 text-xs">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span className="flex-1">{errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} className="text-rose-400/60 hover:text-rose-300 transition-colors">✕</button>
        </div>
      )}

      {/* Content */}
      {isLoading ? (
        <TableSkeleton rows={3} cols={5} />
      ) : error ? (
        <div className="p-5 rounded-xl bg-rose-500/8 border border-rose-500/25 text-rose-400 text-sm">
          Failed to load approvals: {(error as any).message}
        </div>
      ) : approvals.length === 0 ? (
        <EmptyState
          icon={CheckSquare}
          title="No pending approvals"
          description="All clear — no workflow executions are currently awaiting human approval."
        />
      ) : (
        <div className="space-y-4">
          {approvals.map((run) => (
            <div
              key={run.run_id}
              className="rounded-xl border border-amber-500/25 bg-slate-900/50 overflow-hidden"
            >
              {/* Card header */}
              <div className="px-5 py-4 bg-amber-500/6 border-b border-amber-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <Clock className="w-4 h-4 text-amber-400 shrink-0" />
                  <span className="font-mono text-sm font-bold text-slate-100">{run.run_id.slice(0, 16)}…</span>
                  <StatusBadge status={run.status} />
                </div>
                <span className="text-xs text-slate-500 font-mono">
                  Workflow: <span className="text-violet-400 font-semibold">{run.workflow_id}</span> (v{run.workflow_version})
                </span>
              </div>

              {/* Interrupt context */}
              <div className="p-5 space-y-3">
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Interrupt Context / Node Outputs</p>
                <pre className="p-4 bg-[#080c14] rounded-xl border border-slate-800/60 text-xs font-mono text-slate-300 overflow-x-auto max-h-48 leading-relaxed">
                  {JSON.stringify(run.payload?.node_outputs || run.payload?.__interrupt__ || run.payload, null, 2)}
                </pre>

                {/* Actions */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                  <Link to={`/runs/${run.run_id}`} className="text-xs text-blue-400 hover:text-blue-300 font-medium transition-colors">
                    View full execution →
                  </Link>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => resumeMutation.mutate({ runId: run.run_id, decision: 'reject' })}
                      disabled={resumeMutation.isPending}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-rose-600/15 hover:bg-rose-600/25 text-rose-400 border border-rose-500/25 rounded-lg transition-all disabled:opacity-50"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      Reject
                    </button>
                    <button
                      onClick={() => resumeMutation.mutate({ runId: run.run_id, decision: 'approve' })}
                      disabled={resumeMutation.isPending}
                      className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-all shadow-sm hover:shadow-emerald-500/20 disabled:opacity-50"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Approve & Resume
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
