import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import '@xyflow/react/dist/style.css';
import {
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  Background,
  MiniMap,
  Node,
  Edge,
  applyNodeChanges,
  applyEdgeChanges,
  NodeChange,
  EdgeChange,
  Connection,
  addEdge,
  reconnectEdge,
} from '@xyflow/react';
import { WorkflowDefinition, WorkflowNode, WorkflowEdge, RunRecord, ExecutionEvent } from '../../api/types';
import { Layers, ArrowRight, Plus, AlertCircle, CheckCircle2, Link2, X } from 'lucide-react';
import { StatusBadge } from '../common/StatusBadge';
import { WorkflowGraphNode } from './WorkflowGraphNode';
import { WorkflowGroupNode } from './WorkflowGraphGroupNode';
import { StartNode, EndNode } from './WorkflowGraphAnchors';
import { WorkflowInteractiveEdge } from './WorkflowInteractiveEdge';
import { WorkflowGraphToolbar } from './WorkflowGraphToolbar';
import { WorkflowGraphInspector } from './WorkflowGraphInspector';
import {
  calculateDagreLayout,
  VisualGroup,
  detectGraphCycles,
} from './workflowLayout';
import {
  canConnect,
  addConnection,
  removeConnections,
  reconnectConnection,
  insertSequentialNodeOnEdge,
  addSequentialNodeAfter,
  addParallelBranch,
  addJoinNode,
  duplicateNode,
  updateEdgeCondition,
  validateWorkflowGraph,
  autoFixOrphanedMappings,
} from './workflowGraphOps';
import {
  InsertSequentialModal,
  AddParallelBranchModal,
  AddJoinNodeModal,
  ConfigureConditionModal,
  CanvasContextMenu,
  ContextMenuState,
} from './WorkflowCanvasModals';

// Stable custom node types mapping for ReactFlow
const nodeTypes = {
  workflowNode: WorkflowGraphNode,
  workflowGroup: WorkflowGroupNode,
  startNode: StartNode,
  endNode: EndNode,
};

// Stable custom edge types mapping for ReactFlow
const edgeTypes = {
  interactiveEdge: WorkflowInteractiveEdge,
};

export interface WorkflowGraphProps {
  workflow: WorkflowDefinition;
  onUpdateWorkflow?: (updatedWorkflow: WorkflowDefinition) => void | Promise<void>;
  onAddNode?: () => void;
  onDeleteNode?: (nodeId: string) => void;
  runRecord?: RunRecord | null;
  events?: ExecutionEvent[];
  className?: string;
}

const WorkflowGraphInner: React.FC<WorkflowGraphProps> = ({
  workflow: initialWorkflow,
  onUpdateWorkflow,
  onAddNode,
  onDeleteNode,
  runRecord,
  events = [],
  className = '',
}) => {
  const { fitView, zoomIn, zoomOut, setCenter } = useReactFlow();

  // Local active workflow state to support undo/redo and instant canvas updates
  const [currentWorkflow, setCurrentWorkflow] = useState<WorkflowDefinition>(initialWorkflow);
  const [undoStack, setUndoStack] = useState<WorkflowDefinition[]>([]);
  const [redoStack, setRedoStack] = useState<WorkflowDefinition[]>([]);

  // Feedback notifications
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Sync when initialWorkflow changes from parent/server (unless locally modified)
  useEffect(() => {
    setCurrentWorkflow(initialWorkflow);
  }, [initialWorkflow]);

  const [direction, setDirection] = useState<'LR' | 'TB'>('LR');
  const [isCompact, setIsCompact] = useState<boolean>(false);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);

  // Search state
  const [searchQuery, setSearchQuery] = useState('');
  const [activeMatchIndex, setActiveMatchIndex] = useState(0);

  // Inspection & selection
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  // Connect Mode (Method B: Add Connection toolbar mode)
  const [isConnectMode, setIsConnectMode] = useState<boolean>(false);
  const [connectSourceId, setConnectSourceId] = useState<string | null>(null);

  // Context Menu state
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

  // Modals state
  const [insertSeqEdge, setInsertSeqEdge] = useState<{ from: string; to: string } | null>(null);
  const [parallelBranchRefNode, setParallelBranchRefNode] = useState<string | null>(null);
  const [isJoinModalOpen, setIsJoinModalOpen] = useState<boolean>(false);
  const [joinInitialBranches, setJoinInitialBranches] = useState<string[]>([]);
  const [configureConditionEdge, setConfigureConditionEdge] = useState<{
    from: string;
    to: string;
    condition?: any;
  } | null>(null);

  // Visual grouping
  const [groups, setGroups] = useState<VisualGroup[]>([]);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  // Manual positions cache using ref to avoid runaway render loops during drag
  const manualPositionsRef = useRef<Map<string, { x: number; y: number }>>(new Map());

  // Push new workflow state to history and notify parent
  const applyWorkflowChange = useCallback(
    (newWf: WorkflowDefinition, successMsg?: string) => {
      setUndoStack((prev) => [...prev, currentWorkflow]);
      setRedoStack([]);
      setCurrentWorkflow(newWf);
      if (successMsg) {
        setFeedback({ type: 'success', message: successMsg });
        setTimeout(() => setFeedback(null), 3500);
      }
      onUpdateWorkflow?.(newWf);
    },
    [currentWorkflow, onUpdateWorkflow]
  );

  // Undo action
  const handleUndo = useCallback(() => {
    if (undoStack.length === 0) return;
    const previous = undoStack[undoStack.length - 1];
    setUndoStack((prev) => prev.slice(0, -1));
    setRedoStack((prev) => [...prev, currentWorkflow]);
    setCurrentWorkflow(previous);
    setFeedback({ type: 'success', message: 'Action undone' });
    setTimeout(() => setFeedback(null), 2000);
    onUpdateWorkflow?.(previous);
  }, [undoStack, currentWorkflow, onUpdateWorkflow]);

  // Redo action
  const handleRedo = useCallback(() => {
    if (redoStack.length === 0) return;
    const next = redoStack[redoStack.length - 1];
    setRedoStack((prev) => prev.slice(0, -1));
    setUndoStack((prev) => [...prev, currentWorkflow]);
    setCurrentWorkflow(next);
    setFeedback({ type: 'success', message: 'Action redone' });
    setTimeout(() => setFeedback(null), 2000);
    onUpdateWorkflow?.(next);
  }, [redoStack, currentWorkflow, onUpdateWorkflow]);

  const rawNodes = currentWorkflow.nodes || [];
  const rawEdges = currentWorkflow.edges || [];

  // Validation
  const validation = useMemo(() => validateWorkflowGraph(currentWorkflow), [currentWorkflow]);
  const hasCycles = validation.cycles.length > 0;

  // Search matching
  const matchingNodeIds = useMemo(() => {
    if (!searchQuery.trim()) return [];
    const q = searchQuery.toLowerCase();
    return rawNodes
      .filter(
        (n) =>
          n.id.toLowerCase().includes(q) ||
          (n.agent_id && n.agent_id.toLowerCase().includes(q)) ||
          n.type.toLowerCase().includes(q)
      )
      .map((n) => n.id);
  }, [rawNodes, searchQuery]);

  const activeMatchId = matchingNodeIds[activeMatchIndex] || null;

  // Handle group collapse toggle
  const handleToggleGroupCollapse = useCallback((groupId: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  }, []);

  /* ---------------- Interactive Edge & Node Callbacks ---------------- */

  const handleDeleteEdge = useCallback(
    (from: string, to: string) => {
      try {
        const updated = removeConnections(currentWorkflow, [{ from, to }]);
        applyWorkflowChange(updated, `Removed connection ${from} → ${to}`);
      } catch (err: any) {
        setFeedback({ type: 'error', message: err.message });
      }
    },
    [currentWorkflow, applyWorkflowChange]
  );

  const handleInsertNodeOnEdge = useCallback((from: string, to: string) => {
    setInsertSeqEdge({ from, to });
  }, []);

  const handleAddParallelBranchOnEdge = useCallback((from: string, to: string) => {
    setParallelBranchRefNode(from);
  }, []);

  const handleConfigureCondition = useCallback(
    (from: string, to: string, currentCond?: any) => {
      setConfigureConditionEdge({ from, to, condition: currentCond });
    },
    []
  );

  const handleOpenEdgeContextMenu = useCallback(
    (e: React.MouseEvent, from: string, to: string) => {
      const edge = rawEdges.find((ed) => ed.from === from && ed.to === to) || { from, to };
      setContextMenu({
        type: 'edge',
        x: e.clientX,
        y: e.clientY,
        edge,
      });
    },
    [rawEdges]
  );

  const handleOpenNodeContextMenu = useCallback((e: React.MouseEvent, nodeId: string) => {
    setContextMenu({
      type: 'node',
      x: e.clientX,
      y: e.clientY,
      nodeId,
    });
  }, []);

  const handleAddSequentialNodeFromNode = useCallback(
    (nodeId: string) => {
      // If node has 1 outgoing edge, insert between; else append
      const outgoing = rawEdges.filter((e) => e.from === nodeId);
      if (outgoing.length === 1) {
        setInsertSeqEdge({ from: nodeId, to: outgoing[0].to });
      } else {
        setInsertSeqEdge({ from: nodeId, to: '__end__' });
      }
    },
    [rawEdges]
  );

  const handleAddSequentialNodeBefore = useCallback(
    (nodeId: string) => {
      const incoming = rawEdges.filter((e) => e.to === nodeId);
      if (incoming.length === 1) {
        setInsertSeqEdge({ from: incoming[0].from, to: nodeId });
      } else {
        setInsertSeqEdge({ from: '__start__', to: nodeId });
      }
    },
    [rawEdges]
  );

  const handleAddParallelBranchFromNode = useCallback((nodeId: string) => {
    setParallelBranchRefNode(nodeId);
  }, []);

  const handleDuplicateNode = useCallback(
    (nodeId: string) => {
      try {
        const { updatedWorkflow, newNode } = duplicateNode(currentWorkflow, nodeId);
        applyWorkflowChange(updatedWorkflow, `Duplicated node '${nodeId}' as '${newNode.id}'`);
        setSelectedNodeId(newNode.id);
      } catch (err: any) {
        setFeedback({ type: 'error', message: err.message });
      }
    },
    [currentWorkflow, applyWorkflowChange]
  );

  const handleDeleteNodeAction = useCallback(
    (nodeId: string) => {
      if (onDeleteNode) {
        onDeleteNode(nodeId);
      } else {
        const newNodes = (currentWorkflow.nodes || []).filter((n) => n.id !== nodeId);
        const newEdges = (currentWorkflow.edges || []).filter((e) => e.from !== nodeId && e.to !== nodeId);
        applyWorkflowChange(
          {
            ...currentWorkflow,
            nodes: newNodes,
            edges: newEdges,
          },
          `Deleted node '${nodeId}'`
        );
      }
      setSelectedNodeId(null);
    },
    [currentWorkflow, onDeleteNode, applyWorkflowChange]
  );

  const handleAutoFixMappings = useCallback(() => {
    const fixed = autoFixOrphanedMappings(currentWorkflow);
    applyWorkflowChange(fixed, 'Auto-fixed input mappings to workflow inputs');
  }, [currentWorkflow, applyWorkflowChange]);

  // Compute Layout Result
  const computeCurrentLayout = useCallback(() => {
    return calculateDagreLayout(currentWorkflow, {
      direction,
      isCompact,
      manualPositions: manualPositionsRef.current,
      groups,
      collapsedGroups,
      runRecord,
      events,
      searchQuery,
      activeMatchId: activeMatchId || undefined,
      onDeleteNode: handleDeleteNodeAction,
      onToggleGroupCollapse: handleToggleGroupCollapse,
      // Node interactive actions
      onAddSequentialNode: handleAddSequentialNodeFromNode,
      onAddParallelBranchOnNode: handleAddParallelBranchFromNode,
      onConnectNode: (nodeId) => {
        setIsConnectMode(true);
        setConnectSourceId(nodeId);
      },
      onDuplicateNode: handleDuplicateNode,
      onNodeContextMenu: handleOpenNodeContextMenu,
      isConnectMode,
      connectSourceId,
      // Edge interactive actions
      onDeleteEdge: handleDeleteEdge,
      onInsertNodeOnEdge: handleInsertNodeOnEdge,
      onAddParallelBranchOnEdge: handleAddParallelBranchOnEdge,
      onConfigureCondition: handleConfigureCondition,
      onReconnectEdge: (from, to, mode) => {
        setIsConnectMode(true);
        setConnectSourceId(from);
      },
      onOpenEdgeContextMenu: handleOpenEdgeContextMenu,
      selectedEdgeId,
      onSelectEdge: (edgeId) => {
        setSelectedEdgeId(edgeId);
        setSelectedNodeId(null);
        setEdges((eds) => eds.map((e) => ({ ...e, selected: e.id === edgeId })));
      },
    });
  }, [
    currentWorkflow,
    direction,
    isCompact,
    groups,
    collapsedGroups,
    runRecord,
    events,
    searchQuery,
    activeMatchId,
    selectedEdgeId,
    handleDeleteNodeAction,
    handleToggleGroupCollapse,
    handleAddSequentialNodeFromNode,
    handleAddParallelBranchFromNode,
    handleDuplicateNode,
    handleOpenNodeContextMenu,
    isConnectMode,
    connectSourceId,
    handleDeleteEdge,
    handleInsertNodeOnEdge,
    handleAddParallelBranchOnEdge,
    handleConfigureCondition,
    handleOpenEdgeContextMenu,
  ]);

  const initialLayout = useMemo(() => computeCurrentLayout(), [computeCurrentLayout]);
  const [nodes, setNodes] = useState<Node[]>(initialLayout.nodes);
  const [edges, setEdges] = useState<Edge[]>(initialLayout.edges);

  // Sync nodes and edges whenever layout changes
  useEffect(() => {
    const res = computeCurrentLayout();
    setNodes(res.nodes);
    setEdges(res.edges);
  }, [computeCurrentLayout]);

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((nds) => applyNodeChanges(changes, nds));
    changes.forEach((change) => {
      if (change.type === 'position' && change.position && change.id) {
        manualPositionsRef.current.set(change.id, change.position);
      }
    });
  }, []);

  const onEdgesChange = useCallback((changes: EdgeChange[]) => {
    setEdges((eds) => applyEdgeChanges(changes, eds));
  }, []);

  /* ---------------- Connection Handlers (Method A: Drag-and-Connect & Method B: Connect Mode) ---------------- */

  const onConnect = useCallback(
    (connection: Connection) => {
      const source = connection.source;
      const target = connection.target;
      if (!source || !target) return;

      const check = canConnect(currentWorkflow, source, target);
      if (!check.valid) {
        setFeedback({ type: 'error', message: check.reason || 'Invalid connection' });
        setTimeout(() => setFeedback(null), 3000);
        return;
      }

      try {
        const updated = addConnection(currentWorkflow, source, target);
        applyWorkflowChange(updated, `Connected ${source} → ${target}`);
      } catch (err: any) {
        setFeedback({ type: 'error', message: err.message });
      }
    },
    [currentWorkflow, applyWorkflowChange]
  );

  const onReconnect = useCallback(
    (oldEdge: Edge, newConnection: Connection) => {
      if (!newConnection.source || !newConnection.target) return;
      try {
        const updated = reconnectConnection(
          currentWorkflow,
          { from: oldEdge.source, to: oldEdge.target },
          newConnection.source,
          newConnection.target
        );
        applyWorkflowChange(
          updated,
          `Reconnected edge to ${newConnection.source} → ${newConnection.target}`
        );
      } catch (err: any) {
        setFeedback({ type: 'error', message: err.message });
      }
    },
    [currentWorkflow, applyWorkflowChange]
  );

  // Auto Arrange: reset manual drag overrides and run pure Dagre
  const handleAutoArrange = useCallback(() => {
    manualPositionsRef.current.clear();
    const res = calculateDagreLayout(currentWorkflow, {
      direction,
      isCompact,
      manualPositions: new Map(),
      groups,
      collapsedGroups,
      runRecord,
      events,
      searchQuery,
      activeMatchId: activeMatchId || undefined,
      onDeleteNode: handleDeleteNodeAction,
      onToggleGroupCollapse: handleToggleGroupCollapse,
    });
    setNodes(res.nodes);
    setEdges(res.edges);
    window.requestAnimationFrame(() => {
      fitView({ padding: 0.2, duration: 400 });
    });
  }, [
    currentWorkflow,
    direction,
    isCompact,
    groups,
    collapsedGroups,
    runRecord,
    events,
    searchQuery,
    activeMatchId,
    handleDeleteNodeAction,
    handleToggleGroupCollapse,
    fitView,
  ]);

  // Direction toggle
  const handleToggleDirection = useCallback(() => {
    setDirection((d) => (d === 'LR' ? 'TB' : 'LR'));
    window.requestAnimationFrame(() => {
      fitView({ padding: 0.2, duration: 350 });
    });
  }, [fitView]);

  // View mode toggle
  const handleToggleCompact = useCallback(() => {
    setIsCompact((c) => !c);
    window.requestAnimationFrame(() => {
      fitView({ padding: 0.2, duration: 350 });
    });
  }, [fitView]);

  // Search matches
  const handleNextMatch = useCallback(() => {
    if (matchingNodeIds.length === 0) return;
    const nextIdx = (activeMatchIndex + 1) % matchingNodeIds.length;
    setActiveMatchIndex(nextIdx);
    const targetId = matchingNodeIds[nextIdx];
    const targetNode = nodes.find((n) => n.id === targetId);
    if (targetNode) {
      setCenter(targetNode.position.x + 120, targetNode.position.y + 40, {
        zoom: 1.15,
        duration: 400,
      });
      setSelectedNodeId(targetId);
    }
  }, [matchingNodeIds, activeMatchIndex, nodes, setCenter]);

  const handlePrevMatch = useCallback(() => {
    if (matchingNodeIds.length === 0) return;
    const prevIdx = (activeMatchIndex - 1 + matchingNodeIds.length) % matchingNodeIds.length;
    setActiveMatchIndex(prevIdx);
    const targetId = matchingNodeIds[prevIdx];
    const targetNode = nodes.find((n) => n.id === targetId);
    if (targetNode) {
      setCenter(targetNode.position.x + 120, targetNode.position.y + 40, {
        zoom: 1.15,
        duration: 400,
      });
      setSelectedNodeId(targetId);
    }
  }, [matchingNodeIds, activeMatchIndex, nodes, setCenter]);

  // Focus on first match
  useEffect(() => {
    if (matchingNodeIds.length > 0) {
      setActiveMatchIndex(0);
      const targetId = matchingNodeIds[0];
      const targetNode = nodes.find((n) => n.id === targetId);
      if (targetNode) {
        setCenter(targetNode.position.x + 120, targetNode.position.y + 40, {
          zoom: 1.15,
          duration: 400,
        });
      }
    }
  }, [searchQuery]);

  // Node selection & Connect Mode handling
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (node.id === '__start__' || node.id === '__end__') return;

      // Handle Connect Mode (Method B)
      if (isConnectMode) {
        if (!connectSourceId) {
          setConnectSourceId(node.id);
          setFeedback({
            type: 'success',
            message: `Selected source '${node.id}'. Now click destination node to complete connection.`,
          });
        } else if (connectSourceId !== node.id) {
          const check = canConnect(currentWorkflow, connectSourceId, node.id);
          if (!check.valid) {
            setFeedback({ type: 'error', message: check.reason || 'Invalid connection' });
          } else {
            const updated = addConnection(currentWorkflow, connectSourceId, node.id);
            applyWorkflowChange(updated, `Connected ${connectSourceId} → ${node.id}`);
            setIsConnectMode(false);
            setConnectSourceId(null);
          }
        }
        return;
      }

      setSelectedNodeId(node.id.startsWith('group_') ? null : node.id);
      setSelectedEdgeId(null);
      setEdges((eds) => eds.map((e) => (e.selected ? { ...e, selected: false } : e)));
    },
    [isConnectMode, connectSourceId, currentWorkflow, applyWorkflowChange]
  );

  const onEdgeClick = useCallback((_: React.MouseEvent, edge: Edge) => {
    setSelectedEdgeId(edge.id);
    setSelectedNodeId(null);
    setEdges((eds) => eds.map((e) => ({ ...e, selected: e.id === edge.id })));
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setContextMenu(null);
    setEdges((eds) => eds.map((e) => (e.selected ? { ...e, selected: false } : e)));
    if (isConnectMode) {
      setIsConnectMode(false);
      setConnectSourceId(null);
    }
  }, [isConnectMode]);

  /* ---------------- Keyboard Shortcuts (Requirement 8) ---------------- */

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        (e.target as HTMLElement)?.isContentEditable
      ) {
        if (e.key === 'Escape') {
          setSearchQuery('');
          (e.target as HTMLElement).blur();
        }
        return;
      }

      // Undo: Ctrl+Z
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
        return;
      }

      // Redo: Ctrl+Y or Ctrl+Shift+Z
      if (
        ((e.ctrlKey || e.metaKey) && e.key === 'y') ||
        ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'z' || e.key === 'Z'))
      ) {
        e.preventDefault();
        handleRedo();
        return;
      }

      // Delete / Backspace: delete selected edges or node
      if (e.key === 'Delete' || e.key === 'Backspace') {
        const selectedEdges = edges.filter((ed) => ed.selected);
        if (selectedEdges.length > 0) {
          e.preventDefault();
          const edgesToRemove = selectedEdges
            .filter((ed) => ed.source !== '__start__' && ed.target !== '__end__')
            .map((ed) => ({ from: ed.source, to: ed.target }));

          if (edgesToRemove.length > 0) {
            const updated = removeConnections(currentWorkflow, edgesToRemove);
            applyWorkflowChange(
              updated,
              `Deleted ${edgesToRemove.length} connection${edgesToRemove.length > 1 ? 's' : ''}`
            );
          }
          return;
        }

        if (selectedNodeId) {
          e.preventDefault();
          handleDeleteNodeAction(selectedNodeId);
          return;
        }
      }

      // Escape: clear selection, cancel connect mode, close context menu
      if (e.key === 'Escape') {
        setSelectedNodeId(null);
        setContextMenu(null);
        setIsConnectMode(false);
        setConnectSourceId(null);
        setSearchQuery('');
      } else if (e.key === '+' || e.key === '=') {
        zoomIn({ duration: 250 });
      } else if (e.key === '-') {
        zoomOut({ duration: 250 });
      } else if (e.key === 'f' || e.key === '0') {
        fitView({ padding: 0.2, duration: 400 });
      } else if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault();
        const searchInput = document.querySelector(
          'input[placeholder*="Search nodes"]'
        ) as HTMLInputElement;
        if (searchInput) searchInput.focus();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    fitView,
    zoomIn,
    zoomOut,
    handleUndo,
    handleRedo,
    edges,
    selectedNodeId,
    currentWorkflow,
    applyWorkflowChange,
    handleDeleteNodeAction,
  ]);

  // Group selected nodes
  const selectedNodeIds = useMemo(
    () => nodes.filter((n) => n.selected && n.type === 'workflowNode').map((n) => n.id),
    [nodes]
  );

  const handleGroupSelected = useCallback(() => {
    if (selectedNodeIds.length < 2) return;
    const newGroupId = `group_${Date.now()}`;
    const newGroup: VisualGroup = {
      id: newGroupId,
      title: `Group ${groups.length + 1}`,
      nodeIds: [...selectedNodeIds],
      color: '#3b82f6',
    };
    setGroups((prev) => [...prev, newGroup]);
  }, [selectedNodeIds, groups.length]);

  const selectedNodeObject = useMemo(() => {
    if (!selectedNodeId) return null;
    return rawNodes.find((n) => n.id === selectedNodeId) || null;
  }, [selectedNodeId, rawNodes]);

  // Jump to node from inspector
  const handleSelectNodeFromInspector = useCallback(
    (targetId: string) => {
      setSelectedNodeId(targetId);
      const targetNode = nodes.find((n) => n.id === targetId);
      if (targetNode) {
        setCenter(targetNode.position.x + 120, targetNode.position.y + 40, {
          zoom: 1.15,
          duration: 500,
        });
      }
    },
    [nodes, setCenter]
  );

  // Inspector node update
  const handleUpdateNodeFromInspector = useCallback(
    (nodeId: string, updatedNode: WorkflowNode) => {
      const newNodes = (currentWorkflow.nodes || []).map((n) =>
        n.id === nodeId ? updatedNode : n
      );
      applyWorkflowChange(
        {
          ...currentWorkflow,
          nodes: newNodes,
        },
        `Updated node '${nodeId}' configuration`
      );
    },
    [currentWorkflow, applyWorkflowChange]
  );

  if (rawNodes.length === 0) {
    return (
      <div className="p-12 text-center bg-slate-900/50 rounded-xl border border-slate-800 text-slate-400 space-y-4">
        <div>
          <p className="text-base font-semibold text-slate-200">Empty Workflow Draft</p>
          <p className="text-xs text-slate-400 mt-1">
            This workflow draft currently has 0 execution nodes. Add an agent to build the pipeline.
          </p>
        </div>
        {onAddNode && (
          <button
            onClick={onAddNode}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors shadow-sm"
          >
            <Plus className="w-4 h-4" />
            Add First Agent Node
          </button>
        )}
      </div>
    );
  }

  const containerClasses = isFullscreen
    ? 'fixed inset-0 z-50 bg-[#080c14] flex flex-col p-4'
    : `relative rounded-xl border border-slate-800 bg-slate-950 flex flex-col overflow-hidden shadow-lg ${
        className || 'h-[620px] md:h-[680px]'
      }`;

  return (
    <div className="space-y-4">
      {/* Canvas Header / Summary Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-2">
        <div className="flex items-center gap-2.5 flex-wrap">
          <Layers className="w-4 h-4 text-blue-400" />
          <h3 className="text-sm font-semibold text-slate-200 uppercase tracking-wider">
            {hasCycles ? 'Workflow Graph' : 'Workflow DAG'} ({rawNodes.length} nodes, {rawEdges.length} edges)
          </h3>
          {hasCycles && (
            <span className="text-[10px] text-amber-400 font-mono bg-amber-500/10 px-2 py-0.5 rounded-full border border-amber-500/20">
              Contains Loops
            </span>
          )}
          {validation.warnings.length > 0 && (
            <span className="text-[10px] text-yellow-400 font-mono bg-yellow-500/10 px-2 py-0.5 rounded-full border border-yellow-500/20">
              {validation.warnings.length} Warning{validation.warnings.length > 1 ? 's' : ''}
            </span>
          )}
        </div>
        <StatusBadge
          status={
            initialWorkflow.registration_status ||
            (initialWorkflow.registered ? 'registered' : 'disconnected')
          }
        />
      </div>

      {/* Real-time Validation / Error Banner */}
      {!validation.isValid && (
        <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 flex-1 min-w-[260px]">
            <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
            <span>{validation.errors[0]}</span>
          </div>
          <div className="flex items-center gap-2">
            {validation.orphanedMappings.length > 0 && (
              <button
                onClick={handleAutoFixMappings}
                className="px-2.5 py-1 text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white rounded transition-colors"
              >
                Auto-Fix Mappings
              </button>
            )}
            {undoStack.length > 0 && (
              <button
                onClick={handleUndo}
                className="px-2.5 py-1 text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 rounded transition-colors"
              >
                Undo Last Action
              </button>
            )}
          </div>
        </div>
      )}

      {/* Connect Mode Banner */}
      {isConnectMode && (
        <div className="p-2.5 bg-cyan-500/10 border border-cyan-500/30 rounded-xl text-xs text-cyan-300 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Link2 className="w-4 h-4 text-cyan-400 animate-pulse" />
            <span>
              {connectSourceId
                ? `Source selected: [${connectSourceId}]. Click target node to create connection.`
                : 'Connection Mode active: Click source node, then click target node.'}
            </span>
          </div>
          <button
            onClick={() => {
              setIsConnectMode(false);
              setConnectSourceId(null);
            }}
            className="text-cyan-400 hover:text-cyan-200 p-1"
            title="Cancel Connection Mode (Esc)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Feedback Toast */}
      {feedback && (
        <div
          className={`p-2.5 rounded-xl text-xs flex items-center justify-between gap-2 ${
            feedback.type === 'success'
              ? 'bg-emerald-500/10 border border-emerald-500/30 text-emerald-300'
              : 'bg-rose-500/10 border border-rose-500/30 text-rose-300'
          }`}
        >
          <div className="flex items-center gap-1.5">
            {feedback.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            ) : (
              <AlertCircle className="w-4 h-4 text-rose-400" />
            )}
            <span>{feedback.message}</span>
          </div>
          <button onClick={() => setFeedback(null)} className="text-slate-400 hover:text-slate-200">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Main Interactive Canvas */}
      <div className={containerClasses}>
        {/* Toolbar */}
        <WorkflowGraphToolbar
          direction={direction}
          onToggleDirection={handleToggleDirection}
          isCompact={isCompact}
          onToggleCompact={handleToggleCompact}
          onAutoArrange={handleAutoArrange}
          onZoomIn={() => zoomIn({ duration: 250 })}
          onZoomOut={() => zoomOut({ duration: 250 })}
          onFitView={() => fitView({ padding: 0.2, duration: 350 })}
          isFullscreen={isFullscreen}
          onToggleFullscreen={() => setIsFullscreen((f) => !f)}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          matchesCount={matchingNodeIds.length}
          activeMatchIndex={activeMatchIndex}
          onNextMatch={handleNextMatch}
          onPrevMatch={handlePrevMatch}
          selectedNodesCount={selectedNodeIds.length}
          onGroupSelected={handleGroupSelected}
          onAddNode={onAddNode}
          // Interactive props
          canUndo={undoStack.length > 0}
          canRedo={redoStack.length > 0}
          onUndo={handleUndo}
          onRedo={handleRedo}
          isConnectMode={isConnectMode}
          onToggleConnectMode={() => {
            setIsConnectMode((m) => !m);
            setConnectSourceId(null);
          }}
          onAddParallelBranch={() => {
            const ref = selectedNodeId || rawNodes[0]?.id;
            if (ref) setParallelBranchRefNode(ref);
          }}
          onAddJoinNode={() => {
            setJoinInitialBranches(selectedNodeIds.length > 0 ? selectedNodeIds : rawNodes.map((n) => n.id));
            setIsJoinModalOpen(true);
          }}
          hasOrphanedMappings={validation.orphanedMappings.length > 0}
          onAutoFixMappings={handleAutoFixMappings}
        />

        {/* Viewport Canvas */}
        <div className="relative flex-1 w-full min-h-[450px]">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={onNodeClick}
            onEdgeClick={onEdgeClick}
            onPaneClick={onPaneClick}
            onConnect={onConnect}
            onReconnect={onReconnect}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.15}
            maxZoom={2.2}
            nodesConnectable={true}
            elementsSelectable={true}
            edgesReconnectable={true}
            proOptions={{ hideAttribution: true }}
            className="bg-[#080c14]"
            style={{ width: '100%', height: '100%' }}
          >
            <Background color="#1e293b" gap={24} size={1.2} />
            <MiniMap
              nodeColor={(n) => {
                if (n.id === '__start__') return '#10b981';
                if (n.id === '__end__') return '#818cf8';
                if (n.type === 'workflowGroup') return '#3b82f6';
                const nodeData = n.data as any;
                return nodeData?.workflowNode?.type === 'agent' ? '#3b82f6' : '#fbbf24';
              }}
              nodeStrokeColor="#0f172a"
              nodeStrokeWidth={2}
              maskColor="rgba(8, 12, 20, 0.75)"
              className="!bg-slate-950 !border !border-slate-800 !rounded-xl !shadow-lg"
              zoomable
              pannable
            />
          </ReactFlow>

          {/* Inspector Drawer/Sidebar */}
          <WorkflowGraphInspector
            node={selectedNodeObject}
            edges={rawEdges}
            runRecord={runRecord}
            workflowId={currentWorkflow.id}
            onClose={() => setSelectedNodeId(null)}
            onSelectNode={handleSelectNodeFromInspector}
            onAddSequentialNode={handleAddSequentialNodeFromNode}
            onAddSequentialNodeBefore={handleAddSequentialNodeBefore}
            onAddParallelBranch={handleAddParallelBranchFromNode}
            onConnectNode={(nodeId) => {
              setIsConnectMode(true);
              setConnectSourceId(nodeId);
            }}
            onDuplicateNode={handleDuplicateNode}
            onDeleteNode={handleDeleteNodeAction}
            onUpdateNode={handleUpdateNodeFromInspector}
          />
        </div>
      </div>

      {/* Interactive Modals */}
      <InsertSequentialModal
        isOpen={insertSeqEdge !== null}
        edge={insertSeqEdge}
        workflow={currentWorkflow}
        onClose={() => setInsertSeqEdge(null)}
        onSubmit={(newNode) => {
          if (!insertSeqEdge) return;
          const updated = insertSequentialNodeOnEdge(currentWorkflow, insertSeqEdge, newNode);
          applyWorkflowChange(
            updated,
            `Inserted node '${newNode.id}' between ${insertSeqEdge.from} and ${insertSeqEdge.to}`
          );
          setSelectedNodeId(newNode.id);
        }}
      />

      <AddParallelBranchModal
        isOpen={parallelBranchRefNode !== null}
        referenceNodeId={parallelBranchRefNode}
        workflow={currentWorkflow}
        onClose={() => setParallelBranchRefNode(null)}
        onSubmit={(newNode, downstreamJoinId) => {
          if (!parallelBranchRefNode) return;
          const updated = addParallelBranch(
            currentWorkflow,
            parallelBranchRefNode,
            newNode,
            downstreamJoinId
          );
          applyWorkflowChange(
            updated,
            `Created parallel branch '${newNode.id}' alongside '${parallelBranchRefNode}'`
          );
          setSelectedNodeId(newNode.id);
        }}
      />

      <AddJoinNodeModal
        isOpen={isJoinModalOpen}
        initialBranches={joinInitialBranches}
        workflow={currentWorkflow}
        onClose={() => setIsJoinModalOpen(false)}
        onSubmit={(branchIds, joinNode, isExisting) => {
          const updated = addJoinNode(currentWorkflow, branchIds, joinNode, isExisting);
          applyWorkflowChange(
            updated,
            `Established join barrier at '${joinNode.id}' for [${branchIds.join(', ')}]`
          );
          setSelectedNodeId(joinNode.id);
        }}
      />

      <ConfigureConditionModal
        isOpen={configureConditionEdge !== null}
        edge={configureConditionEdge}
        onClose={() => setConfigureConditionEdge(null)}
        onSubmit={(from, to, condition) => {
          const updated = updateEdgeCondition(currentWorkflow, from, to, condition);
          applyWorkflowChange(updated, `Updated execution condition for ${from} → ${to}`);
        }}
      />

      {/* Context Menu for right click */}
      <CanvasContextMenu
        menu={contextMenu}
        onClose={() => setContextMenu(null)}
        onDeleteEdge={handleDeleteEdge}
        onInsertSequentialOnEdge={handleInsertNodeOnEdge}
        onAddParallelBranchOnEdge={handleAddParallelBranchOnEdge}
        onConfigureCondition={handleConfigureCondition}
        onReconnectEdge={(from, to, mode) => {
          setIsConnectMode(true);
          setConnectSourceId(from);
        }}
        onAddSequentialNode={handleAddSequentialNodeFromNode}
        onAddParallelBranchOnNode={handleAddParallelBranchFromNode}
        onAddConnectionFromNode={(nodeId) => {
          setIsConnectMode(true);
          setConnectSourceId(nodeId);
        }}
        onDuplicateNode={handleDuplicateNode}
        onDeleteNode={handleDeleteNodeAction}
        onConfigureNode={(nodeId) => setSelectedNodeId(nodeId)}
      />

      {/* Explicit Edges List with Delete Buttons */}
      {rawEdges.length > 0 && (
        <div className="mt-4 pt-4 border-t border-slate-800">
          <div className="flex items-center justify-between mb-2">
            <h5 className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              Edge Routing Rules ({rawEdges.length})
            </h5>
            <span className="text-[11px] text-slate-500">
              Click an edge to select, drag handles to connect, or press Delete to remove.
            </span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2">
            {rawEdges.map((edge, idx) => (
              <div
                key={idx}
                className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800 text-xs font-mono flex items-center justify-between gap-2 group hover:border-slate-700 transition-colors"
              >
                <div className="flex items-center gap-2 min-w-0 flex-1 truncate">
                  <span className="text-slate-300 truncate" title={edge.from}>
                    {edge.from}
                  </span>
                  <ArrowRight className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                  <span className="text-slate-300 truncate" title={edge.to}>
                    {edge.to}
                  </span>
                  {edge.condition && (
                    <span
                      className="ml-auto text-amber-400 text-[10px] truncate"
                      title={JSON.stringify(edge.condition)}
                    >
                      [{Object.keys(edge.condition)[0]}]
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  data-testid={`delete-rule-${edge.from}-${edge.to}`}
                  onClick={() => handleDeleteEdge(edge.from, edge.to)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 rounded transition-all shrink-0"
                  title={`Delete edge ${edge.from} → ${edge.to}`}
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export const WorkflowGraph: React.FC<WorkflowGraphProps> = (props) => {
  return (
    <ReactFlowProvider>
      <WorkflowGraphInner {...props} />
    </ReactFlowProvider>
  );
};
