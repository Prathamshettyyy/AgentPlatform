import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { WorkflowDefinition, AgentMetadata } from '../../api/types';
import { Bot, Plus, CornerDownRight, AlertCircle, ArrowRight } from 'lucide-react';

interface AddAgentNodeModalProps {
  isOpen: boolean;
  workflow: WorkflowDefinition;
  onClose: () => void;
  onSuccess: () => void;
}

export const AddAgentNodeModal: React.FC<AddAgentNodeModalProps> = ({
  isOpen,
  workflow,
  onClose,
  onSuccess,
}) => {
  const queryClient = useQueryClient();
  const [selectedAgentId, setSelectedAgentId] = useState<string>('');
  const [nodeId, setNodeId] = useState<string>('');
  const [afterNodeId, setAfterNodeId] = useState<string>('');
  const [customMappings, setCustomMappings] = useState<Record<string, string>>({});
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const { data: agents = [], isLoading: isLoadingAgents } = useQuery({
    queryKey: ['agents'],
    queryFn: api.listAgents,
  });

  const selectedAgent = agents.find((a) => a.id === selectedAgentId);
  const existingNodes = workflow.nodes || [];

  // Default selection when agents load
  useEffect(() => {
    if (agents.length > 0 && !selectedAgentId) {
      setSelectedAgentId(agents[0].id);
      setNodeId(agents[0].id);
    }
  }, [agents, selectedAgentId]);

  // Set default preceding node
  useEffect(() => {
    if (existingNodes.length > 0) {
      setAfterNodeId(existingNodes[existingNodes.length - 1].id);
    } else {
      setAfterNodeId('');
    }
  }, [workflow]);

  // Auto-fill inferred input mappings when agent or afterNodeId changes
  useEffect(() => {
    if (!selectedAgent) return;
    const mappings: Record<string, string> = {};
    const props = selectedAgent.input_schema?.properties || {};

    const afterNode = existingNodes.find((n) => n.id === afterNodeId);
    const afterAgent = afterNode ? agents.find((a) => a.id === afterNode.agent_id) : null;
    const afterOutputProps = afterAgent?.output_schema?.properties || {};

    Object.keys(props).forEach((field) => {
      if (afterNodeId && field in afterOutputProps) {
        mappings[field] = `node_outputs.${afterNodeId}.${field}`;
      } else {
        mappings[field] = `workflow_input.${field}`;
      }
    });

    if (Object.keys(props).length === 0) {
      mappings['text'] = 'workflow_input.text';
    }

    setCustomMappings(mappings);
  }, [selectedAgent, afterNodeId]);

  const handleAgentChange = (aid: string) => {
    setSelectedAgentId(aid);
    // Auto-generate node ID (avoid collisions)
    let candidate = aid;
    if (existingNodes.some((n) => n.id === candidate)) {
      let counter = 2;
      while (existingNodes.some((n) => n.id === `${candidate}_${counter}`)) {
        counter++;
      }
      candidate = `${candidate}_${counter}`;
    }
    setNodeId(candidate);
  };

  const addNodeMutation = useMutation({
    mutationFn: () => {
      const formattedMappings: Record<string, any> = {};
      Object.entries(customMappings).forEach(([field, pathVal]) => {
        if (pathVal.trim()) {
          formattedMappings[field] = { path: pathVal.trim() };
        }
      });

      const rootNode = existingNodes.find((n) => !workflow.edges?.some((e) => e.to === n.id));
      const isStart = afterNodeId === '__start__';

      return api.addAgentToWorkflow(workflow.id, {
        agent_id: selectedAgentId,
        node_id: nodeId.trim() || selectedAgentId,
        after: isStart ? undefined : (afterNodeId || undefined),
        before: isStart && rootNode ? rootNode.id : undefined,
        input_mappings: formattedMappings,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] });
      queryClient.invalidateQueries({ queryKey: ['workflow', workflow.id] });
      queryClient.invalidateQueries({ queryKey: ['overview-stats'] });
      onSuccess();
      onClose();
    },
    onError: (err: any) => {
      setErrorMsg(err.message || 'Failed to add agent node');
    },
  });

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-xl p-6 text-slate-100 shadow-xl space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Bot className="w-5 h-5 text-blue-400" />
            <h3 className="text-base font-semibold">Add Agent to Workflow</h3>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 text-sm"
          >
            ✕
          </button>
        </div>

        {errorMsg && (
          <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        <div className="space-y-4">
          {/* Agent Selection */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Select Agent
            </label>
            {isLoadingAgents ? (
              <div className="text-xs text-slate-400">Loading agents...</div>
            ) : agents.length === 0 ? (
              <div className="text-xs text-rose-400">No registered agents available. Connect one first.</div>
            ) : (
              <select
                value={selectedAgentId}
                onChange={(e) => handleAgentChange(e.target.value)}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs text-slate-100 focus:outline-none focus:border-blue-500"
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} ({a.id})
                  </option>
                ))}
              </select>
            )}
            {selectedAgent?.description && (
              <p className="text-xs text-slate-400 mt-1 italic">{selectedAgent.description}</p>
            )}
          </div>

          {/* Node ID */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1">
              Node Identifier in Pipeline
            </label>
            <input
              type="text"
              value={nodeId}
              onChange={(e) => setNodeId(e.target.value)}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-100 focus:outline-none focus:border-blue-500"
              placeholder="e.g. external_text_analysis"
            />
          </div>

          {/* Position / After */}
          {existingNodes.length > 0 && (
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">
                Link After Preceding Node
              </label>
              <select
                value={afterNodeId}
                onChange={(e) => setAfterNodeId(e.target.value)}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono text-slate-100 focus:outline-none focus:border-blue-500"
              >
                <option value="__start__">-- Run at Start (Before first node) --</option>
                <option value="">None (Independent entry node)</option>
                {existingNodes.map((n) => (
                  <option key={n.id} value={n.id}>
                    After {n.id} ({n.agent_id})
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Input Mappings Preview */}
          <div className="space-y-2 pt-2 border-t border-slate-800">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-300">
                Inferred Input Mappings
              </span>
              <span className="text-xs text-slate-500">Auto-generated from schema</span>
            </div>

            <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 space-y-2 max-h-48 overflow-y-auto">
              {Object.keys(customMappings).length === 0 ? (
                <div className="text-xs text-slate-400 italic">No input fields declared by agent.</div>
              ) : (
                Object.entries(customMappings).map(([field, pathVal]) => (
                  <div key={field} className="flex items-center gap-2 text-xs">
                    <span className="w-28 text-blue-400 font-mono font-medium truncate" title={field}>
                      {field}
                    </span>
                    <span className="text-slate-500">←</span>
                    <input
                      type="text"
                      value={pathVal}
                      onChange={(e) =>
                        setCustomMappings((prev) => ({ ...prev, [field]: e.target.value }))
                      }
                      className="flex-1 px-2 py-1 bg-slate-900 border border-slate-800 rounded font-mono text-xs text-slate-200 focus:outline-none focus:border-blue-500"
                    />
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Modal Actions */}
        <div className="flex items-center justify-end gap-2 pt-4 border-t border-slate-800">
          <button
            onClick={onClose}
            className="px-4 py-2 text-xs font-medium text-slate-300 hover:bg-slate-800 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => addNodeMutation.mutate()}
            disabled={addNodeMutation.isPending || !selectedAgentId || !nodeId.trim()}
            className="flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded-lg transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            {addNodeMutation.isPending ? 'Adding Agent...' : 'Add Agent to Workflow'}
          </button>
        </div>
      </div>
    </div>
  );
};

