import { WorkflowDefinition, WorkflowNode, WorkflowEdge } from '../../api/types';

export interface ValidationResult {
  isValid: boolean;
  errors: string[];
  warnings: string[];
  cycles: string[][];
  orphanedMappings: Array<{
    nodeId: string;
    field: string;
    referencedNodeId: string;
    suggestedFix: string;
  }>;
}

/**
 * Returns a set of all ancestor node IDs that can reach targetNodeId.
 */
export function getAncestors(workflow: WorkflowDefinition, targetNodeId: string): Set<string> {
  const ancestors = new Set<string>();
  const incomingMap = new Map<string, string[]>();

  (workflow.nodes || []).forEach((n) => incomingMap.set(n.id, []));
  (workflow.edges || []).forEach((e) => {
    if (incomingMap.has(e.to)) {
      incomingMap.get(e.to)!.push(e.from);
    }
  });

  const queue = [...(incomingMap.get(targetNodeId) || [])];
  while (queue.length > 0) {
    const current = queue.shift()!;
    if (!ancestors.has(current)) {
      ancestors.add(current);
      const parents = incomingMap.get(current) || [];
      for (const p of parents) {
        if (!ancestors.has(p)) {
          queue.push(p);
        }
      }
    }
  }

  return ancestors;
}

/**
 * Detects cycles in the graph given nodes and edges.
 * Returns an array of cycles (each cycle is an array of node IDs).
 */
export function findGraphCycles(nodes: WorkflowNode[], edges: WorkflowEdge[]): string[][] {
  const nodeIds = new Set(nodes.map((n) => n.id));
  const adj = new Map<string, string[]>();
  nodes.forEach((n) => adj.set(n.id, []));

  edges.forEach((e) => {
    if (nodeIds.has(e.from) && nodeIds.has(e.to)) {
      adj.get(e.from)?.push(e.to);
    }
  });

  const visited = new Set<string>();
  const inStack = new Set<string>();
  const path: string[] = [];
  const cycles: string[][] = [];

  const dfs = (curr: string) => {
    visited.add(curr);
    inStack.add(curr);
    path.push(curr);

    const neighbors = adj.get(curr) || [];
    for (const nxt of neighbors) {
      if (!visited.has(nxt)) {
        dfs(nxt);
      } else if (inStack.has(nxt)) {
        const cycleStartIndex = path.indexOf(nxt);
        if (cycleStartIndex !== -1) {
          cycles.push([...path.slice(cycleStartIndex), nxt]);
        }
      }
    }

    path.pop();
    inStack.delete(curr);
  };

  for (const node of nodes) {
    if (!visited.has(node.id)) {
      dfs(node.id);
    }
  }

  return cycles;
}

/**
 * Validates whether a connection can be created without breaking DAG integrity or creating duplicates.
 */
export function canConnect(
  workflow: WorkflowDefinition,
  sourceId: string,
  targetId: string,
  _condition?: any
): { valid: boolean; reason?: string } {
  if (sourceId === targetId) {
    return { valid: false, reason: 'Cannot connect a node to itself.' };
  }

  if (targetId === '__start__') {
    return { valid: false, reason: 'Cannot connect to the START node as a destination.' };
  }

  if (sourceId === '__end__') {
    return { valid: false, reason: 'Cannot connect from the END node as a source.' };
  }

  // Anchor connections (START -> X or X -> END)
  if (sourceId === '__start__' || targetId === '__end__') {
    return { valid: true };
  }

  const nodes = workflow.nodes || [];
  const edges = workflow.edges || [];

  const sourceNode = nodes.find((n) => n.id === sourceId);
  const targetNode = nodes.find((n) => n.id === targetId);

  if (!sourceNode) {
    return { valid: false, reason: `Source node '${sourceId}' does not exist.` };
  }
  if (!targetNode) {
    return { valid: false, reason: `Target node '${targetId}' does not exist.` };
  }

  // Duplicate edge check
  const duplicate = edges.some((e) => e.from === sourceId && e.to === targetId);
  if (duplicate) {
    return { valid: false, reason: `Connection from '${sourceId}' to '${targetId}' already exists.` };
  }

  // Cycle check: if targetId is already an ancestor of sourceId, adding sourceId -> targetId forms a cycle!
  const sourceAncestors = getAncestors(workflow, sourceId);
  if (sourceAncestors.has(targetId)) {
    return {
      valid: false,
      reason: `Cycle detected: '${targetId}' is already upstream of '${sourceId}'.`,
    };
  }

  return { valid: true };
}

/**
 * Adds an edge to the workflow definition immutably.
 */
export function addConnection(
  workflow: WorkflowDefinition,
  sourceId: string,
  targetId: string,
  condition?: any
): WorkflowDefinition {
  if (sourceId === '__start__' || targetId === '__end__') {
    // START and END anchor edges are computed visually from root/leaf status
    return workflow;
  }

  const check = canConnect(workflow, sourceId, targetId, condition);
  if (!check.valid) {
    throw new Error(check.reason || 'Invalid connection');
  }

  const currentEdges = workflow.edges || [];
  const newEdge: WorkflowEdge = {
    from: sourceId,
    to: targetId,
    condition: condition || null,
  };

  return {
    ...workflow,
    edges: [...currentEdges, newEdge],
  };
}

/**
 * Removes one or more edges from the workflow definition immutably.
 * Preserves all nodes and their configurations.
 */
export function removeConnections(
  workflow: WorkflowDefinition,
  edgesToRemove: Array<{ from: string; to: string }>
): WorkflowDefinition {
  const removeSet = new Set(edgesToRemove.map((e) => `${e.from}-->${e.to}`));
  const currentEdges = workflow.edges || [];

  const updatedEdges = currentEdges.filter((e) => !removeSet.has(`${e.from}-->${e.to}`));

  return {
    ...workflow,
    edges: updatedEdges,
  };
}

/**
 * Reconnects an edge by replacing old source/target with new source/target.
 * Handles both regular edges and visual anchor edges.
 */
export function reconnectConnection(
  workflow: WorkflowDefinition,
  oldEdge: { from: string; to: string },
  newSourceId: string,
  newTargetId: string
): WorkflowDefinition {
  // If the edge was an anchor edge from START or to END:
  // e.g. analyze_body -> END reconnected to validate_title_analysis
  if (oldEdge.to === '__end__') {
    if (newTargetId === '__end__' || newTargetId === oldEdge.from) return workflow;
    return addConnection(workflow, oldEdge.from, newTargetId);
  }

  if (oldEdge.from === '__start__') {
    if (newSourceId === '__start__' || newSourceId === oldEdge.to) return workflow;
    return addConnection(workflow, newSourceId, oldEdge.to);
  }

  // Regular edge replacement
  const check = canConnect(workflow, newSourceId, newTargetId);
  if (!check.valid) {
    throw new Error(check.reason || 'Invalid reconnection');
  }

  const currentEdges = workflow.edges || [];
  const updatedEdges = currentEdges.map((e) => {
    if (e.from === oldEdge.from && e.to === oldEdge.to) {
      return {
        ...e,
        from: newSourceId,
        to: newTargetId,
      };
    }
    return e;
  });

  return {
    ...workflow,
    edges: updatedEdges,
  };
}

/**
 * Inserts a sequential node between edge from -> to.
 * Edge A -> B becomes A -> New -> B.
 * Also handles anchor edges A -> END and START -> B.
 */
export function insertSequentialNodeOnEdge(
  workflow: WorkflowDefinition,
  edge: { from: string; to: string },
  newNode: WorkflowNode
): WorkflowDefinition {
  const currentNodes = workflow.nodes || [];
  const currentEdges = workflow.edges || [];

  // Ensure unique ID
  let targetId = newNode.id;
  let counter = 1;
  while (currentNodes.some((n) => n.id === targetId)) {
    targetId = `${newNode.id}_${counter++}`;
  }
  const finalizedNode: WorkflowNode = { ...newNode, id: targetId };

  const newNodes = [...currentNodes, finalizedNode];
  let newEdges = [...currentEdges];

  // Remove the old edge if it was a real edge
  newEdges = newEdges.filter((e) => !(e.from === edge.from && e.to === edge.to));

  // Connect upstream: edge.from -> finalizedNode.id (if not START)
  if (edge.from !== '__start__') {
    newEdges.push({
      from: edge.from,
      to: finalizedNode.id,
      condition: null,
    });
  }

  // Connect downstream: finalizedNode.id -> edge.to (if not END)
  if (edge.to !== '__end__') {
    newEdges.push({
      from: finalizedNode.id,
      to: edge.to,
      condition: null,
    });
  }

  return {
    ...workflow,
    nodes: newNodes,
    edges: newEdges,
  };
}

/**
 * Inserts a sequential node after an existing node.
 * If mode === 'insert_before_downstream' and sourceNode has 1 outgoing edge to B:
 * transforms source -> B into source -> newNode -> B.
 * Otherwise appends source -> newNode.
 */
export function addSequentialNodeAfter(
  workflow: WorkflowDefinition,
  sourceNodeId: string,
  newNode: WorkflowNode,
  mode: 'append' | 'insert_between' = 'append',
  downstreamNodeId?: string
): WorkflowDefinition {
  const currentNodes = workflow.nodes || [];
  const currentEdges = workflow.edges || [];

  let targetId = newNode.id;
  let counter = 1;
  while (currentNodes.some((n) => n.id === targetId)) {
    targetId = `${newNode.id}_${counter++}`;
  }
  const finalizedNode: WorkflowNode = { ...newNode, id: targetId };

  const newNodes = [...currentNodes, finalizedNode];
  let newEdges = [...currentEdges];

  if (mode === 'insert_between' && downstreamNodeId) {
    // Remove source -> downstreamNodeId
    newEdges = newEdges.filter((e) => !(e.from === sourceNodeId && e.to === downstreamNodeId));
    // Add source -> finalizedNode
    newEdges.push({ from: sourceNodeId, to: finalizedNode.id, condition: null });
    // Add finalizedNode -> downstreamNodeId
    newEdges.push({ from: finalizedNode.id, to: downstreamNodeId, condition: null });
  } else {
    // Append source -> finalizedNode
    newEdges.push({ from: sourceNodeId, to: finalizedNode.id, condition: null });
  }

  return {
    ...workflow,
    nodes: newNodes,
    edges: newEdges,
  };
}

/**
 * Adds a parallel branch sharing the upstream predecessor(s) of referenceNodeId (or START).
 * Optionally connects the new branch to a downstream join node.
 */
export function addParallelBranch(
  workflow: WorkflowDefinition,
  referenceNodeId: string,
  newNode: WorkflowNode,
  downstreamJoinNodeId?: string
): WorkflowDefinition {
  const currentNodes = workflow.nodes || [];
  const currentEdges = workflow.edges || [];

  let targetId = newNode.id;
  let counter = 1;
  while (currentNodes.some((n) => n.id === targetId)) {
    targetId = `${newNode.id}_${counter++}`;
  }
  const finalizedNode: WorkflowNode = { ...newNode, id: targetId };

  const newNodes = [...currentNodes, finalizedNode];
  const newEdges = [...currentEdges];

  // Find upstream nodes that point to referenceNodeId
  const upstreamNodes = currentEdges.filter((e) => e.to === referenceNodeId).map((e) => e.from);

  // If referenceNodeId has upstream nodes, connect them to finalizedNode as well!
  if (upstreamNodes.length > 0) {
    upstreamNodes.forEach((u) => {
      newEdges.push({ from: u, to: finalizedNode.id, condition: null });
    });
  }

  // If a downstream join node is specified, connect finalizedNode -> downstreamJoinNodeId
  if (downstreamJoinNodeId && downstreamJoinNodeId !== '__end__') {
    newEdges.push({ from: finalizedNode.id, to: downstreamJoinNodeId, condition: null });
  }

  return {
    ...workflow,
    nodes: newNodes,
    edges: newEdges,
  };
}

/**
 * Creates or connects multiple parallel branch nodes into a Join Node.
 * All branchIds -> joinNodeId.
 */
export function addJoinNode(
  workflow: WorkflowDefinition,
  branchIds: string[],
  joinNode: WorkflowNode,
  isExistingNode = false
): WorkflowDefinition {
  const currentNodes = workflow.nodes || [];
  const currentEdges = workflow.edges || [];

  let newNodes = currentNodes;
  let joinId = joinNode.id;

  if (!isExistingNode) {
    let counter = 1;
    while (newNodes.some((n) => n.id === joinId)) {
      joinId = `${joinNode.id}_${counter++}`;
    }
    const finalizedNode: WorkflowNode = { ...joinNode, id: joinId };
    newNodes = [...currentNodes, finalizedNode];
  }

  const newEdges = [...currentEdges];
  branchIds.forEach((bId) => {
    if (bId !== joinId && !newEdges.some((e) => e.from === bId && e.to === joinId)) {
      newEdges.push({ from: bId, to: joinId, condition: null });
    }
  });

  return {
    ...workflow,
    nodes: newNodes,
    edges: newEdges,
  };
}

/**
 * Duplicates a node and its incoming edges, creating an independent parallel copy.
 */
export function duplicateNode(
  workflow: WorkflowDefinition,
  nodeId: string
): { updatedWorkflow: WorkflowDefinition; newNode: WorkflowNode } {
  const currentNodes = workflow.nodes || [];
  const currentEdges = workflow.edges || [];

  const sourceNode = currentNodes.find((n) => n.id === nodeId);
  if (!sourceNode) {
    throw new Error(`Node '${nodeId}' not found.`);
  }

  let copyId = `${nodeId}_copy`;
  let counter = 1;
  while (currentNodes.some((n) => n.id === copyId)) {
    copyId = `${nodeId}_copy_${counter++}`;
  }

  const newNode: WorkflowNode = JSON.parse(JSON.stringify(sourceNode));
  newNode.id = copyId;

  const newNodes = [...currentNodes, newNode];
  const newEdges = [...currentEdges];

  // Replicate incoming edges
  currentEdges
    .filter((e) => e.to === nodeId)
    .forEach((e) => {
      newEdges.push({
        from: e.from,
        to: copyId,
        condition: e.condition ? JSON.parse(JSON.stringify(e.condition)) : null,
      });
    });

  return {
    updatedWorkflow: {
      ...workflow,
      nodes: newNodes,
      edges: newEdges,
    },
    newNode,
  };
}

/**
 * Updates or clears an edge condition.
 */
export function updateEdgeCondition(
  workflow: WorkflowDefinition,
  from: string,
  to: string,
  condition: any
): WorkflowDefinition {
  const currentEdges = workflow.edges || [];
  const updatedEdges = currentEdges.map((e) => {
    if (e.from === from && e.to === to) {
      return {
        ...e,
        condition: condition || null,
      };
    }
    return e;
  });

  return {
    ...workflow,
    edges: updatedEdges,
  };
}

/**
 * Comprehensive client-side validation of the workflow graph:
 * - Checks DAG cycles
 * - Checks missing nodes in edges
 * - Checks orphaned/unreachable input_mappings
 * - Checks fan-in ambiguity
 */
export function validateWorkflowGraph(workflow: WorkflowDefinition): ValidationResult {
  const nodes = workflow.nodes || [];
  const edges = workflow.edges || [];
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  const errors: string[] = [];
  const warnings: string[] = [];
  const orphanedMappings: ValidationResult['orphanedMappings'] = [];

  // 1. Cycle detection
  const cycles = findGraphCycles(nodes, edges);
  if (cycles.length > 0) {
    cycles.forEach((c) => {
      errors.push(`Cycle detected: ${c.join(' → ')}`);
    });
  }

  // 2. Check edges referencing missing nodes
  edges.forEach((e) => {
    if (!nodeMap.has(e.from)) {
      errors.push(`Edge references non-existent source node '${e.from}'`);
    }
    if (!nodeMap.has(e.to)) {
      errors.push(`Edge references non-existent target node '${e.to}'`);
    }
  });

  // 3. Check input mappings for unreachable ancestors
  nodes.forEach((node) => {
    const ancestors = getAncestors(workflow, node.id);
    const mappings = node.input_mappings || {};

    Object.entries(mappings).forEach(([field, val]) => {
      const path = val?.path || '';
      if (path.startsWith('node_outputs.')) {
        const parts = path.split('.');
        const refNodeId = parts[1];
        if (refNodeId && !ancestors.has(refNodeId)) {
          const suggestedFix = `workflow_input.${parts.slice(2).join('.') || field}`;
          orphanedMappings.push({
            nodeId: node.id,
            field,
            referencedNodeId: refNodeId,
            suggestedFix,
          });
          errors.push(
            `Node '${node.id}' maps field '${field}' to 'node_outputs.${refNodeId}', but '${refNodeId}' is not an upstream ancestor.`
          );
        }
      }
    });
  });

  // 4. Check for ambiguous fan-in (conditional / human approval + unconditional edges into same node)
  nodes.forEach((node) => {
    const incoming = edges.filter((e) => e.to === node.id);
    if (incoming.length > 1) {
      const hasConditional = incoming.some((e) => {
        const src = nodes.find((n) => n.id === e.from);
        return Boolean(e.condition) || src?.type === 'human_approval';
      });
      const hasUnconditional = incoming.some((e) => {
        const src = nodes.find((n) => n.id === e.from);
        return !e.condition && src?.type !== 'human_approval';
      });
      if (hasConditional && hasUnconditional) {
        errors.push(
          `Ambiguous incoming edges for node '${node.id}': cannot mix conditional/approval branches with unconditional branches to the same join node. Route the approval after the join node or gate both parallel branches.`
        );
      }
    }
  });

  return {
    isValid: errors.length === 0,
    errors,
    warnings,
    cycles,
    orphanedMappings,
  };
}

/**
 * Automatically rewrites any orphaned input_mappings (from edges that were removed)
 * to fallback to workflow_input.<field> so the workflow remains valid and executable.
 */
export function autoFixOrphanedMappings(workflow: WorkflowDefinition): WorkflowDefinition {
  const validation = validateWorkflowGraph(workflow);
  if (validation.orphanedMappings.length === 0) return workflow;

  const fixMap = new Map<string, Map<string, string>>();
  validation.orphanedMappings.forEach((m) => {
    if (!fixMap.has(m.nodeId)) fixMap.set(m.nodeId, new Map());
    fixMap.get(m.nodeId)!.set(m.field, m.suggestedFix);
  });

  const updatedNodes = (workflow.nodes || []).map((node) => {
    const fixes = fixMap.get(node.id);
    if (!fixes) return node;

    const newMappings = { ...(node.input_mappings || {}) };
    fixes.forEach((suggestedPath, field) => {
      newMappings[field] = { path: suggestedPath };
    });

    return {
      ...node,
      input_mappings: newMappings,
    };
  });

  return {
    ...workflow,
    nodes: updatedNodes,
  };
}

