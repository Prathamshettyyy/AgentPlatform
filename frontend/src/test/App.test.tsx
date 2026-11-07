import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { StatusBadge } from '../components/common/StatusBadge';
import { ConfirmModal } from '../components/common/ConfirmModal';
import { EmptyState } from '../components/common/EmptyState';
import { ApiError } from '../api/client';

describe('Common UI Components', () => {
  it('renders StatusBadge with appropriate text and styling', () => {
    const { rerender } = render(<StatusBadge status="running" />);
    expect(screen.getByText('running')).toBeInTheDocument();

    rerender(<StatusBadge status="waiting_for_approval" />);
    expect(screen.getByText('Waiting for Approval')).toBeInTheDocument();

    rerender(<StatusBadge status="succeeded" />);
    expect(screen.getByText('succeeded')).toBeInTheDocument();

    rerender(<StatusBadge status="draft" />);
    expect(screen.getByText('Draft')).toBeInTheDocument();
  });

  it('renders ConfirmModal and calls callbacks correctly', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();

    render(
      <ConfirmModal
        isOpen={true}
        title="Delete Test Workflow"
        message="Are you sure you want to permanently delete this workflow?"
        confirmText="Permanently Delete"
        previewItems={[
          { label: 'Runs to delete', value: '3 runs', isDestructive: true },
          { label: 'Referenced Agents', value: 'untouched', isDestructive: false },
        ]}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );

    expect(screen.getByText('Delete Test Workflow')).toBeInTheDocument();
    expect(screen.getByText('Runs to delete')).toBeInTheDocument();
    expect(screen.getByText('3 runs')).toBeInTheDocument();

    // Click cancel
    fireEvent.click(screen.getByText('Cancel'));
    expect(onCancel).toHaveBeenCalledTimes(1);

    // Click confirm
    fireEvent.click(screen.getByText('Permanently Delete'));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('renders EmptyState with action button', () => {
    const onAction = vi.fn();
    render(
      <EmptyState
        title="No items found"
        description="Try creating one now"
        actionText="Create Item"
        onAction={onAction}
      />
    );

    expect(screen.getByText('No items found')).toBeInTheDocument();
    expect(screen.getByText('Try creating one now')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Create Item'));
    expect(onAction).toHaveBeenCalledTimes(1);
  });

  it('constructs ApiError with proper status and message', () => {
    const error = new ApiError(401, 'Unauthorized request');
    expect(error.status).toBe(401);
    expect(error.message).toBe('Unauthorized request');
    expect(error.name).toBe('ApiError');
  });
});

