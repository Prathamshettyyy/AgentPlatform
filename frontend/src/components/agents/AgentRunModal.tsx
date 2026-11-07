import React, { useState } from 'react';
import { X, Play, AlertCircle, CheckCircle2 } from 'lucide-react';
import { AgentMetadata, RunRecord } from '../../api/types';
import { api } from '../../api/client';
import { useNavigate } from 'react-router-dom';

interface AgentRunModalProps {
  isOpen: boolean;
  agent: AgentMetadata;
  onClose: () => void;
}

export const AgentRunModal: React.FC<AgentRunModalProps> = ({ isOpen, agent, onClose }) => {
  const navigate = useNavigate();
  const defaultPayload = agent.id === 'geotechnical_analysis'
    ? JSON.stringify(
        {
          document_id: '7d500784-af45-4a86-a437-e90c3f7b54f2',
          project_id: 'default',
          llm_profile: 'document_analysis',
        },
        null,
        2
      )
    : agent.input_schema
    ? JSON.stringify(
        Object.keys(agent.input_schema.properties || {}).reduce((acc: any, key) => {
          acc[key] = key === 'text' ? 'Sample text for direct agent execution' : 'sample value';
          return acc;
        }, {}),
        null,
        2
      )
    : '{\n  "text": "Analyze this text"\n}';

  const [inputJson, setInputJson] = useState(defaultPayload);
  const [task, setTask] = useState(
    agent.id === 'geotechnical_analysis'
      ? 'Synthesize geotechnical engineering report and analyze foundation recommendations'
      : 'direct agent execution'
  );
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<RunRecord | null>(null);

  if (!isOpen) return null;

  const handleRun = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);

    let parsed = {};
    try {
      parsed = JSON.parse(inputJson);
    } catch {
      setError('Inputs must be valid JSON');
      return;
    }

    setIsLoading(true);
    try {
      const res = await api.runAgent(agent.id, parsed, task);
      setResult(res);
      setIsLoading(false);
    } catch (err: any) {
      setIsLoading(false);
      setError(err.message || 'Execution failed');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
      <div className="relative w-full max-w-xl bg-slate-900 border border-slate-800 rounded-xl shadow-2xl p-6 text-slate-100 max-h-[90vh] flex flex-col">
        <button onClick={onClose} className="absolute top-4 right-4 text-slate-400 hover:text-slate-200">
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-4 shrink-0">
          <div className="p-2 bg-blue-500/10 text-blue-400 rounded-lg">
            <Play className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-slate-100">Execute Agent</h3>
            <p className="text-xs text-slate-400 font-mono">{agent.name} ({agent.id})</p>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg text-rose-400 text-xs flex items-center gap-2 shrink-0">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-4 pr-1">
          <form onSubmit={handleRun} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1">Task Description</label>
              <input
                type="text"
                value={task}
                onChange={(e) => setTask(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-100 focus:outline-none focus:border-blue-500"
              />
            </div>

            <div>
              <div className="flex justify-between items-center mb-1">
                <label className="block text-xs font-medium text-slate-300">Inputs (JSON)</label>
                {agent.input_schema && (
                  <span className="text-xs text-slate-400 font-mono">Declared Schema: {Object.keys(agent.input_schema.properties || {}).join(', ')}</span>
                )}
              </div>
              <textarea
                rows={5}
                value={inputJson}
                onChange={(e) => setInputJson(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono text-slate-200 focus:outline-none focus:border-blue-500"
              />
            </div>

            <div className="flex justify-end gap-2">
              <button
                type="submit"
                disabled={isLoading}
                className="px-4 py-2 text-xs font-semibold bg-blue-600 hover:bg-blue-500 text-white rounded-lg flex items-center gap-2"
              >
                {isLoading ? 'Running...' : 'Run Agent Now'}
              </button>
            </div>
          </form>

          {/* Execution Result view */}
          {result && (
            <div className="mt-4 p-4 rounded-lg bg-slate-950 border border-slate-800 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-emerald-400 text-sm font-semibold">
                  <CheckCircle2 className="w-4 h-4" />
                  Execution {result.status}
                </div>
                <button
                  onClick={() => navigate(`/runs/${result.run_id}`)}
                  className="text-xs text-blue-400 hover:underline font-mono"
                >
                  View Run #{result.run_id.slice(0, 8)} →
                </button>
              </div>

              <div>
                <span className="text-xs text-slate-400 block mb-1 font-medium">Output:</span>
                <pre className="p-3 rounded bg-slate-900 text-xs font-mono text-slate-200 overflow-x-auto max-h-48 border border-slate-800/60">
                  {JSON.stringify(result.payload?.final_output || result.payload, null, 2)}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

