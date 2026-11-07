import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { FileText, Search, RefreshCw, ChevronDown, ChevronUp, Clock, Info } from 'lucide-react';
import { Link } from 'react-router-dom';
import { StatusBadge } from '../components/common/StatusBadge';
import { TableSkeleton } from '../components/common/Skeleton';
import { EmptyState } from '../components/common/EmptyState';

export const EventsPage: React.FC = () => {
  const [searchTerm, setSearchTerm] = useState('');
  const [isAutoRefresh, setIsAutoRefresh] = useState(true);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);
  const [limit, setLimit] = useState(100);

  const { data: events = [], isLoading, error, refetch } = useQuery({
    queryKey: ['events', limit],
    queryFn: () => api.listEvents(undefined, limit),
    refetchInterval: isAutoRefresh ? 3000 : false,
  });

  const filteredEvents = events.filter((ev) => {
    const term = searchTerm.toLowerCase();
    return (
      ev.run_id.toLowerCase().includes(term) ||
      ev.node_id.toLowerCase().includes(term) ||
      ev.status.toLowerCase().includes(term)
    );
  });

  const toggleRow = (idx: number) => setExpandedRow((prev) => (prev === idx ? null : idx));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="page-header">
        <div>
          <h2 className="section-title">Logs & Events</h2>
          <p className="section-subtitle">Persisted execution event telemetry and step-level node states</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsAutoRefresh(!isAutoRefresh)}
            className={`btn-secondary text-[11px] ${isAutoRefresh ? 'border-blue-500/30 text-blue-400 bg-blue-500/8' : ''}`}
          >
            <Clock className="w-3.5 h-3.5" />
            {isAutoRefresh ? 'Auto (3s)' : 'Manual'}
          </button>
          <button onClick={() => refetch()} className="btn-secondary text-[11px]">
            <RefreshCw className="w-3.5 h-3.5" />
            Refresh
          </button>
        </div>
      </div>

      {/* Info notice */}
      <div className="flex items-start gap-2.5 p-3 rounded-xl bg-blue-500/5 border border-blue-500/15 text-xs text-slate-400">
        <Info className="w-3.5 h-3.5 text-blue-400 shrink-0 mt-0.5" />
        <span>
          Sanitized workflow execution events recorded in the SQLite repository. Sensitive tokens and credential headers are redacted at recording time.
        </span>
      </div>

      {/* Search & Limit */}
      <div className="flex flex-col sm:flex-row gap-2">
        <div className="flex-1 flex items-center gap-2 px-3 py-2.5 bg-slate-900/60 border border-slate-800/80 rounded-xl">
          <Search className="w-4 h-4 text-slate-500 shrink-0" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search by Run ID, Node ID, or status…"
            className="flex-1 bg-transparent text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none"
          />
          {searchTerm && (
            <button onClick={() => setSearchTerm('')} className="text-[11px] text-slate-500 hover:text-slate-300 transition-colors">Clear</button>
          )}
        </div>

        <div className="flex items-center gap-2 px-3 py-2.5 bg-slate-900/60 border border-slate-800/80 rounded-xl shrink-0">
          <span className="text-xs text-slate-500">Rows:</span>
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="bg-transparent text-sm text-slate-300 border-none focus:outline-none cursor-pointer"
          >
            {[50, 100, 200].map((v) => (
              <option key={v} value={v} className="bg-slate-900 text-slate-200">{v}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      {isLoading ? (
        <TableSkeleton rows={8} cols={5} />
      ) : error ? (
        <div className="p-5 rounded-xl bg-rose-500/8 border border-rose-500/25 text-rose-400 text-sm">
          Failed to load events: {(error as any).message}
        </div>
      ) : filteredEvents.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="No execution events"
          description={searchTerm ? 'No events match your filter.' : 'Run a workflow or agent to generate events.'}
        />
      ) : (
        <div className="table-container">
          <table className="w-full text-left">
            <thead className="bg-slate-950/40 border-b border-slate-800/60">
              <tr>
                <th className="table-header hidden sm:table-cell">Timestamp</th>
                <th className="table-header">Node / Step</th>
                <th className="table-header">Status</th>
                <th className="table-header">Run ID</th>
                <th className="table-header text-right">Payload</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              {filteredEvents.map((ev, idx) => {
                const isExpanded = expandedRow === idx;
                const hasPayload = ev.payload && Object.keys(ev.payload).length > 0;
                return (
                  <React.Fragment key={idx}>
                    <tr className={`table-row ${isExpanded ? 'bg-slate-800/30' : ''}`}>
                      <td className="table-cell hidden sm:table-cell text-[11px] text-slate-500 whitespace-nowrap">
                        {ev.created_at ? new Date(ev.created_at).toLocaleTimeString() : '—'}
                      </td>
                      <td className="table-cell text-xs font-semibold text-slate-200">{ev.node_id}</td>
                      <td className="table-cell"><StatusBadge status={ev.status} /></td>
                      <td className="table-cell text-[11px] text-slate-400">
                        <Link to={`/runs/${ev.run_id}`} className="hover:text-blue-400 transition-colors">
                          {ev.run_id.slice(0, 8)}…
                        </Link>
                      </td>
                      <td className="table-cell text-right">
                        {hasPayload ? (
                          <button
                            onClick={() => toggleRow(idx)}
                            className="inline-flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 font-sans transition-colors"
                          >
                            {isExpanded ? 'Hide' : 'Inspect'}
                            {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                          </button>
                        ) : (
                          <span className="text-[11px] text-slate-700 font-sans italic">none</span>
                        )}
                      </td>
                    </tr>
                    {isExpanded && hasPayload && (
                      <tr className="bg-[#080c14]">
                        <td colSpan={5} className="px-4 py-3 border-b border-slate-800/40">
                          <p className="text-[10px] font-sans font-semibold text-slate-600 uppercase tracking-wider mb-2">
                            Payload — {ev.node_id}
                          </p>
                          <pre className="p-3 bg-slate-900/80 rounded-lg border border-slate-800/60 text-xs text-slate-300 overflow-x-auto max-h-64 leading-relaxed">
                            {JSON.stringify(ev.payload, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
          <div className="px-4 py-2.5 border-t border-slate-800/60 bg-slate-950/20 text-[11px] text-slate-600">
            {filteredEvents.length} event{filteredEvents.length !== 1 ? 's' : ''}
            {searchTerm ? ` matching "${searchTerm}"` : ''}
          </div>
        </div>
      )}
    </div>
  );
};
