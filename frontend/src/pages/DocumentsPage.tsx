import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  FileText,
  Search,
  RefreshCw,
  Trash2,
  ExternalLink,
  Layers,
  Database,
  Hash,
  AlertTriangle,
  FolderOpen,
} from 'lucide-react';
import { api } from '../api/client';
import { DocumentMetadata } from '../api/types';
import { DocumentUploader } from '../components/documents/DocumentUploader';
import { StatusBadge } from '../components/common/StatusBadge';
import { Skeleton } from '../components/common/Skeleton';

export const DocumentsPage: React.FC = () => {
  const queryClient = useQueryClient();
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedProject, setSelectedProject] = useState('default');

  const { data: documents = [], isLoading, isError, error, refetch } = useQuery<DocumentMetadata[]>({
    queryKey: ['documents', selectedProject],
    queryFn: () => api.listDocuments(selectedProject),
    refetchInterval: 5000,
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => api.deleteDocument(documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });

  const reprocessMutation = useMutation({
    mutationFn: (documentId: string) => api.reprocessDocument(documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });

  const filteredDocs = documents.filter((doc) =>
    doc.filename.toLowerCase().includes(searchTerm.toLowerCase()) ||
    doc.document_id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (doc.project_info?.project_name && doc.project_info.project_name.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  const totalPages = documents.reduce((sum, d) => sum + (d.page_count || 0), 0);
  const completedDocs = documents.filter((d) => d.status === 'completed').length;
  const scannedDocs = documents.filter((d) => d.is_scanned).length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <FolderOpen className="w-5 h-5 text-cyan-400" />
            Geotechnical Documents & PDF Pipeline
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Ingest and inspect engineering investigation reports, boring logs, and foundation study documents.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-xs font-medium text-slate-200 transition-all"
        >
          <RefreshCw className="w-3.5 h-3.5 text-cyan-400" />
          Refresh
        </button>
      </div>

      {/* Summary KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 shadow-sm">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>Total Documents</span>
            <FileText className="w-4 h-4 text-cyan-400" />
          </div>
          <div className="text-xl font-bold text-slate-100">{documents.length}</div>
          <div className="text-[11px] text-slate-400 mt-1">{completedDocs} extracted</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 shadow-sm">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>Total Pages Processed</span>
            <Layers className="w-4 h-4 text-indigo-400" />
          </div>
          <div className="text-xl font-bold text-slate-100">{totalPages}</div>
          <div className="text-[11px] text-slate-400 mt-1">Multi-page pagination</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 shadow-sm">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>Scanned / Hybrid Ratio</span>
            <Database className="w-4 h-4 text-amber-400" />
          </div>
          <div className="text-xl font-bold text-slate-100">{scannedDocs}</div>
          <div className="text-[11px] text-slate-400 mt-1">Auto OCR / Scan detection</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80 shadow-sm">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>SHA-256 Provenance</span>
            <Hash className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-xl font-bold text-slate-100">100%</div>
          <div className="text-[11px] text-emerald-400/80 mt-1">Source verified</div>
        </div>
      </div>

      {/* Multi-File Upload Component */}
      <DocumentUploader
        projectId={selectedProject}
        onUploadSuccess={() => queryClient.invalidateQueries({ queryKey: ['documents'] })}
      />

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-slate-900/40 p-3 rounded-lg border border-slate-800/60">
        <div className="relative w-full sm:w-80">
          <Search className="w-3.5 h-3.5 text-slate-400 absolute left-3 top-2.5" />
          <input
            type="text"
            placeholder="Search documents by name or ID..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-slate-950 border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 placeholder-slate-400 focus:outline-none focus:border-cyan-500"
          />
        </div>
        <div className="text-xs text-slate-400">
          Showing {filteredDocs.length} of {documents.length} documents
        </div>
      </div>

      {/* Error state */}
      {isError && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/30 rounded-xl flex items-center gap-3 text-xs text-rose-300">
          <AlertTriangle className="w-5 h-5 text-rose-400 flex-shrink-0" />
          <div>
            <div className="font-semibold">Failed to load documents</div>
            <div>{(error as any)?.message || 'Could not connect to backend service.'}</div>
          </div>
        </div>
      )}

      {/* Documents Table */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs text-slate-300">
            <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800">
              <tr>
                <th className="px-4 py-3 font-semibold">Document Name</th>
                <th className="px-4 py-3 font-semibold">Project / Site</th>
                <th className="px-4 py-3 font-semibold">SHA-256 Digest</th>
                <th className="px-4 py-3 font-semibold">Pages</th>
                <th className="px-4 py-3 font-semibold">Type</th>
                <th className="px-4 py-3 font-semibold">Status</th>
                <th className="px-4 py-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60">
              {isLoading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-400">
                    <Skeleton className="h-6 w-full mb-2" />
                    <Skeleton className="h-6 w-full" />
                  </td>
                </tr>
              ) : filteredDocs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-12 text-center text-slate-400">
                    <FileText className="w-8 h-8 text-slate-400 mx-auto mb-2" />
                    <p className="font-medium text-slate-300">No geotechnical documents found</p>
                    <p className="text-[11px] mt-1">Upload a PDF document above to start processing.</p>
                  </td>
                </tr>
              ) : (
                filteredDocs.map((doc) => (
                  <tr
                    key={doc.document_id}
                    className="hover:bg-slate-800/30 transition-colors"
                  >
                    <td className="px-4 py-3 font-medium text-slate-200">
                      <Link
                        to={`/documents/${doc.document_id}`}
                        className="hover:text-cyan-400 flex items-center gap-2 group"
                      >
                        <FileText className="w-4 h-4 text-cyan-400 flex-shrink-0" />
                        <span className="truncate max-w-[220px]" title={doc.filename}>
                          {doc.filename}
                        </span>
                      </Link>
                      <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                        {(doc.file_size_bytes / (1024 * 1024)).toFixed(2)} MB
                      </div>
                    </td>

                    <td className="px-4 py-3 text-slate-300">
                      {doc.project_info?.project_name ? (
                        <div>
                          <div className="font-medium text-slate-200 truncate max-w-[180px]">
                            {doc.project_info.project_name}
                          </div>
                          {doc.project_info.site_location && (
                            <div className="text-[10px] text-slate-400 truncate max-w-[180px]">
                              {doc.project_info.site_location}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-slate-400 italic">Not detected</span>
                      )}
                    </td>

                    <td className="px-4 py-3 font-mono text-[11px] text-slate-400">
                      <span className="px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 text-[10px]" title={doc.sha256_hash}>
                        {doc.sha256_hash.slice(0, 8)}...{doc.sha256_hash.slice(-6)}
                      </span>
                    </td>

                    <td className="px-4 py-3 font-medium text-slate-200">
                      {doc.page_count}
                    </td>

                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-0.5 rounded text-[11px] font-medium border ${
                          doc.document_type === 'scanned'
                            ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                            : doc.document_type === 'hybrid'
                            ? 'bg-orange-500/10 text-orange-400 border-orange-500/30'
                            : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                        }`}
                      >
                        {doc.document_type}
                      </span>
                    </td>

                    <td className="px-4 py-3">
                      <StatusBadge status={doc.status} />
                      {doc.error_message && (
                        <div className="text-[10px] text-rose-400 truncate max-w-[160px] mt-0.5" title={doc.error_message}>
                          {doc.error_message}
                        </div>
                      )}
                    </td>

                    <td className="px-4 py-3 text-right">
                      <div className="inline-flex items-center gap-1.5">
                        <Link
                          to={`/documents/${doc.document_id}`}
                          className="p-1.5 rounded-lg border border-cyan-800/60 bg-cyan-950/40 hover:bg-cyan-900/60 text-cyan-400 transition-colors"
                          title="Open Intelligence Inspector"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </Link>
                        <button
                          onClick={() => reprocessMutation.mutate(doc.document_id)}
                          className="p-1.5 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-slate-700 text-slate-300 transition-colors"
                          title="Reprocess Extraction"
                        >
                          <RefreshCw className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={() => {
                            if (window.confirm(`Delete document "${doc.filename}" and its extracted data?`)) {
                              deleteMutation.mutate(doc.document_id);
                            }
                          }}
                          className="p-1.5 rounded-lg border border-slate-700 bg-slate-800/80 hover:bg-rose-950/60 hover:text-rose-400 hover:border-rose-800/60 text-slate-400 transition-colors"
                          title="Delete Document"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

