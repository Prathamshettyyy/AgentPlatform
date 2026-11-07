import React, { useState, memo } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  getSmoothStepPath,
  EdgeProps,
  Position,
} from '@xyflow/react';
import { X, Plus, GitBranch, Settings, CornerDownRight } from 'lucide-react';

export interface WorkflowInteractiveEdgeData {
  from: string;
  to: string;
  condition?: any;
  isAnchor?: boolean;
  anchorType?: 'start' | 'end';
  onDeleteEdge?: (from: string, to: string) => void;
  onInsertNode?: (from: string, to: string) => void;
  onAddParallelBranch?: (from: string, to: string) => void;
  onConfigureCondition?: (from: string, to: string, currentCondition?: any) => void;
  onReconnectEdge?: (from: string, to: string, mode: 'source' | 'target') => void;
  onOpenContextMenu?: (e: React.MouseEvent, from: string, to: string) => void;
  onSelectEdge?: (edgeId: string) => void;
  labelOffsetY?: number;
}

export const WorkflowInteractiveEdge: React.FC<EdgeProps> = memo((props) => {
  const {
    id,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    style = {},
    markerEnd,
    selected,
    data,
  } = props;

  const [isHovered, setIsHovered] = useState(false);

  const edgeData = data as unknown as WorkflowInteractiveEdgeData | undefined;
  const isAnchor = edgeData?.isAnchor ?? false;
  const from = edgeData?.from || '';
  const to = edgeData?.to || '';
  const condition = edgeData?.condition;

  const isHorizontal = !sourcePosition || sourcePosition === Position.Right || sourcePosition === Position.Left;

  let computedCenterX: number | undefined;
  let computedCenterY: number | undefined;

  if (isAnchor && edgeData?.anchorType === 'start') {
    if (isHorizontal) {
      // Step early in the open channel after START so the vertical fan-out never cuts through downstream nodes
      computedCenterX = Math.min(sourceX + 35, sourceX + (targetX - sourceX) * 0.3);
    } else {
      computedCenterY = Math.min(sourceY + 35, sourceY + (targetY - sourceY) * 0.3);
    }
  } else if (isAnchor && edgeData?.anchorType === 'end') {
    if (isHorizontal) {
      computedCenterX = Math.max(targetX - 35, sourceX + (targetX - sourceX) * 0.7);
    } else {
      computedCenterY = Math.max(targetY - 35, sourceY + (targetY - sourceY) * 0.7);
    }
  } else if (!isAnchor && isHorizontal) {
    // When an edge spans across intermediate ranks/columns (e.g. Col 1 -> Col 3 bypassing Col 2),
    // turn late in the open channel right before the target node so the edge travels horizontally
    // above/below intermediate nodes without dropping vertical lines into or beside them.
    const span = targetX - sourceX;
    if (span > 320) {
      computedCenterX = targetX - 45;
    }
  }

  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    borderRadius: 16,
    centerX: computedCenterX,
    centerY: computedCenterY,
  });

  const labelOffsetY = edgeData?.labelOffsetY ?? 0;
  const computedLabelY = labelY + labelOffsetY;

  const isHighlighted = selected || isHovered;

  const strokeColor = isAnchor
    ? edgeData?.anchorType === 'start'
      ? '#10b981'
      : '#818cf8'
    : selected
    ? '#38bdf8'
    : isHovered
    ? '#60a5fa'
    : '#3b82f6';

  const strokeWidth = selected ? 3.5 : isHovered ? 3 : 2.5;

  return (
    <>
      {/* Invisible wider hover path for easier mouse detection */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={28}
        className="cursor-pointer"
        onClick={(e) => {
          e.stopPropagation();
          setIsHovered(true);
          edgeData?.onSelectEdge?.(id);
        }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        onContextMenu={(e) => {
          if (edgeData?.onOpenContextMenu && from && to) {
            e.preventDefault();
            e.stopPropagation();
            edgeData.onOpenContextMenu(e, from, to);
          }
        }}
      />

      {/* Selected Glow Shadow */}
      {selected && (
        <path
          d={edgePath}
          fill="none"
          stroke="#38bdf8"
          strokeWidth={7}
          strokeOpacity={0.25}
          className="pointer-events-none transition-all duration-200"
        />
      )}

      {/* Actual SVG Edge */}
      <BaseEdge
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: strokeColor,
          strokeWidth,
          strokeDasharray: condition ? '5,4' : undefined,
          transition: 'stroke 0.2s, stroke-width 0.2s',
        }}
      />

      {/* Edge Controls & Label via EdgeLabelRenderer */}
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${computedLabelY}px)`,
            pointerEvents: isHighlighted ? 'all' : 'none',
            zIndex: isHighlighted ? 50 : 10,
          }}
          className="nodrag nopan flex items-center gap-1 select-none group transition-all"
          onMouseEnter={() => setIsHovered(true)}
          onMouseLeave={() => setIsHovered(false)}
        >
          {/* Condition Pill (if present) */}
          {condition && (
            <span
              onClick={(e) => {
                e.stopPropagation();
                edgeData?.onConfigureCondition?.(from, to, condition);
              }}
              title={`Condition: ${JSON.stringify(condition)}`}
              className="px-2 py-0.5 text-[10px] font-mono rounded-full bg-slate-900/90 border border-amber-500/50 text-amber-300 shadow-md cursor-pointer hover:bg-amber-950/60 transition-colors"
            >
              if {Object.keys(condition)[0] || 'cond'}
            </span>
          )}

          {/* Interactive Floating Action Buttons (Shown when selected or hovered) */}
          {isHighlighted && !isAnchor && from && to && (
            <div
              data-testid={`edge-controls-${from}-${to}`}
              className="flex items-center gap-0.5 p-1 bg-slate-900/95 border border-slate-700/80 rounded-lg shadow-xl backdrop-blur-sm animate-in fade-in duration-150"
            >
              {/* Insert Sequential Node (+) */}
              {edgeData?.onInsertNode && (
                <button
                  type="button"
                  data-testid={`insert-sequential-${from}-${to}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    edgeData.onInsertNode?.(from, to);
                  }}
                  className="p-1 text-slate-300 hover:text-emerald-400 hover:bg-slate-800 rounded transition-colors"
                  title="Insert sequential node between these nodes"
                >
                  <Plus className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Add Parallel Branch */}
              {edgeData?.onAddParallelBranch && (
                <button
                  type="button"
                  data-testid={`parallel-branch-${from}-${to}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    edgeData.onAddParallelBranch?.(from, to);
                  }}
                  className="p-1 text-slate-300 hover:text-blue-400 hover:bg-slate-800 rounded transition-colors"
                  title="Add parallel branch"
                >
                  <GitBranch className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Configure Condition */}
              {edgeData?.onConfigureCondition && (
                <button
                  type="button"
                  data-testid={`condition-${from}-${to}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    edgeData.onConfigureCondition?.(from, to, condition);
                  }}
                  className="p-1 text-slate-300 hover:text-amber-400 hover:bg-slate-800 rounded transition-colors"
                  title="Configure branch condition"
                >
                  <Settings className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Reconnect Destination */}
              {edgeData?.onReconnectEdge && (
                <button
                  type="button"
                  data-testid={`reconnect-${from}-${to}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    edgeData.onReconnectEdge?.(from, to, 'target');
                  }}
                  className="p-1 text-slate-300 hover:text-purple-400 hover:bg-slate-800 rounded transition-colors"
                  title="Reconnect edge destination"
                >
                  <CornerDownRight className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Delete Connection (X / Trash) */}
              {edgeData?.onDeleteEdge && (
                <button
                  type="button"
                  data-testid={`delete-edge-${from}-${to}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    edgeData.onDeleteEdge?.(from, to);
                  }}
                  className="p-1 text-slate-300 hover:text-rose-400 hover:bg-rose-500/20 rounded transition-colors"
                  title="Delete connection"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}

          {/* Start Anchor Edge: Insert Node Before First Node (START -> target) */}
          {isHighlighted && isAnchor && edgeData?.anchorType === 'start' && to && edgeData?.onInsertNode && (
            <div
              data-testid={`start-edge-controls-${to}`}
              className="flex items-center gap-1 p-1 bg-slate-900/95 border border-emerald-500/60 rounded-lg shadow-xl backdrop-blur-sm animate-in fade-in duration-150"
            >
              <button
                type="button"
                data-testid={`insert-before-${to}`}
                onClick={(e) => {
                  e.stopPropagation();
                  edgeData.onInsertNode?.('__start__', to);
                }}
                className="flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-emerald-300 hover:text-emerald-100 hover:bg-emerald-950/60 rounded transition-colors"
                title={`Insert a new node before ${to} (between START and ${to})`}
              >
                <Plus className="w-3.5 h-3.5 text-emerald-400" />
                <span>Insert Node Before <strong>{to}</strong></span>
              </button>
            </div>
          )}

          {/* Anchor Edge to END: Insert Sequential Node, Add Parallel Branch, or Connect to Join Node */}
          {isHighlighted && isAnchor && edgeData?.anchorType === 'end' && from && (
            <div className="flex items-center gap-1 p-1 bg-slate-900/95 border border-slate-700/80 rounded-lg shadow-xl backdrop-blur-sm animate-in fade-in duration-150">
              {/* Insert Sequential Node (+) */}
              {edgeData?.onInsertNode && (
                <button
                  type="button"
                  data-testid={`insert-sequential-${from}-end`}
                  onClick={(e) => {
                    e.stopPropagation();
                    edgeData.onInsertNode?.(from, '__end__');
                  }}
                  className="p-1 text-slate-300 hover:text-emerald-400 hover:bg-slate-800 rounded transition-colors"
                  title={`Insert sequential node after ${from} (before END)`}
                >
                  <Plus className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Add Parallel Branch */}
              {edgeData?.onAddParallelBranch && (
                <button
                  type="button"
                  data-testid={`parallel-branch-${from}-end`}
                  onClick={(e) => {
                    e.stopPropagation();
                    edgeData.onAddParallelBranch?.(from, '__end__');
                  }}
                  className="p-1 text-slate-300 hover:text-blue-400 hover:bg-slate-800 rounded transition-colors"
                  title={`Add parallel branch alongside ${from}`}
                >
                  <GitBranch className="w-3.5 h-3.5" />
                </button>
              )}

              {/* Connect to Join Node */}
              {edgeData?.onReconnectEdge && (
                <button
                  type="button"
                  data-testid={`connect-leaf-join-${from}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    edgeData.onReconnectEdge?.(from, '__end__', 'target');
                  }}
                  className="px-2 py-0.5 text-[10px] font-medium text-slate-200 hover:text-purple-300 hover:bg-slate-800 rounded flex items-center gap-1 transition-colors"
                  title="Connect this branch output to a downstream join node instead of END"
                >
                  <CornerDownRight className="w-3 h-3 text-purple-400" />
                  Connect to Join Node
                </button>
              )}
            </div>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
});

