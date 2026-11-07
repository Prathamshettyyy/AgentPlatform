import dagre from '@dagrejs/dagre';
import { Node, Edge, MarkerType, Position } from '@xyflow/react';
import { WorkflowDefinition, WorkflowNode, WorkflowEdge, RunRecord, ExecutionEvent } from '../../api/types';

export interface VisualGroup {
  id: string;
  title: string;
  nodeIds: string[];
  color?: string;
}

export interface WorkflowNodeData extends Record<string, unknown> {
  workflowNode: WorkflowNode;
  isCompact: boolean;
  nodeWidth?: number;
  nodeHeight?: number;
  runtimeStatus?: 'pending' | 'running' | 'succeeded' | 'failed' | 'waiting_for_approval' | 'skipped';
  runtimeInfo?: {
    durationMs?: number;
    worker?: string;
    attempt?: number;
    error?: string;
    output?: any;
    startTime?: string;
    endTime?: string;
  };
  isHighlighted?: boolean;
  onDelete?: (nodeId: string) => void;
  onAddSequentialNode?: (nodeId: string) => void;
  onAddParallelBranch?: (nodeId: string) => void;
  onConnectNode?: (nodeId: string) => void;
  onDuplicateNode?: (nodeId: string) => void;
  onContextMenu?: (e: React.MouseEvent, nodeId: string) => void;
  isConnectMode?: boolean;
  isConnectSource?: boolean;
  isRoot?: boolean;
  isLeaf?: boolean;
  groupId?: string;
}

export interface WorkflowGroupData extends Record<string, unknown> {
  groupId: string;
  title: string;
  nodeCount: number;
  isCollapsed: boolean;
  inputCount: number;
  outputCount: number;
  status?: string;
  onToggleCollapse: (groupId: string) => void;
  color?: string;
}

export interface LayoutOptions {
  direction?: 'LR' | 'TB';
  isCompact?: boolean;
  manualPositions?: Map<string, { x: number; y: number }>;
  groups?: VisualGroup[];
  collapsedGroups?: Set<string>;
  runRecord?: RunRecord | null;
  events?: ExecutionEvent[];
  searchQuery?: string;
  activeMatchId?: string;
  onDeleteNode?: (nodeId: string) => void;
  onToggleGroupCollapse?: (groupId: string) => void;
  // Node interactive actions
  onAddSequentialNode?: (nodeId: string) => void;
  onAddParallelBranchOnNode?: (nodeId: string) => void;
  onConnectNode?: (nodeId: string) => void;
  onDuplicateNode?: (nodeId: string) => void;
  onNodeContextMenu?: (e: React.MouseEvent, nodeId: string) => void;
  isConnectMode?: boolean;
  connectSourceId?: string | null;
  // Edge interactive actions
  onDeleteEdge?: (from: string, to: string) => void;
  onInsertNodeOnEdge?: (from: string, to: string) => void;
  onAddParallelBranchOnEdge?: (from: string, to: string) => void;
  onConfigureCondition?: (from: string, to: string, condition?: any) => void;
  onReconnectEdge?: (from: string, to: string, mode: 'source' | 'target') => void;
  onOpenEdgeContextMenu?: (e: React.MouseEvent, from: string, to: string) => void;
  onSelectEdge?: (edgeId: string) => void;
  selectedEdgeId?: string | null;
}

/**
 * Checks whether the graph contains any cycles.
 */
export function detectGraphCycles(nodes: WorkflowNode[], edges: WorkflowEdge[]): boolean {
  const nodeIds = new Set(nodes.map((n) => n.id));
  const adj = new Map<string, string[]>();
  nodes.forEach((n) => adj.set(n.id, []));

  edges.forEach((e) => {
    if (nodeIds.has(e.from) && nodeIds.has(e.to)) {
      adj.get(e.from)?.push(e.to);
    }
  });

  const visited = new Set<string>();
  const recStack = new Set<string>();

  const isCyclic = (nodeId: string): boolean => {
    visited.add(nodeId);
    recStack.add(nodeId);

    const neighbors = adj.get(nodeId) || [];
    for (const neighbor of neighbors) {
      if (!visited.has(neighbor)) {
        if (isCyclic(neighbor)) return true;
      } else if (recStack.has(neighbor)) {
        return true;
      }
    }

    recStack.delete(nodeId);
    return false;
  };

  for (const node of nodes) {
    if (!visited.has(node.id)) {
      if (isCyclic(node.id)) return true;
    }
  }

  return false;
}

/**
 * Calculates accurate layout dimensions for a workflow node to ensure
 * Dagre layout, HTML card rendering, and connector handles match to the exact pixel.
 */
export function getNodeDimensions(
  node: WorkflowNode,
  isCompact: boolean = false,
  hasRuntimeInfo: boolean = false
): { width: number; height: number } {
  const width = isCompact ? 230 : 290;
  if (isCompact) {
    return { width, height: 76 };
  }

  if (node.type === 'trigger') {
    return { width, height: 104 };
  }

  let height = 62; // base: 28px padding + 28px header + 6px margin
  if (node.type === 'agent' && node.agent_id) {
    height += 24;
  }
  if (hasRuntimeInfo) {
    height += 24;
  }
  const mappingCount = Object.keys(node.input_mappings || {}).length;
  if (mappingCount > 0) {
    const shown = Math.min(mappingCount, 4);
    height += 32 + shown * 18 + (mappingCount > 4 ? 18 : 0);
  }
  if (node.type === 'human_approval' && node.approval_options?.length) {
    height += 30;
  }

  return { width, height: Math.max(88, Math.round(height)) };
}

/**
 * Computes dynamic graph layout using Dagre.
 */
export function calculateDagreLayout(
  workflow: WorkflowDefinition,
  options: LayoutOptions = {}
): {
  nodes: Node[];
  edges: Edge[];
  hasCycles: boolean;
  stats: { nodeCount: number; edgeCount: number; parallelBranchCount: number };
} {
  const {
    direction = 'LR',
    isCompact = false,
    manualPositions = new Map(),
    groups = [],
    collapsedGroups = new Set(),
    runRecord,
    events = [],
    searchQuery = '',
    activeMatchId,
    onDeleteNode,
    onToggleGroupCollapse,
  } = options;

  const rawNodes = workflow.nodes || [];
  const rawEdges = workflow.edges || [];
  const validNodeIds = new Set(rawNodes.map((n) => n.id));
  const validEdges = rawEdges.filter((e) => validNodeIds.has(e.from) && validNodeIds.has(e.to));

  const hasCycles = detectGraphCycles(rawNodes, validEdges);

  // Map node -> group
  const nodeToGroup = new Map<string, VisualGroup>();
  groups.forEach((g) => {
    g.nodeIds.forEach((id) => nodeToGroup.set(id, g));
  });

  // Calculate runtime node status and info from RunRecord and ExecutionEvents
  const runtimeStatusMap = new Map<string, { status: any; info: any }>();
  if (runRecord) {
    const outputs = runRecord.payload?.node_outputs || {};
    const finalErr = runRecord.payload?.error;

    rawNodes.forEach((node) => {
      let status: 'pending' | 'running' | 'succeeded' | 'failed' | 'waiting_for_approval' | 'skipped' =
        'pending';
      const nodeOut = outputs[node.id];
      const nodeEvts = events.filter((ev) => ev.node_id === node.id);

      if (nodeOut !== undefined) {
        status = 'succeeded';
      } else if (runRecord.status === 'running' || runRecord.status === 'resuming') {
        const lastEvt = nodeEvts[nodeEvts.length - 1];
        if (lastEvt && lastEvt.status === 'running') {
          status = 'running';
        }
      } else if (runRecord.status === 'waiting_for_approval' && node.type === 'human_approval') {
        status = 'waiting_for_approval';
      } else if (runRecord.status === 'failed' && finalErr) {
        status = 'failed';
      }

      runtimeStatusMap.set(node.id, {
        status,
        info: {
          output: nodeOut,
          error: status === 'failed' ? (typeof finalErr === 'string' ? finalErr : finalErr?.message) : undefined,
        },
      });
    });
  }

  // Pre-calculate in-degrees and out-degrees
  const incomingMap = new Map<string, string[]>();
  const outgoingMap = new Map<string, string[]>();
  rawNodes.forEach((n) => {
    incomingMap.set(n.id, []);
    outgoingMap.set(n.id, []);
  });
  validEdges.forEach((e) => {
    incomingMap.get(e.to)?.push(e.from);
    outgoingMap.get(e.from)?.push(e.to);
  });

  const rootNodeIds = rawNodes.filter((n) => (incomingMap.get(n.id) || []).length === 0).map((n) => n.id);
  const leafNodeIds = rawNodes.filter((n) => (outgoingMap.get(n.id) || []).length === 0).map((n) => n.id);

  // Initialize Dagre Graph
  const g = new dagre.graphlib.Graph({ compound: true });
  g.setGraph({
    rankdir: direction,
    nodesep: isCompact ? 40 : 65,
    ranksep: isCompact ? 80 : 120,
    marginx: 40,
    marginy: 40,
  });
  g.setDefaultEdgeLabel(() => ({}));

  // Track which nodes are visible vs inside collapsed groups
  const visibleNodes = rawNodes.filter((node) => {
    const grp = nodeToGroup.get(node.id);
    return !grp || !collapsedGroups.has(grp.id);
  });

  // Add START and END anchors to Dagre
  const includeAnchors = rawNodes.length > 0;
  if (includeAnchors) {
    g.setNode('__start__', { width: 100, height: 36 });
    g.setNode('__end__', { width: 100, height: 36 });
  }

  // Add Group nodes to Dagre
  groups.forEach((group) => {
    const isCollapsed = collapsedGroups.has(group.id);
    if (isCollapsed) {
      g.setNode(`group_${group.id}`, { width: 280, height: 90 });
    }
  });

  // Add visible nodes to Dagre
  visibleNodes.forEach((node) => {
    const rt = runtimeStatusMap.get(node.id);
    const { width, height } = getNodeDimensions(node, isCompact, !!rt?.info);

    g.setNode(node.id, { width, height });

    // Compound graph grouping
    const grp = nodeToGroup.get(node.id);
    if (grp && !collapsedGroups.has(grp.id)) {
      if (!g.hasNode(`group_${grp.id}`)) {
        g.setNode(`group_${grp.id}`, {});
      }
      g.setParent(node.id, `group_${grp.id}`);
    }
  });

  // Connect START to root nodes with weight to align all independent branches at the initial rank
  if (includeAnchors) {
    rootNodeIds.forEach((rootId) => {
      const grp = nodeToGroup.get(rootId);
      const targetId = grp && collapsedGroups.has(grp.id) ? `group_${grp.id}` : rootId;
      if (g.hasNode(targetId)) {
        g.setEdge('__start__', targetId, { weight: 10, minlen: 1 });
      }
    });
  }

  // Add edges
  validEdges.forEach((edge) => {
    const srcGrp = nodeToGroup.get(edge.from);
    const tgtGrp = nodeToGroup.get(edge.to);

    const fromId = srcGrp && collapsedGroups.has(srcGrp.id) ? `group_${srcGrp.id}` : edge.from;
    const toId = tgtGrp && collapsedGroups.has(tgtGrp.id) ? `group_${tgtGrp.id}` : edge.to;

    if (fromId !== toId && g.hasNode(fromId) && g.hasNode(toId)) {
      g.setEdge(fromId, toId);
    }
  });

  // Connect leaf nodes to END
  if (includeAnchors) {
    leafNodeIds.forEach((leafId) => {
      const grp = nodeToGroup.get(leafId);
      const sourceId = grp && collapsedGroups.has(grp.id) ? `group_${grp.id}` : leafId;
      if (g.hasNode(sourceId)) {
        g.setEdge(sourceId, '__end__', { weight: 10, minlen: 1 });
      }
    });
  }

  // Execute Dagre layout
  dagre.layout(g);

  // Construct ReactFlow Nodes
  const flowNodes: Node[] = [];
  const isHoriz = direction !== 'TB';

  // START Node
  if (includeAnchors && g.hasNode('__start__')) {
    const startDag = g.node('__start__');
    const startWidth = 100;
    const startHeight = 36;
    flowNodes.push({
      id: '__start__',
      type: 'startNode',
      position: manualPositions.get('__start__') || {
        x: startDag.x - startDag.width / 2,
        y: startDag.y - startDag.height / 2,
      },
      width: startWidth,
      height: startHeight,
      sourcePosition: isHoriz ? Position.Right : Position.Bottom,
      targetPosition: isHoriz ? Position.Left : Position.Top,
      handles: [
        {
          id: 'start-source',
          type: 'source',
          position: isHoriz ? Position.Right : Position.Bottom,
          x: isHoriz ? startWidth : Math.round(startWidth / 2),
          y: isHoriz ? Math.round(startHeight / 2) : startHeight,
          width: 0,
          height: 0,
        },
      ],
      data: { label: 'START', direction },
      selectable: false,
    });
  }

  // END Node
  if (includeAnchors && g.hasNode('__end__')) {
    const endDag = g.node('__end__');
    const endWidth = 100;
    const endHeight = 36;
    flowNodes.push({
      id: '__end__',
      type: 'endNode',
      position: manualPositions.get('__end__') || {
        x: endDag.x - endDag.width / 2,
        y: endDag.y - endDag.height / 2,
      },
      width: endWidth,
      height: endHeight,
      sourcePosition: isHoriz ? Position.Right : Position.Bottom,
      targetPosition: isHoriz ? Position.Left : Position.Top,
      handles: [
        {
          id: 'end-target',
          type: 'target',
          position: isHoriz ? Position.Left : Position.Top,
          x: isHoriz ? 0 : Math.round(endWidth / 2),
          y: isHoriz ? Math.round(endHeight / 2) : 0,
          width: 0,
          height: 0,
        },
      ],
      data: { label: 'END', direction },
      selectable: false,
    });
  }

  // Collapsed Group Nodes
  groups.forEach((group) => {
    const isCollapsed = collapsedGroups.has(group.id);
    if (isCollapsed && g.hasNode(`group_${group.id}`)) {
      const grpDag = g.node(`group_${group.id}`);
      const grpWidth = 280;
      const grpHeight = 90;
      flowNodes.push({
        id: `group_${group.id}`,
        type: 'workflowGroup',
        position: manualPositions.get(`group_${group.id}`) || {
          x: grpDag.x - grpDag.width / 2,
          y: grpDag.y - grpDag.height / 2,
        },
        width: grpWidth,
        height: grpHeight,
        sourcePosition: isHoriz ? Position.Right : Position.Bottom,
        targetPosition: isHoriz ? Position.Left : Position.Top,
        handles: [
          {
            id: 'target',
            type: 'target',
            position: isHoriz ? Position.Left : Position.Top,
            x: isHoriz ? 0 : Math.round(grpWidth / 2),
            y: isHoriz ? Math.round(grpHeight / 2) : 0,
            width: 0,
            height: 0,
          },
          {
            id: 'source',
            type: 'source',
            position: isHoriz ? Position.Right : Position.Bottom,
            x: isHoriz ? grpWidth : Math.round(grpWidth / 2),
            y: isHoriz ? Math.round(grpHeight / 2) : grpHeight,
            width: 0,
            height: 0,
          },
        ],
        data: {
          groupId: group.id,
          title: group.title,
          nodeCount: group.nodeIds.length,
          isCollapsed: true,
          inputCount: 2,
          outputCount: 2,
          onToggleCollapse: onToggleGroupCollapse || (() => {}),
          color: group.color,
          direction,
        } as WorkflowGroupData,
      });
    }
  });

  // Regular Workflow Nodes
  visibleNodes.forEach((node) => {
    const dagNode = g.node(node.id);
    const rt = runtimeStatusMap.get(node.id);
    const { width, height } = getNodeDimensions(node, isCompact, !!rt?.info);
    const halfH = Math.round(height / 2);
    const halfW = Math.round(width / 2);

    const manualPos = manualPositions.get(node.id);
    const position = manualPos || {
      x: dagNode ? dagNode.x - dagNode.width / 2 : 0,
      y: dagNode ? dagNode.y - dagNode.height / 2 : 0,
    };

    const isMatch =
      searchQuery.trim().length > 0 &&
      (node.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (node.agent_id && node.agent_id.toLowerCase().includes(searchQuery.toLowerCase())) ||
        node.type.toLowerCase().includes(searchQuery.toLowerCase()));

    const isCurrentActiveMatch = activeMatchId === node.id;

    flowNodes.push({
      id: node.id,
      type: 'workflowNode',
      position,
      width,
      height,
      sourcePosition: isHoriz ? Position.Right : Position.Bottom,
      targetPosition: isHoriz ? Position.Left : Position.Top,
      handles: [
        {
          id: 'target',
          type: 'target',
          position: isHoriz ? Position.Left : Position.Top,
          x: isHoriz ? 0 : halfW,
          y: isHoriz ? halfH : 0,
          width: 0,
          height: 0,
        },
        {
          id: 'source',
          type: 'source',
          position: isHoriz ? Position.Right : Position.Bottom,
          x: isHoriz ? width : halfW,
          y: isHoriz ? halfH : height,
          width: 0,
          height: 0,
        },
      ],
      data: {
        workflowNode: node,
        nodeWidth: width,
        nodeHeight: height,
        direction,
        isCompact,
        runtimeStatus: rt?.status,
        runtimeInfo: rt?.info,
        isHighlighted: isMatch || isCurrentActiveMatch,
        onDelete: onDeleteNode,
        onAddSequentialNode: options.onAddSequentialNode,
        onAddParallelBranch: options.onAddParallelBranchOnNode,
        onConnectNode: options.onConnectNode,
        onDuplicateNode: options.onDuplicateNode,
        onContextMenu: options.onNodeContextMenu,
        isConnectMode: options.isConnectMode,
        isConnectSource: options.connectSourceId === node.id,
        isRoot: rootNodeIds.includes(node.id),
        isLeaf: leafNodeIds.includes(node.id),
        groupId: nodeToGroup.get(node.id)?.id,
      } as WorkflowNodeData,
    });
  });

  // Construct ReactFlow Edges
  const flowEdges: Edge[] = [];

  // Anchor Edges: START -> Roots
  if (includeAnchors) {
    rootNodeIds.forEach((rootId) => {
      const grp = nodeToGroup.get(rootId);
      const targetId = grp && collapsedGroups.has(grp.id) ? `group_${grp.id}` : rootId;
      const edgeId = `start->${targetId}`;

      flowEdges.push({
        id: edgeId,
        source: '__start__',
        target: targetId,
        sourceHandle: 'start-source',
        targetHandle: 'target',
        type: 'interactiveEdge',
        selected: options.selectedEdgeId === edgeId,
        animated: true,
        style: { stroke: '#10b981', strokeWidth: 2.5 },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: '#10b981',
          width: 18,
          height: 18,
        },
        data: {
          from: '__start__',
          to: targetId,
          isAnchor: true,
          anchorType: 'start',
          onInsertNode: options.onInsertNodeOnEdge,
          onSelectEdge: options.onSelectEdge,
          onOpenContextMenu: options.onOpenEdgeContextMenu,
        },
      });
    });
  }

  // Real Workflow Edges
  validEdges.forEach((edge, idx) => {
    const srcGrp = nodeToGroup.get(edge.from);
    const tgtGrp = nodeToGroup.get(edge.to);

    const sourceId = srcGrp && collapsedGroups.has(srcGrp.id) ? `group_${srcGrp.id}` : edge.from;
    const targetId = tgtGrp && collapsedGroups.has(tgtGrp.id) ? `group_${tgtGrp.id}` : edge.to;

    if (sourceId === targetId) return;

    // Parallel edge offset: when multiple edges target the same join node, offset their controls so they don't collide
    const convergingEdges = validEdges.filter((e) => e.to === edge.to);
    const convergingIdx = convergingEdges.indexOf(edge);
    const convergingTotal = convergingEdges.length;
    const labelOffsetY = convergingTotal > 1 ? (convergingIdx - (convergingTotal - 1) / 2) * 36 : 0;

    const edgeId = `edge-${edge.from}->${edge.to}-${idx}`;

    flowEdges.push({
      id: edgeId,
      source: sourceId,
      target: targetId,
      sourceHandle: 'source',
      targetHandle: 'target',
      type: 'interactiveEdge',
      selected: options.selectedEdgeId === edgeId,
      data: {
        from: edge.from,
        to: edge.to,
        condition: edge.condition,
        isAnchor: false,
        labelOffsetY,
        onDeleteEdge: options.onDeleteEdge,
        onInsertNode: options.onInsertNodeOnEdge,
        onAddParallelBranch: options.onAddParallelBranchOnEdge,
        onConfigureCondition: options.onConfigureCondition,
        onReconnectEdge: options.onReconnectEdge,
        onOpenContextMenu: options.onOpenEdgeContextMenu,
        onSelectEdge: options.onSelectEdge,
      },
      style: { stroke: '#3b82f6', strokeWidth: 2.5 },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#3b82f6',
        width: 18,
        height: 18,
      },
    });
  });

  // Anchor Edges: Leaves -> END
  if (includeAnchors) {
    leafNodeIds.forEach((leafId) => {
      const grp = nodeToGroup.get(leafId);
      const sourceId = grp && collapsedGroups.has(grp.id) ? `group_${grp.id}` : leafId;
      const edgeId = `${sourceId}->end`;

      flowEdges.push({
        id: edgeId,
        source: sourceId,
        target: '__end__',
        sourceHandle: 'source',
        targetHandle: 'end-target',
        type: 'interactiveEdge',
        selected: options.selectedEdgeId === edgeId,
        data: {
          from: sourceId,
          to: '__end__',
          isAnchor: true,
          anchorType: 'end',
          onInsertNode: options.onInsertNodeOnEdge,
          onAddParallelBranch: options.onAddParallelBranchOnEdge,
          onReconnectEdge: options.onReconnectEdge,
          onOpenContextMenu: options.onOpenEdgeContextMenu,
          onSelectEdge: options.onSelectEdge,
        },
        style: { stroke: '#818cf8', strokeWidth: 2.5 },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: '#818cf8',
          width: 18,
          height: 18,
        },
      });
    });
  }

  return {
    nodes: flowNodes,
    edges: flowEdges,
    hasCycles,
    stats: {
      nodeCount: rawNodes.length,
      edgeCount: validEdges.length,
      parallelBranchCount: rootNodeIds.length,
    },
  };
}

/**
 * Generator helper for testing graphs of arbitrary scale (3 to 200+ nodes).
 */
export function generateScaleTestWorkflow(
  nodeCount: number,
  topology: 'parallel' | 'dense' | 'fan_out_in' | 'cycle' = 'fan_out_in'
): WorkflowDefinition {
  const nodes: WorkflowNode[] = [];
  const edges: WorkflowEdge[] = [];

  for (let i = 0; i < nodeCount; i++) {
    nodes.push({
      id: `node_${i.toString().padStart(3, '0')}`,
      type: i % 8 === 0 ? 'human_approval' : 'agent',
      agent_id: `agent_service_${(i % 5) + 1}`,
      input_mappings: {
        payload: { path: `workflow_input.field_${i % 10}` },
        context: { literal: `sample_context_${i}` },
      },
      approval_options: i % 8 === 0 ? ['Approve', 'Reject'] : undefined,
    });
  }

  if (nodeCount <= 1) {
    return { id: `test_scale_${nodeCount}`, version: '1.0.0', nodes, edges };
  }

  if (topology === 'parallel') {
    // All nodes parallel roots converging into the final node
    const finalNode = nodes[nodeCount - 1].id;
    for (let i = 0; i < nodeCount - 1; i++) {
      edges.push({ from: nodes[i].id, to: finalNode });
    }
  } else if (topology === 'fan_out_in') {
    // Stage-based fan-out and fan-in (e.g. 5 stages of parallel branches)
    const stageSize = Math.max(2, Math.floor(Math.sqrt(nodeCount)));
    for (let i = 0; i < nodeCount - stageSize; i++) {
      const nextStageStart = (Math.floor(i / stageSize) + 1) * stageSize;
      const targetIdx = nextStageStart + (i % stageSize);
      if (targetIdx < nodeCount) {
        edges.push({ from: nodes[i].id, to: nodes[targetIdx].id });
      }
      // Add cross fan-in
      const crossIdx = nextStageStart + ((i + 1) % stageSize);
      if (crossIdx < nodeCount && crossIdx !== targetIdx) {
        edges.push({ from: nodes[i].id, to: nodes[crossIdx].id });
      }
    }
  } else if (topology === 'dense') {
    // Dense connections
    for (let i = 0; i < nodeCount - 1; i++) {
      edges.push({ from: nodes[i].id, to: nodes[i + 1].id });
      if (i + 2 < nodeCount) edges.push({ from: nodes[i].id, to: nodes[i + 2].id });
      if (i + 3 < nodeCount) edges.push({ from: nodes[i].id, to: nodes[i + 3].id });
    }
  } else if (topology === 'cycle') {
    for (let i = 0; i < nodeCount - 1; i++) {
      edges.push({ from: nodes[i].id, to: nodes[i + 1].id });
    }
    // Backward edge forming a loop
    edges.push({ from: nodes[nodeCount - 1].id, to: nodes[Math.floor(nodeCount / 2)].id });
  }

  return {
    id: `test_scale_${nodeCount}_${topology}`,
    version: '1.0.0',
    nodes,
    edges,
  };
}
