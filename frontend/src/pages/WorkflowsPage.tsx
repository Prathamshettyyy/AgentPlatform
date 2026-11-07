import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { WorkflowDefinition, WorkflowDeletePreview } from '../api/types';
import { GitBranch, Play, Plus, Trash2, Unlink, CheckCircle2, Search, AlertCircle, FileCode, ChevronRight, Layers } from 'lucide-react';
import { Link } from 'react-router-dom';
import { StatusBadge } from '../components/common/StatusBadge';
import { EmptyState } from '../components/common/EmptyState';
import { TableSkeleton } from '../components/common/Skeleton';
import { ConfirmModal } from '../components/common/ConfirmModal';
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal';
import { CreateWorkflowModal } from '../components/workflows/CreateWorkflowModal';

export const WorkflowsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedWorkflowForRun, setSelectedWorkflowForRun] = useState<WorkflowDefinition | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [workflowToDelete, setWorkflowToDelete] = useState<WorkflowDefinition | null>(null);
  const [deletePreview, setDeletePreview] = useState<WorkflowDeletePreview | null>(null);
  const [isFetchingPreview, setIsFetchingPreview] = useState(false);
  const [workflowToDisconnect, setWorkflowToDisconnect] = useState<WorkflowDefinition | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data: workflows = [], isLoading, error } = useQuery({
    queryKey: ['workflows'],
    queryFn: () => api.listWorkflows(true),
  });

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: api.listAgents,
  });

  const disconnectMutation = useMutation({
    mutationFn: (workflowId: string) => api.disconnectWorkflow(workflowId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] });
      queryClient.invalidateQueries({ queryKey: ['overview-stats'] });
      setWorkflowToDisconnect(null);
    },
    onError: (err: any) => { setErrorMsg(err.message || 'Failed to disconnect'); setWorkflowToDisconnect(null); },
  });

  const registerMutation = useMutation({
    mutationFn: (workflow: WorkflowDefinition) => api.registerWorkflow(workflow.id, workflow),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] });
      queryClient.invalidateQueries({ queryKey: ['overview-stats'] });
      setErrorMsg(null);
    },
    onError: (err: any) => { setErrorMsg(err.message || 'Registration failed'); },
  });

  const deleteMutation = useMutation({
    mutationFn: (workflowId: string) => api.deleteWorkflow(workflowId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] });
      queryClient.invalidateQueries({ queryKey: ['overview-stats'] });
      setWorkflowToDelete(null);
      setDeletePreview(null);
    },
    onError: (err: any) => {
      setErrorMsg(err.message || 'Failed to delete workflow');
      setWorkflowToDelete(null);
      setDeletePreview(null);
    },
  });

  const handleInitiateDelete = async (wf: WorkflowDefinition) => {
    setWorkflowToDelete(wf);
    setIsFetchingPreview(true);
    try {
      const preview = await api.previewDeleteWorkflow(wf.id);
      setDeletePreview(preview);
    } catch {
      setDeletePreview(null);
    } finally {
      setIsFetchingPreview(false);
    }
  };

  const filteredWorkflows = workflows.filter(
    (w) =>
      w.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (w.nodes || []).some((n) => (n.agent_id || n.id).toLowerCase().includes(searchTerm.toLowerCase()))
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="page-header">
        <div>
          <h2 className="section-title">Workflows</h2>
          <p className="section-subtitle">Registered multi-agent pipelines and saved local drafts</p>
        </div>
        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="btn-primary"
        >
          <Plus className="w-3.5 h-3.5" />
          Create Workflow
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
          placeholder="Search workflows by ID or agent node…"
          className="flex-1 bg-transparent text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none"
        />
        {searchTerm && (
          <button onClick={() => setSearchTerm('')} className="text-[11px] text-slate-500 hover:text-slate-300 transition-colors">Clear</button>
        )}
      </div>

      {/* Table */}
      {isLoading ? (
        <TableSkeleton rows={4} cols={5} />
      ) : error ? (
        <div className="p-6 rounded-xl bg-rose-500/8 border border-rose-500/25 text-rose-400 text-sm">
          Failed to load workflows: {(error as any).message}
        </div>
      ) : filteredWorkflows.length === 0 ? (
        <EmptyState
          icon={GitBranch}
          title="No workflows found"
          description={
            searchTerm
              ? 'No workflows matched your search.'
              : 'Create your first workflow to connect agents into a pipeline.'
          }
          actionText="Create Workflow"
          onAction={() => setIsCreateModalOpen(true)}
        />
      ) : (
        <div className="table-container">
          <table className="w-full text-left">
            <thead className="bg-slate-950/40 border-b border-slate-800/60">
              <tr>
                <th className="table-header">Workflow</th>
                <th className="table-header hidden sm:table-cell">Version</th>
                <th className="table-header hidden lg:table-cell">Nodes</th>
                <th className="table-header">Status</th>
                <th className="table-header text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredWorkflows.map((wf) => {
                const isRegistered = wf.registered !== false && wf.registration_status !== 'disconnected';
                const nodeCount = wf.nodes?.length || 0;
                const isDraft = nodeCount === 0;

                return (
                  <tr key={wf.id} className="table-row">
                    {/* Identity */}
                    <td className="table-cell">
                      <div className="flex items-center gap-3">
                        <div className={`p-2 rounded-lg border shrink-0 ${
                          isDraft
                            ? 'bg-slate-800/50 border-slate-700/40 text-slate-500'
                            : isRegistered
                            ? 'bg-violet-500/10 border-violet-500/20 text-violet-400'
                            : 'bg-slate-700/30 border-slate-700/30 text-slate-500'
                        }`}>
                          {isDraft ? <FileCode className="w-4 h-4" /> : <GitBranch className="w-4 h-4" />}
                        </div>
                        <div className="min-w-0">
                          <Link
                            to={`/workflows/${wf.id}`}
                            className="font-mono text-sm font-semibold text-slate-100 hover:text-violet-400 transition-colors truncate block"
                          >
                            {wf.id}
                          </Link>
                          {wf.workflow_file && (
                            <p className="text-[10px] text-slate-600 font-mono truncate max-w-[280px]" title={wf.workflow_file}>
                              {wf.workflow_file.replace(/\\/g, '/').split('/').slice(-2).join('/')}
                            </p>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* Version */}
                    <td className="table-cell hidden sm:table-cell font-mono text-xs text-slate-500">
                      v{wf.version || '1.0.0'}
                    </td>

                    {/* Nodes */}
                    <td className="table-cell hidden lg:table-cell">
                      {isDraft ? (
                        <span className="text-xs text-slate-600 italic">Empty draft</span>
                      ) : (
                        <div className="flex items-center gap-1.5">
                          <Layers className="w-3 h-3 text-slate-600 shrink-0" />
                          <span className="text-xs text-slate-400">{nodeCount} node{nodeCount !== 1 ? 's' : ''}</span>
                        </div>
                      )}
                    </td>

                    {/* Status */}
                    <td className="table-cell">
                      <StatusBadge
                        status={isDraft ? 'draft' : isRegistered ? 'registered' : 'disconnected'}
                      />
                    </td>

                    {/* Actions */}
                    <td className="table-cell text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        {isRegistered && nodeCount > 0 && (
                          <button
                            onClick={() => setSelectedWorkflowForRun(wf)}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-semibold bg-emerald-600/15 hover:bg-emerald-600/25 text-emerald-400 rounded-lg border border-emerald-500/20 transition-all"
                          >
                            <Play className="w-3 h-3" />
                            Run
                          </button>
                        )}

                        {!isRegistered && nodeCount > 0 && (
                          <button
                            onClick={() => registerMutation.mutate(wf)}
                            disabled={registerMutation.isPending}
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-semibold bg-blue-600/15 hover:bg-blue-600/25 text-blue-400 rounded-lg border border-blue-500/20 transition-all disabled:opacity-50"
                          >
                            <CheckCircle2 className="w-3 h-3" />
                            Register
                          </button>
                        )}

                        <Link
                          to={`/workflows/${wf.id}`}
                          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-[11px] font-medium bg-slate-800/60 hover:bg-slate-700/60 text-slate-300 rounded-lg border border-slate-700/40 transition-all"
                        >
                          Details
                          <ChevronRight className="w-3 h-3" />
                        </Link>

                        {isRegistered && (
                          <button
                            onClick={() => setWorkflowToDisconnect(wf)}
                            className="p-1.5 rounded-lg text-slate-600 hover:text-amber-400 hover:bg-amber-500/10 border border-transparent hover:border-amber-500/15 transition-all"
                            title="Disconnect from registry"
                          >
                            <Unlink className="w-3.5 h-3.5" />
                          </button>
                        )}

                        <button
                          onClick={() => handleInitiateDelete(wf)}
                          className="p-1.5 rounded-lg text-slate-600 hover:text-rose-400 hover:bg-rose-500/10 border border-transparent hover:border-rose-500/15 transition-all"
                          title="Delete workflow"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-4 py-2.5 border-t border-slate-800/60 bg-slate-950/20 text-[11px] text-slate-600">
            {filteredWorkflows.length} workflow{filteredWorkflows.length !== 1 ? 's' : ''}
            {searchTerm ? ` matching "${searchTerm}"` : ' total'}
            {' · '}
            {workflows.filter((w) => w.registered !== false && w.registration_status !== 'disconnected').length} registered
          </div>
        </div>
      )}

      {/* Modals */}
      {selectedWorkflowForRun && (
        <WorkflowRunModal isOpen={true} workflow={selectedWorkflowForRun} onClose={() => setSelectedWorkflowForRun(null)} />
      )}

      {isCreateModalOpen && (
        <CreateWorkflowModal
          isOpen={true}
          availableAgents={agents}
          onClose={() => setIsCreateModalOpen(false)}
          onSuccess={() => queryClient.invalidateQueries({ queryKey: ['workflows'] })}
        />
      )}

      {workflowToDisconnect && (
        <ConfirmModal
          isOpen={true}
          title={`Disconnect: ${workflowToDisconnect.id}`}
          message="Disconnects the workflow from the active execution registry. The local YAML file and execution history are preserved."
          confirmText="Disconnect"
          cancelText="Cancel"
          isDanger={false}
          isLoading={disconnectMutation.isPending}
          previewItems={[
            { label: 'Workflow ID', value: workflowToDisconnect.id },
            { label: 'Local Definition', value: 'Preserved on disk', isDestructive: false },
            { label: 'Execution History', value: 'Preserved in database', isDestructive: false },
          ]}
          onConfirm={() => disconnectMutation.mutate(workflowToDisconnect.id)}
          onCancel={() => setWorkflowToDisconnect(null)}
        />
      )}

      {workflowToDelete && (
        <ConfirmModal
          isOpen={true}
          title={`Delete Workflow: ${workflowToDelete.id}`}
          message="This permanently removes the workflow, all its versions, runs, events, checkpoints, and the local YAML definition file."
          confirmText="Permanently Delete"
          cancelText="Cancel"
          isDanger={true}
          isLoading={deleteMutation.isPending || isFetchingPreview}
          previewItems={[
            { label: 'Workflow ID', value: workflowToDelete.id },
            { label: 'Runs', value: `${deletePreview?.run_count ?? 0} run(s)`, isDestructive: true },
            { label: 'Events', value: `${deletePreview?.event_count ?? 0} event(s)`, isDestructive: true },
            { label: 'Checkpoints', value: `${deletePreview?.checkpoint_count ?? 0} record(s)`, isDestructive: true },
            { label: 'Local Definition', value: deletePreview?.has_local_file ? 'Deleted from disk' : 'Not present', isDestructive: deletePreview?.has_local_file },
            { label: 'Referenced Agents', value: 'Untouched', isDestructive: false },
          ]}
          onConfirm={() => deleteMutation.mutate(workflowToDelete.id)}
          onCancel={() => { setWorkflowToDelete(null); setDeletePreview(null); }}
        />
      )}
    </div>
  );
};
