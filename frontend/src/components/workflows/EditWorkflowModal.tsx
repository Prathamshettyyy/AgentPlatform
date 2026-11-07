import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { WorkflowDefinition } from '../../api/types';
import { Code2, Save, AlertCircle } from 'lucide-react';

interface EditWorkflowModalProps {
  isOpen: boolean;
  workflow: WorkflowDefinition;
  onClose: () => void;
  onSuccess: () => void;
}

export const EditWorkflowModal: React.FC<EditWorkflowModalProps> = ({
  isOpen,
  workflow,
  onClose,
  onSuccess,
}) => {
  const queryClient = useQueryClient();

  // Strip transient metadata fields for clean editing
  const cleanDefinition = {
    id: workflow.id,
    version: workflow.version || '1.0.0',
    nodes: (workflow.nodes || []).map((n) => ({
      id: n.id,
      type: n.type,
      agent_id: n.agent_id,
      input_mappings: n.input_mappings || {},
      ...(n.approval_payload_path ? { approval_payload_path: n.approval_payload_path } : {}),
      ...(n.approval_options ? { approval_options: n.approval_options } : {}),
    })),
    edges: (workflow.edges || []).map((e) => ({
      from: e.from,
      to: e.to,
      ...(e.condition ? { condition: e.condition } : {}),
    })),
    ...(workflow.max_steps ? { max_steps: workflow.max_steps } : {}),
  };

  const [rawJson, setRawJson] = useState<string>(
    JSON.stringify(cleanDefinition, null, 2)
  );
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const updateMutation = useMutation({
    mutationFn: (updatedWf: WorkflowDefinition) =>
      api.updateWorkflow(workflow.id, updatedWf),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] });
      queryClient.invalidateQueries({ queryKey: ['workflow', workflow.id] });
      queryClient.invalidateQueries({ queryKey: ['overview-stats'] });
      onSuccess();
      onClose();
    },
    onError: (err: any) => {
      setErrorMsg(err.message || 'Failed to save workflow definition');
    },
  });

  if (!isOpen) return null;

  const handleSave = () => {
    setErrorMsg(null);
    try {
      const parsed = JSON.parse(rawJson);
      if (!parsed || typeof parsed !== 'object') {
        throw new Error('Definition must be a JSON object');
      }
      if (!Array.isArray(parsed.nodes)) {
        throw new Error("'nodes' must be an array");
      }
      if (!Array.isArray(parsed.edges)) {
        throw new Error("'edges' must be an array");
      }
      updateMutation.mutate(parsed);
    } catch (err: any) {
      setErrorMsg(`JSON Validation Error: ${err.message}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-xl p-6 text-slate-100 shadow-xl space-y-4">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Code2 className="w-5 h-5 text-purple-400" />
            <h3 className="text-base font-semibold">Edit Workflow Definition: {workflow.id}</h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200 text-sm">
            ✕
          </button>
        </div>

        {errorMsg && (
          <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMsg}</span>
          </div>
        )}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-slate-300">
              Workflow Nodes & Edges (JSON)
            </label>
            <span className="text-xs text-slate-500">
              Changes are immediately written to disk upon saving
            </span>
          </div>
          <textarea
            value={rawJson}
            onChange={(e) => setRawJson(e.target.value)}
            rows={16}
            className="w-full p-4 bg-slate-950 border border-slate-800 rounded-xl font-mono text-xs text-slate-200 leading-relaxed focus:outline-none focus:border-purple-500"
            spellCheck={false}
          />
        </div>

        <div className="flex items-center justify-between pt-4 border-t border-slate-800">
          <div className="text-xs text-slate-500">
            {workflow.workflow_file ? `File: ${workflow.workflow_file}` : 'Draft definition'}
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium text-slate-300 hover:bg-slate-800 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={updateMutation.isPending}
              className="flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-purple-600 hover:bg-purple-500 disabled:opacity-50 rounded-lg transition-colors shadow-sm"
            >
              <Save className="w-4 h-4" />
              {updateMutation.isPending ? 'Saving...' : 'Save Definition'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

