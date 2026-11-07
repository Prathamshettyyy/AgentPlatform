import React, { memo } from 'react';
import { Handle, Position, NodeProps, NodeToolbar } from '@xyflow/react';
import {
  Bot,
  UserCheck,
  Trash2,
  CornerDownRight,
  Clock,
  Plus,
  GitBranch,
  Link2,
  Copy,
  Radio,
  Zap,
} from 'lucide-react';
import { StatusBadge } from '../common/StatusBadge';
import { WorkflowNodeData } from './workflowLayout';

export const WorkflowGraphNode: React.FC<NodeProps> = memo(({ data, selected }) => {
  const nodeData = data as unknown as WorkflowNodeData;
  if (!nodeData || !nodeData.workflowNode) {
    return null;
  }
  const {
    workflowNode,
    direction = 'LR',
    isCompact,
    runtimeStatus,
    runtimeInfo,
    isHighlighted,
    onDelete,
    onAddSequentialNode,
    onAddParallelBranch,
    onConnectNode,
    onDuplicateNode,
    onContextMenu,
    isConnectMode,
    isConnectSource,
    isRoot,
    isLeaf,
  } = nodeData;

  const isHorizontal = direction !== 'TB';
  const isAgent = workflowNode.type === 'agent';
  const isTrigger = workflowNode.type === 'trigger';
  const mappingEntries = Object.entries(workflowNode.input_mappings || {});

  // Runtime status styling
  let statusBorder = 'border-slate-800 hover:border-slate-700';
  let statusGlow = '';

  if (runtimeStatus === 'running') {
    statusBorder = 'border-blue-500 ring-2 ring-blue-500/30';
    statusGlow = 'animate-pulse';
  } else if (runtimeStatus === 'succeeded') {
    statusBorder = 'border-emerald-500/80 hover:border-emerald-400';
  } else if (runtimeStatus === 'failed') {
    statusBorder = 'border-rose-500 ring-2 ring-rose-500/30';
  } else if (runtimeStatus === 'waiting_for_approval') {
    statusBorder = 'border-amber-500 ring-2 ring-amber-500/30';
  }

  const selectionClass = isConnectSource
    ? 'ring-2 ring-cyan-400 border-cyan-400 shadow-lg shadow-cyan-500/20 animate-pulse'
    : selected
    ? 'ring-2 ring-blue-400 border-blue-400 shadow-lg shadow-blue-500/10'
    : isHighlighted
    ? 'ring-2 ring-amber-400/80 border-amber-400'
    : '';

  return (
    <div
      data-testid={`flow-node-${workflowNode.id}`}
      style={{
        width: `${nodeData.nodeWidth || (isCompact ? 230 : 290)}px`,
        height: nodeData.nodeHeight ? `${nodeData.nodeHeight}px` : undefined,
      }}
      onContextMenu={(e) => {
        if (onContextMenu) {
          e.preventDefault();
          e.stopPropagation();
          onContextMenu(e, workflowNode.id);
        }
      }}
      className={`relative bg-slate-950 border rounded-xl shadow-md transition-all duration-150 select-none ${
        isCompact ? 'w-[230px] p-2.5' : 'w-[290px] p-3.5'
      } ${statusBorder} ${selectionClass} ${statusGlow}`}
    >
      {/* Node Contextual Toolbar (Shown on Selection) */}
      {selected && (
        <NodeToolbar
          isVisible={selected}
          position={isHorizontal ? Position.Top : Position.Right}
          className="flex items-center gap-0.5 p-1 bg-slate-900/95 border border-slate-700/80 rounded-lg shadow-xl backdrop-blur-md z-40"
        >
          {onAddSequentialNode && (
            <button
              type="button"
              data-testid={`node-toolbar-add-seq-${workflowNode.id}`}
              onClick={(e) => {
                e.stopPropagation();
                onAddSequentialNode(workflowNode.id);
              }}
              className="p-1 text-slate-300 hover:text-emerald-400 hover:bg-slate-800 rounded transition-colors"
              title="Add Sequential Node after this node"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          )}

          {onAddParallelBranch && (
            <button
              type="button"
              data-testid={`node-toolbar-add-parallel-${workflowNode.id}`}
              onClick={(e) => {
                e.stopPropagation();
                onAddParallelBranch(workflowNode.id);
              }}
              className="p-1 text-slate-300 hover:text-blue-400 hover:bg-slate-800 rounded transition-colors"
              title="Add Parallel Branch alongside this node"
            >
              <GitBranch className="w-3.5 h-3.5" />
            </button>
          )}

          {onConnectNode && (
            <button
              type="button"
              data-testid={`node-toolbar-connect-${workflowNode.id}`}
              onClick={(e) => {
                e.stopPropagation();
                onConnectNode(workflowNode.id);
              }}
              className="p-1 text-slate-300 hover:text-cyan-400 hover:bg-slate-800 rounded transition-colors"
              title="Connect to another node"
            >
              <Link2 className="w-3.5 h-3.5" />
            </button>
          )}

          {onDuplicateNode && (
            <button
              type="button"
              data-testid={`node-toolbar-duplicate-${workflowNode.id}`}
              onClick={(e) => {
                e.stopPropagation();
                onDuplicateNode(workflowNode.id);
              }}
              className="p-1 text-slate-300 hover:text-indigo-400 hover:bg-slate-800 rounded transition-colors"
              title="Duplicate node (runs in parallel)"
            >
              <Copy className="w-3.5 h-3.5" />
            </button>
          )}

          {onDelete && (
            <button
              type="button"
              data-testid={`node-toolbar-delete-${workflowNode.id}`}
              onClick={(e) => {
                e.stopPropagation();
                onDelete(workflowNode.id);
              }}
              className="p-1 text-slate-300 hover:text-rose-400 hover:bg-rose-500/20 rounded transition-colors"
              title="Delete node"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </NodeToolbar>
      )}

      {/* Target Connector Handle (Input) */}
      <Handle
        type="target"
        id="target"
        position={isHorizontal ? Position.Left : Position.Top}
        className={`!w-3 !h-3 !border-2 !border-slate-950 transition-colors z-20 ${
          isConnectMode
            ? '!w-4 !h-4 !bg-cyan-400 ring-4 ring-cyan-500/30'
            : isRoot
            ? '!bg-emerald-400'
            : '!bg-blue-500 hover:!bg-blue-300'
        }`}
      />

      {/* Node Header */}
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <div
            className={`p-1.5 rounded-lg shrink-0 ${
              isTrigger
                ? 'bg-purple-500/10 text-purple-400'
                : isAgent
                ? 'bg-blue-500/10 text-blue-400'
                : 'bg-amber-500/10 text-amber-400'
            }`}
          >
            {isTrigger ? (
              workflowNode.trigger_type === 'schedule' ? (
                <Clock className="w-3.5 h-3.5" />
              ) : (
                <Radio className="w-3.5 h-3.5" />
              )
            ) : isAgent ? (
              <Bot className="w-3.5 h-3.5" />
            ) : (
              <UserCheck className="w-3.5 h-3.5" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h4
              className="font-semibold text-xs text-slate-100 truncate leading-snug"
              title={workflowNode.id}
            >
              {workflowNode.id}
            </h4>
            <span className="text-[10px] text-slate-400 font-mono capitalize block">
              {isTrigger ? `Trigger: ${workflowNode.trigger_type || 'webhook'}` : workflowNode.type}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {runtimeStatus ? (
            <StatusBadge status={runtimeStatus} />
          ) : (
            workflowNode.status && <StatusBadge status={workflowNode.status} />
          )}

          {onDelete && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(workflowNode.id);
              }}
              className="p-1 text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 rounded transition-colors"
              title={`Remove node '${workflowNode.id}'`}
            >
              <Trash2 className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      {/* Target Agent / Service */}
      {isAgent && workflowNode.agent_id && (
        <div className="text-[11px] text-slate-400 truncate font-mono mt-1 mb-1">
          <span className="text-slate-500">agent: </span>
          <span className="text-slate-300">{workflowNode.agent_id}</span>
        </div>
      )}

      {/* Trigger Configuration Summary */}
      {isTrigger && (
        <div className="mt-1 mb-1 text-[11px] font-mono text-slate-300">
          {workflowNode.trigger_type === 'schedule' ? (
            <div className="flex items-center gap-1.5 p-1.5 px-2 rounded bg-purple-500/10 border border-purple-500/20 text-purple-300">
              <Clock className="w-3 h-3 text-purple-400 shrink-0" />
              <span className="truncate">{workflowNode.trigger_config?.cron || '0 * * * *'}</span>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-1 p-1.5 px-2 rounded bg-purple-500/10 border border-purple-500/20 text-purple-300">
              <span className="truncate text-[10px]">POST /v1/webhooks/...</span>
              <span className="text-[9px] px-1 bg-purple-500/20 rounded font-semibold text-purple-300">POST</span>
            </div>
          )}
        </div>
      )}

      {/* Runtime details (if active in execution view) */}
      {runtimeInfo && (
        <div className="mt-1.5 pt-1.5 border-t border-slate-800/60 flex items-center justify-between text-[10px] font-mono text-slate-400">
          {runtimeInfo.durationMs !== undefined && (
            <span className="flex items-center gap-1 text-emerald-400">
              <Clock className="w-2.5 h-2.5" />
              {runtimeInfo.durationMs}ms
            </span>
          )}
          {runtimeInfo.worker && (
            <span className="truncate max-w-[120px] text-slate-400" title={runtimeInfo.worker}>
              {runtimeInfo.worker}
            </span>
          )}
        </div>
      )}

      {/* Expanded Mode: Input Mappings and Approvals */}
      {!isCompact && mappingEntries.length > 0 && (
        <div className="mt-2 pt-2 border-t border-slate-800/80 space-y-1">
          <span className="text-[10px] text-slate-400 font-medium block">
            Mappings ({mappingEntries.length}):
          </span>
          <div className="space-y-1 max-h-28 overflow-y-auto pr-1">
            {mappingEntries.slice(0, 4).map(([field, mapping]) => (
              <div
                key={field}
                className="text-[10px] flex items-center gap-1 font-mono text-slate-300 truncate"
              >
                <CornerDownRight className="w-2.5 h-2.5 text-slate-500 shrink-0" />
                <span className="text-blue-400 font-medium shrink-0">{field}</span>
                <span className="text-slate-600">←</span>
                <span
                  className="text-slate-400 truncate"
                  title={mapping.path || JSON.stringify(mapping.literal)}
                >
                  {mapping.path || JSON.stringify(mapping.literal)}
                </span>
              </div>
            ))}
            {mappingEntries.length > 4 && (
              <span className="text-[9px] text-slate-500 block italic">
                +{mappingEntries.length - 4} more mappings...
              </span>
            )}
          </div>
        </div>
      )}

      {!isCompact && workflowNode.type === 'human_approval' && workflowNode.approval_options && (
        <div className="mt-2 pt-1.5 border-t border-slate-800/60 flex gap-1 flex-wrap">
          {workflowNode.approval_options.map((opt) => (
            <span
              key={opt}
              className="px-1.5 py-0.2 rounded text-[10px] font-mono bg-slate-800 text-slate-300"
            >
              {opt}
            </span>
          ))}
        </div>
      )}

      {/* Source Connector Handle (Output) */}
      <Handle
        type="source"
        id="source"
        position={isHorizontal ? Position.Right : Position.Bottom}
        className={`!w-3 !h-3 !border-2 !border-slate-950 transition-colors z-20 ${
          isLeaf ? '!bg-indigo-400' : '!bg-blue-500 hover:!bg-blue-300'
        }`}
      />
    </div>
  );
});
