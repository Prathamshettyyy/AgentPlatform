import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { AgentMetadata, AgentDeletePreview } from '../api/types';
import { Bot, Play, Trash2, Search, Link2, Terminal, AlertCircle, ChevronRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { StatusBadge } from '../components/common/StatusBadge';
import { EmptyState } from '../components/common/EmptyState';
import { TableSkeleton } from '../components/common/Skeleton';
import { ConfirmModal } from '../components/common/ConfirmModal';
import { AgentRunModal } from '../components/agents/AgentRunModal';

export const AgentsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedAgentForRun, setSelectedAgentForRun] = useState<AgentMetadata | null>(null);
  const [agentToDelete, setAgentToDelete] = useState<AgentMetadata | null>(null);
  const [deletePreview, setDeletePreview] = useState<AgentDeletePreview | null>(null);
  const [isFetchingPreview, setIsFetchingPreview] = useState(false);
  const [showConnectGuide, setShowConnectGuide] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data: agents = [], isLoading, error } = useQuery({
    queryKey: ['agents'],
    queryFn: api.listAgents,
  });

  const deleteMutation = useMutation({
    mutationFn: (agentId: string) => api.deleteAgent(agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] });
      queryClient.invalidateQueries({ queryKey: ['workflows'] });
      queryClient.invalidateQueries({ queryKey: ['overview-stats'] });
      setAgentToDelete(null);
      setDeletePreview(null);
    },
    onError: (err: any) => {
      setErrorMsg(err.message || 'Failed to delete agent');
      setAgentToDelete(null);
      setDeletePreview(null);
    },
  });

  const handleInitiateDelete = async (agent: AgentMetadata) => {
    setAgentToDelete(agent);
    setIsFetchingPreview(true);
    try {
      const preview = await api.previewDeleteAgent(agent.id);
      setDeletePreview(preview);
    } catch {
      setDeletePreview(null);
    } finally {
      setIsFetchingPreview(false);
    }
  };

  const filteredAgents = agents.filter(
    (a) =>
      a.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      a.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (a.description || '').toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="page-header">
        <div>
          <h2 className="section-title">Agents</h2>
          <p className="section-subtitle">Connected execution nodes available for workflows and direct runs</p>
        </div>
        <button
          onClick={() => setShowConnectGuide(true)}
          className="btn-secondary"
        >
          <Link2 className="w-3.5 h-3.5 text-blue-400" />
          Connect Agent
        </button>
      </div>

      {/* Error banner */}
      {errorMsg && (
        <div className="flex items-center gap-3 p-3 rounded-xl bg-rose-500/8 border border-rose-500/25 text-rose-400 text-xs">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span className="flex-1">{errorMsg}</span>
          <button onClick={() => setErrorMsg(null)} className="text-rose-400/60 hover:text-rose-300 transition-colors">✕</button>
        </div>
      )}

      {/* Search */}
      <div className="flex items-center gap-2 px-3 py-2.5 bg-slate-900/60 border border-slate-800/80 rounded-xl">
        <Search className="w-4 h-4 text-slate-500 shrink-0" />
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Search by name, ID, or description…"
          className="flex-1 bg-transparent text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none"
        />
        {searchTerm && (
          <button onClick={() => setSearchTerm('')} className="text-[11px] text-slate-500 hover:text-slate-300 transition-colors">
            Clear
          </button>
        )}
      </div>

      {/* Table */}
      {isLoading ? (
        <TableSkeleton rows={4} cols={5} />
      ) : error ? (
        <div className="p-6 rounded-xl bg-rose-500/8 border border-rose-500/25 text-rose-400 text-sm">
          Failed to load agents: {(error as any).message}
        </div>
      ) : filteredAgents.length === 0 ? (
        <EmptyState
          icon={Bot}
          title="No agents found"
          description={
            searchTerm
              ? 'No agents matched your search query.'
              : 'No external agents are connected to the platform yet.'
          }
          actionText="How to connect an agent"
          onAction={() => setShowConnectGuide(true)}
        />
      ) : (
        <div className="table-container">
          <table className="w-full text-left">
            <thead className="bg-slate-950/40 border-b border-slate-800/60">
              <tr>
                <th className="table-header">Agent</th>
                <th className="table-header hidden md:table-cell">Adapter</th>
                <th className="table-header hidden sm:table-cell">Version</th>
                <th className="table-header">Status</th>
                <th className="table-header text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredAgents.map((agent) => (
                <tr key={agent.id} className="table-row">
                  {/* Agent identity */}
                  <td className="table-cell">
                    <div className="flex items-center gap-3">
                      <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/15 text-blue-400 shrink-0">
                        <Bot className="w-4 h-4" />
                      </div>
                      <div className="min-w-0">
                        <Link
                          to={`/agents/${agent.id}`}
                          className="font-mono text-sm font-semibold text-slate-100 hover:text-blue-400 transition-colors truncate block"
                        >
                          {agent.id}
                        </Link>
                        <span className="text-xs text-slate-500 truncate block">{agent.name}</span>
                        {agent.description && (
                          <p className="text-[11px] text-slate-600 line-clamp-1 mt-0.5 max-w-sm">
                            {agent.description}
                          </p>
                        )}
                      </div>
                    </div>
                  </td>

                  {/* Adapter */}
                  <td className="table-cell hidden md:table-cell">
                    <span className="badge bg-slate-800/80 border border-slate-700/60 text-slate-400 font-mono">
                      {agent.adapter_type || 'python_callable'}
                    </span>
                  </td>

                  {/* Version */}
                  <td className="table-cell hidden sm:table-cell font-mono text-xs text-slate-500">
                    v{agent.version || '1.0.0'}
                  </td>

                  {/* Status */}
                  <td className="table-cell">
                    <StatusBadge status={agent.status || 'available'} />
                  </td>

                  {/* Actions */}
                  <td className="table-cell text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        onClick={() => setSelectedAgentForRun(agent)}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-semibold bg-blue-600/15 hover:bg-blue-600/25 text-blue-400 rounded-lg border border-blue-500/20 transition-all"
                        title="Run this agent"
                      >
                        <Play className="w-3 h-3" />
                        Run
                      </button>
                      <Link
                        to={`/agents/${agent.id}`}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-medium bg-slate-800/60 hover:bg-slate-700/60 text-slate-300 rounded-lg border border-slate-700/40 transition-all"
                      >
                        Details
                        <ChevronRight className="w-3 h-3" />
                      </Link>
                      <button
                        onClick={() => handleInitiateDelete(agent)}
                        className="p-1.5 rounded-lg text-slate-600 hover:text-rose-400 hover:bg-rose-500/10 border border-transparent hover:border-rose-500/15 transition-all"
                        title="Delete agent"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-4 py-2.5 border-t border-slate-800/60 bg-slate-950/20 text-[11px] text-slate-600">
            {filteredAgents.length} agent{filteredAgents.length !== 1 ? 's' : ''}
            {searchTerm ? ` matching "${searchTerm}"` : ' total'}
          </div>
        </div>
      )}

      {/* Connect guide modal */}
      {showConnectGuide && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-lg bg-slate-900 border border-slate-700/60 rounded-2xl shadow-2xl overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-800/60 flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
                  <Terminal className="w-4 h-4" />
                </div>
                <h3 className="font-semibold text-slate-100">Connect an External Agent</h3>
              </div>
              <button
                onClick={() => setShowConnectGuide(false)}
                className="text-slate-500 hover:text-slate-200 p-1 rounded-lg hover:bg-slate-800 transition-colors"
              >
                ✕
              </button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-sm text-slate-400 leading-relaxed">
                For security, the platform enforces explicit local trust approval before importing external Python code.
                Use the CLI to connect project directories:
              </p>
              <div className="p-4 bg-[#0a0f1e] rounded-xl border border-slate-800/80 font-mono text-xs space-y-2">
                <span className="text-slate-600"># Connect with explicit trust flag:</span>
                <div className="text-blue-300">python -m app.cli agents connect ../your_agent_dir --trust</div>
              </div>
              <p className="text-xs text-slate-500 leading-relaxed">
                The CLI computes a SHA-256 fingerprint, discovers agent entrypoints, generates a secure adapter bridge,
                and stores signed metadata in the trusted manifest directory.
              </p>
            </div>
            <div className="px-6 pb-5 flex justify-end">
              <button
                onClick={() => setShowConnectGuide(false)}
                className="btn-secondary"
              >
                Got It
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Run modal */}
      {selectedAgentForRun && (
        <AgentRunModal
          isOpen={true}
          agent={selectedAgentForRun}
          onClose={() => setSelectedAgentForRun(null)}
        />
      )}

      {/* Delete modal */}
      {agentToDelete && (
        <ConfirmModal
          isOpen={true}
          title={`Delete Agent: ${agentToDelete.name || agentToDelete.id}`}
          message="This will permanently delete the agent, manifest, adapter, catalog entry, and all associated runs, events, and checkpoints. Referencing workflows will have this node removed."
          confirmText="Permanently Delete"
          cancelText="Cancel"
          isDanger={true}
          isLoading={deleteMutation.isPending || isFetchingPreview}
          previewItems={[
            { label: 'Agent ID', value: agentToDelete.id },
            { label: 'Direct Runs', value: `${deletePreview?.direct_run_count ?? 0} run(s)`, isDestructive: (deletePreview?.direct_run_count ?? 0) > 0 },
            { label: 'Events', value: `${deletePreview?.event_count ?? 0} event(s)`, isDestructive: (deletePreview?.event_count ?? 0) > 0 },
            { label: 'Checkpoints', value: `${deletePreview?.checkpoint_count ?? 0} record(s)`, isDestructive: (deletePreview?.checkpoint_count ?? 0) > 0 },
            { label: 'Manifest & Adapter', value: deletePreview?.has_manifest || deletePreview?.has_adapter ? 'Deleted from disk' : 'Not present', isDestructive: Boolean(deletePreview?.has_manifest || deletePreview?.has_adapter) },
            { label: 'Catalog Entry', value: deletePreview?.has_catalog_entry ? 'Removed' : 'Not listed', isDestructive: Boolean(deletePreview?.has_catalog_entry) },
            { label: 'Referencing Workflows', value: deletePreview?.workflows_referencing?.length ? deletePreview.workflows_referencing.join(', ') : 'None', isDestructive: Boolean(deletePreview?.workflows_referencing?.length) },
            { label: 'External Source Code', value: 'Untouched', isDestructive: false },
          ]}
          onConfirm={() => deleteMutation.mutate(agentToDelete.id)}
          onCancel={() => { setAgentToDelete(null); setDeletePreview(null); }}
        />
      )}
    </div>
  );
};
