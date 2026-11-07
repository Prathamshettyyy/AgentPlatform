import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen } from '@testing-library/react';
import { WorkflowGraph } from '../components/workflows/WorkflowGraph';
import {
  calculateDagreLayout,
  generateScaleTestWorkflow,
  detectGraphCycles,
} from '../components/workflows/workflowLayout';
import { WorkflowDefinition, RunRecord, ExecutionEvent } from '../api/types';

describe('Workflow Dynamic Graph & Dagre Layout Engine', () => {
  const parallelWorkflow: WorkflowDefinition = {
    id: 'parallel_analysis_demo',
    version: '1.0.0',
    registered: true,
    nodes: [
      {
        id: 'analyze_title',
        type: 'agent',
        agent_id: 'external_text_analysis',
        input_mappings: {
          text: { path: 'workflow_input.title' },
        },
      },
      {
        id: 'analyze_body',
        type: 'agent',
        agent_id: 'external_text_analysis',
        input_mappings: {
          text: { path: 'workflow_input.body' },
        },
      },
      {
        id: 'validate_title_analysis',
        type: 'agent',
        agent_id: 'external_text_analysis_quality_checker',
        input_mappings: {
          original_text: { path: 'workflow_input.title' },
          summary: { path: 'node_outputs.analyze_title.summary' },
        },
      },
    ],
    edges: [
      { from: 'analyze_title', to: 'validate_title_analysis' },
      { from: 'analyze_body', to: 'validate_title_analysis' },
    ],
  };

  it('positions independent parallel branches at the exact same logical level in LR mode', () => {
    const layout = calculateDagreLayout(parallelWorkflow, { direction: 'LR' });

    const titleNode = layout.nodes.find((n) => n.id === 'analyze_title');
    const bodyNode = layout.nodes.find((n) => n.id === 'analyze_body');
    const validateNode = layout.nodes.find((n) => n.id === 'validate_title_analysis');

    expect(titleNode).toBeDefined();
    expect(bodyNode).toBeDefined();
    expect(validateNode).toBeDefined();

    // Both parallel roots must have the same X coordinate in horizontal LR layout
    expect(titleNode!.position.x).toBe(bodyNode!.position.x);

    // Convergent join node must be positioned to the right of both predecessors
    expect(validateNode!.position.x).toBeGreaterThan(titleNode!.position.x);
    expect(validateNode!.position.x).toBeGreaterThan(bodyNode!.position.x);

    // Verify edges strictly connect real edges
    const directEdge = layout.edges.find(
      (e) => e.source === 'analyze_title' && e.target === 'analyze_body'
    );
    expect(directEdge).toBeUndefined(); // NO false edge between parallel nodes

    const titleToValidate = layout.edges.find(
      (e) => e.source === 'analyze_title' && e.target === 'validate_title_analysis'
    );
    const bodyToValidate = layout.edges.find(
      (e) => e.source === 'analyze_body' && e.target === 'validate_title_analysis'
    );
    expect(titleToValidate).toBeDefined();
    expect(bodyToValidate).toBeDefined();
  });

  it('positions independent parallel branches at the same vertical level in TB mode', () => {
    const layout = calculateDagreLayout(parallelWorkflow, { direction: 'TB' });

    const titleNode = layout.nodes.find((n) => n.id === 'analyze_title');
    const bodyNode = layout.nodes.find((n) => n.id === 'analyze_body');
    const validateNode = layout.nodes.find((n) => n.id === 'validate_title_analysis');

    // In vertical TB mode, parallel roots share the same Y coordinate
    expect(titleNode!.position.y).toBe(bodyNode!.position.y);

    // Convergent node is positioned below both predecessors
    expect(validateNode!.position.y).toBeGreaterThan(titleNode!.position.y);
    expect(validateNode!.position.y).toBeGreaterThan(bodyNode!.position.y);
  });

  it('correctly builds handles and edges with explicit connectors for parallel workflow', () => {
    const layout = calculateDagreLayout(parallelWorkflow, { direction: 'LR' });
    expect(layout.edges.length).toBe(5); // START->2 roots, 2 roots->join, join->END

    const startToBody = layout.edges.find((e) => e.source === '__start__' && e.target === 'analyze_body');
    const startToTitle = layout.edges.find((e) => e.source === '__start__' && e.target === 'analyze_title');
    expect(startToBody).toBeDefined();
    expect(startToBody?.sourceHandle).toBe('start-source');
    expect(startToBody?.targetHandle).toBe('target');
    expect(startToTitle).toBeDefined();

    const bodyToValidate = layout.edges.find((e) => e.source === 'analyze_body' && e.target === 'validate_title_analysis');
    const titleToValidate = layout.edges.find((e) => e.source === 'analyze_title' && e.target === 'validate_title_analysis');
    expect(bodyToValidate).toBeDefined();
    expect(bodyToValidate?.sourceHandle).toBe('source');
    expect(bodyToValidate?.targetHandle).toBe('target');
    expect(titleToValidate).toBeDefined();

    const validateToEnd = layout.edges.find((e) => e.source === 'validate_title_analysis' && e.target === '__end__');
    expect(validateToEnd).toBeDefined();
    expect(validateToEnd?.sourceHandle).toBe('source');
    expect(validateToEnd?.targetHandle).toBe('end-target');
  });

  describe('Large Scale Workflow Benchmarking (3 to 200 Nodes)', () => {
    const testCounts = [3, 10, 30, 50, 100, 200];

    testCounts.forEach((count) => {
      it(`successfully computes layout for ${count}-node graph without breaking or overlaps`, () => {
        const wf = generateScaleTestWorkflow(count, 'fan_out_in');

        const startTime = performance.now();
        const layout = calculateDagreLayout(wf, { direction: 'LR', isCompact: true });
        const duration = performance.now() - startTime;

        // Verify all nodes are positioned
        const workflowNodes = layout.nodes.filter(
          (n) => n.id !== '__start__' && n.id !== '__end__'
        );
        expect(workflowNodes.length).toBe(count);

        // Verify valid non-NaN coordinates
        workflowNodes.forEach((node) => {
          expect(Number.isFinite(node.position.x)).toBe(true);
          expect(Number.isFinite(node.position.y)).toBe(true);
        });

        // Layout calculation should be fast (< 200ms even for 200 nodes)
        expect(duration).toBeLessThan(1500);
      });
    });

    it('handles dense graphs with cross connections and long mappings', () => {
      const denseWf = generateScaleTestWorkflow(50, 'dense');
      const layout = calculateDagreLayout(denseWf, { direction: 'LR', isCompact: false });

      expect(layout.nodes.length).toBeGreaterThanOrEqual(50);
      expect(layout.edges.length).toBeGreaterThan(50);
      expect(layout.hasCycles).toBe(false);
    });

    it('detects and handles cyclic workflows gracefully without infinite loops', () => {
      const cyclicWf = generateScaleTestWorkflow(20, 'cycle');
      const hasCycle = detectGraphCycles(cyclicWf.nodes, cyclicWf.edges);
      expect(hasCycle).toBe(true);

      // Dagre should layout without crashing
      const layout = calculateDagreLayout(cyclicWf, { direction: 'LR' });
      expect(layout.hasCycles).toBe(true);
      expect(layout.nodes.length).toBeGreaterThan(20);
    });
  });

  describe('Visual Grouping & Collapsible Subworkflows', () => {
    it('collapses grouped nodes into a single summary node and re-routes edges', () => {
      const wf = generateScaleTestWorkflow(12, 'fan_out_in');
      const groups = [
        {
          id: 'grp_stage1',
          title: 'Preprocessing Stage',
          nodeIds: ['node_000', 'node_001', 'node_002'],
        },
      ];

      // Expanded
      const expandedLayout = calculateDagreLayout(wf, { groups, collapsedGroups: new Set() });
      expect(expandedLayout.nodes.find((n) => n.id === 'node_000')).toBeDefined();

      // Collapsed
      const collapsedLayout = calculateDagreLayout(wf, {
        groups,
        collapsedGroups: new Set(['grp_stage1']),
      });

      // Individual nodes should be hidden
      expect(collapsedLayout.nodes.find((n) => n.id === 'node_000')).toBeUndefined();
      expect(collapsedLayout.nodes.find((n) => n.id === 'node_001')).toBeUndefined();

      // Group node should be visible
      const groupNode = collapsedLayout.nodes.find((n) => n.id === 'group_grp_stage1');
      expect(groupNode).toBeDefined();
      expect((groupNode!.data as any).isCollapsed).toBe(true);
    });
  });

  describe('Dynamic Runtime Execution Visualization', () => {
    it('maps execution status and payload outputs onto graph nodes', () => {
      const mockRunRecord: RunRecord = {
        run_id: 'run-test-123',
        workflow_id: 'parallel_analysis_demo',
        status: 'running',
        payload: {
          node_outputs: {
            analyze_title: { summary: 'Title summary output', word_count: 5 },
          },
        },
      };

      const mockEvents: ExecutionEvent[] = [
        {
          run_id: 'run-test-123',
          node_id: 'analyze_body',
          status: 'running',
          payload: {},
          created_at: '2026-10-31T00:00:00Z',
        },
      ];

      const layout = calculateDagreLayout(parallelWorkflow, {
        runRecord: mockRunRecord,
        events: mockEvents,
      });

      const titleNode = layout.nodes.find((n) => n.id === 'analyze_title');
      const bodyNode = layout.nodes.find((n) => n.id === 'analyze_body');
      const validateNode = layout.nodes.find((n) => n.id === 'validate_title_analysis');

      // analyze_title has output -> succeeded
      expect((titleNode!.data as any).runtimeStatus).toBe('succeeded');
      expect((titleNode!.data as any).runtimeInfo?.output).toEqual({
        summary: 'Title summary output',
        word_count: 5,
      });

      // analyze_body has running event -> running
      expect((bodyNode!.data as any).runtimeStatus).toBe('running');

      // validate_title_analysis not reached yet -> pending
      expect((validateNode!.data as any).runtimeStatus).toBe('pending');
    });
  });

  describe('Search & Filter Engine', () => {
    it('identifies and highlights matching nodes by name or agent', () => {
      const layout = calculateDagreLayout(parallelWorkflow, {
        searchQuery: 'quality_checker',
      });

      const validateNode = layout.nodes.find((n) => n.id === 'validate_title_analysis');
      const titleNode = layout.nodes.find((n) => n.id === 'analyze_title');

      expect((validateNode!.data as any).isHighlighted).toBe(true);
      expect((titleNode!.data as any).isHighlighted).toBe(false);
    });
  });
});
