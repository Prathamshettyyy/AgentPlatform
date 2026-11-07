import React from 'react';
import {
  ZoomIn,
  ZoomOut,
  Maximize2,
  Sparkles,
  ArrowRight,
  ArrowDown,
  Rows,
  Columns,
  Search,
  X,
  ChevronDown,
  ChevronUp,
  FolderPlus,
  Maximize,
  Minimize,
  Plus,
  Undo2,
  Redo2,
  Link2,
  GitBranch,
  Split,
  Wrench,
} from 'lucide-react';

export interface WorkflowGraphToolbarProps {
  direction: 'LR' | 'TB';
  onToggleDirection: () => void;
  isCompact: boolean;
  onToggleCompact: () => void;
  onAutoArrange: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFitView: () => void;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  matchesCount: number;
  activeMatchIndex: number;
  onNextMatch: () => void;
  onPrevMatch: () => void;
  selectedNodesCount: number;
  onGroupSelected?: () => void;
  onAddNode?: () => void;
  // Interactive Editing Props
  canUndo?: boolean;
  canRedo?: boolean;
  onUndo?: () => void;
  onRedo?: () => void;
  isConnectMode?: boolean;
  onToggleConnectMode?: () => void;
  onAddParallelBranch?: () => void;
  onAddJoinNode?: () => void;
  hasOrphanedMappings?: boolean;
  onAutoFixMappings?: () => void;
}

export const WorkflowGraphToolbar: React.FC<WorkflowGraphToolbarProps> = ({
  direction,
  onToggleDirection,
  isCompact,
  onToggleCompact,
  onAutoArrange,
  onZoomIn,
  onZoomOut,
  onFitView,
  isFullscreen,
  onToggleFullscreen,
  searchQuery,
  onSearchChange,
  matchesCount,
  activeMatchIndex,
  onNextMatch,
  onPrevMatch,
  selectedNodesCount,
  onGroupSelected,
  onAddNode,
  canUndo = false,
  canRedo = false,
  onUndo,
  onRedo,
  isConnectMode = false,
  onToggleConnectMode,
  onAddParallelBranch,
  onAddJoinNode,
  hasOrphanedMappings = false,
  onAutoFixMappings,
}) => {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2.5 p-2 bg-slate-900/90 border-b border-slate-800 backdrop-blur-md">
      {/* Left controls: Search & Quick Edit Actions */}
      <div className="flex items-center gap-2 flex-1 min-w-[240px] max-w-lg">
        {/* Undo / Redo */}
        <div className="flex items-center gap-0.5 bg-slate-950 border border-slate-800 rounded-lg p-0.5 shrink-0">
          <button
            type="button"
            onClick={onUndo}
            disabled={!canUndo}
            className="p-1.5 text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:hover:text-slate-400 rounded transition-colors"
            title="Undo (Ctrl+Z)"
          >
            <Undo2 className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={onRedo}
            disabled={!canRedo}
            className="p-1.5 text-slate-400 hover:text-slate-200 disabled:opacity-30 disabled:hover:text-slate-400 rounded transition-colors"
            title="Redo (Ctrl+Y)"
          >
            <Redo2 className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Search Bar */}
        <div className="relative flex-1">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search nodes by ID, agent, or type... (Ctrl+F)"
            className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-16 py-1.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500/30"
          />
          {searchQuery && (
            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
              <span className="text-[10px] text-slate-400 font-mono">
                {matchesCount > 0 ? `${activeMatchIndex + 1}/${matchesCount}` : '0'}
              </span>
              <button
                type="button"
                onClick={() => onSearchChange('')}
                className="text-slate-500 hover:text-slate-300 p-0.5"
                title="Clear Search (Esc)"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>

        {matchesCount > 1 && (
          <div className="flex items-center gap-0.5 border border-slate-800 rounded-lg p-0.5 bg-slate-950 shrink-0">
            <button
              type="button"
              onClick={onPrevMatch}
              className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded"
              title="Previous Match"
            >
              <ChevronUp className="w-3 h-3" />
            </button>
            <button
              type="button"
              onClick={onNextMatch}
              className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded"
              title="Next Match"
            >
              <ChevronDown className="w-3 h-3" />
            </button>
          </div>
        )}

        {selectedNodesCount >= 2 && onGroupSelected && (
          <button
            type="button"
            onClick={onGroupSelected}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs font-medium text-blue-300 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/30 rounded-lg transition-colors shrink-0 shadow-sm"
            title="Create a visual group from selected nodes"
          >
            <FolderPlus className="w-3.5 h-3.5" />
            <span>Group ({selectedNodesCount})</span>
          </button>
        )}
      </div>

      {/* Right controls: Connection & Branch Actions & Layout */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {/* Auto Fix Mappings Alert/Button */}
        {hasOrphanedMappings && onAutoFixMappings && (
          <button
            type="button"
            onClick={onAutoFixMappings}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-500/30 rounded-lg transition-colors animate-pulse"
            title="Automatically rewrite disconnected input mappings to workflow inputs"
          >
            <Wrench className="w-3.5 h-3.5 text-amber-400" />
            <span>Auto-Fix Mappings</span>
          </button>
        )}

        {/* Add Connection Mode Button */}
        {onToggleConnectMode && (
          <button
            type="button"
            onClick={onToggleConnectMode}
            className={`inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
              isConnectMode
                ? 'bg-cyan-500/20 text-cyan-300 border-cyan-400 ring-2 ring-cyan-500/30'
                : 'text-slate-300 bg-slate-950 hover:bg-slate-800 border-slate-800'
            }`}
            title="Add Connection mode: Click source node, then click target node"
          >
            <Link2 className={`w-3.5 h-3.5 ${isConnectMode ? 'text-cyan-400' : 'text-slate-400'}`} />
            <span>{isConnectMode ? 'Connecting...' : 'Connect'}</span>
          </button>
        )}

        {/* Add Parallel Branch */}
        {onAddParallelBranch && (
          <button
            type="button"
            onClick={onAddParallelBranch}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-slate-300 bg-slate-950 hover:bg-slate-800 border border-slate-800 rounded-lg transition-colors"
            title="Add a parallel branch alongside selected or root node"
          >
            <GitBranch className="w-3.5 h-3.5 text-blue-400" />
            <span>Parallel Branch</span>
          </button>
        )}

        {/* Add Join Node */}
        {onAddJoinNode && (
          <button
            type="button"
            onClick={onAddJoinNode}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-slate-300 bg-slate-950 hover:bg-slate-800 border border-slate-800 rounded-lg transition-colors"
            title="Create a fan-in barrier join node for parallel branches"
          >
            <Split className="w-3.5 h-3.5 text-purple-400 rotate-180" />
            <span>Join Barrier</span>
          </button>
        )}

        {/* Layout Direction */}
        <button
          type="button"
          onClick={onToggleDirection}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-slate-300 bg-slate-950 hover:bg-slate-800 border border-slate-800 rounded-lg transition-colors"
          title={`Switch layout to ${direction === 'LR' ? 'Vertical (Top to Bottom)' : 'Horizontal (Left to Right)'}`}
        >
          {direction === 'LR' ? (
            <>
              <ArrowRight className="w-3.5 h-3.5 text-blue-400" />
              <span>LR</span>
            </>
          ) : (
            <>
              <ArrowDown className="w-3.5 h-3.5 text-emerald-400" />
              <span>TB</span>
            </>
          )}
        </button>

        {/* View Mode: Compact vs Expanded */}
        <button
          type="button"
          onClick={onToggleCompact}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-slate-300 bg-slate-950 hover:bg-slate-800 border border-slate-800 rounded-lg transition-colors"
          title={isCompact ? 'Switch to Expanded Details' : 'Switch to Compact Cards'}
        >
          {isCompact ? <Rows className="w-3.5 h-3.5 text-purple-400" /> : <Columns className="w-3.5 h-3.5 text-purple-400" />}
          <span>{isCompact ? 'Compact' : 'Expanded'}</span>
        </button>

        {/* Auto Arrange */}
        <button
          type="button"
          onClick={onAutoArrange}
          className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-blue-400 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/30 rounded-lg transition-colors"
          title="Auto Arrange Layout (Dagre)"
        >
          <Sparkles className="w-3.5 h-3.5 text-blue-400" />
          <span>Auto Arrange</span>
        </button>

        <div className="h-4 w-px bg-slate-800 mx-1 hidden sm:block" />

        {/* Canvas Navigation Buttons */}
        <div className="flex items-center gap-0.5 bg-slate-950 border border-slate-800 rounded-lg p-0.5">
          <button
            type="button"
            onClick={onZoomIn}
            className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded"
            title="Zoom In (+)"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={onZoomOut}
            className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded"
            title="Zoom Out (-)"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={onFitView}
            className="p-1 hover:bg-slate-800 text-slate-400 hover:text-slate-200 rounded"
            title="Fit Entire Graph to View (F)"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Fullscreen Toggle */}
        <button
          type="button"
          onClick={onToggleFullscreen}
          className="p-1.5 bg-slate-950 hover:bg-slate-800 border border-slate-800 text-slate-400 hover:text-slate-200 rounded-lg transition-colors"
          title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen Canvas'}
        >
          {isFullscreen ? <Minimize className="w-3.5 h-3.5" /> : <Maximize className="w-3.5 h-3.5" />}
        </button>

        {/* Add Node Button */}
        {onAddNode && (
          <button
            type="button"
            onClick={onAddNode}
            className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors shadow-sm ml-1"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add Node</span>
          </button>
        )}
      </div>
    </div>
  );
};
