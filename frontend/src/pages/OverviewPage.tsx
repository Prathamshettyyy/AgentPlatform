import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import {
  Bot,
  GitBranch,
  PlayCircle,
  CheckSquare,
  AlertTriangle,
  ArrowUpRight,
  Server,
  Activity,
  TrendingUp,
  Clock,
  Zap,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { StatusBadge } from '../components/common/StatusBadge';
import { Skeleton } from '../components/common/Skeleton';

/* ── Metric card ── */
interface StatCardProps {
  title: string;
  value: number | string;
  subtext: string;
  icon: React.ElementType;
  accent: string;      // tailwind colour classes for icon bg/border/text
  link: string;
  loading: boolean;
}

const StatCard: React.FC<StatCardProps> = ({ title, value, subtext, icon: Icon, accent, link, loading }) => (
  <Link
    to={link}
    className="group relative p-5 rounded-xl bg-slate-900/50 border border-slate-800/80 hover:border-slate-700/80 hover:bg-slate-900/80 transition-all duration-200 overflow-hidden"
  >
    {/* subtle glow bg */}
    <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none">
      <div className={`absolute -top-6 -right-6 w-24 h-24 rounded-full blur-2xl opacity-20 ${accent.split(' ')[2]?.replace('text-', 'bg-') || ''}`} />
    </div>

    <div className="relative">
      <div className="flex items-start justify-between mb-4">
        <span className="text-xs font-medium text-slate-500">{title}</span>
        <div className={`p-2 rounded-lg border ${accent}`}>
          <Icon className="w-3.5 h-3.5" />
        </div>
      </div>

      <div className="text-3xl font-bold text-slate-50 font-mono tracking-tight mb-1.5">
        {loading ? <Skeleton className="h-9 w-14" /> : value}
      </div>

      <div className="flex items-center justify-between">
        <span className="text-[11px] text-slate-500">{subtext}</span>
        <ArrowUpRight className="w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 transition-colors" />
      </div>
    </div>
  </Link>
);

/* ── Main page ── */
export const OverviewPage: React.FC = () => {
  const { isConnected, baseUrl, authMode } = useAuth();

  const { data: stats, isLoading: statsLoading, error: statsError } = useQuery({
    queryKey: ['overview-stats'],
    queryFn: api.getOverview,
    refetchInterval: 5000,
  });

  const { data: recentRuns, isLoading: runsLoading } = useQuery({
    queryKey: ['recent-runs'],
    queryFn: () => api.listRuns(),
    refetchInterval: 5000,
  });

  const cards: Omit<StatCardProps, 'loading'>[] = [
    {
      title: 'Connected Agents',
      value: stats?.agents_count ?? 0,
      subtext: 'Ready for execution',
      icon: Bot,
      accent: 'bg-blue-500/10 border-blue-500/25 text-blue-400',
      link: '/agents',
    },
    {
      title: 'Workflows',
      value: stats?.workflows_total ?? 0,
      subtext: `${stats?.workflows_registered ?? 0} registered · ${stats?.workflows_drafts ?? 0} drafts`,
      icon: GitBranch,
      accent: 'bg-violet-500/10 border-violet-500/25 text-violet-400',
      link: '/workflows',
    },
    {
      title: 'Total Runs',
      value: stats?.runs_total ?? 0,
      subtext: `${stats?.runs_succeeded ?? 0} succeeded · ${stats?.runs_failed ?? 0} failed`,
      icon: PlayCircle,
      accent: 'bg-emerald-500/10 border-emerald-500/25 text-emerald-400',
      link: '/runs',
    },
    {
      title: 'Pending Approvals',
      value: stats?.pending_approvals ?? 0,
      subtext: (stats?.pending_approvals ?? 0) > 0 ? 'Requires human review' : 'All clear',
      icon: CheckSquare,
      accent:
        (stats?.pending_approvals ?? 0) > 0
          ? 'bg-amber-500/10 border-amber-500/30 text-amber-400'
          : 'bg-slate-800/50 border-slate-700/40 text-slate-500',
      link: '/approvals',
    },
  ];

  return (
    <div className="space-y-7">
      {/* Offline banner */}
      {!isConnected && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-rose-500/8 border border-rose-500/25 text-rose-300">
          <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-rose-300">Backend API Disconnected</p>
            <p className="text-xs text-rose-400/70 mt-0.5">
              Cannot reach <code className="font-mono bg-rose-950/50 px-1.5 py-0.5 rounded">{baseUrl}</code>.
              Ensure the server is running and check Settings.
            </p>
          </div>
          <Link to="/settings" className="btn-danger shrink-0 text-[11px]">
            Configure
          </Link>
        </div>
      )}

      {/* Auth error */}
      {statsError && String(statsError).includes('401') && (
        <div className="flex items-start gap-3 p-4 rounded-xl bg-amber-500/8 border border-amber-500/25 text-amber-300">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold">Authentication Required</p>
            <p className="text-xs text-amber-400/70 mt-0.5">
              The API rejected your request (HTTP 401). Set your token in Settings or start the server in dev mode.
            </p>
          </div>
          <Link to="/settings" className="btn-secondary shrink-0 text-[11px]">
            Set Token
          </Link>
        </div>
      )}

      {/* Page heading */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h2 className="section-title flex items-center gap-2">
            <Activity className="w-5 h-5 text-blue-400" />
            Operational Overview
          </h2>
          <p className="section-subtitle mt-1">Real-time platform health and execution state</p>
        </div>
        <div className="flex items-center gap-2">
          <div
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs border ${
              isConnected
                ? 'bg-emerald-500/8 border-emerald-500/20 text-emerald-400'
                : 'bg-rose-500/8 border-rose-500/20 text-rose-400'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'}`} />
            {isConnected ? 'Online' : 'Offline'}
          </div>
          <Link to="/workflows" className="btn-primary text-[11px]">
            <GitBranch className="w-3.5 h-3.5" />
            Manage Workflows
          </Link>
        </div>
      </div>

      {/* KPI grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {cards.map((card) => (
          <StatCard key={card.title} {...card} loading={statsLoading} />
        ))}
      </div>

      {/* Bottom two-col */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* Recent runs table */}
        <div className="xl:col-span-2 rounded-xl bg-slate-900/50 border border-slate-800/80 overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-800/60 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-blue-400" />
              <h3 className="text-sm font-semibold text-slate-100">Recent Executions</h3>
            </div>
            <Link to="/runs" className="text-[11px] font-medium text-blue-400 hover:text-blue-300 transition-colors">
              View all →
            </Link>
          </div>

          {runsLoading ? (
            <div className="p-5 space-y-3">
              {[...Array(4)].map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : !recentRuns || recentRuns.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <PlayCircle className="w-8 h-8 text-slate-700 mx-auto mb-3" />
              <p className="text-sm text-slate-500">No executions yet</p>
              <p className="text-xs text-slate-600 mt-1">Run a workflow to see results here</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-slate-800/60">
                    <th className="table-header">Run ID</th>
                    <th className="table-header">Target</th>
                    <th className="table-header">Status</th>
                    <th className="table-header">Time</th>
                    <th className="table-header text-right">View</th>
                  </tr>
                </thead>
                <tbody>
                  {recentRuns.slice(0, 7).map((run) => (
                    <tr key={run.run_id} className="table-row">
                      <td className="table-cell font-mono text-[11px] text-slate-300">
                        <Link to={`/runs/${run.run_id}`} className="hover:text-blue-400 transition-colors">
                          {run.run_id.slice(0, 8)}…
                        </Link>
                      </td>
                      <td className="table-cell">
                        {run.workflow_id ? (
                          <span className="text-[11px] font-mono text-violet-400">{run.workflow_id}</span>
                        ) : (
                          <span className="text-[11px] font-mono text-blue-400">{run.payload?.agent_id || 'agent'}</span>
                        )}
                      </td>
                      <td className="table-cell">
                        <StatusBadge status={run.status} />
                      </td>
                      <td className="table-cell text-[11px] text-slate-500 font-mono">
                        {run.created_at ? new Date(run.created_at).toLocaleTimeString() : '—'}
                      </td>
                      <td className="table-cell text-right">
                        <Link
                          to={`/runs/${run.run_id}`}
                          className="text-[11px] text-blue-400 hover:text-blue-300 font-medium transition-colors"
                        >
                          Details →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Platform info */}
        <div className="rounded-xl bg-slate-900/50 border border-slate-800/80 overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-800/60 flex items-center gap-2">
            <Server className="w-4 h-4 text-blue-400" />
            <h3 className="text-sm font-semibold text-slate-100">Platform Info</h3>
          </div>

          <div className="p-5 space-y-3">
            {[
              { label: 'API Server', value: baseUrl, mono: true },
              { label: 'Status', value: isConnected ? 'Online' : 'Offline', color: isConnected ? 'text-emerald-400' : 'text-rose-400' },
              { label: 'Auth Mode', value: authMode || 'required', mono: true },
              { label: 'Engine', value: 'LangGraph (DAGs)', mono: true },
              { label: 'Checkpointer', value: 'AsyncSqliteSaver', mono: true },
            ].map(({ label, value, mono, color }) => (
              <div key={label} className="flex justify-between items-center text-xs py-2 border-b border-slate-800/40 last:border-0">
                <span className="text-slate-500">{label}</span>
                <span className={`${mono ? 'font-mono' : ''} ${color || 'text-slate-300'} text-right max-w-[55%] truncate`}>
                  {value}
                </span>
              </div>
            ))}
          </div>

          <div className="px-5 pb-5">
            <Link
              to="/settings"
              className="w-full btn-secondary justify-center text-[11px]"
            >
              <Zap className="w-3.5 h-3.5" />
              Auth & Settings
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
};
