import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { Bot, ArrowLeft, Play, Shield, Wrench, Code2, Clock, ChevronRight } from 'lucide-react';
import { StatusBadge } from '../components/common/StatusBadge';
import { Skeleton } from '../components/common/Skeleton';
import { AgentRunModal } from '../components/agents/AgentRunModal';

export const AgentDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [isRunModalOpen, setIsRunModalOpen] = useState(false);

  const { data: agent, isLoading, error } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => api.getAgent(id!),
    enabled: Boolean(id),
  });

  const { data: allRuns = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: () => api.listRuns(),
  });

  const agentRuns = allRuns.filter((r) => r.payload?.agent_id === id);

  if (isLoading) {
    return (
      <div className="space-y-6 w-full">
        <Skeleton className="h-6 w-32" />
        <Skeleton className="h-44 w-full rounded-xl" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <Skeleton className="lg:col-span-2 h-96 rounded-xl" />
          <Skeleton className="h-96 rounded-xl" />
        </div>
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="p-6 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-400 text-sm">
        Failed to load agent details: {(error as any)?.message || 'Agent not found'}
      </div>
    );
  }

  return (
    <div className="space-y-6 w-full">
      {/* Back button */}
      <Link
        to="/agents"
        className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-200 font-medium transition-colors"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to Agents
      </Link>

      {/* Header Profile */}
      <div className="card p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-blue-500/10 border border-blue-500/20 text-blue-400 rounded-xl shrink-0">
            <Bot className="w-7 h-7" />
          </div>
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <h2 className="text-xl font-bold text-slate-100">{agent.name}</h2>
              <span className="font-mono text-xs text-slate-400 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700/50">
                {agent.id}
              </span>
              <StatusBadge status={agent.status || 'available'} />
            </div>
            <p className="text-xs text-slate-400 mt-1.5">{agent.description || 'No description provided.'}</p>
          </div>
        </div>

        <button
          onClick={() => setIsRunModalOpen(true)}
          className="btn-primary shrink-0 self-start md:self-auto"
        >
          <Play className="w-3.5 h-3.5" />
          Run Agent
        </button>
      </div>

      {/* Details Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Schemas & Properties (2 cols) */}
        <div className="lg:col-span-2 space-y-6">
          {/* Input Schema */}
          <div className="card p-6 space-y-3">
            <div className="flex items-center gap-2 text-slate-200">
              <Code2 className="w-4 h-4 text-blue-400" />
              <h3 className="text-sm font-semibold">Declared Input Schema</h3>
            </div>
            {agent.input_schema ? (
              <pre className="p-4 bg-[#080c14] rounded-xl border border-slate-800/80 text-xs font-mono text-slate-300 overflow-x-auto max-h-80 leading-relaxed">
                {JSON.stringify(agent.input_schema, null, 2)}
              </pre>
            ) : (
              <p className="text-xs text-slate-500 italic">No formal JSON schema declared.</p>
            )}
          </div>

          {/* Output Schema */}
          {agent.output_schema && (
            <div className="card p-6 space-y-3">
              <div className="flex items-center gap-2 text-slate-200">
                <Code2 className="w-4 h-4 text-emerald-400" />
                <h3 className="text-sm font-semibold">Declared Output Schema</h3>
              </div>
              <pre className="p-4 bg-[#080c14] rounded-xl border border-slate-800/80 text-xs font-mono text-slate-300 overflow-x-auto max-h-80 leading-relaxed">
                {JSON.stringify(agent.output_schema, null, 2)}
              </pre>
            </div>
          )}

          {/* Recent Direct Runs */}
          <div className="card p-6 space-y-3">
            <h3 className="text-sm font-semibold text-slate-200">Recent Direct Runs</h3>
            {agentRuns.length === 0 ? (
              <p className="text-xs text-slate-500 italic">No direct executions recorded for this agent.</p>
            ) : (
              <div className="divide-y divide-slate-800/60 text-xs">
                {agentRuns.slice(0, 5).map((r) => (
                  <div key={r.run_id} className="py-2.5 flex items-center justify-between">
                    <div className="flex items-center gap-2.5 font-mono">
                      <StatusBadge status={r.status} />
                      <span className="text-slate-300">{r.run_id.slice(0, 10)}…</span>
                    </div>
                    <Link to={`/runs/${r.run_id}`} className="text-blue-400 hover:text-blue-300 font-medium inline-flex items-center gap-1 transition-colors">
                      Details
                      <ChevronRight className="w-3 h-3" />
                    </Link>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Metadata & Security Audit */}
        <div className="space-y-6">
          <div className="card p-6 space-y-4">
            <div className="flex items-center gap-2 text-slate-200">
              <Shield className="w-4 h-4 text-purple-400" />
              <h3 className="text-sm font-semibold">Runtime Metadata</h3>
            </div>

            <div className="space-y-3 text-xs">
              <div className="flex justify-between py-1.5 border-b border-slate-800/60">
                <span className="text-slate-500">Adapter Type</span>
                <span className="font-mono text-slate-300">{agent.adapter_type || 'python_callable'}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-800/60">
                <span className="text-slate-500">Version</span>
                <span className="font-mono text-slate-300">v{agent.version || '1.0.0'}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-800/60">
                <span className="text-slate-500">Status</span>
                <StatusBadge status={agent.status || 'available'} />
              </div>
              {agent.entrypoint && (
                <div className="flex justify-between py-1.5 border-b border-slate-800/60">
                  <span className="text-slate-500">Entrypoint</span>
                  <span className="font-mono text-slate-300 truncate max-w-[180px]" title={agent.entrypoint}>
                    {agent.entrypoint}
                  </span>
                </div>
              )}
            </div>

            {/* Capabilities */}
            <div className="pt-2">
              <span className="text-xs font-medium text-slate-400 block mb-2">Capabilities</span>
              <div className="flex flex-wrap gap-1.5">
                {agent.capabilities && agent.capabilities.length > 0 ? (
                  agent.capabilities.map((cap) => (
                    <span
                      key={cap}
                      className="badge bg-purple-500/10 border border-purple-500/20 text-purple-300 font-mono"
                    >
                      {cap}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-slate-500 italic">None declared</span>
                )}
              </div>
            </div>

            {/* Bound Tools */}
            <div className="pt-2">
              <span className="text-xs font-medium text-slate-400 block mb-2 flex items-center gap-1.5">
                <Wrench className="w-3.5 h-3.5 text-amber-400" />
                Bound Tools
              </span>
              <div className="flex flex-wrap gap-1.5">
                {agent.execution?.allowed_tools && agent.execution.allowed_tools.length > 0 ? (
                  agent.execution.allowed_tools.map((t: string) => (
                    <span
                      key={t}
                      className="badge bg-amber-500/10 border border-amber-500/20 text-amber-300 font-mono"
                    >
                      {t}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-slate-500 italic">No external tools attached</span>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Direct Run Modal */}
      {isRunModalOpen && (
        <AgentRunModal
          isOpen={true}
          agent={agent}
          onClose={() => setIsRunModalOpen(false)}
        />
      )}
    </div>
  );
};
