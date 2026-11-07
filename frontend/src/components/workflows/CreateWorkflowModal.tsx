import React, { useState } from 'react';
import { X, Plus, AlertCircle, Bot } from 'lucide-react';
import { AgentMetadata, WorkflowNode } from '../../api/types';
import { api } from '../../api/client';

interface CreateWorkflowModalProps {
  isOpen: boolean;
  availableAgents: AgentMetadata[];
  onClose: () => void;
  onSuccess: () => void;
}

export const CreateWorkflowModal: React.FC<CreateWorkflowModalProps> = ({
  isOpen,
  availableAgents,
  onClose,
  onSuccess,
}) => {
  const [workflowId, setWorkflowId] = useState('');
  const [mode, setMode] = useState<'empty' | 'agents'>('agents');
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  if (!isOpen) return null;

  const toggleAgent = (agentId: string) => {
    setSelectedAgents((prev) =>
      prev.includes(agentId) ? prev.filter((id) => id !== agentId) : [...prev, agentId]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const cleanId = workflowId.trim().toLowerCase();
    if (!cleanId) {
      setError('Workflow ID is required.');
      return;
    }
    if (!/^[a-z][a-z0-9_-]{1,63}$/.test(cleanId)) {
      setError('Workflow ID must start with a lowercase letter and contain only lowercase letters, digits, hyphens, or underscores.');
      return;
    }

    setIsLoading(true);
    try {
      if (mode === 'empty') {
        // Save empty draft
        await api.createDraft({ id: cleanId, version: '1.0.0', nodes: [], edges: [] });
      } else {
        if (selectedAgents.length === 0) {
          setError('Please select at least one agent or choose "Create empty draft".');
          setIsLoading(false);
          return;
        }

        // Build nodes & edges
        const nodes: WorkflowNode[] = selectedAgents.map((aid, idx) => {
          const node: WorkflowNode = {
            id: aid,
            type: 'agent',
            agent_id: aid,
          };
          if (idx === 0) {
            node.input_mappings = { text: { path: 'workflow_input.text' } };
          }
          return node;
        });

        const edges = [];
        for (let i = 0; i < selectedAgents.length - 1; i++) {
          edges.push({
            from: selectedAgents[i],
            to: selectedAgents[i + 1],
          });
        }

        await api.createWorkflow({
          id: cleanId,
          version: '1.0.0',
          nodes,
          edges,
        });
      }

      setIsLoading(false);
      onSuccess();
      onClose();
    } catch (err: any) {
      setIsLoading(false);
      setError(err.message || 'Failed to create workflow');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="relative w-full max-w-lg bg-slate-900 border border-slate-800 rounded-xl shadow-2xl p-6 text-slate-100">
        <button onClick={onClose} className="absolute top-4 right-4 text-slate-400 hover:text-slate-200">
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-blue-500/10 text-blue-400 rounded-lg">
            <Plus className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-slate-100">Create Workflow</h3>
            <p className="text-xs text-slate-400">Configure a new multi-agent pipeline</p>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg text-rose-400 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Workflow ID (e.g. text_analysis_flow)
            </label>
            <input
              type="text"
              required
              value={workflowId}
              onChange={(e) => setWorkflowId(e.target.value)}
              placeholder="my_workflow"
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-2">Creation Mode</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setMode('agents')}
                className={`p-3 rounded-lg border text-left transition-all ${
                  mode === 'agents'
                    ? 'bg-blue-600/10 border-blue-500/40 text-blue-300'
                    : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <div className="font-semibold text-xs text-slate-200">1. Create with agents</div>
                <div className="text-xs text-slate-400 mt-1">Select connected agents and register graph</div>
              </button>

              <button
                type="button"
                onClick={() => setMode('empty')}
                className={`p-3 rounded-lg border text-left transition-all ${
                  mode === 'empty'
                    ? 'bg-blue-600/10 border-blue-500/40 text-blue-300'
                    : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                }`}
              >
                <div className="font-semibold text-xs text-slate-200">2. Empty draft</div>
                <div className="text-xs text-slate-400 mt-1">Save local definition and configure nodes later</div>
              </button>
            </div>
          </div>

          {mode === 'agents' && (
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Select Agents in Execution Order
              </label>
              {availableAgents.length === 0 ? (
                <p className="text-xs text-amber-400 p-2 bg-amber-500/10 rounded border border-amber-500/20">
                  No active agents connected. Connect an external agent first or select "Empty draft".
                </p>
              ) : (
                <div className="space-y-1.5 max-h-48 overflow-y-auto p-1 bg-slate-950 border border-slate-800 rounded-lg">
                  {availableAgents.map((agent) => {
                    const isSelected = selectedAgents.includes(agent.id);
                    const selectedIdx = selectedAgents.indexOf(agent.id);
                    return (
                      <div
                        key={agent.id}
                        onClick={() => toggleAgent(agent.id)}
                        className={`flex items-center justify-between p-2 rounded cursor-pointer transition-colors ${
                          isSelected
                            ? 'bg-blue-600/20 border border-blue-500/30 text-slate-100'
                            : 'hover:bg-slate-800/40 text-slate-300'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          <Bot className="w-4 h-4 text-blue-400 shrink-0" />
                          <span className="text-xs font-medium font-mono">{agent.id}</span>
                          <span className="text-xs text-slate-400">({agent.name})</span>
                        </div>
                        {isSelected && (
                          <span className="text-xs bg-blue-500 text-white rounded-full px-2 py-0.5 font-bold">
                            #{selectedIdx + 1}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-3 pt-3 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              disabled={isLoading}
              className="px-4 py-2 text-sm text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-lg"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isLoading}
              className="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white rounded-lg flex items-center gap-2"
            >
              {isLoading ? 'Creating...' : mode === 'empty' ? 'Save Empty Draft' : 'Create & Register'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};
