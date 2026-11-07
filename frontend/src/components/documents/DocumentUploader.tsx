import React, { useState, useRef } from 'react';
import { Upload, FileText, AlertCircle, CheckCircle2, Loader2, X } from 'lucide-react';
import { api } from '../../api/client';

interface DocumentUploaderProps {
  projectId?: string;
  onUploadSuccess?: () => void;
}

export const DocumentUploader: React.FC<DocumentUploaderProps> = ({
  projectId = 'default',
  onUploadSuccess,
}) => {
  const [isDragging, setIsDragging] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successCount, setSuccessCount] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFiles = (files: FileList | File[]) => {
    setError(null);
    setSuccessCount(null);
    const validPdfs: File[] = [];

    Array.from(files).forEach((file) => {
      if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
        validPdfs.push(file);
      } else {
        setError(`File "${file.name}" was skipped: Only PDF documents are supported.`);
      }
    });

    if (validPdfs.length > 0) {
      setSelectedFiles((prev) => [...prev, ...validPdfs]);
    }
  };

  const removeFile = (idx: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const startUpload = async () => {
    if (selectedFiles.length === 0) return;
    setUploading(true);
    setError(null);
    setSuccessCount(null);

    try {
      const results = await api.uploadDocuments(selectedFiles, projectId);
      setSuccessCount(results.length);
      setSelectedFiles([]);
      if (onUploadSuccess) {
        onUploadSuccess();
      }
    } catch (err: any) {
      setError(err.message || 'Failed to upload PDF documents.');
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2">
            <Upload className="w-4 h-4 text-cyan-400" />
            PDF Ingestion Pipeline
          </h3>
          <p className="text-xs text-slate-400">
            Upload geotechnical reports, boring logs, and foundation investigation documents for automated extraction.
          </p>
        </div>
      </div>

      {/* Drag & Drop Zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (e.dataTransfer.files) {
            handleFiles(e.dataTransfer.files);
          }
        }}
        onClick={() => fileInputRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-6 flex flex-col items-center justify-center cursor-pointer transition-all ${
          isDragging
            ? 'border-cyan-500 bg-cyan-950/20'
            : 'border-slate-700/80 hover:border-slate-600 bg-slate-950/40 hover:bg-slate-950/60'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files) {
              handleFiles(e.target.files);
            }
          }}
        />
        <div className="p-3 rounded-full bg-slate-800/80 border border-slate-700 text-cyan-400 mb-2">
          <FileText className="w-6 h-6" />
        </div>
        <p className="text-sm font-medium text-slate-200">
          Click to select or drag and drop multiple PDF documents
        </p>
        <p className="text-xs text-slate-400 mt-1">
          Supported: Multi-page reports, borehole logs, engineering drawings (.pdf up to 100MB)
        </p>
      </div>

      {/* File queue */}
      {selectedFiles.length > 0 && (
        <div className="mt-4 space-y-2">
          <div className="text-xs font-medium text-slate-400 flex items-center justify-between">
            <span>Ready to ingest ({selectedFiles.length} {selectedFiles.length === 1 ? 'file' : 'files'})</span>
            <button
              onClick={() => setSelectedFiles([])}
              className="text-xs text-slate-500 hover:text-slate-300"
            >
              Clear all
            </button>
          </div>
          <div className="max-h-36 overflow-y-auto space-y-1.5 pr-1">
            {selectedFiles.map((f, i) => (
              <div
                key={i}
                className="flex items-center justify-between px-3 py-2 bg-slate-800/50 border border-slate-700/60 rounded-md text-xs text-slate-300"
              >
                <div className="flex items-center gap-2 truncate">
                  <FileText className="w-3.5 h-3.5 text-cyan-400 flex-shrink-0" />
                  <span className="truncate">{f.name}</span>
                  <span className="text-slate-400 flex-shrink-0">
                    ({(f.size / (1024 * 1024)).toFixed(2)} MB)
                  </span>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    removeFile(i);
                  }}
                  className="text-slate-400 hover:text-rose-400 p-0.5"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>

          <div className="flex justify-end pt-2">
            <button
              onClick={startUpload}
              disabled={uploading}
              className="inline-flex items-center gap-2 px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:bg-cyan-900 disabled:text-slate-500 text-white rounded-lg text-xs font-semibold shadow-sm transition-all"
            >
              {uploading ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Processing & Extracting...
                </>
              ) : (
                <>
                  <Upload className="w-3.5 h-3.5" />
                  Ingest {selectedFiles.length} {selectedFiles.length === 1 ? 'Document' : 'Documents'}
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Notifications */}
      {error && (
        <div className="mt-3 p-3 bg-rose-500/10 border border-rose-500/30 rounded-lg flex items-center gap-2 text-xs text-rose-300">
          <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {successCount !== null && (
        <div className="mt-3 p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg flex items-center gap-2 text-xs text-emerald-300">
          <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
          <span>
            Successfully ingested and extracted {successCount} {successCount === 1 ? 'document' : 'documents'}.
          </span>
        </div>
      )}
    </div>
  );
};

