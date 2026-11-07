import React, { useState } from 'react';
import {
  X,
  Bot,
  UserCheck,
  CornerDownRight,
  Clock,
  Cpu,
  AlertCircle,
  Copy,
  Check,
  ArrowRight,
  ArrowLeft,
  Terminal,
  Plus,
  GitBranch,
  Link2,
  Trash2,
  Edit2,
  Save,
  Radio,
  Zap,
} from 'lucide-react';
import { WorkflowNode, WorkflowEdge, RunRecord } from '../../api/types';
import { StatusBadge } from '../common/StatusBadge';

interface WorkflowGraphInspectorProps {
  node: WorkflowNode | null;
  edges: WorkflowEdge[];
  runRecord?: RunRecord | null;
  workflowId?: string;
  onClose: () => void;
  onSelectNode: (nodeId: string) => void;
  onAddSequentialNode?: (nodeId: string) => void;
  onAddSequentialNodeBefore?: (nodeId: string) => void;
  onAddParallelBranch?: (nodeId: string) => void;
  onConnectNode?: (nodeId: string) => void;
  onDuplicateNode?: (nodeId: string) => void;
  onDeleteNode?: (nodeId: string) => void;
  onUpdateNode?: (nodeId: string, updatedNode: WorkflowNode) => void;
}

export const WorkflowGraphInspector: React.FC<WorkflowGraphInspectorProps> = ({
  node,
  edges,
  runRecord,
  workflowId,
  onClose,
  onSelectNode,
  onAddSequentialNode,
  onAddSequentialNodeBefore,
  onAddParallelBranch,
  onConnectNode,
  onDuplicateNode,
  onDeleteNode,
  onUpdateNode,
}) => {
  const [copied, setCopied] = useState(false);
  const [copiedWebhook, setCopiedWebhook] = useState(false);
  const [isEditingMappings, setIsEditingMappings] = useState(false);
  const [editMappingsText, setEditMappingsText] = useState('');
  const [mappingError, setMappingError] = useState<string | null>(null);

  React.useEffect(() => {
    if (node) {
      setEditMappingsText(JSON.stringify(node.input_mappings || {}, null, 2));
      setIsEditingMappings(false);
      setMappingError(null);
    }
  }, [node]);

  if (!node) return null;

  const isAgent = node.type === 'agent';
  const incoming = edges.filter((e) => e.to === node.id).map((e) => e.from);
  const outgoing = edges.filter((e) => e.from === node.id).map((e) => e.to);

  // Runtime info
  const runtimeOutput = runRecord?.payload?.node_outputs?.[node.id];
  const runtimeError = runRecord?.payload?.error;

  const handleCopy = (data: any) => {
    navigator.clipboard.writeText(typeof data === 'string' ? data : JSON.stringify(data, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSaveMappings = () => {
    try {
      const parsed = JSON.parse(editMappingsText);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setMappingError('Mappings must be a JSON object of { fieldName: { path: "..." } }');
        return;
      }
      onUpdateNode?.(node.id, {
        ...node,
        input_mappings: parsed,
      });
      setIsEditingMappings(false);
      setMappingError(null);
    } catch (err: any) {
      setMappingError(`Invalid JSON: ${err.message}`);
    }
  };

  return (
    <div className="absolute right-0 top-0 bottom-0 w-80 sm:w-96 bg-slate-950/95 border-l border-slate-800 shadow-2xl z-30 flex flex-col backdrop-blur-md animate-in slide-in-from-right duration-200">
      {/* Header */}
      <div className="p-4 border-b border-slate-800 flex items-start justify-between gap-3 bg-slate-900/60">
        <div className="flex items-center gap-2.5 min-w-0">
          <div
            className={`p-2 rounded-lg shrink-0 ${
              node.type === 'trigger'
                ? 'bg-purple-500/10 text-purple-400'
                : isAgent
                ? 'bg-blue-500/10 text-blue-400'
                : 'bg-amber-500/10 text-amber-400'
            }`}
          >
            {node.type === 'trigger' ? (
              node.trigger_type === 'schedule' ? (
                <Clock className="w-5 h-5" />
              ) : (
                <Radio className="w-5 h-5" />
              )
            ) : isAgent ? (
              <Bot className="w-5 h-5" />
            ) : (
              <UserCheck className="w-5 h-5" />
            )}
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-sm text-slate-100 truncate" title={node.id}>
              {node.id}
            </h3>
            <span className="text-xs text-slate-400 font-mono capitalize block mt-0.5">
              {node.type === 'trigger' ? `Trigger (${node.trigger_type || 'webhook'})` : `${node.type} node`}
            </span>
          </div>
        </div>

        <button
          onClick={onClose}
          className="p-1.5 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded-lg transition-colors"
          title="Close Inspector (Esc)"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Quick Action Buttons */}
      <div className="p-2 border-b border-slate-800/80 bg-slate-950 flex items-center justify-between gap-1 overflow-x-auto">
        {onAddSequentialNode && (
          <button
            onClick={() => onAddSequentialNode(node.id)}
            className="p-1.5 text-slate-300 hover:text-emerald-400 hover:bg-slate-800/80 rounded transition-colors"
            title="Add Sequential Node after this node"
          >
            <Plus className="w-4 h-4" />
          </button>
        )}
        {onAddParallelBranch && (
          <button
            onClick={() => onAddParallelBranch(node.id)}
            className="p-1.5 text-slate-300 hover:text-blue-400 hover:bg-slate-800/80 rounded transition-colors"
            title="Add Parallel Branch alongside this node"
          >
            <GitBranch className="w-4 h-4" />
          </button>
        )}
        {onConnectNode && (
          <button
            onClick={() => onConnectNode(node.id)}
            className="p-1.5 text-slate-300 hover:text-cyan-400 hover:bg-slate-800/80 rounded transition-colors"
            title="Connect this node to another"
          >
            <Link2 className="w-4 h-4" />
          </button>
        )}
        {onDuplicateNode && (
          <button
            onClick={() => onDuplicateNode(node.id)}
            className="p-1.5 text-slate-300 hover:text-indigo-400 hover:bg-slate-800/80 rounded transition-colors"
            title="Duplicate node (runs in parallel)"
          >
            <Copy className="w-4 h-4" />
          </button>
        )}
        {onDeleteNode && (
          <button
            onClick={() => {
              onDeleteNode(node.id);
              onClose();
            }}
            className="p-1.5 text-slate-400 hover:text-rose-400 hover:bg-rose-500/20 rounded transition-colors ml-auto"
            title="Delete this node"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Body content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-5 text-xs text-slate-300">
        {/* Basic Configuration */}
        <div className="space-y-2">
          <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
            Node Details
          </span>
          <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Node ID:</span>
              <span className="font-mono text-slate-200 font-medium">{node.id}</span>
            </div>
            {isAgent && node.agent_id && (
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Target Agent:</span>
                <span className="font-mono text-blue-400">{node.agent_id}</span>
              </div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-slate-400">Type:</span>
              <span className="font-mono capitalize text-slate-300">{node.type}</span>
            </div>
            {node.type === 'trigger' && (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">Trigger Type:</span>
                  <span className="font-mono text-purple-300 font-medium capitalize">
                    {node.trigger_type || 'webhook'}
                  </span>
                </div>
                {node.trigger_type === 'schedule' ? (
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Cron Schedule:</span>
                    <span className="font-mono text-emerald-400 font-medium">
                      {node.trigger_config?.cron || '0 * * * *'}
                    </span>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center justify-between">
                      <span className="text-slate-400">HTTP Method:</span>
                      <span className="font-mono text-emerald-400 font-semibold text-[10px] px-1.5 py-0.5 bg-emerald-500/10 rounded border border-emerald-500/20">
                        POST
                      </span>
                    </div>
                    {node.trigger_config?.secret_token && (
                      <div className="flex items-center justify-between">
                        <span className="text-slate-400">Secret Token:</span>
                        <span className="font-mono text-slate-300">
                          {node.trigger_config.secret_token}
                        </span>
                      </div>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        </div>

        {/* Webhook Endpoint & cURL Snippet */}
        {node.type === 'trigger' && (!node.trigger_type || node.trigger_type === 'webhook') && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
                Incoming Webhook Endpoint
              </span>
              <button
                type="button"
                onClick={() => {
                  const url = `http://127.0.0.1:8000/v1/webhooks/${workflowId || 'WORKFLOW_ID'}`;
                  navigator.clipboard.writeText(url);
                  setCopiedWebhook(true);
                  setTimeout(() => setCopiedWebhook(false), 2000);
                }}
                className="inline-flex items-center gap-1 text-[11px] text-purple-400 hover:text-purple-300"
              >
                {copiedWebhook ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                <span>{copiedWebhook ? 'Copied' : 'Copy URL'}</span>
              </button>
            </div>
            <div className="p-2.5 rounded-lg bg-slate-900 border border-purple-500/30 text-purple-200 font-mono text-[11px] break-all select-all">
              POST http://127.0.0.1:8000/v1/webhooks/{workflowId || 'WORKFLOW_ID'}
            </div>
            <div className="space-y-1">
              <span className="text-[10px] text-slate-400 font-medium">Quick Test with cURL:</span>
              <pre className="p-2.5 rounded-lg bg-[#080c14] border border-slate-800 text-[10px] font-mono text-slate-300 overflow-x-auto leading-relaxed whitespace-pre-wrap">
{`curl -X POST http://127.0.0.1:8000/v1/webhooks/${workflowId || 'WORKFLOW_ID'} \\
  -H "Content-Type: application/json"${node.trigger_config?.secret_token ? ` \\\n  -H "X-Webhook-Token: ${node.trigger_config.secret_token}"` : ''} \\
  -d '{"subject": "Incoming Email", "body": "Need analysis", "from": "sender@domain.com"}'`}
              </pre>
            </div>
          </div>
        )}

        {/* Runtime Execution Details if available */}
        {runRecord && (
          <div className="space-y-2">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
              Runtime Execution State
            </span>
            <div className="p-3 rounded-lg bg-slate-900/60 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Status:</span>
                <StatusBadge status={runtimeOutput !== undefined ? 'succeeded' : runRecord.status} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-400">Run ID:</span>
                <span className="font-mono text-slate-300 truncate max-w-[170px]" title={runRecord.run_id}>
                  {runRecord.run_id}
                </span>
              </div>
            </div>

            {/* Runtime Output */}
            {runtimeOutput !== undefined && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400 font-medium">Node Output Payload:</span>
                  <button
                    onClick={() => handleCopy(runtimeOutput)}
                    className="inline-flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300"
                  >
                    {copied ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    <span>{copied ? 'Copied' : 'Copy JSON'}</span>
                  </button>
                </div>
                <pre className="p-3 rounded-lg bg-[#080c14] border border-slate-800 font-mono text-[11px] text-slate-200 overflow-x-auto max-h-48 leading-relaxed">
                  {JSON.stringify(runtimeOutput, null, 2)}
                </pre>
              </div>
            )}

            {/* Runtime Error */}
            {runtimeError && (
              <div className="p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-rose-300 space-y-1">
                <div className="flex items-center gap-1.5 font-semibold">
                  <AlertCircle className="w-3.5 h-3.5 text-rose-400" />
                  <span>Execution Error</span>
                </div>
                <p className="font-mono text-[11px] leading-relaxed break-words">
                  {typeof runtimeError === 'string' ? runtimeError : runtimeError.message || JSON.stringify(runtimeError)}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Input Mappings (with inline edit) */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Input Mappings ({Object.keys(node.input_mappings || {}).length})
            </span>
            {onUpdateNode && !isEditingMappings && (
              <button
                onClick={() => setIsEditingMappings(true)}
                className="inline-flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300"
              >
                <Edit2 className="w-3 h-3" />
                <span>Edit JSON</span>
              </button>
            )}
          </div>

          {isEditingMappings ? (
            <div className="space-y-2">
              <textarea
                value={editMappingsText}
                onChange={(e) => setEditMappingsText(e.target.value)}
                rows={6}
                className="w-full bg-[#080c14] border border-slate-700 rounded-lg p-2 font-mono text-[11px] text-slate-200 focus:outline-none focus:border-blue-500"
              />
              {mappingError && (
                <div className="text-[11px] text-rose-400">{mappingError}</div>
              )}
              <div className="flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setIsEditingMappings(false);
                    setEditMappingsText(JSON.stringify(node.input_mappings || {}, null, 2));
                  }}
                  className="btn-secondary py-1 text-xs"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveMappings}
                  className="btn-primary py-1 text-xs"
                >
                  <Save className="w-3 h-3 mr-1" />
                  Save Mappings
                </button>
              </div>
            </div>
          ) : (
            node.input_mappings && Object.keys(node.input_mappings).length > 0 ? (
              <div className="space-y-1.5 p-3 rounded-lg bg-slate-900/60 border border-slate-800">
                {Object.entries(node.input_mappings).map(([field, mapping]) => (
                  <div key={field} className="flex items-center gap-1.5 font-mono text-slate-300">
                    <CornerDownRight className="w-3 h-3 text-slate-500 shrink-0" />
                    <span className="text-blue-400 font-medium shrink-0">{field}</span>
                    <span className="text-slate-600">←</span>
                    <span
                      className="text-slate-400 truncate flex-1"
                      title={mapping.path || JSON.stringify(mapping.literal)}
                    >
                      {mapping.path || JSON.stringify(mapping.literal)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-2.5 rounded-lg bg-slate-900/40 border border-slate-800/80 text-[11px] text-slate-500 italic">
                No custom input mappings defined.
              </div>
            )
          )}
        </div>

        {/* Human Approval decisions */}
        {node.type === 'human_approval' && node.approval_options && (
          <div className="space-y-2">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
              Approval Decisions
            </span>
            <div className="flex gap-1.5 flex-wrap">
              {node.approval_options.map((opt) => (
                <span
                  key={opt}
                  className="px-2.5 py-1 rounded text-xs font-mono bg-slate-900 border border-slate-800 text-slate-300"
                >
                  {opt}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Graph Dependencies (Upstream & Downstream) */}
        <div className="space-y-3 pt-2 border-t border-slate-800">
          <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block">
            Graph Dependencies
          </span>

          {/* Incoming */}
          <div>
            <span className="text-slate-400 text-[11px] block mb-1">
              Incoming Predecessors ({incoming.length}):
            </span>
            {incoming.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {incoming.map((pred) => (
                  <button
                    key={pred}
                    onClick={() => onSelectNode(pred)}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-blue-400 hover:text-blue-300 font-mono text-[11px] transition-colors"
                    title={`Focus node '${pred}'`}
                  >
                    <ArrowLeft className="w-3 h-3" />
                    <span>{pred}</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="flex items-center justify-between gap-2 p-1.5 rounded bg-slate-900/60 border border-slate-800">
                <span className="text-slate-400 text-[11px] italic">Root node (Receives workflow input)</span>
                {onAddSequentialNodeBefore && (
                  <button
                    type="button"
                    onClick={() => onAddSequentialNodeBefore(node.id)}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/20 transition-colors"
                    title={`Insert a new node before ${node.id}`}
                  >
                    <Plus className="w-3 h-3" />
                    Insert Before
                  </button>
                )}
              </div>
            )}
          </div>

          {/* Outgoing */}
          <div>
            <span className="text-slate-400 text-[11px] block mb-1">
              Outgoing Successors ({outgoing.length}):
            </span>
            {outgoing.length > 0 ? (
              <div className="flex flex-wrap gap-1.5">
                {outgoing.map((succ) => (
                  <button
                    key={succ}
                    onClick={() => onSelectNode(succ)}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded bg-slate-900 hover:bg-slate-800 border border-slate-800 text-emerald-400 hover:text-emerald-300 font-mono text-[11px] transition-colors"
                    title={`Focus node '${succ}'`}
                  >
                    <span>{succ}</span>
                    <ArrowRight className="w-3 h-3" />
                  </button>
                ))}
              </div>
            ) : (
              <span className="text-slate-500 text-[11px] italic">Terminal node (Yields final workflow output)</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
