import React, { useState } from 'react';
import { X, Play, AlertCircle } from 'lucide-react';
import { WorkflowDefinition, RunRecord } from '../../api/types';
import { api } from '../../api/client';
import { useNavigate } from 'react-router-dom';

interface WorkflowRunModalProps {
  isOpen: boolean;
  workflow: WorkflowDefinition;
  onClose: () => void;
  onSuccess?: (run: RunRecord) => void;
}

export const WorkflowRunModal: React.FC<WorkflowRunModalProps> = ({
  isOpen,
  workflow,
  onClose,
  onSuccess,
}) => {
  const navigate = useNavigate();

  const getInitialInputJson = () => {
    const fields: Record<string, string> = {};
    for (const node of workflow?.nodes || []) {
      for (const [_, mapping] of Object.entries(node.input_mappings || {})) {
        const path = (mapping as any)?.path;
        if (typeof path === 'string' && path.startsWith('workflow_input.')) {
          const field = path.replace('workflow_input.', '').split('.')[0];
          if (field && !(field in fields)) {
            fields[field] = `Sample ${field}`;
          }
        }
      }
    }
    if (Object.keys(fields).length > 0) {
      return JSON.stringify(fields, null, 2);
    }
    return '{\n  "text": "Analyze this sample input text."\n}';
  };

  const [inputJson, setInputJson] = useState(getInitialInputJson);
  const [allowPartial, setAllowPartial] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  React.useEffect(() => {
    if (isOpen) {
      setInputJson(getInitialInputJson());
      setError(null);
    }
  }, [isOpen, workflow?.id]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    let parsedInputs: Record<string, any> = {};
    try {
      parsedInputs = JSON.parse(inputJson);
    } catch {
      setError('Input must be a valid JSON object.');
      return;
    }

    setIsLoading(true);
    try {
      const result = await api.startRun(workflow.id, parsedInputs, allowPartial);
      setIsLoading(false);
      onClose();
      if (onSuccess) onSuccess(result);
      navigate(`/runs/${result.run_id}`);
    } catch (err: any) {
      setIsLoading(false);
      setError(err.message || 'Failed to start workflow execution');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="relative w-full max-w-lg bg-slate-900 border border-slate-800 rounded-xl shadow-2xl p-6 text-slate-100">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-200"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-blue-500/10 text-blue-400 rounded-lg">
            <Play className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-slate-100">Run Workflow</h3>
            <p className="text-xs text-slate-400 font-mono">{workflow.id} (v{workflow.version})</p>
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
              Workflow Input (JSON object)
            </label>
            <textarea
              rows={6}
              value={inputJson}
              onChange={(e) => setInputJson(e.target.value)}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono text-slate-200 focus:outline-none focus:border-blue-500"
              placeholder='{ "text": "value" }'
            />
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="allowPartial"
              checked={allowPartial}
              onChange={(e) => setAllowPartial(e.target.checked)}
              className="rounded bg-slate-950 border-slate-800 text-blue-600 focus:ring-0"
            />
            <label htmlFor="allowPartial" className="text-xs text-slate-300">
              Allow partial execution (continue if optional nodes skip)
            </label>
          </div>

          <div className="flex justify-end gap-3 pt-2">
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
              {isLoading ? (
                <>
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Executing...
                </>
              ) : (
                'Start Execution'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

