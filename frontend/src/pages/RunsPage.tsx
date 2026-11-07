import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { PlayCircle, Search, SlidersHorizontal, RefreshCw, AlertCircle } from 'lucide-react';
import { Link } from 'react-router-dom';
import { StatusBadge } from '../components/common/StatusBadge';
import { TableSkeleton } from '../components/common/Skeleton';
import { EmptyState } from '../components/common/EmptyState';

const STATUS_OPTIONS = [
  { value: 'all', label: 'All Statuses' },
  { value: 'running', label: 'Running' },
  { value: 'succeeded', label: 'Succeeded' },
  { value: 'failed', label: 'Failed' },
  { value: 'waiting_for_approval', label: 'Awaiting Approval' },
  { value: 'partially_succeeded', label: 'Partially Succeeded' },
];

export const RunsPage: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [searchTerm, setSearchTerm] = useState('');

  const { data: runs = [], isLoading, error, refetch } = useQuery({
    queryKey: ['runs', statusFilter],
    queryFn: () => api.listRuns(statusFilter === 'all' ? undefined : statusFilter),
    refetchInterval: 5000,
  });

  const filteredRuns = runs.filter((run) => {
    const target = run.workflow_id || run.payload?.agent_id || 'direct_agent';
    return (
      run.run_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      target.toLowerCase().includes(searchTerm.toLowerCase())
    );
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="page-header">
        <div>
          <h2 className="section-title">Runs</h2>
          <p className="section-subtitle">Persisted execution records, node outputs, and checkpoint state</p>
        </div>
        <button
          onClick={() => refetch()}
          className="btn-secondary"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-2">
        <div className="flex-1 flex items-center gap-2 px-3 py-2.5 bg-slate-900/60 border border-slate-800/80 rounded-xl">
          <Search className="w-4 h-4 text-slate-500 shrink-0" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search by Run ID or Workflow / Agent ID…"
            className="flex-1 bg-transparent text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none"
          />
          {searchTerm && (
            <button onClick={() => setSearchTerm('')} className="text-[11px] text-slate-500 hover:text-slate-300 transition-colors">Clear</button>
          )}
        </div>

        <div className="flex items-center gap-2 px-3 py-2.5 bg-slate-900/60 border border-slate-800/80 rounded-xl shrink-0">
          <SlidersHorizontal className="w-3.5 h-3.5 text-slate-500 shrink-0" />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-transparent text-sm text-slate-300 border-none focus:outline-none cursor-pointer pr-2"
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value} className="bg-slate-900 text-slate-200">
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      {isLoading ? (
        <TableSkeleton rows={6} cols={6} />
      ) : error ? (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-rose-500/8 border border-rose-500/25 text-rose-400 text-sm">
          <AlertCircle className="w-4 h-4 shrink-0" />
          Failed to load runs: {(error as any).message}
        </div>
      ) : filteredRuns.length === 0 ? (
        <EmptyState
          icon={PlayCircle}
          title="No execution runs found"
          description={
            statusFilter !== 'all' || searchTerm
              ? 'No runs matched your filter criteria.'
              : 'Run a workflow or agent to see execution records here.'
          }
        />
      ) : (
        <div className="table-container">
          <table className="w-full text-left">
            <thead className="bg-slate-950/40 border-b border-slate-800/60">
              <tr>
                <th className="table-header">Run ID</th>
                <th className="table-header">Target</th>
                <th className="table-header">Status</th>
                <th className="table-header hidden md:table-cell">Owner</th>
                <th className="table-header hidden sm:table-cell">Started</th>
                <th className="table-header text-right">View</th>
              </tr>
            </thead>
            <tbody>
              {filteredRuns.map((run) => {
                const isWorkflow = Boolean(run.workflow_id);
                const targetName = run.workflow_id || run.payload?.agent_id || 'direct_agent';
                const errorMsg = run.payload?.error?.message;

                return (
                  <tr key={run.run_id} className="table-row">
                    {/* Run ID */}
                    <td className="table-cell">
                      <Link
                        to={`/runs/${run.run_id}`}
                        className="font-mono text-[11px] font-medium text-slate-300 hover:text-blue-400 transition-colors"
                      >
                        {run.run_id.slice(0, 12)}…
                      </Link>
                    </td>

                    {/* Target */}
                    <td className="table-cell">
                      <div className="min-w-0">
                        <span className={`font-mono text-xs font-medium ${isWorkflow ? 'text-violet-400' : 'text-blue-400'}`}>
                          {targetName}
                        </span>
                        {run.workflow_version && (
                          <span className="text-slate-600 text-[10px] font-mono ml-1.5">v{run.workflow_version}</span>
                        )}
                        {errorMsg && (
                          <p className="text-[11px] text-rose-400 truncate max-w-[240px] mt-0.5">{errorMsg}</p>
                        )}
                      </div>
                    </td>

                    {/* Status */}
                    <td className="table-cell">
                      <StatusBadge status={run.status} />
                    </td>

                    {/* Owner */}
                    <td className="table-cell hidden md:table-cell font-mono text-xs text-slate-500">
                      {run.owner_id || 'development'}
                    </td>

                    {/* Time */}
                    <td className="table-cell hidden sm:table-cell font-mono text-[11px] text-slate-500">
                      {run.created_at ? new Date(run.created_at).toLocaleString() : '—'}
                    </td>

                    {/* Action */}
                    <td className="table-cell text-right">
                      <Link
                        to={`/runs/${run.run_id}`}
                        className="text-[11px] font-medium text-blue-400 hover:text-blue-300 transition-colors"
                      >
                        Details →
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-4 py-2.5 border-t border-slate-800/60 bg-slate-950/20 text-[11px] text-slate-600">
            {filteredRuns.length} run{filteredRuns.length !== 1 ? 's' : ''}
            {searchTerm || statusFilter !== 'all' ? ' matched' : ' total'}
            {' · '}auto-refreshing every 5s
          </div>
        </div>
      )}
    </div>
  );
};
