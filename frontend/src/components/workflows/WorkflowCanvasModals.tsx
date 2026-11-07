import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { WorkflowDefinition, WorkflowNode } from '../../api/types';
import {
  X,
  Plus,
  GitBranch,
  Split,
  Settings,
  Layers,
  Check,
  AlertCircle,
  CornerDownRight,
  Trash2,
  Copy,
  Radio,
  Zap,
  Clock,
} from 'lucide-react';

/* =========================================================================
   1. Insert Sequential Node Modal
========================================================================= */

interface InsertSequentialModalProps {
  isOpen: boolean;
  edge: { from: string; to: string } | null;
  workflow: WorkflowDefinition;
  onClose: () => void;
  onSubmit: (newNode: WorkflowNode) => void;
}

export const InsertSequentialModal: React.FC<InsertSequentialModalProps> = ({
  isOpen,
  edge,
  workflow,
  onClose,
  onSubmit,
}) => {
  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => api.listAgents(),
  });

  const [nodeType, setNodeType] = useState<'agent' | 'human_approval' | 'trigger'>('agent');
  const [agentId, setAgentId] = useState<string>('');
  const [nodeId, setNodeId] = useState<string>('');
  const [triggerType, setTriggerType] = useState<'webhook' | 'schedule'>('webhook');
  const [secretToken, setSecretToken] = useState<string>('');
  const [cronExpression, setCronExpression] = useState<string>('0 * * * *');
  const defaultPayload = edge?.from && edge.from !== '__start__' ? `node_outputs.${edge.from}` : 'workflow_input';
  const [approvalPayloadPath, setApprovalPayloadPath] = useState<string>(defaultPayload);
  const [approvalOptionsStr, setApprovalOptionsStr] = useState<string>('approve, reject');
  const [error, setError] = useState<string | null>(null);

  // Sync payload default when edge changes
  React.useEffect(() => {
    if (edge?.from) {
      setApprovalPayloadPath(edge.from !== '__start__' ? `node_outputs.${edge.from}` : 'workflow_input');
    }
  }, [edge]);

  // Set initial agent
  React.useEffect(() => {
    if (agents.length > 0 && !agentId) {
      setAgentId(agents[0].id);
      if (nodeType === 'agent') {
        setNodeId(`${agents[0].id}_step`);
      }
    }
  }, [agents, agentId, nodeType]);

  if (!isOpen || !edge) return null;

  const handleAgentChange = (newAgentId: string) => {
    setAgentId(newAgentId);
    if (!nodeId || nodeId.endsWith('_step') || nodeId.endsWith('_approval')) {
      setNodeId(`${newAgentId}_step`);
    }
  };

  const handleNodeTypeChange = (type: 'agent' | 'human_approval' | 'trigger') => {
    setNodeType(type);
    if (type === 'human_approval' && (!nodeId || nodeId.endsWith('_step') || nodeId.endsWith('_trigger'))) {
      setNodeId('approval_gate');
    } else if (type === 'trigger' && (!nodeId || nodeId.endsWith('_step') || nodeId === 'approval_gate')) {
      setNodeId('email_webhook_trigger');
    } else if (type === 'agent' && (nodeId === 'approval_gate' || nodeId.endsWith('_trigger') || !nodeId)) {
      setNodeId(`${agentId || 'agent'}_step`);
    }
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    const finalId = nodeId.trim();
    if (!finalId) {
      setError('Node ID is required.');
      return;
    }

    if (workflow.nodes?.some((n) => n.id === finalId)) {
      setError(`A node with ID '${finalId}' already exists.`);
      return;
    }

    const payloadPath = (approvalPayloadPath || defaultPayload).trim();
    const parsedOptions = approvalOptionsStr
      .split(',')
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean);
    const finalOptions = parsedOptions.length > 0 ? Array.from(new Set(parsedOptions)) : ['approve', 'reject'];

    const newNode: WorkflowNode = {
      id: finalId,
      type: nodeType,
      ...(nodeType === 'agent' ? { agent_id: agentId } : {}),
      status: 'available',
      input_mappings:
        nodeType === 'agent'
          ? edge.from !== '__start__'
            ? { text: { path: `node_outputs.${edge.from}.text` } }
            : { text: { path: 'workflow_input.text' } }
          : {},
      ...(nodeType === 'human_approval'
        ? {
            approval_payload_path: payloadPath,
            approval_options: finalOptions,
            execute_in: 'workflow',
          }
        : {}),
      ...(nodeType === 'trigger'
        ? {
            trigger_type: triggerType,
            trigger_config:
              triggerType === 'webhook'
                ? { secret_token: secretToken.trim() || undefined }
                : { cron: cronExpression.trim() || '0 * * * *' },
          }
        : {}),
    };

    onSubmit(newNode);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="card w-full max-w-md p-6 space-y-4 border-slate-700 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2 text-slate-100 font-semibold text-sm">
            <Plus className="w-4 h-4 text-emerald-400" />
            Insert Sequential Node
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-xs font-mono flex items-center justify-between">
          <span className="text-slate-400 font-semibold">{edge.from === '__start__' ? 'START' : edge.from}</span>
          <span className="text-emerald-400 font-bold">→ [New Node] →</span>
          <span className="text-slate-400 font-semibold">{edge.to === '__end__' ? 'END' : edge.to}</span>
        </div>

        {error && (
          <div className="p-2.5 rounded bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center gap-1.5">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Node Type</label>
            <div className="grid grid-cols-3 gap-2">
              <button
                type="button"
                onClick={() => handleNodeTypeChange('agent')}
                className={`py-2 px-2 text-xs rounded-lg border font-medium transition-colors text-center ${
                  nodeType === 'agent'
                    ? 'border-blue-500 bg-blue-500/10 text-blue-400'
                    : 'border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-700'
                }`}
              >
                Agent Execution
              </button>
              <button
                type="button"
                onClick={() => handleNodeTypeChange('human_approval')}
                className={`py-2 px-2 text-xs rounded-lg border font-medium transition-colors text-center ${
                  nodeType === 'human_approval'
                    ? 'border-amber-500 bg-amber-500/10 text-amber-400'
                    : 'border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-700'
                }`}
              >
                Human Approval
              </button>
              <button
                type="button"
                onClick={() => handleNodeTypeChange('trigger')}
                className={`py-2 px-2 text-xs rounded-lg border font-medium transition-colors text-center ${
                  nodeType === 'trigger'
                    ? 'border-purple-500 bg-purple-500/10 text-purple-400'
                    : 'border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-700'
                }`}
              >
                Trigger / Webhook
              </button>
            </div>
          </div>

          {nodeType === 'agent' && (
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Agent Service</label>
              <select
                value={agentId}
                onChange={(e) => handleAgentChange(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
              >
                {agents.map((ag) => (
                  <option key={ag.id} value={ag.id}>
                    {ag.name} ({ag.id})
                  </option>
                ))}
              </select>
            </div>
          )}

          {nodeType === 'human_approval' && (
            <div className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Approval Payload Path</label>
                <input
                  type="text"
                  value={approvalPayloadPath}
                  onChange={(e) => setApprovalPayloadPath(e.target.value)}
                  placeholder="e.g. node_outputs.analyze_title or workflow_input"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-amber-500 font-mono"
                />
                <span className="text-[10px] text-slate-500 mt-1 block">
                  Path to the data presented for review (e.g. <code>node_outputs.previous_node</code> or <code>workflow_input</code>).
                </span>
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Approval Options</label>
                <input
                  type="text"
                  value={approvalOptionsStr}
                  onChange={(e) => setApprovalOptionsStr(e.target.value)}
                  placeholder="approve, reject"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-amber-500 font-mono"
                />
                <span className="text-[10px] text-slate-500 mt-1 block">
                  Comma-separated list of decision choices available to the human reviewer.
                </span>
              </div>
            </div>
          )}

          {nodeType === 'trigger' && (
            <div className="space-y-3 p-3 rounded-lg bg-slate-900/60 border border-purple-500/30">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Trigger Mechanism</label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setTriggerType('webhook');
                      if (nodeId.endsWith('_schedule') || nodeId === 'schedule_trigger') {
                        setNodeId('email_webhook_trigger');
                      }
                    }}
                    className={`py-1.5 px-2 text-xs rounded border flex items-center justify-center gap-1.5 transition-colors ${
                      triggerType === 'webhook'
                        ? 'border-purple-400 bg-purple-500/20 text-purple-300 font-semibold'
                        : 'border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Radio className="w-3.5 h-3.5 text-purple-400" />
                    <span>Incoming Webhook</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setTriggerType('schedule');
                      if (nodeId.endsWith('_webhook') || nodeId === 'email_webhook_trigger') {
                        setNodeId('schedule_trigger');
                      }
                    }}
                    className={`py-1.5 px-2 text-xs rounded border flex items-center justify-center gap-1.5 transition-colors ${
                      triggerType === 'schedule'
                        ? 'border-purple-400 bg-purple-500/20 text-purple-300 font-semibold'
                        : 'border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Clock className="w-3.5 h-3.5 text-purple-400" />
                    <span>Schedule (Cron)</span>
                  </button>
                </div>
              </div>

              {triggerType === 'webhook' ? (
                <div className="space-y-2">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300 mb-1">
                      Optional Secret Token (Authorization)
                    </label>
                    <input
                      type="text"
                      value={secretToken}
                      onChange={(e) => setSecretToken(e.target.value)}
                      placeholder="e.g. secret_token_xyz (or leave empty for public)"
                      className="w-full bg-slate-950 border border-slate-700 rounded p-1.5 text-xs text-slate-200 font-mono focus:outline-none focus:border-purple-500"
                    />
                    <span className="text-[10px] text-slate-500 mt-1 block">
                      Validates <code>X-Webhook-Token</code> header or <code>?token=</code> query parameter.
                    </span>
                  </div>
                  <div className="p-2 rounded bg-purple-500/10 border border-purple-500/20 text-[10px] text-purple-300">
                    💡 Payload fields (e.g. email body, subject, sender) will flow into downstream agents via <code>workflow_input</code> or <code>node_outputs.{nodeId || 'trigger'}.*</code>.
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-300 mb-1">
                      Cron Expression
                    </label>
                    <input
                      type="text"
                      value={cronExpression}
                      onChange={(e) => setCronExpression(e.target.value)}
                      placeholder="0 * * * *"
                      className="w-full bg-slate-950 border border-slate-700 rounded p-1.5 text-xs text-slate-200 font-mono focus:outline-none focus:border-purple-500"
                    />
                    <div className="flex gap-1 mt-1.5">
                      {[
                        { label: 'Hourly', val: '0 * * * *' },
                        { label: 'Daily 9am', val: '0 9 * * *' },
                        { label: 'Every 15m', val: '*/15 * * * *' },
                      ].map((preset) => (
                        <button
                          key={preset.label}
                          type="button"
                          onClick={() => setCronExpression(preset.val)}
                          className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-700"
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Node ID</label>
            <input
              type="text"
              value={nodeId}
              onChange={(e) => setNodeId(e.target.value)}
              placeholder="e.g. text_analyzer_v2"
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              data-testid="confirm-insert-sequential"
            >
              Insert Node
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

/* =========================================================================
   2. Add Parallel Branch Modal
========================================================================= */

interface AddParallelBranchModalProps {
  isOpen: boolean;
  referenceNodeId: string | null;
  workflow: WorkflowDefinition;
  onClose: () => void;
  onSubmit: (newNode: WorkflowNode, downstreamJoinId?: string) => void;
}

export const AddParallelBranchModal: React.FC<AddParallelBranchModalProps> = ({
  isOpen,
  referenceNodeId,
  workflow,
  onClose,
  onSubmit,
}) => {
  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => api.listAgents(),
  });

  const [agentId, setAgentId] = useState<string>('');
  const [nodeId, setNodeId] = useState<string>('');
  const [downstreamJoinId, setDownstreamJoinId] = useState<string>('none');
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    if (agents.length > 0 && !agentId) {
      setAgentId(agents[0].id);
      setNodeId(`${agents[0].id}_branch`);
    }
  }, [agents, agentId]);

  if (!isOpen || !referenceNodeId) return null;

  // Potential downstream join nodes (nodes that come after referenceNodeId or existing join nodes)
  const candidateJoinNodes = (workflow.nodes || []).filter((n) => n.id !== referenceNodeId);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    const finalId = nodeId.trim();
    if (!finalId) {
      setError('Branch Node ID is required.');
      return;
    }

    if (workflow.nodes?.some((n) => n.id === finalId)) {
      setError(`A node with ID '${finalId}' already exists.`);
      return;
    }

    const newNode: WorkflowNode = {
      id: finalId,
      type: 'agent',
      agent_id: agentId,
      status: 'available',
      input_mappings: { text: { path: 'workflow_input.text' } },
    };

    onSubmit(newNode, downstreamJoinId === 'none' ? undefined : downstreamJoinId);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="card w-full max-w-md p-6 space-y-4 border-slate-700 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2 text-slate-100 font-semibold text-sm">
            <GitBranch className="w-4 h-4 text-blue-400" />
            Add Parallel Branch
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs text-slate-400">
          Spawns an independent parallel execution branch running alongside{' '}
          <span className="font-mono text-blue-400 font-semibold">{referenceNodeId}</span>.
        </p>

        {error && (
          <div className="p-2.5 rounded bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center gap-1.5">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Agent Service</label>
            <select
              value={agentId}
              onChange={(e) => {
                setAgentId(e.target.value);
                setNodeId(`${e.target.value}_branch`);
              }}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
            >
              {agents.map((ag) => (
                <option key={ag.id} value={ag.id}>
                  {ag.name} ({ag.id})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Branch Node ID</label>
            <input
              type="text"
              value={nodeId}
              onChange={(e) => setNodeId(e.target.value)}
              placeholder="e.g. analyze_sentiment"
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Downstream Join Node (Barrier)
            </label>
            <select
              value={downstreamJoinId}
              onChange={(e) => setDownstreamJoinId(e.target.value)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-blue-500 font-mono"
            >
              <option value="none">Leave Open (Connect to END or join later)</option>
              {candidateJoinNodes.map((cn) => (
                <option key={cn.id} value={cn.id}>
                  {cn.id} ({cn.agent_id || cn.type})
                </option>
              ))}
            </select>
            <span className="text-[10px] text-slate-500 mt-1 block">
              Selecting a join node forces the pipeline to wait until both branches finish before proceeding.
            </span>
          </div>

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              data-testid="confirm-add-parallel-branch"
            >
              Create Branch
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

/* =========================================================================
   3. Add Join Node Modal
========================================================================= */

interface AddJoinNodeModalProps {
  isOpen: boolean;
  initialBranches?: string[];
  workflow: WorkflowDefinition;
  onClose: () => void;
  onSubmit: (branchIds: string[], joinNode: WorkflowNode, isExisting: boolean) => void;
}

export const AddJoinNodeModal: React.FC<AddJoinNodeModalProps> = ({
  isOpen,
  initialBranches = [],
  workflow,
  onClose,
  onSubmit,
}) => {
  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => api.listAgents(),
  });

  const [selectedBranches, setSelectedBranches] = useState<string[]>(initialBranches);
  const [mode, setMode] = useState<'create_new' | 'use_existing'>('create_new');
  const [existingNodeId, setExistingNodeId] = useState<string>('');
  const [agentId, setAgentId] = useState<string>('');
  const [newNodeId, setNewNodeId] = useState<string>('barrier_join_node');
  const [error, setError] = useState<string | null>(null);

  React.useEffect(() => {
    if (initialBranches.length > 0) {
      setSelectedBranches(initialBranches);
    } else {
      setSelectedBranches((workflow.nodes || []).slice(0, 2).map((n) => n.id));
    }
  }, [initialBranches, workflow.nodes]);

  React.useEffect(() => {
    if (agents.length > 0 && !agentId) {
      setAgentId(agents[0].id);
    }
  }, [agents, agentId]);

  if (!isOpen) return null;

  const allNodes = workflow.nodes || [];

  const handleToggleBranch = (id: string) => {
    setSelectedBranches((prev) =>
      prev.includes(id) ? prev.filter((b) => b !== id) : [...prev, id]
    );
  };

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedBranches.length === 0) {
      setError('Please select at least 1 incoming branch to join.');
      return;
    }

    if (mode === 'use_existing') {
      if (!existingNodeId) {
        setError('Please select an existing node as the join target.');
        return;
      }
      const existingNode = allNodes.find((n) => n.id === existingNodeId);
      if (!existingNode) {
        setError('Selected node does not exist.');
        return;
      }
      onSubmit(selectedBranches, existingNode, true);
    } else {
      const finalId = newNodeId.trim();
      if (!finalId) {
        setError('Join Node ID is required.');
        return;
      }
      if (allNodes.some((n) => n.id === finalId)) {
        setError(`A node with ID '${finalId}' already exists.`);
        return;
      }

      const joinNode: WorkflowNode = {
        id: finalId,
        type: 'agent',
        agent_id: agentId,
        status: 'available',
        input_mappings: {},
      };
      onSubmit(selectedBranches, joinNode, false);
    }

    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="card w-full max-w-md p-6 space-y-4 border-slate-700 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2 text-slate-100 font-semibold text-sm">
            <Split className="w-4 h-4 text-purple-400 rotate-180" />
            Add Fan-In Join Node (Barrier)
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs text-slate-400">
          Converge multiple parallel branches into a single barrier node. The join node will only execute once all branches have succeeded.
        </p>

        {error && (
          <div className="p-2.5 rounded bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center gap-1.5">
            <AlertCircle className="w-4 h-4 shrink-0" />
            {error}
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Select Incoming Parallel Branches ({selectedBranches.length})
            </label>
            <div className="max-h-36 overflow-y-auto space-y-1 bg-slate-900/60 p-2 rounded-lg border border-slate-800">
              {allNodes.map((n) => {
                const isSelected = selectedBranches.includes(n.id);
                return (
                  <div
                    key={n.id}
                    onClick={() => handleToggleBranch(n.id)}
                    className={`flex items-center justify-between p-1.5 rounded cursor-pointer text-xs font-mono transition-colors ${
                      isSelected
                        ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                        : 'hover:bg-slate-800 text-slate-400'
                    }`}
                  >
                    <span>{n.id}</span>
                    {isSelected && <Check className="w-3.5 h-3.5 text-blue-400" />}
                  </div>
                );
              })}
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Target Mode</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setMode('create_new')}
                className={`py-2 px-3 text-xs rounded-lg border font-medium transition-colors ${
                  mode === 'create_new'
                    ? 'border-purple-500 bg-purple-500/10 text-purple-400'
                    : 'border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-700'
                }`}
              >
                Create New Join Node
              </button>
              <button
                type="button"
                onClick={() => setMode('use_existing')}
                className={`py-2 px-3 text-xs rounded-lg border font-medium transition-colors ${
                  mode === 'use_existing'
                    ? 'border-purple-500 bg-purple-500/10 text-purple-400'
                    : 'border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-700'
                }`}
              >
                Use Existing Node
              </button>
            </div>
          </div>

          {mode === 'create_new' ? (
            <>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Agent Service</label>
                <select
                  value={agentId}
                  onChange={(e) => setAgentId(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-purple-500 font-mono"
                >
                  {agents.map((ag) => (
                    <option key={ag.id} value={ag.id}>
                      {ag.name} ({ag.id})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Join Node ID</label>
                <input
                  type="text"
                  value={newNodeId}
                  onChange={(e) => setNewNodeId(e.target.value)}
                  placeholder="e.g. aggregate_findings"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-purple-500 font-mono"
                />
              </div>
            </>
          ) : (
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Select Existing Join Destination
              </label>
              <select
                value={existingNodeId}
                onChange={(e) => setExistingNodeId(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-purple-500 font-mono"
              >
                <option value="">-- Choose node --</option>
                {allNodes
                  .filter((n) => !selectedBranches.includes(n.id))
                  .map((n) => (
                    <option key={n.id} value={n.id}>
                      {n.id} ({n.agent_id || n.type})
                    </option>
                  ))}
              </select>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              data-testid="confirm-add-join-node"
            >
              Establish Join Barrier
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

/* =========================================================================
   4. Configure Condition Modal
========================================================================= */

interface ConfigureConditionModalProps {
  isOpen: boolean;
  edge: { from: string; to: string; condition?: any } | null;
  onClose: () => void;
  onSubmit: (from: string, to: string, condition: any) => void;
}

export const ConfigureConditionModal: React.FC<ConfigureConditionModalProps> = ({
  isOpen,
  edge,
  onClose,
  onSubmit,
}) => {
  const [operator, setOperator] = useState<'none' | 'equals' | 'truthy' | 'exists'>('none');
  const [fieldPath, setFieldPath] = useState<string>('');
  const [targetValue, setTargetValue] = useState<string>('');

  React.useEffect(() => {
    if (edge?.condition) {
      const keys = Object.keys(edge.condition);
      if (keys.length > 0) {
        const op = keys[0];
        setOperator(op as any);
        const condObj = edge.condition[op];
        if (condObj && typeof condObj === 'object') {
          setFieldPath(condObj.path || '');
          setTargetValue(condObj.value !== undefined ? String(condObj.value) : '');
        }
      }
    } else if (edge) {
      setOperator('none');
      setFieldPath(`node_outputs.${edge.from}.status`);
      setTargetValue('passed');
    }
  }, [edge]);

  if (!isOpen || !edge) return null;

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (operator === 'none') {
      onSubmit(edge.from, edge.to, null);
    } else {
      let val: any = targetValue;
      if (targetValue === 'true') val = true;
      else if (targetValue === 'false') val = false;
      else if (!isNaN(Number(targetValue)) && targetValue.trim() !== '') val = Number(targetValue);

      const conditionPayload = {
        [operator]: {
          path: fieldPath.trim(),
          ...(operator === 'equals' ? { value: val } : {}),
        },
      };
      onSubmit(edge.from, edge.to, conditionPayload);
    }
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="card w-full max-w-md p-6 space-y-4 border-slate-700 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2 text-slate-100 font-semibold text-sm">
            <Settings className="w-4 h-4 text-amber-400" />
            Configure Edge Condition
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-xs font-mono flex items-center justify-between">
          <span className="text-slate-400">{edge.from}</span>
          <span className="text-amber-400 font-bold">──[ condition ]──&gt;</span>
          <span className="text-slate-400">{edge.to}</span>
        </div>

        <form onSubmit={handleSave} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">Execution Rule</label>
            <select
              value={operator}
              onChange={(e) => setOperator(e.target.value as any)}
              className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-amber-500 font-mono"
            >
              <option value="none">Unconditional (Always run downstream node)</option>
              <option value="equals">Equals (Path value equals target)</option>
              <option value="truthy">Truthy (Path value is not false, null, or empty)</option>
              <option value="exists">Exists (Path key is present in output)</option>
            </select>
          </div>

          {operator !== 'none' && (
            <>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">State Path</label>
                <input
                  type="text"
                  value={fieldPath}
                  onChange={(e) => setFieldPath(e.target.value)}
                  placeholder={`e.g. node_outputs.${edge.from}.passed`}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-amber-500 font-mono"
                />
              </div>

              {operator === 'equals' && (
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1">Target Value</label>
                  <input
                    type="text"
                    value={targetValue}
                    onChange={(e) => setTargetValue(e.target.value)}
                    placeholder="e.g. true, passed, or 100"
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-amber-500 font-mono"
                  />
                </div>
              )}
            </>
          )}

          <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-800">
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              data-testid="confirm-configure-condition"
            >
              Save Condition
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

/* =========================================================================
   5. Canvas Context Menu (for Right-Click on Edge or Node)
========================================================================= */

export interface ContextMenuState {
  type: 'edge' | 'node';
  x: number;
  y: number;
  edge?: { from: string; to: string; condition?: any };
  nodeId?: string;
}

interface CanvasContextMenuProps {
  menu: ContextMenuState | null;
  onClose: () => void;
  onDeleteEdge?: (from: string, to: string) => void;
  onInsertSequentialOnEdge?: (from: string, to: string) => void;
  onAddParallelBranchOnEdge?: (from: string, to: string) => void;
  onConfigureCondition?: (from: string, to: string, condition?: any) => void;
  onReconnectEdge?: (from: string, to: string, mode: 'source' | 'target') => void;
  onAddSequentialNode?: (nodeId: string) => void;
  onAddParallelBranchOnNode?: (nodeId: string) => void;
  onAddConnectionFromNode?: (nodeId: string) => void;
  onDuplicateNode?: (nodeId: string) => void;
  onDeleteNode?: (nodeId: string) => void;
  onConfigureNode?: (nodeId: string) => void;
}

export const CanvasContextMenu: React.FC<CanvasContextMenuProps> = ({
  menu,
  onClose,
  onDeleteEdge,
  onInsertSequentialOnEdge,
  onAddParallelBranchOnEdge,
  onConfigureCondition,
  onReconnectEdge,
  onAddSequentialNode,
  onAddParallelBranchOnNode,
  onAddConnectionFromNode,
  onDuplicateNode,
  onDeleteNode,
  onConfigureNode,
}) => {
  if (!menu) return null;

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} onContextMenu={(e) => { e.preventDefault(); onClose(); }} />
      <div
        style={{ left: menu.x, top: menu.y }}
        className="fixed z-50 min-w-[210px] bg-slate-900 border border-slate-700/80 rounded-xl shadow-2xl py-1.5 text-xs text-slate-200 backdrop-blur-md animate-in fade-in duration-100"
      >
        {menu.type === 'edge' && menu.edge && (
          <>
            <div className="px-3 py-1 text-[10px] font-mono text-slate-500 uppercase tracking-wider border-b border-slate-800 mb-1">
              Connection: {menu.edge.from} → {menu.edge.to}
            </div>

            <button
              onClick={() => {
                onClose();
                onInsertSequentialOnEdge?.(menu.edge!.from, menu.edge!.to);
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-800 text-left transition-colors"
            >
              <Plus className="w-3.5 h-3.5 text-emerald-400" />
              Insert Sequential Node
            </button>

            <button
              onClick={() => {
                onClose();
                onAddParallelBranchOnEdge?.(menu.edge!.from, menu.edge!.to);
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-800 text-left transition-colors"
            >
              <GitBranch className="w-3.5 h-3.5 text-blue-400" />
              Add Parallel Branch
            </button>

            <button
              onClick={() => {
                onClose();
                onReconnectEdge?.(menu.edge!.from, menu.edge!.to, 'target');
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-800 text-left transition-colors"
            >
              <CornerDownRight className="w-3.5 h-3.5 text-purple-400" />
              Reconnect Destination
            </button>

            <button
              onClick={() => {
                onClose();
                onConfigureCondition?.(menu.edge!.from, menu.edge!.to, menu.edge!.condition);
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-800 text-left transition-colors"
            >
              <Settings className="w-3.5 h-3.5 text-amber-400" />
              Configure Condition
            </button>

            <div className="my-1 border-t border-slate-800" />

            <button
              onClick={() => {
                onClose();
                onDeleteEdge?.(menu.edge!.from, menu.edge!.to);
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-rose-500/10 text-rose-400 text-left transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5 text-rose-400" />
              Delete Connection
            </button>
          </>
        )}

        {menu.type === 'node' && menu.nodeId && (
          <>
            <div className="px-3 py-1 text-[10px] font-mono text-slate-500 uppercase tracking-wider border-b border-slate-800 mb-1">
              Node: {menu.nodeId}
            </div>

            <button
              onClick={() => {
                onClose();
                onAddSequentialNode?.(menu.nodeId!);
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-800 text-left transition-colors"
            >
              <Plus className="w-3.5 h-3.5 text-emerald-400" />
              Add Sequential Node
            </button>

            <button
              onClick={() => {
                onClose();
                onAddParallelBranchOnNode?.(menu.nodeId!);
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-800 text-left transition-colors"
            >
              <GitBranch className="w-3.5 h-3.5 text-blue-400" />
              Add Parallel Branch
            </button>

            <button
              onClick={() => {
                onClose();
                onAddConnectionFromNode?.(menu.nodeId!);
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-800 text-left transition-colors"
            >
              <CornerDownRight className="w-3.5 h-3.5 text-cyan-400" />
              Connect to Node...
            </button>

            <button
              onClick={() => {
                onClose();
                onDuplicateNode?.(menu.nodeId!);
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-800 text-left transition-colors"
            >
              <Copy className="w-3.5 h-3.5 text-indigo-400" />
              Duplicate Node (Parallel)
            </button>

            <button
              onClick={() => {
                onClose();
                onConfigureNode?.(menu.nodeId!);
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-slate-800 text-left transition-colors"
            >
              <Settings className="w-3.5 h-3.5 text-amber-400" />
              Configure Node
            </button>

            <div className="my-1 border-t border-slate-800" />

            <button
              onClick={() => {
                onClose();
                onDeleteNode?.(menu.nodeId!);
              }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-rose-500/10 text-rose-400 text-left transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5 text-rose-400" />
              Delete Node
            </button>
          </>
        )}
      </div>
    </>
  );
};

