import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { WorkflowRunModal } from '../components/workflows/WorkflowRunModal';
import { api } from '../api/client';
import { BrowserRouter } from 'react-router-dom';

vi.mock('../api/client', () => ({
  api: {
    startRun: vi.fn(),
  },
}));

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

describe('WorkflowRunModal', () => {
  const sampleWorkflow = {
    id: 'test_flow',
    version: '1.0.0',
    nodes: [],
    edges: [],
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders modal without any Direct or Temporal execution backend selector', () => {
    render(
      <BrowserRouter>
        <WorkflowRunModal
          isOpen={true}
          workflow={sampleWorkflow}
          onClose={vi.fn()}
        />
      </BrowserRouter>
    );

    expect(screen.getByText('Run Workflow')).toBeInTheDocument();
    expect(screen.getByText('test_flow (v1.0.0)')).toBeInTheDocument();
    expect(screen.getByText('Workflow Input (JSON object)')).toBeInTheDocument();
    expect(screen.getByText(/Allow partial execution/i)).toBeInTheDocument();

    // Verify there is NO execution engine / backend selection UI
    expect(screen.queryByText(/Execution Engine/i)).toBeNull();
    expect(screen.queryByText(/Temporal Orchestration/i)).toBeNull();
    expect(screen.queryByText(/Direct \(LangGraph\)/i)).toBeNull();
  });

  it('submits only workflow_id, inputs, and allow_partial to api.startRun', async () => {
    (api.startRun as any).mockResolvedValueOnce({ run_id: 'run-123' });

    render(
      <BrowserRouter>
        <WorkflowRunModal
          isOpen={true}
          workflow={sampleWorkflow}
          onClose={vi.fn()}
        />
      </BrowserRouter>
    );

    const submitBtn = screen.getByRole('button', { name: /Start Execution/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(api.startRun).toHaveBeenCalledTimes(1);
      // Signature: (workflowId, inputs, allowPartial)
      expect(api.startRun).toHaveBeenCalledWith(
        'test_flow',
        { text: 'Analyze this sample input text.' },
        true
      );
      expect(mockNavigate).toHaveBeenCalledWith('/runs/run-123');
    });
  });
});

