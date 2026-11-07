import React, { memo } from 'react';
import { Handle, Position, NodeProps } from '@xyflow/react';
import { Folder, FolderOpen, ChevronRight, ChevronDown } from 'lucide-react';
import { WorkflowGroupData } from './workflowLayout';

export const WorkflowGroupNode: React.FC<NodeProps> = memo(({ data }) => {
  const group = data as unknown as WorkflowGroupData;
  if (!group) return null;

  const isHorizontal = group.direction !== 'TB';
  const color = group.color || '#3b82f6';

  if (group.isCollapsed) {
    return (
      <div
        className="relative bg-slate-900/90 border-2 rounded-xl p-3 shadow-lg backdrop-blur-md min-w-[240px] max-w-[280px] select-none cursor-pointer hover:border-blue-400 transition-colors"
        style={{ borderColor: `${color}80` }}
        onClick={() => group.onToggleCollapse(group.groupId)}
      >
        <Handle
          type="target"
          id="target"
          position={isHorizontal ? Position.Left : Position.Top}
          className="!w-3 !h-3 !bg-blue-400 !border-2 !border-slate-950 z-20"
        />

        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div
              className="p-1 rounded-md"
              style={{ backgroundColor: `${color}20`, color }}
            >
              <Folder className="w-4 h-4" />
            </div>
            <div>
              <h4 className="text-xs font-semibold text-slate-100">{group.title}</h4>
              <span className="text-[10px] text-slate-400 font-mono">Collapsed Group</span>
            </div>
          </div>
          <button
            onClick={(e) => {
              e.stopPropagation();
              group.onToggleCollapse(group.groupId);
            }}
            className="p-1 hover:bg-slate-800 rounded text-slate-400 hover:text-slate-200"
            title="Expand Group"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        <div className="mt-2.5 pt-2 border-t border-slate-800/80 flex items-center justify-between text-[11px] font-mono text-slate-400">
          <span className="px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
            {group.nodeCount} Nodes
          </span>
          <span className="text-blue-400 hover:underline">Click to Expand</span>
        </div>

        <Handle
          type="source"
          id="source"
          position={isHorizontal ? Position.Right : Position.Bottom}
          className="!w-3 !h-3 !bg-blue-400 !border-2 !border-slate-950 z-20"
        />
      </div>
    );
  }

  // Expanded Group Container
  return (
    <div
      className="relative bg-slate-950/40 border-2 border-dashed rounded-2xl p-4 shadow-md backdrop-blur-sm min-w-[320px] min-h-[220px]"
      style={{ borderColor: `${color}60` }}
    >
      <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-800/60">
        <div className="flex items-center gap-2">
          <FolderOpen className="w-4 h-4" style={{ color }} />
          <span className="text-xs font-semibold text-slate-200 uppercase tracking-wider">
            {group.title}
          </span>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-800 text-slate-400">
            {group.nodeCount} nodes
          </span>
        </div>
        <button
          onClick={() => group.onToggleCollapse(group.groupId)}
          className="p-1 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded text-xs flex items-center gap-1"
          title="Collapse Group"
        >
          <ChevronDown className="w-3.5 h-3.5" />
          <span className="text-[10px]">Collapse</span>
        </button>
      </div>
    </div>
  );
});
