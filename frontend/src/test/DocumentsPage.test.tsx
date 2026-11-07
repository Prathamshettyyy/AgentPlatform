import { describe, it, expect, vi } from 'vitest';
import React from 'react';
import { render, screen } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DocumentsPage } from '../pages/DocumentsPage';
import { DocumentUploader } from '../components/documents/DocumentUploader';

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>{children}</BrowserRouter>
    </QueryClientProvider>
  );
};

describe('Document Intelligence Frontend Components', () => {
  it('renders DocumentUploader with drag and drop zone and information', () => {
    render(<DocumentUploader />, { wrapper: createWrapper() });

    expect(screen.getByText('PDF Ingestion Pipeline')).toBeInTheDocument();
    expect(
      screen.getByText('Click to select or drag and drop multiple PDF documents')
    ).toBeInTheDocument();
  });

  it('renders DocumentsPage header and KPI summary cards', () => {
    render(<DocumentsPage />, { wrapper: createWrapper() });

    expect(
      screen.getByText('Geotechnical Documents & PDF Pipeline')
    ).toBeInTheDocument();
    expect(screen.getByText('Total Documents')).toBeInTheDocument();
    expect(screen.getByText('Total Pages Processed')).toBeInTheDocument();
    expect(screen.getByText('Scanned / Hybrid Ratio')).toBeInTheDocument();
    expect(screen.getByText('SHA-256 Provenance')).toBeInTheDocument();
  });
});

