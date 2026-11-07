import React from 'react';
import {
  CheckCircle2,
  Clock,
  Loader2,
  XCircle,
  AlertTriangle,
  ShieldAlert,
  Play,
  RotateCcw,
  ArrowLeft,
  FileSpreadsheet,
  ExternalLink,
  Activity,
} from 'lucide-react';
import type {
  DocumentMetadata,
  DocumentProjectAssociation,
  DocumentReadinessResponse,
  PortalStage,
  ProjectSession,
  UserDecision,
  WorkflowRun,
  WorkflowRunEvent,
} from '../api/types';
import { getAgentPlatformUiUrl } from '../api/client';

interface ProcessingViewProps {
  session: ProjectSession;
  stages: PortalStage[];
  documents: DocumentMetadata[];
  readinessMap: Record<string, DocumentReadinessResponse>;
  associations: DocumentProjectAssociation[];
  workflowRun: WorkflowRun | null;
  workflowEvents: WorkflowRunEvent[];
  onAssociationDecision: (
    associationId: string,
    decision: UserDecision,
    notes?: string
  ) => Promise<void> | void;
  onProceedAfterReview: () => Promise<void> | void;
  onRetryWorkflow: () => Promise<void> | void;
  onOpenResults: () => void;
  onBackToUpload: () => void;
  isActionBusy: boolean;
}

export const ProcessingView: React.FC<ProcessingViewProps> = ({
  session,
  stages,
  documents,
  readinessMap: _readinessMap,
  associations,
  workflowRun,
  workflowEvents: _workflowEvents,
  onAssociationDecision,
  onProceedAfterReview,
  onRetryWorkflow,
  onOpenResults,
  onBackToUpload,
  isActionBusy,
}) => {
  const completedCount = stages.filter((s) => s.status === 'SUCCEEDED').length;
  const allCompleted =
    stages.every((s) => s.status === 'SUCCEEDED') ||
    workflowRun?.status === 'succeeded' ||
    workflowRun?.status === 'partially_succeeded';

  const hasFailure =
    stages.some((s) => s.status === 'FAILED') ||
    workflowRun?.status === 'failed' ||
    Boolean(session.errorMessage);

  // Only show site plans / drawings that do NOT automatically match the soil report
  const reviewAssociations = associations.filter((a) => a.match_status !== 'MATCHED');

  const needsHumanConfirmation =
    reviewAssociations.length > 0 || stages.some((s) => s.status === 'NEEDS_REVIEW');

  const hasUnresolvedPossibleMatch = reviewAssociations.some(
    (a) =>
      (a.match_status === 'POSSIBLE_MATCH' || a.match_status === 'PENDING_CONFIRMATION') &&
      a.user_decision === 'PENDING'
  );

  const onlyMismatches =
    reviewAssociations.length > 0 &&
    reviewAssociations.every((a) => a.match_status === 'MISMATCH');

  const confirmedCount = associations.filter(
    (a) => a.match_status === 'MATCHED' || a.user_decision === 'CONFIRMED'
  ).length;

  const canProceedAfterReview = !hasUnresolvedPossibleMatch && confirmedCount > 0;

  const progressPct = Math.round((completedCount / Math.max(stages.length, 1)) * 100);

  return (
    <div className="w-full px-5 sm:px-8 lg:px-10 xl:px-12 py-6 space-y-6">
      {/* Project Header & Overall Progress Bar */}
      <div className="rounded-3xl border border-slate-800/90 bg-slate-900/85 p-6 sm:p-7 space-y-5 shadow-xl">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={`inline-flex items-center gap-1.5 text-xs font-medium px-3 py-0.5 rounded-full border ${
                  allCompleted
                    ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                    : hasFailure
                    ? 'bg-red-500/15 text-red-300 border-red-500/30'
                    : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                }`}
              >
                {allCompleted
                  ? 'All Engineering Reports Ready'
                  : hasFailure
                  ? 'Action Required'
                  : 'Analysis in Progress'}
              </span>
              <span className="text-xs text-slate-400">
                {documents.length} {documents.length === 1 ? 'Document' : 'Documents'} Attached
              </span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-bold text-white">{session.projectName}</h1>
            <p className="text-sm text-slate-300">{session.projectAddress}</p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={onBackToUpload}
              className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-medium text-slate-200 transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              Back to Upload
            </button>

            {session.runId && (
              <a
                href={`${getAgentPlatformUiUrl()}/runs`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-slate-800/80 hover:bg-slate-700 border border-slate-700 text-xs font-medium text-slate-300 transition-colors"
              >
                <Activity className="w-3.5 h-3.5 text-amber-400" />
                System Logs
                <ExternalLink className="w-3 h-3 text-slate-400" />
              </a>
            )}

            {allCompleted && (
              <button
                type="button"
                data-testid="view-final-results-btn"
                onClick={onOpenResults}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 text-slate-950 font-bold text-xs shadow-lg shadow-emerald-500/20 transition-all"
              >
                <FileSpreadsheet className="w-4 h-4" />
                Open Engineering Reports
              </button>
            )}
          </div>
        </div>

        {/* Smooth Progress Bar */}
        <div className="space-y-2 pt-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-300 font-medium">
              Overall Analysis Progress ({completedCount} of {stages.length} steps complete)
            </span>
            <span className="font-bold text-amber-300">{allCompleted ? 100 : progressPct}%</span>
          </div>
          <div className="w-full h-2.5 rounded-full bg-slate-950 border border-slate-800 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                allCompleted
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-400'
                  : hasFailure
                  ? 'bg-red-500'
                  : 'bg-gradient-to-r from-amber-500 to-orange-400'
              }`}
              style={{ width: `${allCompleted ? 100 : Math.max(progressPct, 8)}%` }}
            />
          </div>
        </div>
      </div>

      {/* Failure Banner & Retry Control */}
      {hasFailure && (
        <div
          data-testid="stage-failure-banner"
          className="rounded-3xl border border-red-500/40 bg-red-950/30 p-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4"
        >
          <div className="flex items-start gap-3.5">
            <XCircle className="w-6 h-6 text-red-400 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <h3 className="text-sm font-bold text-red-200">
                Analysis Paused Due to a Processing Error
              </h3>
              <p className="text-xs text-red-300">
                {session.errorMessage ||
                  workflowRun?.output?.error ||
                  workflowRun?.payload?.error ||
                  'One or more analysis steps encountered an issue.'}
              </p>
            </div>
          </div>

          <button
            type="button"
            data-testid="retry-workflow-btn"
            disabled={isActionBusy}
            onClick={() => onRetryWorkflow()}
            className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-red-500 hover:bg-red-400 text-slate-950 font-semibold text-xs shrink-0"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            Retry Analysis
          </button>
        </div>
      )}

      {/* User-Friendly Site Location Verification Banner (Only shows non-matching or similar site plans) */}
      {needsHumanConfirmation && !allCompleted && (
        <div
          data-testid="human-confirmation-gate"
          className={`rounded-3xl border p-6 sm:p-7 space-y-5 shadow-xl ${
            onlyMismatches
              ? 'border-red-500/40 bg-red-950/20'
              : 'border-amber-500/40 bg-amber-950/20'
          }`}
        >
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-slate-800/80 pb-5">
            <div className="flex items-start gap-3.5">
              <div
                className={`w-11 h-11 rounded-2xl flex items-center justify-center shrink-0 ${
                  onlyMismatches
                    ? 'bg-red-500/15 border border-red-500/30 text-red-400'
                    : 'bg-amber-500/15 border border-amber-500/30 text-amber-400'
                }`}
              >
                <ShieldAlert className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <h3 className="text-lg font-bold text-white">
                  {onlyMismatches
                    ? 'Site Location Does Not Match Your Soil Report'
                    : 'Verify Site Location Details Before Continuing'}
                </h3>
                <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
                  Your Soil Report is for{' '}
                  <strong className="text-amber-300">{session.projectAddress}</strong>. Please
                  review the site plan location check below before we generate your engineering
                  reports.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2.5 shrink-0">
              <button
                type="button"
                onClick={onBackToUpload}
                className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-xs font-semibold text-slate-200 transition-colors"
              >
                Upload Different Site Plan
              </button>
              <button
                type="button"
                data-testid="proceed-workflow-btn"
                disabled={!canProceedAfterReview || isActionBusy}
                onClick={() => onProceedAfterReview()}
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 disabled:opacity-40 text-slate-950 font-bold text-xs shadow-lg shadow-amber-500/20 transition-all"
              >
                <Play className="w-3.5 h-3.5" />
                {hasUnresolvedPossibleMatch
                  ? 'Please Confirm Site Plan Below'
                  : 'Continue to Generate Reports'}
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {reviewAssociations.map((assoc) => {
              const isMismatch = assoc.match_status === 'MISMATCH';
              const isConfirmed = assoc.user_decision === 'CONFIRMED';
              const isRejected = assoc.user_decision === 'REJECTED';

              return (
                <div
                  key={assoc.association_id}
                  className={`p-5 rounded-2xl border flex flex-col justify-between gap-4 text-xs transition-all ${
                    isMismatch
                      ? 'bg-red-950/25 border-red-500/35'
                      : isConfirmed
                      ? 'bg-emerald-950/20 border-emerald-500/35'
                      : 'bg-slate-950/90 border-slate-800'
                  }`}
                >
                  <div className="space-y-2.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="font-bold text-white text-sm">{assoc.filename}</span>
                      <span
                        className={`font-semibold px-3 py-1 rounded-full text-xs border ${
                          isMismatch
                            ? 'bg-red-500/20 text-red-300 border-red-500/40'
                            : isConfirmed
                            ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                            : isRejected
                            ? 'bg-slate-800 text-slate-400 border-slate-700'
                            : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                        }`}
                      >
                        {isMismatch
                          ? 'Location Does Not Match'
                          : isConfirmed
                          ? '✓ Included in Project'
                          : isRejected
                          ? 'Skipped'
                          : 'Similar Location Found'}
                      </span>
                    </div>

                    {isMismatch ? (
                      <div className="p-3.5 rounded-xl bg-red-950/40 border border-red-500/25 space-y-1.5">
                        <p className="text-red-200 font-semibold text-xs">
                          This site drawing does not match the location in your Soil Report (
                          {session.projectAddress}).
                        </p>
                        {assoc.conflict_reasons.length > 0 && (
                          <p className="text-red-300/90 text-xs leading-relaxed">
                            Why it doesn&apos;t match: {assoc.conflict_reasons.join(' • ')}
                          </p>
                        )}
                      </div>
                    ) : (
                      <div className="p-3.5 rounded-xl bg-slate-900/90 border border-slate-800 space-y-1.5">
                        <p className="text-slate-200 font-medium text-xs leading-relaxed">
                          This site drawing is in the same subdivision and block as your Soil
                          Report, with a slight address difference:
                        </p>
                        {assoc.conflict_reasons.length > 0 && (
                          <p className="text-amber-300 text-xs">
                            • {assoc.conflict_reasons.join(' • ')}
                          </p>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap items-center justify-between gap-2 pt-3 border-t border-slate-800/80">
                    {isMismatch ? (
                      <>
                        <span className="text-xs text-red-300 font-medium">
                          {isConfirmed
                            ? 'Included manually by user'
                            : 'Automatically excluded because location does not match'}
                        </span>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            data-testid={`reject-assoc-${assoc.document_id}`}
                            disabled={isActionBusy}
                            onClick={() => onAssociationDecision(assoc.association_id, 'REJECTED')}
                            className="px-3 py-1.5 rounded-xl bg-red-500/20 hover:bg-red-500/30 border border-red-500/40 text-red-200 font-semibold"
                          >
                            Keep Excluded
                          </button>
                          <button
                            type="button"
                            data-testid={`confirm-assoc-${assoc.document_id}`}
                            disabled={isActionBusy}
                            onClick={() => onAssociationDecision(assoc.association_id, 'CONFIRMED')}
                            className="px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300"
                          >
                            Use Anyway
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <span className="text-xs text-slate-300">
                          {isConfirmed
                            ? 'Confirmed for this project'
                            : isRejected
                            ? 'Excluded from this project'
                            : 'Does this site plan belong to your project?'}
                        </span>
                        <div className="flex items-center gap-2">
                          <button
                            type="button"
                            data-testid={`confirm-assoc-${assoc.document_id}`}
                            disabled={isActionBusy}
                            onClick={() => onAssociationDecision(assoc.association_id, 'CONFIRMED')}
                            className="px-3.5 py-2 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold shadow-sm"
                          >
                            Yes, Use This Site Plan
                          </button>
                          <button
                            type="button"
                            data-testid={`reject-assoc-${assoc.document_id}`}
                            disabled={isActionBusy}
                            onClick={() => onAssociationDecision(assoc.association_id, 'REJECTED')}
                            className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 font-medium"
                          >
                            No, Skip File
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Main 12-Column Grid: Analysis Steps (8 cols) + Attached Documents Summary (4 cols) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        <div className="lg:col-span-8 rounded-3xl border border-slate-800/90 bg-slate-900/85 p-6 space-y-5 shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-800 pb-4">
            <div>
              <h2 className="text-lg font-bold text-white">Analysis &amp; Report Generation Steps</h2>
              <p className="text-xs text-slate-400">
                Real-time progress across document extraction, geotechnical analysis, foundation research, and vendor specs
              </p>
            </div>
            <span className="text-xs font-semibold px-3 py-1 rounded-full bg-slate-950 border border-slate-800 text-slate-300">
              {completedCount} / {stages.length} Done
            </span>
          </div>

          <div className="grid grid-cols-1 gap-3">
            {stages.map((stage) => {
              const isSucceeded = stage.status === 'SUCCEEDED';
              const isRunning = stage.status === 'RUNNING';
              const isFailed = stage.status === 'FAILED';
              const isNeedsReview = stage.status === 'NEEDS_REVIEW';

              return (
                <div
                  key={stage.id}
                  className={`p-4 rounded-2xl border transition-all flex items-start justify-between gap-4 ${
                    isSucceeded
                      ? 'bg-emerald-950/15 border-emerald-500/30'
                      : isRunning
                      ? 'bg-sky-950/20 border-sky-500/40 shadow-md shadow-sky-500/5'
                      : isFailed
                      ? 'bg-red-950/20 border-red-500/40'
                      : isNeedsReview
                      ? 'bg-amber-950/20 border-amber-500/40'
                      : 'bg-slate-950/60 border-slate-800/80'
                  }`}
                >
                  <div className="flex items-start gap-3.5">
                    <div className="mt-0.5">
                      {isSucceeded ? (
                        <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                      ) : isRunning ? (
                        <Loader2 className="w-5 h-5 text-sky-400 animate-spin" />
                      ) : isFailed ? (
                        <XCircle className="w-5 h-5 text-red-400" />
                      ) : isNeedsReview ? (
                        <AlertTriangle className="w-5 h-5 text-amber-400" />
                      ) : (
                        <Clock className="w-5 h-5 text-slate-500" />
                      )}
                    </div>
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-semibold text-amber-400/90">
                          Step {stage.number}
                        </span>
                        <span className="text-sm font-bold text-white">{stage.title}</span>
                      </div>
                      <p className="text-xs text-slate-400">{stage.subtitle}</p>
                      {stage.detail && (
                        <p className="text-xs text-slate-300 pt-0.5">{stage.detail}</p>
                      )}
                    </div>
                  </div>

                  <span
                    data-testid={`stage-status-${stage.id}`}
                    className={`text-[10px] font-mono uppercase px-2.5 py-1 rounded-full border shrink-0 ${
                      isSucceeded
                        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                        : isRunning
                        ? 'bg-sky-500/15 text-sky-300 border-sky-500/30'
                        : isFailed
                        ? 'bg-red-500/15 text-red-300 border-red-500/30'
                        : isNeedsReview
                        ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                        : 'bg-slate-900 text-slate-400 border-slate-700'
                    }`}
                  >
                    {stage.status}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Side Column: Project Files & Deliverable Preview (4 cols) */}
        <div className="lg:col-span-4 space-y-6">
          <div className="rounded-3xl border border-slate-800/90 bg-slate-900/85 p-6 space-y-4">
            <h3 className="text-sm font-bold text-white">
              Project Files ({documents.length})
            </h3>
            {documents.length === 0 ? (
              <p className="text-xs text-slate-400">Uploading project documents...</p>
            ) : (
              <div className="space-y-2.5 text-xs">
                {documents.map((doc) => (
                  <div
                    key={doc.document_id}
                    className="p-3.5 rounded-2xl bg-slate-950/90 border border-slate-800 flex items-center justify-between gap-2"
                  >
                    <span className="text-slate-200 font-medium truncate">{doc.filename}</span>
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-slate-900 border border-slate-800 text-slate-300 shrink-0">
                      {doc.page_count} {doc.page_count === 1 ? 'page' : 'pages'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="rounded-3xl border border-slate-800/90 bg-slate-900/85 p-6 space-y-3">
            <h3 className="text-sm font-bold text-white">What You Will Receive</h3>
            <ul className="space-y-2.5 text-xs text-slate-300">
              <li className="flex items-center gap-2.5">
                <CheckCircle2 className="w-4 h-4 text-amber-400 shrink-0" />
                <span>
                  <strong className="text-white">1. Geotechnical Analysis</strong> — Soil profile,
                  lab results, groundwater &amp; PVR swell
                </span>
              </li>
              <li className="flex items-center gap-2.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>
                  <strong className="text-white">2. Foundation Research</strong> — Shallow &amp;
                  deep foundation system comparisons
                </span>
              </li>
              <li className="flex items-center gap-2.5">
                <CheckCircle2 className="w-4 h-4 text-sky-400 shrink-0" />
                <span>
                  <strong className="text-white">3. Vendor Requirements</strong> — Complete scope of
                  work &amp; vendor proposal checklist
                </span>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};
export default ProcessingView;

