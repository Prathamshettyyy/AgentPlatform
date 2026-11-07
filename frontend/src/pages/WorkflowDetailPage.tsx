import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { WorkflowDefinition } from '../api/types';
import { GitBranch, ArrowLeft, Play, CheckCircle2, Unlink, Code2, AlertCircle, Plus, Edit3, Layers, FileText, ChevronRight } from 'lucide-react';
import { StatusBadge } from '../components/common/StatusBadge';
import { Skeleton } from '../components/common/Skeleton';
import { WorkflowGraph } from '../components/workflows/WorkflowGraph';
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal';
import { AddAgentNodeModal } from '../components/workflows/AddAgentNodeModal';
import { EditWorkflowModal } from '../components/workflows/EditWorkflowModal';

export const WorkflowDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [isRunModalOpen, setIsRunModalOpen] = useState(false);
  const [isAddAgentModalOpen, setIsAddAgentModalOpen] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'graph' | 'yaml' | 'runs'>('graph');
  const [statusMsg, setStatusMsg] = useState<{ type: 'error' | 'success'; text: string } | null>(null);

  const { data: workflows = [], isLoading } = useQuery({
    queryKey: ['workflows'],
    queryFn: () => api.listWorkflows(true),
  });

  const workflow = workflows.find((w) => w.id === id);

  const { data: allRuns = [] } = useQuery({
    queryKey: ['runs'],
    queryFn: () => api.listRuns(),
  });

  const workflowRuns = allRuns.filter((r) => r.workflow_id === id);

  const registerMutation = useMutation({
    mutationFn: () => api.registerWorkflow(id!, workflow!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] });
      queryClient.invalidateQueries({ queryKey: ['workflow', id] });
      setStatusMsg({ type: 'success', text: 'Workflow successfully validated and registered!' });
    },
    onError: (err: any) => {
      setStatusMsg({ type: 'error', text: `Registration failed: ${err.message}` });
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: () => api.disconnectWorkflow(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] });
      setStatusMsg({ type: 'success', text: 'Workflow disconnected from active API registry.' });
    },
    onError: (err: any) => {
      setStatusMsg({ type: 'error', text: `Disconnect failed: ${err.message}` });
    },
  });

  const deleteNodeMutation = useMutation({
    mutationFn: (nodeId: string) => api.removeNodeFromWorkflow(id!, nodeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] });
      setStatusMsg({ type: 'success', text: 'Node removed from workflow.' });
    },
    onError: (err: any) => {
      setStatusMsg({ type: 'error', text: `Failed to remove node: ${err.message}` });
    },
  });

  const updateWorkflowMutation = useMutation({
    mutationFn: (updated: WorkflowDefinition) => api.updateWorkflow(id!, updated),
    onSuccess: (data) => {
      queryClient.setQueryData(['workflows'], (prev: WorkflowDefinition[] | undefined) =>
        prev ? prev.map((w) => (w.id === id ? { ...w, ...data } : w)) : [data]
      );
      queryClient.invalidateQueries({ queryKey: ['workflows'] });
      queryClient.invalidateQueries({ queryKey: ['workflow', id] });
    },
    onError: (err: any) => {
      setStatusMsg({ type: 'error', text: `Failed to save workflow changes: ${err.message}` });
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-6 w-full">
        <Skeleton className="h-6 w-36" />
        <Skeleton className="h-32 w-full rounded-xl" />
        <Skeleton className="h-96 w-full rounded-xl" />
      </div>
    );
  }

  if (!workflow) {
    return (
      <div className="p-6 bg-rose-500/10 border border-rose-500/20 rounded-xl text-rose-400 text-sm">
        Workflow '{id}' not found.
      </div>
    );
  }

  const isRegistered = workflow.registered !== false && workflow.registration_status !== 'disconnected';
  const nodeCount = workflow.nodes?.length || 0;

  return (
    <div className="space-y-6 w-full">
      {/* Back button */}
      <Link
        to="/workflows"
        className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-200 font-medium transition-colors"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to Workflows
      </Link>

      {/* Status Alert Banner */}
      {statusMsg && (
        <div
          className={`p-3.5 rounded-xl text-xs flex items-center justify-between ${
            statusMsg.type === 'success'
              ? 'bg-emerald-500/10 border border-emerald-500/25 text-emerald-400'
              : 'bg-rose-500/10 border border-rose-500/25 text-rose-400'
          }`}
        >
          <span>{statusMsg.text}</span>
          <button onClick={() => setStatusMsg(null)} className="text-xs hover:underline">
            Dismiss
          </button>
        </div>
      )}

      {/* Header Profile */}
      <div className="card p-6 flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-purple-500/10 border border-purple-500/20 text-purple-400 rounded-xl shrink-0">
            <GitBranch className="w-7 h-7" />
          </div>
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <h2 className="text-xl font-bold text-slate-100 font-mono">{workflow.id}</h2>
              <span className="font-mono text-xs text-slate-400 bg-slate-800/80 px-2 py-0.5 rounded border border-slate-700/50">
                v{workflow.version || '1.0.0'}
              </span>
              <StatusBadge status={nodeCount === 0 ? 'draft' : isRegistered ? 'registered' : 'disconnected'} />
            </div>
            {workflow.workflow_file && (
              <p className="text-[11px] text-slate-500 font-mono mt-1">File: {workflow.workflow_file}</p>
            )}
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <button
            onClick={() => setIsAddAgentModalOpen(true)}
            className="btn-primary"
          >
            <Plus className="w-3.5 h-3.5" />
            Add Agent Node
          </button>

          <button
            onClick={() => setIsEditModalOpen(true)}
            className="btn-secondary"
          >
            <Edit3 className="w-3.5 h-3.5 text-purple-400" />
            Edit Definition
          </button>

          {isRegistered && nodeCount > 0 && (
            <button
              onClick={() => setIsRunModalOpen(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg transition-all shadow-sm"
            >
              <Play className="w-3.5 h-3.5" />
              Execute Workflow
            </button>
          )}

          {!isRegistered && nodeCount > 0 && (
            <button
              onClick={() => registerMutation.mutate()}
              disabled={registerMutation.isPending}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-all shadow-sm disabled:opacity-50"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              {registerMutation.isPending ? 'Registering...' : 'Validate & Register'}
            </button>
          )}

          {!isRegistered && nodeCount === 0 && (
            <button
              disabled={true}
              title="Add at least 1 agent node before registering this workflow"
              className="btn-secondary opacity-50 cursor-not-allowed"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              Register (Needs Nodes)
            </button>
          )}

          {isRegistered && (
            <button
              onClick={() => disconnectMutation.mutate()}
              disabled={disconnectMutation.isPending}
              className="btn-secondary text-amber-400"
            >
              <Unlink className="w-3.5 h-3.5 text-amber-400" />
              Disconnect
            </button>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800/60 gap-0">
        <button
          onClick={() => setActiveTab('graph')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-all ${
            activeTab === 'graph'
              ? 'border-blue-500 text-blue-400'
              : 'border-transparent text-slate-500 hover:text-slate-300 hover:border-slate-700'
          }`}
        >
          <Layers className="w-3.5 h-3.5" />
          Visual Graph
        </button>
        <button
          onClick={() => setActiveTab('yaml')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-all ${
            activeTab === 'yaml'
              ? 'border-blue-500 text-blue-400'
              : 'border-transparent text-slate-500 hover:text-slate-300 hover:border-slate-700'
          }`}
        >
          <Code2 className="w-3.5 h-3.5" />
          Raw Definition (JSON)
        </button>
        <button
          onClick={() => setActiveTab('runs')}
          className={`flex items-center gap-2 px-4 py-2.5 text-xs font-medium border-b-2 transition-all ${
            activeTab === 'runs'
              ? 'border-blue-500 text-blue-400'
              : 'border-transparent text-slate-500 hover:text-slate-300 hover:border-slate-700'
          }`}
        >
          <FileText className="w-3.5 h-3.5" />
          Execution History ({workflowRuns.length})
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === 'graph' && (
        <WorkflowGraph
          workflow={workflow}
          onUpdateWorkflow={(updated) => updateWorkflowMutation.mutate(updated)}
          onAddNode={() => setIsAddAgentModalOpen(true)}
          onDeleteNode={(nodeId) => deleteNodeMutation.mutate(nodeId)}
        />
      )}

      {activeTab === 'yaml' && (
        <div className="card p-6 space-y-2">
          <div className="flex items-center gap-2 text-slate-200 text-sm font-semibold mb-2">
            <Code2 className="w-4 h-4 text-purple-400" />
            Serialized Workflow Definition
          </div>
          <pre className="p-4 bg-[#080c14] rounded-xl border border-slate-800/80 text-xs font-mono text-slate-300 overflow-x-auto max-h-96 leading-relaxed">
            {JSON.stringify(workflow, null, 2)}
          </pre>
        </div>
      )}

      {activeTab === 'runs' && (
        <div className="card p-6 space-y-4">
          <h3 className="text-sm font-semibold text-slate-200">Workflow Execution History</h3>
          {workflowRuns.length === 0 ? (
            <p className="text-xs text-slate-500 italic">No execution runs recorded for this workflow yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-slate-800/60 text-slate-500 uppercase tracking-wider">
                    <th className="py-2.5 font-semibold">Run ID</th>
                    <th className="py-2.5 font-semibold">Status</th>
                    <th className="py-2.5 font-semibold">Started At</th>
                    <th className="py-2.5 font-semibold text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/40">
                  {workflowRuns.map((r) => (
                    <tr key={r.run_id} className="hover:bg-slate-800/20 transition-colors">
                      <td className="py-3 font-mono font-medium text-slate-300">
                        {r.run_id.slice(0, 12)}…
                      </td>
                      <td className="py-3">
                        <StatusBadge status={r.status} />
                      </td>
                      <td className="py-3 text-slate-500 font-mono">
                        {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
                      </td>
                      <td className="py-3 text-right">
                        <Link
                          to={`/runs/${r.run_id}`}
                          className="text-blue-400 hover:text-blue-300 font-medium inline-flex items-center gap-1 transition-colors"
                        >
                          Inspect
                          <ChevronRight className="w-3 h-3" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Modals */}
      {isRunModalOpen && (
        <WorkflowRunModal
          isOpen={true}
          workflow={workflow}
          onClose={() => setIsRunModalOpen(false)}
        />
      )}

      {isAddAgentModalOpen && (
        <AddAgentNodeModal
          isOpen={true}
          workflow={workflow}
          onClose={() => setIsAddAgentModalOpen(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ['workflows'] });
            queryClient.invalidateQueries({ queryKey: ['workflow', id] });
            setStatusMsg({ type: 'success', text: 'Agent node added successfully!' });
          }}
        />
      )}

      {isEditModalOpen && (
        <EditWorkflowModal
          isOpen={true}
          workflow={workflow}
          onClose={() => setIsEditModalOpen(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ['workflows'] });
            queryClient.invalidateQueries({ queryKey: ['workflow', id] });
            setStatusMsg({ type: 'success', text: 'Workflow definition updated.' });
          }}
        />
      )}
    </div>
  );
};
