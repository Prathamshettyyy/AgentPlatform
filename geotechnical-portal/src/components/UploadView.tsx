import React, { useRef, useState } from 'react';
import {
  Upload,
  FileText,
  Image as ImageIcon,
  X,
  MapPin,
  Building2,
  ArrowRight,
  AlertCircle,
  CheckCircle2,
  ShieldCheck,
  Clock,
  FolderOpen,
  Sparkles,
  Loader2,
} from 'lucide-react';
import type { ProjectSession } from '../api/types';
import { portalApi } from '../api/client';

export interface StagedFile {
  id: string;
  file: File;
  category: string;
  status: 'READY' | 'UPLOADING' | 'UPLOADED' | 'ERROR';
  detectedLocation?: string;
  error?: string;
}

interface UploadViewProps {
  onStartAnalysis: (params: {
    projectName: string;
    projectAddress: string;
    subdivision?: string;
    blockNumber?: string;
    lotNumber?: string;
    files: File[];
  }) => Promise<void>;
  recentSessions: ProjectSession[];
  onSelectSession: (session: ProjectSession) => void;
  onLoadDemoProject: () => Promise<void>;
  isSubmitting: boolean;
  submitError?: string | null;
}

const ALLOWED_EXTENSIONS = ['.pdf', '.jpg', '.jpeg', '.png'];
const MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024; // 100 MB

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

function inferDocumentCategory(filename: string): string {
  const lower = filename.toLowerCase();
  if (lower.includes('soil') || lower.includes('geotech') || lower.includes('boring')) {
    return 'Soil Investigation Report';
  }
  if (lower.includes('site plan') || lower.includes('site_plan') || lower.includes('plat')) {
    return 'Site Plan / Civil Drawing';
  }
  if (lower.includes('foundation') || lower.includes('structural')) {
    return 'Foundation Drawing';
  }
  if (lower.includes('arch')) {
    return 'Architectural Drawing';
  }
  if (lower.endsWith('.jpg') || lower.endsWith('.jpeg') || lower.endsWith('.png')) {
    return 'Site / Drawing Image';
  }
  return 'Engineering Document';
}

export const UploadView: React.FC<UploadViewProps> = ({
  onStartAnalysis,
  recentSessions,
  onSelectSession,
  onLoadDemoProject,
  isSubmitting,
  submitError,
}) => {
  const [projectName, setProjectName] = useState('');
  const [projectAddress, setProjectAddress] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [subdivision, setSubdivision] = useState('');
  const [blockNumber, setBlockNumber] = useState('');
  const [lotNumber, setLotNumber] = useState('');
  const [stagedFiles, setStagedFiles] = useState<StagedFile[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isDetectingInfo, setIsDetectingInfo] = useState(false);
  const [detectedFromFile, setDetectedFromFile] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const autoDetectFromSoilReport = async (newItems: StagedFile[]) => {
    // Prefer the Soil Investigation Report (typically small & contains full project name/address)
    const soilCandidates = newItems.filter((item) =>
      /soil|geotech|boring/i.test(item.file.name)
    );
    const targetItems = soilCandidates.length > 0 ? soilCandidates : newItems.slice(0, 1);
    if (targetItems.length === 0) return;

    try {
      setIsDetectingInfo(true);
      const uploaded = await Promise.resolve(
        portalApi.uploadDocuments(
          targetItems.map((i) => i.file),
          'proj_autodetect_preview'
        )
      );
      if (!Array.isArray(uploaded) || uploaded.length === 0) return;

      const primaryDoc =
        uploaded.find((d) => /soil|geotech|boring/i.test(d.filename)) ||
        uploaded.find((d) => d.project_info?.project_name || d.project_info?.site_location) ||
        uploaded[0];

      const info = primaryDoc?.project_info || {};
      const autoName =
        (info.project_name && info.site_location
          ? `${info.project_name} (${info.site_location.split(',')[0]})`
          : info.project_name) ||
        info.site_location ||
        '';
      const autoAddress =
        info.site_location ||
        uploaded.map((d) => d.project_info?.site_location).find(Boolean) ||
        info.legal_description ||
        '';

      if (autoName) {
        setProjectName((prev) => (prev.trim() ? prev : autoName));
      }
      if (autoAddress) {
        setProjectAddress((prev) => (prev.trim() ? prev : autoAddress));
      }
      if (info.subdivision) {
        setSubdivision((prev) => (prev.trim() ? prev : info.subdivision || ''));
      }
      if (info.block) {
        setBlockNumber((prev) => (prev.trim() ? prev : info.block || ''));
      }
      if (info.lot) {
        setLotNumber((prev) => (prev.trim() ? prev : info.lot || ''));
      }
      if (autoName || autoAddress) {
        setDetectedFromFile(primaryDoc.filename);
      }

      // Attach detected location to the staged file entry
      setStagedFiles((prev) =>
        prev.map((sf) => {
          const matchDoc = uploaded.find((u) => u.filename === sf.file.name);
          const loc = matchDoc?.project_info?.site_location;
          return loc ? { ...sf, detectedLocation: loc } : sf;
        })
      );
    } catch {
      // Non-fatal preview error; full extraction still runs on submit
    } finally {
      setIsDetectingInfo(false);
    }
  };

  const validateAndAddFiles = (incoming: FileList | File[]) => {
    setValidationError(null);
    const next: StagedFile[] = [];
    const errors: string[] = [];

    Array.from(incoming).forEach((file) => {
      const lower = file.name.toLowerCase();
      const hasValidExt = ALLOWED_EXTENSIONS.some((ext) => lower.endsWith(ext));
      if (!hasValidExt) {
        errors.push(`"${file.name}" has an unsupported format. Allowed: PDF, JPG, JPEG, PNG.`);
        return;
      }
      if (file.size === 0) {
        errors.push(`"${file.name}" is empty (0 bytes).`);
        return;
      }
      if (file.size > MAX_FILE_SIZE_BYTES) {
        errors.push(`"${file.name}" exceeds the 100 MB file size limit.`);
        return;
      }
      const duplicate = stagedFiles.some(
        (existing) => existing.file.name === file.name && existing.file.size === file.size
      );
      if (duplicate) {
        return;
      }
      next.push({
        id: `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        file,
        category: inferDocumentCategory(file.name),
        status: 'READY',
      });
    });

    if (errors.length > 0) {
      setValidationError(errors.join(' '));
    }
    if (next.length > 0) {
      setStagedFiles((prev) => [...prev, ...next]);
      void autoDetectFromSoilReport(next);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      validateAndAddFiles(e.dataTransfer.files);
    }
  };

  const handleRemoveFile = (id: string) => {
    setStagedFiles((prev) => prev.filter((item) => item.id !== id));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setValidationError(null);

    if (stagedFiles.length === 0) {
      setValidationError('Please upload at least one project document (PDF, JPG, JPEG, or PNG).');
      return;
    }

    setStagedFiles((prev) => prev.map((f) => ({ ...f, status: 'UPLOADING' })));
    try {
      await onStartAnalysis({
        projectName: projectName.trim(),
        projectAddress: projectAddress.trim(),
        subdivision: subdivision.trim() || undefined,
        blockNumber: blockNumber.trim() || undefined,
        lotNumber: lotNumber.trim() || undefined,
        files: stagedFiles.map((f) => f.file),
      });
    } catch {
      setStagedFiles((prev) => prev.map((f) => ({ ...f, status: 'READY' })));
    }
  };

  return (
    <div className="w-full px-5 sm:px-8 lg:px-10 xl:px-12 py-6 space-y-6">
      {/* Modern Full-Width Hero Banner */}
      <div className="relative overflow-hidden rounded-3xl border border-slate-800/90 bg-gradient-to-r from-slate-900 via-slate-900/95 to-amber-950/35 p-6 sm:p-8 shadow-2xl">
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-center">
          <div className="xl:col-span-7 space-y-3">
            <div className="inline-flex items-center gap-2 px-3.5 py-1 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs font-medium">
              <Sparkles className="w-3.5 h-3.5" />
              AI-Powered Geotechnical &amp; Foundation Engineering Assistant
            </div>
            <h1 className="text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-white">
              Turn Soil Reports &amp; Site Plans into Ready-to-Use Foundation Packages
            </h1>
            <p className="text-sm sm:text-base text-slate-300 leading-relaxed max-w-3xl">
              Simply upload your geotechnical report and site drawings. GeoStrata automatically
              identifies your project details, analyzes soil conditions and risks, compares
              foundation options, and prepares a complete vendor requirement document.
            </p>
          </div>

          {/* 3 Deliverable Highlights */}
          <div className="xl:col-span-5 grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="p-4 rounded-2xl bg-slate-950/75 border border-slate-800/90 space-y-1.5">
              <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-amber-500/15 text-amber-400 text-xs font-bold">
                01
              </span>
              <h3 className="text-xs font-bold text-white">Geotechnical Analysis</h3>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Soil strata, groundwater, PVR swell &amp; site risks
              </p>
            </div>
            <div className="p-4 rounded-2xl bg-slate-950/75 border border-slate-800/90 space-y-1.5">
              <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-emerald-500/15 text-emerald-400 text-xs font-bold">
                02
              </span>
              <h3 className="text-xs font-bold text-white">Foundation Research</h3>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Shallow vs. deep foundation options &amp; comparisons
              </p>
            </div>
            <div className="p-4 rounded-2xl bg-slate-950/75 border border-slate-800/90 space-y-1.5">
              <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-sky-500/15 text-sky-400 text-xs font-bold">
                03
              </span>
              <h3 className="text-xs font-bold text-white">Vendor Requirements</h3>
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Complete contractor scope, specs &amp; bid checklist
              </p>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left / Main Column: Upload Workspace (8 of 12 columns) */}
        <div className="lg:col-span-8">
          <form
            onSubmit={handleSubmit}
            className="rounded-3xl border border-slate-800/90 bg-slate-900/75 p-6 sm:p-8 space-y-6 shadow-xl"
          >
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
              <div>
                <h2 className="text-lg sm:text-xl font-bold text-white">
                  Upload Project Files
                </h2>
                <p className="text-xs sm:text-sm text-slate-400 mt-0.5">
                  Drop your soil report and site drawings below — project name and address are detected automatically
                </p>
              </div>
              <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-300 bg-emerald-500/10 px-3 py-1 rounded-full border border-emerald-500/25">
                <CheckCircle2 className="w-3.5 h-3.5" />
                Smart Auto-Fill Enabled
              </span>
            </div>

            {(validationError || submitError) && (
              <div
                role="alert"
                className="flex items-start gap-3 p-4 rounded-2xl bg-red-500/10 border border-red-500/30 text-red-200 text-sm"
              >
                <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="font-semibold text-red-300">Unable to start analysis</p>
                  <p className="text-xs text-red-200/90">{validationError || submitError}</p>
                </div>
              </div>
            )}

            {/* Drag and Drop Upload Zone FIRST for a user-friendly experience */}
            <div className="space-y-2.5">
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setIsDragging(true);
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setIsDragging(false);
                }}
                onDrop={handleDrop}
                onClick={() => !isSubmitting && fileInputRef.current?.click()}
                data-testid="dropzone"
                className={`cursor-pointer rounded-2xl border-2 border-dashed p-8 sm:p-10 text-center transition-all ${
                  isDragging
                    ? 'border-amber-400 bg-amber-500/10 scale-[1.005]'
                    : 'border-slate-700/80 hover:border-amber-500/60 bg-slate-950/60 hover:bg-slate-950/90'
                }`}
              >
                <input
                  ref={fileInputRef}
                  data-testid="file-input"
                  type="file"
                  multiple
                  accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                  onChange={(e) => {
                    if (e.target.files && e.target.files.length > 0) {
                      validateAndAddFiles(e.target.files);
                      e.target.value = '';
                    }
                  }}
                  className="hidden"
                />
                <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-amber-500/20 to-orange-500/10 border border-amber-500/30 flex items-center justify-center mx-auto mb-3.5 text-amber-400 shadow-lg shadow-amber-500/10">
                  <Upload className="w-6 h-6" />
                </div>
                <p className="text-base font-semibold text-white">
                  Drag &amp; drop project documents here, or{' '}
                  <span className="text-amber-400 underline underline-offset-4">browse files</span>
                </p>
                <p className="text-xs text-slate-400 mt-1.5">
                  Supports <span className="text-slate-200 font-medium">PDF, JPG, JPEG, PNG</span>{' '}
                  (up to 100 MB per file)
                </p>
                <div className="flex flex-wrap items-center justify-center gap-2 mt-4">
                  {[
                    'Soil Investigation Reports',
                    'Boring Logs',
                    'Site Plans',
                    'Foundation Drawings',
                    'Architectural Drawings',
                  ].map((tag) => (
                    <span
                      key={tag}
                      className="text-xs px-3 py-1 rounded-full bg-slate-900/90 border border-slate-800 text-slate-300"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Uploaded / Staged File List */}
            {stagedFiles.length > 0 && (
              <div className="space-y-2.5">
                <div className="flex items-center justify-between text-xs text-slate-400">
                  <span className="font-semibold text-slate-200">
                    Attached Project Files ({stagedFiles.length})
                  </span>
                  <span>
                    Total Size:{' '}
                    {formatBytes(stagedFiles.reduce((acc, item) => acc + item.file.size, 0))}
                  </span>
                </div>
                <div className="divide-y divide-slate-800/80 rounded-2xl border border-slate-800 bg-slate-950/90 overflow-hidden">
                  {stagedFiles.map((item) => {
                    const isImage = /\.(jpg|jpeg|png)$/i.test(item.file.name);
                    return (
                      <div
                        key={item.id}
                        className="flex items-center justify-between gap-3 px-4 py-3.5 hover:bg-slate-900/60 transition-colors"
                      >
                        <div className="flex items-center gap-3.5 min-w-0">
                          <div className="w-10 h-10 rounded-xl bg-slate-900 border border-slate-800 flex items-center justify-center shrink-0 text-amber-400">
                            {isImage ? (
                              <ImageIcon className="w-4 h-4" />
                            ) : (
                              <FileText className="w-4 h-4" />
                            )}
                          </div>
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-white truncate">
                              {item.file.name}
                            </p>
                            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400 mt-0.5">
                              <span>{formatBytes(item.file.size)}</span>
                              <span>&bull;</span>
                              <span className="text-amber-300/90 font-medium">{item.category}</span>
                              {item.detectedLocation && (
                                <>
                                  <span>&bull;</span>
                                  <span className="text-emerald-300 font-medium">
                                    Location: {item.detectedLocation}
                                  </span>
                                </>
                              )}
                            </div>
                          </div>
                        </div>

                        <div className="flex items-center gap-3 shrink-0">
                          <span
                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                              item.status === 'UPLOADING'
                                ? 'bg-blue-500/15 text-blue-300 border border-blue-500/30'
                                : 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                            }`}
                          >
                            <CheckCircle2 className="w-3.5 h-3.5" />
                            {item.status === 'UPLOADING' ? 'Uploading...' : 'Ready'}
                          </span>
                          {!isSubmitting && (
                            <button
                              type="button"
                              aria-label={`Remove ${item.file.name}`}
                              onClick={() => handleRemoveFile(item.id)}
                              className="p-1.5 rounded-lg text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                            >
                              <X className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Project Name & Location Inputs (Auto-extracted as soon as Soil Report is attached) */}
            <div className="p-4 sm:p-5 rounded-2xl bg-slate-950/60 border border-slate-800/80 space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-semibold text-slate-200">
                    Project Name &amp; Site Location
                  </span>
                  {isDetectingInfo ? (
                    <span className="inline-flex items-center gap-1.5 text-xs text-amber-300 bg-amber-500/10 px-2.5 py-0.5 rounded-full border border-amber-500/25">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      Reading Soil Report...
                    </span>
                  ) : detectedFromFile ? (
                    <span className="inline-flex items-center gap-1.5 text-xs text-emerald-300 bg-emerald-500/10 px-2.5 py-0.5 rounded-full border border-emerald-500/25">
                      <CheckCircle2 className="w-3 h-3" />
                      Auto-detected from {detectedFromFile}
                    </span>
                  ) : (
                    <span className="text-xs text-slate-400">
                      (Automatically filled when you attach a Soil Report)
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => setShowAdvanced((v) => !v)}
                  className="text-xs text-amber-400 hover:text-amber-300 font-medium"
                >
                  {showAdvanced ? 'Hide Legal Parcel Fields' : '+ Subdivision / Block / Lot'}
                </button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label
                    htmlFor="project-name-input"
                    className="block text-xs font-medium text-slate-300"
                  >
                    Project Name
                  </label>
                  <div className="relative">
                    <Building2 className="w-4 h-4 text-slate-400 absolute left-3.5 top-3" />
                    <input
                      id="project-name-input"
                      type="text"
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value)}
                      placeholder="Auto-detected from soil report..."
                      disabled={isSubmitting}
                      className="w-full pl-10 pr-3.5 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-amber-500"
                    />
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label
                    htmlFor="project-address-input"
                    className="block text-xs font-medium text-slate-300"
                  >
                    Project Location / Address
                  </label>
                  <div className="relative">
                    <MapPin className="w-4 h-4 text-slate-400 absolute left-3.5 top-3" />
                    <input
                      id="project-address-input"
                      type="text"
                      value={projectAddress}
                      onChange={(e) => setProjectAddress(e.target.value)}
                      placeholder="Auto-detected from soil report..."
                      disabled={isSubmitting}
                      className="w-full pl-10 pr-3.5 py-2.5 rounded-xl bg-slate-900 border border-slate-800 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-amber-500"
                    />
                  </div>
                </div>
              </div>

              {showAdvanced && (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 border-t border-slate-800/80">
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Subdivision</label>
                    <input
                      type="text"
                      value={subdivision}
                      onChange={(e) => setSubdivision(e.target.value)}
                      placeholder="e.g., White Oak Terrace"
                      className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Block Number</label>
                    <input
                      type="text"
                      value={blockNumber}
                      onChange={(e) => setBlockNumber(e.target.value)}
                      placeholder="e.g., 1"
                      className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-white"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-400 mb-1">Lot Number(s)</label>
                    <input
                      type="text"
                      value={lotNumber}
                      onChange={(e) => setLotNumber(e.target.value)}
                      placeholder="e.g., 11 & 12"
                      className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-white"
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Submit Button */}
            <div className="pt-1">
              <button
                type="submit"
                disabled={isSubmitting}
                data-testid="start-analysis-button"
                className="w-full py-4 px-6 rounded-2xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 disabled:opacity-50 text-slate-950 font-bold text-sm shadow-lg shadow-amber-500/20 flex items-center justify-center gap-2 transition-all"
              >
                {isSubmitting ? (
                  <>
                    <Clock className="w-4 h-4 animate-spin" />
                    Analyzing Project Documents...
                  </>
                ) : (
                  <>
                    Start Project Analysis
                    <ArrowRight className="w-4 h-4" />
                  </>
                )}
              </button>
            </div>
          </form>
        </div>

        {/* Right Column: Sample Project, How It Works & Recent Projects (4 of 12 columns) */}
        <div className="lg:col-span-4 space-y-6">
          {/* Quick-Load Sample Project */}
          <div className="rounded-3xl border border-amber-500/30 bg-gradient-to-b from-amber-500/12 to-slate-900/90 p-6 space-y-3.5 shadow-lg">
            <div className="flex items-center gap-2 text-amber-300 font-bold text-sm">
              <Sparkles className="w-4 h-4" />
              Explore Sample Project
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              Open the pre-loaded{' '}
              <span className="text-white font-semibold">2432–2436 White Oak Drive</span> residence
              investigation (Soil Report + Site Plans) to explore the full 3-deliverable engineering
              experience immediately.
            </p>
            <button
              type="button"
              onClick={onLoadDemoProject}
              disabled={isSubmitting}
              className="w-full py-3 px-4 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-xs font-semibold flex items-center justify-center gap-2 transition-colors"
            >
              <FolderOpen className="w-4 h-4" />
              Open White Oak Sample Project
            </button>
          </div>

          {/* Recent Project Sessions */}
          {recentSessions.length > 0 && (
            <div className="rounded-3xl border border-slate-800/90 bg-slate-900/80 p-6 space-y-3.5">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-white">Recent Projects</h3>
                <span className="text-xs text-slate-400">{recentSessions.length} saved</span>
              </div>
              <div className="space-y-2.5 max-h-80 overflow-y-auto pr-1">
                {recentSessions.map((sess) => {
                  const isDone = Boolean(
                    sess.geotechnicalReportId && sess.foundationResearchReportId
                  );
                  return (
                    <button
                      key={sess.projectId}
                      type="button"
                      onClick={() => onSelectSession(sess)}
                      className="w-full text-left p-3.5 rounded-2xl bg-slate-950/90 hover:bg-slate-800/70 border border-slate-800/90 transition-all space-y-1.5 group"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-white group-hover:text-amber-300 transition-colors truncate">
                          {sess.projectName}
                        </span>
                        <span
                          className={`text-[10px] font-medium px-2.5 py-0.5 rounded-full shrink-0 ${
                            isDone
                              ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'
                              : 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                          }`}
                        >
                          {isDone ? 'Ready' : 'In Progress'}
                        </span>
                      </div>
                      <p className="text-xs text-slate-400 truncate">{sess.projectAddress}</p>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Simple How It Works Card */}
          <div className="rounded-3xl border border-slate-800/90 bg-slate-900/80 p-6 space-y-4">
            <div className="flex items-center gap-2 text-sm font-bold text-white">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              How GeoStrata Works
            </div>
            <ol className="space-y-3.5 text-xs text-slate-300">
              <li className="flex items-start gap-3">
                <span className="w-6 h-6 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-300 font-bold flex items-center justify-center shrink-0 text-xs">
                  1
                </span>
                <div>
                  <span className="font-semibold text-white">Reads Soil Reports &amp; Site Plans</span>
                  <p className="text-slate-400 mt-0.5 leading-relaxed">
                    Extracts boring logs, soil layers, lab test tables, and site plan layouts while
                    checking that all drawings match your property address.
                  </p>
                </div>
              </li>
              <li className="flex items-start gap-3">
                <span className="w-6 h-6 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-bold flex items-center justify-center shrink-0 text-xs">
                  2
                </span>
                <div>
                  <span className="font-semibold text-white">Evaluates Foundation Options</span>
                  <p className="text-slate-400 mt-0.5 leading-relaxed">
                    Analyzes swell potential (PVR), groundwater, and bearing pressures to compare
                    shallow and deep foundation systems.
                  </p>
                </div>
              </li>
              <li className="flex items-start gap-3">
                <span className="w-6 h-6 rounded-lg bg-sky-500/15 border border-sky-500/30 text-sky-300 font-bold flex items-center justify-center shrink-0 text-xs">
                  3
                </span>
                <div>
                  <span className="font-semibold text-white">Prepares Vendor Bid Package</span>
                  <p className="text-slate-400 mt-0.5 leading-relaxed">
                    Generates a complete 12-section Vendor Foundation Requirement Document ready for
                    Professional Engineer review.
                  </p>
                </div>
              </li>
            </ol>
          </div>
        </div>
      </div>
    </div>
  );
};

