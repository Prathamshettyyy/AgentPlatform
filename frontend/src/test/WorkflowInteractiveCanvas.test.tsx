import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { WorkflowGraphToolbar } from '../components/workflows/WorkflowGraphToolbar';
import { WorkflowGraphInspector } from '../components/workflows/WorkflowGraphInspector';
import {
  InsertSequentialModal,
  AddParallelBranchModal,
  AddJoinNodeModal,
  ConfigureConditionModal,
} from '../components/workflows/WorkflowCanvasModals';
import { WorkflowDefinition, WorkflowNode } from '../api/types';

vi.mock('../api/client', () => ({
  api: {
    listAgents: vi.fn().mockResolvedValue([
      { id: 'external_text_analysis', name: 'External Text Analysis' },
      { id: 'external_text_analysis_quality_checker', name: 'Quality Checker' },
    ]),
  },
}));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

const sampleParallelWorkflow: WorkflowDefinition = {
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

describe('Workflow Interactive Toolbar & Modals', () => {
  beforeEach(() => {
    queryClient.clear();
  });

  it('renders interactive toolbar with Undo, Redo, Connect Mode, and Branch controls', () => {
    const onUndo = vi.fn();
    const onRedo = vi.fn();
    const onToggleConnectMode = vi.fn();
    const onAddParallelBranch = vi.fn();
    const onAddJoinNode = vi.fn();
    const onAutoFixMappings = vi.fn();

    render(
      <WorkflowGraphToolbar
        direction="LR"
        onToggleDirection={vi.fn()}
        isCompact={false}
        onToggleCompact={vi.fn()}
        onAutoArrange={vi.fn()}
        onZoomIn={vi.fn()}
        onZoomOut={vi.fn()}
        onFitView={vi.fn()}
        isFullscreen={false}
        onToggleFullscreen={vi.fn()}
        searchQuery=""
        onSearchChange={vi.fn()}
        matchesCount={0}
        activeMatchIndex={0}
        onNextMatch={vi.fn()}
        onPrevMatch={vi.fn()}
        selectedNodesCount={0}
        canUndo={true}
        canRedo={true}
        onUndo={onUndo}
        onRedo={onRedo}
        isConnectMode={false}
        onToggleConnectMode={onToggleConnectMode}
        onAddParallelBranch={onAddParallelBranch}
        onAddJoinNode={onAddJoinNode}
        hasOrphanedMappings={true}
        onAutoFixMappings={onAutoFixMappings}
      />
    );

    // Undo & Redo buttons
    fireEvent.click(screen.getByTitle('Undo (Ctrl+Z)'));
    expect(onUndo).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTitle('Redo (Ctrl+Y)'));
    expect(onRedo).toHaveBeenCalledTimes(1);

    // Connect mode button
    fireEvent.click(screen.getByText('Connect'));
    expect(onToggleConnectMode).toHaveBeenCalledTimes(1);

    // Parallel Branch button
    fireEvent.click(screen.getByText('Parallel Branch'));
    expect(onAddParallelBranch).toHaveBeenCalledTimes(1);

    // Join Barrier button
    fireEvent.click(screen.getByText('Join Barrier'));
    expect(onAddJoinNode).toHaveBeenCalledTimes(1);

    // Auto-fix mappings button
    fireEvent.click(screen.getByText('Auto-Fix Mappings'));
    expect(onAutoFixMappings).toHaveBeenCalledTimes(1);
  });

  it('renders and submits InsertSequentialModal', async () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();

    render(
      <QueryClientProvider client={queryClient}>
        <InsertSequentialModal
          isOpen={true}
          edge={{ from: 'analyze_title', to: 'validate_title_analysis' }}
          workflow={sampleParallelWorkflow}
          onClose={onClose}
          onSubmit={onSubmit}
        />
      </QueryClientProvider>
    );

    expect(screen.getByText('Insert Sequential Node')).toBeInTheDocument();
    expect(screen.getByText(/analyze_title/i)).toBeInTheDocument();
    expect(screen.getByText(/validate_title_analysis/i)).toBeInTheDocument();

    const input = screen.getByPlaceholderText('e.g. text_analyzer_v2');
    fireEvent.change(input, { target: { value: 'custom_step_node' } });

    const submitBtn = screen.getByTestId('confirm-insert-sequential');
    fireEvent.click(submitBtn);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const createdNode = onSubmit.mock.calls[0][0] as WorkflowNode;
    expect(createdNode.id).toBe('custom_step_node');
    expect(createdNode.type).toBe('agent');
  });

  it('renders and submits AddParallelBranchModal', async () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();

    render(
      <QueryClientProvider client={queryClient}>
        <AddParallelBranchModal
          isOpen={true}
          referenceNodeId="analyze_body"
          workflow={sampleParallelWorkflow}
          onClose={onClose}
          onSubmit={onSubmit}
        />
      </QueryClientProvider>
    );

    expect(screen.getByText('Add Parallel Branch')).toBeInTheDocument();
    expect(screen.getByText('analyze_body')).toBeInTheDocument();

    const input = screen.getByPlaceholderText('e.g. analyze_sentiment');
    fireEvent.change(input, { target: { value: 'analyze_sentiment' } });

    const submitBtn = screen.getByTestId('confirm-add-parallel-branch');
    fireEvent.click(submitBtn);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const createdNode = onSubmit.mock.calls[0][0] as WorkflowNode;
    expect(createdNode.id).toBe('analyze_sentiment');
    expect(createdNode.type).toBe('agent');
  });

  it('renders and submits AddJoinNodeModal', async () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();

    render(
      <QueryClientProvider client={queryClient}>
        <AddJoinNodeModal
          isOpen={true}
          initialBranches={['analyze_title', 'analyze_body']}
          workflow={sampleParallelWorkflow}
          onClose={onClose}
          onSubmit={onSubmit}
        />
      </QueryClientProvider>
    );

    expect(screen.getByText('Add Fan-In Join Node (Barrier)')).toBeInTheDocument();
    expect(screen.getByText(/Incoming Parallel Branches \(2\)/i)).toBeInTheDocument();

    const submitBtn = screen.getByTestId('confirm-add-join-node');
    fireEvent.click(submitBtn);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const branchIds = onSubmit.mock.calls[0][0] as string[];
    expect(branchIds).toEqual(['analyze_title', 'analyze_body']);
  });

  it('renders and submits ConfigureConditionModal', () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();

    render(
      <ConfigureConditionModal
        isOpen={true}
        edge={{ from: 'analyze_title', to: 'validate_title_analysis', condition: null }}
        onClose={onClose}
        onSubmit={onSubmit}
      />
    );

    expect(screen.getByText('Configure Edge Condition')).toBeInTheDocument();

    const submitBtn = screen.getByTestId('confirm-configure-condition');
    fireEvent.click(submitBtn);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith('analyze_title', 'validate_title_analysis', null);
  });

  it('renders WorkflowGraphInspector with node actions and allows editing input mappings', () => {
    const onUpdateNode = vi.fn();
    const onAddSeq = vi.fn();
    const onAddParallel = vi.fn();
    const onDuplicate = vi.fn();
    const onDelete = vi.fn();

    render(
      <WorkflowGraphInspector
        node={sampleParallelWorkflow.nodes[2]}
        edges={sampleParallelWorkflow.edges}
        onClose={vi.fn()}
        onSelectNode={vi.fn()}
        onAddSequentialNode={onAddSeq}
        onAddParallelBranch={onAddParallel}
        onDuplicateNode={onDuplicate}
        onDeleteNode={onDelete}
        onUpdateNode={onUpdateNode}
      />
    );

    expect(screen.getAllByText('validate_title_analysis')[0]).toBeInTheDocument();
    expect(screen.getByText('external_text_analysis_quality_checker')).toBeInTheDocument();
    expect(screen.getByText(/Incoming Predecessors \(2\)/i)).toBeInTheDocument();

    // Quick action buttons
    fireEvent.click(screen.getByTitle('Add Sequential Node after this node'));
    expect(onAddSeq).toHaveBeenCalledWith('validate_title_analysis');

    fireEvent.click(screen.getByTitle('Add Parallel Branch alongside this node'));
    expect(onAddParallel).toHaveBeenCalledWith('validate_title_analysis');

    fireEvent.click(screen.getByTitle('Duplicate node (runs in parallel)'));
    expect(onDuplicate).toHaveBeenCalledWith('validate_title_analysis');

    // Edit JSON mappings
    fireEvent.click(screen.getByText('Edit JSON'));
    expect(screen.getByText('Save Mappings')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Save Mappings'));
    expect(onUpdateNode).toHaveBeenCalledTimes(1);
  });

  it('renders and submits InsertSequentialModal for Human Approval with approval_payload_path', async () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();

    render(
      <QueryClientProvider client={queryClient}>
        <InsertSequentialModal
          isOpen={true}
          edge={{ from: 'analyze_title', to: 'validate_title_analysis' }}
          workflow={sampleParallelWorkflow}
          onClose={onClose}
          onSubmit={onSubmit}
        />
      </QueryClientProvider>
    );

    // Switch to Human Approval
    fireEvent.click(screen.getByText('Human Approval'));

    expect(screen.getByText('Approval Payload Path')).toBeInTheDocument();
    expect(screen.getByText('Approval Options')).toBeInTheDocument();

    const submitBtn = screen.getByTestId('confirm-insert-sequential');
    fireEvent.click(submitBtn);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const createdNode = onSubmit.mock.calls[0][0] as WorkflowNode;
    expect(createdNode.type).toBe('human_approval');
    expect(createdNode.approval_payload_path).toBe('node_outputs.analyze_title');
    expect(createdNode.approval_options).toEqual(['approve', 'reject']);
    expect(createdNode.execute_in).toBe('workflow');
  });

  it('renders and submits InsertSequentialModal for Trigger / Webhook', () => {
    const onSubmit = vi.fn();
    const onClose = vi.fn();

    render(
      <QueryClientProvider client={queryClient}>
        <InsertSequentialModal
          isOpen={true}
          edge={{ from: '__start__', to: 'analyze_title' }}
          workflow={sampleParallelWorkflow}
          onClose={onClose}
          onSubmit={onSubmit}
        />
      </QueryClientProvider>
    );

    // Switch to Trigger / Webhook
    fireEvent.click(screen.getByText('Trigger / Webhook'));

    expect(screen.getByText('Incoming Webhook')).toBeInTheDocument();
    expect(screen.getByText('Schedule (Cron)')).toBeInTheDocument();

    const submitBtn = screen.getByTestId('confirm-insert-sequential');
    fireEvent.click(submitBtn);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const createdNode = onSubmit.mock.calls[0][0] as WorkflowNode;
    expect(createdNode.type).toBe('trigger');
    expect(createdNode.trigger_type).toBe('webhook');
  });

  it('allows inserting a node before a root node from WorkflowGraphInspector', () => {
    const onAddBefore = vi.fn();

    render(
      <WorkflowGraphInspector
        node={sampleParallelWorkflow.nodes[0]} // analyze_title is a root node
        edges={sampleParallelWorkflow.edges}
        onClose={vi.fn()}
        onSelectNode={vi.fn()}
        onAddSequentialNodeBefore={onAddBefore}
      />
    );

    expect(screen.getByText(/Root node \(Receives workflow input\)/i)).toBeInTheDocument();
    const insertBeforeBtn = screen.getByText('Insert Before');
    expect(insertBeforeBtn).toBeInTheDocument();

    fireEvent.click(insertBeforeBtn);
    expect(onAddBefore).toHaveBeenCalledWith('analyze_title');
  });
});
