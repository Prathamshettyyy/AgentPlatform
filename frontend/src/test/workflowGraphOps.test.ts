import { describe, it, expect } from 'vitest';
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
  getAncestors,
  validateWorkflowGraph,
  autoFixOrphanedMappings,
} from '../components/workflows/workflowGraphOps';
import { WorkflowDefinition, WorkflowNode } from '../api/types';

const sampleWorkflow: WorkflowDefinition = {
  id: 'parallel_analysis_demo',
  version: '1.0.5',
  nodes: [
    {
      id: 'analyze_title',
      type: 'agent',
      agent_id: 'external_text_analysis',
      status: 'available',
      input_mappings: { text: { path: 'workflow_input.title' } },
    },
    {
      id: 'analyze_body',
      type: 'agent',
      agent_id: 'external_text_analysis',
      status: 'available',
      input_mappings: { text: { path: 'workflow_input.body' } },
    },
    {
      id: 'validate_title_analysis',
      type: 'agent',
      agent_id: 'external_text_analysis_quality_checker',
      status: 'available',
      input_mappings: {
        summary: { path: 'node_outputs.analyze_title.summary' },
      },
    },
  ],
  edges: [
    { from: 'analyze_title', to: 'validate_title_analysis', condition: null },
    { from: 'analyze_body', to: 'validate_title_analysis', condition: null },
  ],
};

describe('workflowGraphOps', () => {
  it('correctly calculates node ancestors', () => {
    const ancestors = getAncestors(sampleWorkflow, 'validate_title_analysis');
    expect(ancestors.has('analyze_title')).toBe(true);
    expect(ancestors.has('analyze_body')).toBe(true);
    expect(ancestors.has('validate_title_analysis')).toBe(false);
  });

  it('validates connections and rejects self-loops and duplicate edges', () => {
    expect(canConnect(sampleWorkflow, 'analyze_title', 'analyze_title').valid).toBe(false);
    expect(canConnect(sampleWorkflow, 'analyze_title', 'validate_title_analysis').valid).toBe(false);
    expect(canConnect(sampleWorkflow, 'validate_title_analysis', 'analyze_title').valid).toBe(false); // cycle!
  });

  it('allows valid new connections', () => {
    const wf: WorkflowDefinition = {
      id: 'test',
      version: '1.0.0',
      nodes: [
        { id: 'a', type: 'agent' },
        { id: 'b', type: 'agent' },
      ],
      edges: [],
    };
    expect(canConnect(wf, 'a', 'b').valid).toBe(true);
    const updated = addConnection(wf, 'a', 'b');
    expect(updated.edges).toHaveLength(1);
    expect(updated.edges[0]).toEqual({ from: 'a', to: 'b', condition: null });
  });

  it('removes connection without deleting either connected node', () => {
    const updated = removeConnections(sampleWorkflow, [
      { from: 'analyze_body', to: 'validate_title_analysis' },
    ]);
    expect(updated.edges).toHaveLength(1);
    expect(updated.edges[0].from).toBe('analyze_title');
    // Both nodes still exist
    expect(updated.nodes?.find((n) => n.id === 'analyze_body')).toBeDefined();
    expect(updated.nodes?.find((n) => n.id === 'validate_title_analysis')).toBeDefined();
  });

  it('inserts a sequential node on an edge A -> B resulting in A -> New -> B', () => {
    const newNode: WorkflowNode = {
      id: 'pre_filter',
      type: 'agent',
      agent_id: 'external_filter',
    };
    const updated = insertSequentialNodeOnEdge(
      sampleWorkflow,
      { from: 'analyze_title', to: 'validate_title_analysis' },
      newNode
    );

    expect(updated.nodes?.find((n) => n.id === 'pre_filter')).toBeDefined();
    // Old edge should be gone
    expect(
      updated.edges.some((e) => e.from === 'analyze_title' && e.to === 'validate_title_analysis')
    ).toBe(false);
    // New edges: analyze_title -> pre_filter, pre_filter -> validate_title_analysis
    expect(
      updated.edges.some((e) => e.from === 'analyze_title' && e.to === 'pre_filter')
    ).toBe(true);
    expect(
      updated.edges.some((e) => e.from === 'pre_filter' && e.to === 'validate_title_analysis')
    ).toBe(true);
    // analyze_body -> validate_title_analysis remains intact
    expect(
      updated.edges.some((e) => e.from === 'analyze_body' && e.to === 'validate_title_analysis')
    ).toBe(true);
  });

  it('adds a parallel branch sharing upstream predecessor and optionally connecting to join node', () => {
    const branch3: WorkflowNode = {
      id: 'analyze_keywords',
      type: 'agent',
      agent_id: 'external_text_analysis',
    };

    const updated = addParallelBranch(
      sampleWorkflow,
      'analyze_body',
      branch3,
      'validate_title_analysis'
    );

    expect(updated.nodes?.find((n) => n.id === 'analyze_keywords')).toBeDefined();
    // Sibling branch connected to validate_title_analysis
    expect(
      updated.edges.some((e) => e.from === 'analyze_keywords' && e.to === 'validate_title_analysis')
    ).toBe(true);
  });

  it('adds a join node fanning in from multiple branches', () => {
    const joinNode: WorkflowNode = {
      id: 'final_synthesizer',
      type: 'agent',
      agent_id: 'synthesizer_agent',
    };

    const updated = addJoinNode(
      sampleWorkflow,
      ['analyze_title', 'analyze_body'],
      joinNode
    );

    expect(updated.nodes?.find((n) => n.id === 'final_synthesizer')).toBeDefined();
    expect(
      updated.edges.some((e) => e.from === 'analyze_title' && e.to === 'final_synthesizer')
    ).toBe(true);
    expect(
      updated.edges.some((e) => e.from === 'analyze_body' && e.to === 'final_synthesizer')
    ).toBe(true);
  });

  it('duplicates a node and copies incoming connections', () => {
    const { updatedWorkflow, newNode } = duplicateNode(sampleWorkflow, 'validate_title_analysis');
    expect(newNode.id).toBe('validate_title_analysis_copy');
    expect(updatedWorkflow.nodes?.some((n) => n.id === 'validate_title_analysis_copy')).toBe(true);
    // validate_title_analysis had 2 incoming edges (analyze_title, analyze_body)
    expect(
      updatedWorkflow.edges.some((e) => e.from === 'analyze_title' && e.to === 'validate_title_analysis_copy')
    ).toBe(true);
    expect(
      updatedWorkflow.edges.some((e) => e.from === 'analyze_body' && e.to === 'validate_title_analysis_copy')
    ).toBe(true);
  });

  it('detects orphaned input mappings when an edge is deleted and can auto-fix them', () => {
    // Delete edge analyze_title -> validate_title_analysis
    const broken = removeConnections(sampleWorkflow, [
      { from: 'analyze_title', to: 'validate_title_analysis' },
    ]);
    const validation = validateWorkflowGraph(broken);
    expect(validation.isValid).toBe(false);
    expect(validation.orphanedMappings.length).toBeGreaterThan(0);
    expect(validation.orphanedMappings[0].field).toBe('summary');

    // Auto-fix
    const fixed = autoFixOrphanedMappings(broken);
    const fixedNode = fixed.nodes?.find((n) => n.id === 'validate_title_analysis');
    expect(fixedNode?.input_mappings?.summary?.path).toBe('workflow_input.summary');
    expect(validateWorkflowGraph(fixed).isValid).toBe(true);
  });
});
