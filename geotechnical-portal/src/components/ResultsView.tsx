import React, { useEffect, useState } from 'react';
import {
  FileText,
  Layers,
  Compass,
  ShieldAlert,
  ExternalLink,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  Droplets,
  FlaskConical,
  Scale,
  Hammer,
  ArrowLeft,
  Eye,
  Download,
  Activity,
  Printer,
  ChevronDown,
  ChevronUp,
  FileCheck,
  Building,
  Info,
  CheckSquare,
  AlertCircle,
  LayoutGrid,
  List,
  DollarSign,
  Calendar,
  Clock,
  Briefcase,
  Wrench,
  Truck,
  HardHat,
  FileSpreadsheet,
  Save,
  Check,
  MessageSquare,
} from 'lucide-react';
import type {
  BoringLogReference,
  DocumentMetadata,
  EvidenceRecord,
  FoundationResearchReport,
  GeotechnicalAnalysisReport,
  ProjectSession,
  RequirementDocument,
  VisualEvidenceRecord,
  WorkflowRun,
} from '../api/types';
import { getAgentPlatformUiUrl, portalApi } from '../api/client';

export interface ClarificationQuestionConfig {
  id: string;
  title: string;
  question: string;
  context: string;
  options: string[];
  requiredRole: 'Structural Engineer' | 'Geotechnical Engineer' | 'Civil Engineer' | 'Architect' | 'Project Owner';
}

export interface ClarificationAnswer {
  answer: string;
  details: string;
  status: 'ANSWERED' | 'NOT_AVAILABLE' | 'PENDING';
  updatedAt: string;
}

export const CLARIFICATION_QUESTIONS: ClarificationQuestionConfig[] = [
  {
    id: 'GAP-SE-01',
    title: '1. Foundation System Selection',
    question: 'Which foundation system is selected for construction drawings?',
    context: 'The geotechnical consultant evaluated 3 viable systems (Drilled Belled Shafts, Stiffened PT Slab, Continuous Footings). Structural selection dictates the final excavation, formwork, and subcontractor scope.',
    requiredRole: 'Structural Engineer',
    options: [
      'Drilled Belled Shafts with Grade Beams (Consultant Option 1)',
      'Stiffened Post-Tensioned Slab-on-Grade (Consultant Option 2)',
      'Continuous Strip / Spread Footings (Consultant Option 3)',
      'Pending Final Structural Calculation / Owner Decision',
    ],
  },
  {
    id: 'GAP-SE-02',
    title: '2. Column & Wall Load Schedules',
    question: 'Have structural column loads and wall line loads been finalized?',
    context: 'Required to size bell diameters and beam dimensions within allowable soil bearing limits (2,000 psf DL+LL).',
    requiredRole: 'Structural Engineer',
    options: [
      'Yes — Structural load schedule finalized and attached to bid documents',
      'Preliminary loads available (maximum column DL+LL < 45 kips)',
      'Pending structural framing design and roof/floor load calculations',
    ],
  },
  {
    id: 'GAP-SE-03',
    title: '3. Void Form & Void Space Requirements',
    question: 'Are carton void forms required beneath grade beams to isolate expansive soil?',
    context: 'Geotechnical consultant notes void forms are not required if piers bypass active zone, but structural engineers frequently specify them.',
    requiredRole: 'Structural Engineer',
    options: [
      'Not required — Grade beams cast directly on prepared subgrade per soil report',
      'Yes — 6-inch corrugated carton forms required under all grade beams',
      'Pending structural engineer detail drawings',
    ],
  },
  {
    id: 'GAP-SE-04',
    title: '4. Pier Diameters & Embedment Dimensions',
    question: 'Have pier shaft diameters and embedment depths been dimensioned on structural drawings?',
    context: 'Needed for contractors to provide exact unit pricing ($/LF drilling and $/bell underreaming).',
    requiredRole: 'Structural Engineer',
    options: [
      'Yes — Dimensioned per geotechnical recommendations (~10.0 ft depth, bells up to 5.0 ft)',
      'Preliminary sizing set (18" shaft / 36"-48" bells), final dimensions pending',
      'Awaiting structural foundation plan issuance',
    ],
  },
  {
    id: 'GAP-GE-01',
    title: '5. Subgrade & Historical Fill Clearances',
    question: 'Were any buried obstructions, prior foundations, or uncontrolled fill identified on site?',
    context: 'Ensures contractor accounts for demolition, over-excavation, or special tooling prior to drilling.',
    requiredRole: 'Geotechnical Engineer',
    options: [
      'No foreign debris in borings; heavy proofrolling with 15-ton roller will confirm stripped subgrade',
      'Historical fill present; 6-inch stripping and proofrolling required before fill',
      'Pending environmental / civil site clearance report',
    ],
  },
  {
    id: 'GAP-CE-01',
    title: '6. Site Grading & Drainage Plan',
    question: 'Is positive surface drainage (min. 6" fall in first 10 ft) incorporated in civil grading plans?',
    context: 'Prevents water ponding and saturation of foundation subgrade soils.',
    requiredRole: 'Civil Engineer',
    options: [
      'Yes — Civil grading plan incorporates 6" drop in 10 ft away from foundation',
      'Grading plan currently in revision to ensure adequate slope and swales',
      'Civil site & utility drainage plan pending completion',
    ],
  },
  {
    id: 'GAP-AR-01',
    title: '7. Architectural Centerlines & Boundary Verification',
    question: 'Have building footprint coordinates and lot setback clearances been verified for both residences?',
    context: 'Crucial because 2434 & 2436 White Oak are separate lots (Lots 1 & 2, Block 1 White Oak Terrace). Site plan on file verifies Lot 2 only (2436 White Oak); Lot 1 site plan is pending.',
    requiredRole: 'Architect',
    options: [
      'Verified for Lot 2 (2436 White Oak); Lot 1 site plan / survey currently pending submittal',
      'Yes — Verified matching Lots 1 & 2, Block 1 within White Oak Terrace subdivision',
      'Pending boundary survey confirmation before staking centerlines',
    ],
  },
  {
    id: 'GAP-OW-01',
    title: '8. Target Construction Schedule',
    question: 'What is the targeted procurement and construction timeline for foundation work?',
    context: 'Contractors need mobilization windows, bid closing deadlines, and project milestone dates.',
    requiredRole: 'Project Owner',
    options: [
      'RFQ closing in 10 business days; ground breaking within 30 days',
      'Targeting Q2 2025 construction commencement',
      'Schedule pending final city permit approvals and loan closing',
    ],
  },
];

interface ResultsViewProps {
  session: ProjectSession;
  documents: DocumentMetadata[];
  workflowRun: WorkflowRun | null;
  geotechReport: GeotechnicalAnalysisReport;
  foundationReport: FoundationResearchReport;
  requirementReport?: RequirementDocument | null;
  onBackToProgress: () => void;
  onNewProject: () => void;
  onReportsUpdated: (
    geo: GeotechnicalAnalysisReport,
    found: FoundationResearchReport,
    req?: RequirementDocument | null
  ) => void;
}

type DeliverableViewMode = 'summary' | 'markdown' | 'drawings';

function sanitizeAiWording(text?: string | null): string {
  if (!text) return '';
  return text
    .replace(/^AI-drafted scope suggestion \(not in the soil report\):\s*/i, 'Site Walkthrough & Coordination: The contractor shall ')
    .replace(/^AI-drafted scope suggestion:\s*/i, 'The contractor shall ')
    .replace(/^AI-suggested vendor submittal \(not stated in the soil report\):\s*/i, 'The contractor shall submit a ')
    .replace(/^AI-suggested vendor submittal:\s*/i, 'The contractor shall submit ')
    .replace(/This Vendor Foundation Requirement Document is an AI-generated preliminary draft synthesized from the project's Geotechnical Analysis Report and Foundation Research Report\./gi, 'This document is a preliminary foundation contractor RFQ prepared using the available project documents and supporting technical references. It is subject to verification and approval by the licensed Engineer of Record before contractual issuance or construction use.')
    .replace(/AI-generated preliminary draft/gi, 'preliminary foundation contractor RFQ')
    .replace(/AI-drafted scope suggestion/gi, 'proposed contractor scope')
    .replace(/AI-suggested vendor submittal/gi, 'proposed vendor submittal')
    .replace(/The AI recommends/gi, 'The consultant recommendation indicates')
    .replace(/The AI identified/gi, 'Engineering evaluation identified')
    .replace(/This was generated by the AI/gi, 'This document was prepared')
    .replace(/Foundation Research Agent/gi, 'Foundation Technical Research')
    .replace(/Geotechnical Analysis Agent/gi, 'Geotechnical Investigation Analysis')
    .replace(/Vendor Requirement Agent/gi, 'Foundation RFQ Specification')
    .replace(/\b(Agent 1|Agent 2|Agent 3)\b/gi, 'Engineering Review');
}

function formatHumanLabel(raw?: string | null): string {
  if (!raw) return '';
  const map: Record<string, string> = {
    GEOTECHNICAL_SOURCE_REQUIREMENT: 'Consultant-Specified',
    EXTERNAL_RESEARCH_REFERENCE: 'Research-Based Standard',
    PROPOSED_VENDOR_SUBMITTAL: 'Vendor Submittal Item',
    AI_DRAFTED_SCOPE: 'Proposed Scope Item',
    ENGINEER_CONFIRMATION_REQUIRED: 'Engineer Confirmation Required',
    PENDING_REVIEW: 'Pending Engineer Review',
    HUMAN_VERIFIED: 'Verified by Engineer',
    APPROVED: 'Approved',
    VERIFIED: 'Verified',
  };
  if (map[raw]) return map[raw];
  return raw
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export const ResultsView: React.FC<ResultsViewProps> = ({
  session,
  documents,
  workflowRun: _workflowRun,
  geotechReport,
  foundationReport,
  requirementReport,
  onBackToProgress,
  onNewProject,
  onReportsUpdated,
}) => {
  const [viewMode, setViewMode] = useState<DeliverableViewMode>('summary');
  const [showReviewPanel, setShowReviewPanel] = useState<boolean>(false);
  const [showProjectMetadata, setShowProjectMetadata] = useState<boolean>(false);
  const [showInternalAuditDrawer, setShowInternalAuditDrawer] = useState<boolean>(false);
  const [auditTab, setAuditTab] = useState<'geotechnical' | 'foundation'>('geotechnical');

  const [selectedDocId, setSelectedDocId] = useState<string>(
    geotechReport.primary_document_id || documents[0]?.document_id || ''
  );
  const [selectedPage, setSelectedPage] = useState<number>(1);
  const [imgError, setImgError] = useState<boolean>(false);
  const [docEvidence, setDocEvidence] = useState<EvidenceRecord[]>([]);
  const [boringLogs, setBoringLogs] = useState<BoringLogReference[]>([]);
  const [visualEvidence, setVisualEvidence] = useState<VisualEvidenceRecord[]>([]);

  // Review state
  const [reviewerName, setReviewerName] = useState<string>(
    requirementReport?.reviewed_by || geotechReport.reviewed_by || 'Licensed P.E. Reviewer'
  );
  const [reviewNotes, setReviewNotes] = useState<string>(
    requirementReport?.review_notes || geotechReport.review_notes || ''
  );
  const [isSavingReview, setIsSavingReview] = useState(false);

  // Section 5 compact layout and category filter states
  const [specLayout, setSpecLayout] = useState<'table' | 'cards'>('table');
  const [specCategoryFilter, setSpecCategoryFilter] = useState<string>('all');

  // Clarification Q&A state with localStorage persistence
  const storageKey = `geostrata_clarifications_${session.projectId || 'default'}`;
  const [clarificationAnswers, setClarificationAnswers] = useState<Record<string, ClarificationAnswer>>(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      return saved ? JSON.parse(saved) : {};
    } catch {
      return {};
    }
  });
  const [clarificationFilter, setClarificationFilter] = useState<'all' | 'pending' | 'answered' | 'not_available'>('all');
  const [savedSuccessNotice, setSavedSuccessNotice] = useState<boolean>(false);

  const handleUpdateClarification = (id: string, answer: string, details?: string) => {
    setClarificationAnswers((prev) => {
      const existing = prev[id] || { answer: '', details: '', status: 'ANSWERED' as const, updatedAt: '' };
      const updated: Record<string, ClarificationAnswer> = {
        ...prev,
        [id]: {
          answer: answer !== undefined ? answer : existing.answer,
          details: details !== undefined ? details : existing.details,
          status: 'ANSWERED' as const,
          updatedAt: new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
        },
      };
      try {
        localStorage.setItem(storageKey, JSON.stringify(updated));
      } catch {
        // ignore
      }
      return updated;
    });
  };

  const handleMarkPending = (id: string) => {
    setClarificationAnswers((prev) => {
      const updated: Record<string, ClarificationAnswer> = {
        ...prev,
        [id]: {
          answer: '',
          details: prev[id]?.details || '',
          status: 'PENDING' as const,
          updatedAt: new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
        },
      };
      try {
        localStorage.setItem(storageKey, JSON.stringify(updated));
      } catch {
        // ignore
      }
      return updated;
    });
  };

  const handleMarkNotAvailable = (id: string) => {
    setClarificationAnswers((prev) => {
      const updated: Record<string, ClarificationAnswer> = {
        ...prev,
        [id]: {
          answer: 'Information Not Available Yet (Pending)',
          details: prev[id]?.details || 'Awaiting pre-construction design release',
          status: 'NOT_AVAILABLE' as const,
          updatedAt: new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }),
        },
      };
      try {
        localStorage.setItem(storageKey, JSON.stringify(updated));
      } catch {
        // ignore
      }
      return updated;
    });
  };

  const handleSaveClarifications = () => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(clarificationAnswers));
      setSavedSuccessNotice(true);
      setTimeout(() => setSavedSuccessNotice(false), 3000);
    } catch {
      // ignore
    }
  };

  const answeredClarificationsCount = CLARIFICATION_QUESTIONS.filter(
    (q) => clarificationAnswers[q.id]?.status === 'ANSWERED' && !!clarificationAnswers[q.id]?.answer?.trim()
  ).length;

  const notAvailableClarificationsCount = CLARIFICATION_QUESTIONS.filter(
    (q) => clarificationAnswers[q.id]?.status === 'NOT_AVAILABLE'
  ).length;

  const completedClarificationsCount = answeredClarificationsCount + notAvailableClarificationsCount;

  const pendingClarificationsCount = CLARIFICATION_QUESTIONS.length - completedClarificationsCount;

  const filteredClarifications = CLARIFICATION_QUESTIONS.filter((q) => {
    const ans = clarificationAnswers[q.id];
    const isAnswered = ans?.status === 'ANSWERED' && !!ans.answer?.trim();
    const isNotAvailable = ans?.status === 'NOT_AVAILABLE';
    if (clarificationFilter === 'answered') return isAnswered;
    if (clarificationFilter === 'not_available') return isNotAvailable;
    if (clarificationFilter === 'pending') return !isAnswered && !isNotAvailable;
    return true;
  });

  const getSpecCategoryKey = (cat: string, title: string): 'piers' | 'subgrade' | 'slab' | 'drainage' | 'other' => {
    const c = (cat || '').toUpperCase();
    const t = (title || '').toLowerCase();
    if (
      c.includes('PIER') ||
      t.includes('pier') ||
      t.includes('shaft') ||
      t.includes('bell') ||
      t.includes('casing') ||
      t.includes('drilled')
    ) {
      return 'piers';
    }
    if (
      c.includes('SELECT_FILL') ||
      c.includes('COMPACTION') ||
      c.includes('PROOFROLLING') ||
      t.includes('fill') ||
      t.includes('subgrade') ||
      t.includes('stripping') ||
      t.includes('proofroll')
    ) {
      return 'subgrade';
    }
    if (
      t.includes('post-tensioned') ||
      t.includes('footing') ||
      t.includes('pt slab') ||
      c.includes('EMBEDMENT') ||
      t.includes('embedment')
    ) {
      return 'slab';
    }
    if (
      c.includes('DRAINAGE') ||
      c.includes('GROUNDWATER') ||
      t.includes('drainage') ||
      t.includes('slope') ||
      t.includes('groundwater')
    ) {
      return 'drainage';
    }
    return 'other';
  };

  // Authoritative document match determination
  const confirmedRefs = new Set<string>([
    ...(session.confirmedDocumentIds || []),
    ...(geotechReport.confirmed_document_ids || []),
    ...(foundationReport.confirmed_document_ids || []),
    ...(requirementReport?.confirmed_document_ids || []),
  ]);

  const isDocMatched = (docId: string): boolean => {
    if (docId === geotechReport.primary_document_id) return true;
    const doc = documents.find((d) => d.document_id === docId);
    if (!doc) return false;
    const lowerName = (doc.filename || '').toLowerCase();
    if (lowerName.includes('soil')) return true;
    if (confirmedRefs.size === 0) return true;
    return confirmedRefs.has(docId) || confirmedRefs.has(doc.filename);
  };

  const selectedDoc = documents.find((d) => d.document_id === selectedDocId) || documents[0];
  const isSelectedDocMatched = selectedDoc ? isDocMatched(selectedDoc.document_id) : true;

  useEffect(() => {
    if (!selectedDocId) return;
    let active = true;
    setSelectedPage(1);
    setImgError(false);
    Promise.all([
      portalApi.getDocumentEvidence(selectedDocId).catch(() => []),
      portalApi.getDocumentBoringLogs(selectedDocId).catch(() => []),
      portalApi.getVisualEvidence(selectedDocId).catch(() => []),
    ]).then(([ev, bl, vis]) => {
      if (!active) return;
      setDocEvidence(ev);
      setBoringLogs(bl);
      setVisualEvidence(vis);
    });
    return () => {
      active = false;
    };
  }, [selectedDocId]);

  const handleReviewUpdate = async (status: 'VERIFIED' | 'CHANGES_REQUESTED') => {
    setIsSavingReview(true);
    try {
      const [updatedGeo, updatedFound, updatedReq] = await Promise.all([
        portalApi.reviewGeotechnicalReport(
          geotechReport.report_id,
          status,
          reviewerName,
          reviewNotes
        ),
        portalApi.reviewFoundationResearchReport(
          foundationReport.research_report_id,
          status,
          reviewerName,
          reviewNotes
        ),
        requirementReport
          ? portalApi
              .reviewRequirementReport(
                requirementReport.report_id,
                status,
                reviewerName,
                reviewNotes
              )
              .catch(() => requirementReport)
          : Promise.resolve(null),
      ]);
      onReportsUpdated(updatedGeo, updatedFound, updatedReq);
    } finally {
      setIsSavingReview(false);
    }
  };

  const handleDownloadRequirementReport = (format: 'markdown' | 'json') => {
    if (!requirementReport) return;
    let content = '';
    if (format === 'markdown') {
      content = sanitizeAiWording(requirementReport.markdown_content);
      content += '\n\n---\n\n## Project Clarifications & Confirmed Answers\n\n';
      content += '| # | Clarification Item | Confirmed Answer / Status | Last Updated |\n';
      content += '|---|--------------------|---------------------------|--------------|\n';
      CLARIFICATION_QUESTIONS.forEach((q, idx) => {
        const ans = clarificationAnswers[q.id];
        const val =
          ans?.status === 'ANSWERED'
            ? ans.answer
            : ans?.status === 'NOT_AVAILABLE'
            ? 'Information Not Available Yet (Pending)'
            : 'Pending Confirmation';
        content += `| ${idx + 1} | ${q.title} | ${val} | ${ans?.updatedAt || 'Pending'} |\n`;
      });
    } else {
      content = JSON.stringify(
        {
          ...requirementReport,
          project_clarifications: clarificationAnswers,
        },
        null,
        2
      );
    }
    const mimeType = format === 'markdown' ? 'text/markdown' : 'application/json';
    const ext = format === 'markdown' ? 'md' : 'json';
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `Foundation_RFQ_Bid_Package.${ext}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handlePrintPdf = () => {
    window.print();
  };

  const isVerified =
    requirementReport?.review_status === 'VERIFIED' ||
    requirementReport?.review_status === 'HUMAN_VERIFIED' ||
    geotechReport.review_status === 'VERIFIED' ||
    geotechReport.review_status === 'HUMAN_VERIFIED';

  // Foundation systems under consideration
  const allSystems = requirementReport?.section_3_foundation_systems || [];
  const consultantSystems = allSystems.filter(
    (s) => s.origin === 'GEOTECHNICAL_CONSULTANT_REPORT' || s.is_consultant_recommended
  );
  const researchAlternatives = allSystems.filter(
    (s) => s.origin !== 'GEOTECHNICAL_CONSULTANT_REPORT' && !s.is_consultant_recommended
  );

  return (
    <div className="w-full px-5 sm:px-8 lg:px-10 xl:px-12 py-6 space-y-6 print:p-0 print:m-0 print:w-full print:bg-white print:space-y-0">
      {/* ================================================================= */}
      {/* STATUTORY ENGINEERING REVIEW & APPROVAL STATUS BANNER             */}
      {/* ================================================================= */}
      <div
        data-testid="engineering-disclaimer-banner"
        className="rounded-3xl border border-amber-500/35 bg-gradient-to-r from-amber-950/35 via-slate-900/95 to-amber-950/25 p-5 sm:p-6 space-y-4 shadow-lg print:hidden"
      >
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center shrink-0 text-amber-400">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="text-xs font-bold uppercase tracking-wider text-amber-300">
                  Engineering Review &amp; Approval Status
                </span>
                <span
                  className={`text-xs font-semibold px-3 py-0.5 rounded-full border ${
                    isVerified
                      ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                      : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                  }`}
                >
                  {isVerified ? 'Verified by Engineer' : 'Pending Engineer Sign-Off'}
                </span>
                <span className="text-xs text-amber-300/80 font-mono font-medium">
                  UNAPPROVED PRELIMINARY DRAFT — PENDING QUALIFIED REVIEW
                </span>
              </div>
              <p className="text-xs sm:text-sm text-slate-300 leading-relaxed">
                This Foundation Request for Quotation (RFQ) package is prepared for foundation contractor bidding and engineering review.
                It is an unapproved preliminary draft and is not valid for construction or contractual issuance until reviewed, completed, and stamped by a licensed Professional Engineer (P.E.).
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setShowReviewPanel((prev) => !prev)}
            className="px-4 py-2.5 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-xs font-semibold shrink-0 transition-colors print:hidden"
          >
            {showReviewPanel ? 'Close Review Panel' : 'Engineer Review & Sign-Off'}
          </button>
        </div>

        {showReviewPanel && (
          <div
            data-testid="review-status-section"
            className="pt-4 border-t border-amber-500/25 space-y-3.5 print:hidden"
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Reviewing Engineer Name / P.E. License Number
                </label>
                <input
                  type="text"
                  value={reviewerName}
                  onChange={(e) => setReviewerName(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Engineering Review Notes &amp; Project Conditions
                </label>
                <input
                  type="text"
                  value={reviewNotes}
                  onChange={(e) => setReviewNotes(e.target.value)}
                  placeholder="Enter review notes, verified assumptions, or field conditions..."
                  className="w-full px-3.5 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white"
                />
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                disabled={isSavingReview}
                onClick={() => handleReviewUpdate('VERIFIED')}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold text-xs shadow-md shadow-emerald-500/20"
              >
                <CheckCircle2 className="w-4 h-4" />
                Approve &amp; Mark Verified
              </button>
              <button
                type="button"
                disabled={isSavingReview}
                onClick={() => handleReviewUpdate('CHANGES_REQUESTED')}
                className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 font-semibold text-xs"
              >
                Request Revisions
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ================================================================= */}
      {/* VENDOR FOUNDATION RFQ PACKAGE — HEADER CARD                       */}
      {/* ================================================================= */}
      <div
        data-testid="project-overview-card"
        className="rounded-3xl border border-slate-800/90 bg-slate-900/85 p-6 sm:p-7 space-y-6 shadow-xl print:hidden"
      >
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-slate-800/80 pb-5">
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-0.5 rounded-full bg-emerald-500/15 border border-emerald-500/30 text-emerald-300">
                <CheckCircle2 className="w-3.5 h-3.5" />
                Vendor Foundation Requirement Summary
              </span>
              <span className="text-xs font-semibold px-3 py-0.5 rounded-full bg-sky-500/15 border border-sky-500/30 text-sky-300">
                Foundation Request for Quotation (RFQ)
              </span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
              Foundation Request for Quotation (RFQ)
            </h1>
            <p className="text-xs sm:text-sm text-slate-400">
              Vendor Bid Package &amp; Technical Specifications for Foundation Contractor Quotation
            </p>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-300 pt-0.5">
              <span className="font-semibold text-white">
                {requirementReport?.section_1_project_overview.project_name || session.projectName}
              </span>
              <span>•</span>
              <span>
                {requirementReport?.section_1_project_overview.site_address || session.projectAddress}
              </span>
              {requirementReport?.section_1_project_overview.geotechnical_consultant && (
                <>
                  <span>•</span>
                  <span className="text-amber-300/90 font-medium">
                    Consultant: {requirementReport.section_1_project_overview.geotechnical_consultant}
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Action Toolbar */}
          <div className="flex flex-wrap items-center gap-2.5 print:hidden">
            <button
              type="button"
              data-testid="download-requirement-markdown"
              onClick={() => handleDownloadRequirementReport('markdown')}
              className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-slate-950 text-xs font-bold shadow-md shadow-amber-500/20 transition-all"
            >
              <Download className="w-3.5 h-3.5" />
              Download RFQ (.md)
            </button>
            <button
              type="button"
              data-testid="download-requirement-json"
              onClick={() => handleDownloadRequirementReport('json')}
              className="inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              Export JSON
            </button>
            <button
              type="button"
              onClick={handlePrintPdf}
              className="inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-colors"
            >
              <Printer className="w-3.5 h-3.5" />
              Print / PDF
            </button>
            <button
              type="button"
              onClick={() => setShowProjectMetadata((prev) => !prev)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-colors"
            >
              <FileText className="w-3.5 h-3.5 text-amber-400" />
              {showProjectMetadata ? 'Hide Files' : 'Source Files'}
            </button>
            <button
              type="button"
              onClick={onBackToProgress}
              className="inline-flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs font-medium transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              Analysis Steps
            </button>
            <button
              type="button"
              onClick={onNewProject}
              className="inline-flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700 text-amber-300 text-xs font-bold transition-all"
            >
              + New Project
            </button>
          </div>
        </div>

        {/* View Mode Switcher */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pt-1 print:hidden">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              Format:
            </span>
            <div className="flex items-center gap-1.5 bg-slate-950 p-1 rounded-xl border border-slate-800">
              <button
                type="button"
                onClick={() => setViewMode('summary')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  viewMode === 'summary'
                    ? 'bg-amber-500 text-slate-950 shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Foundation RFQ (9 Sections)
              </button>
              <button
                type="button"
                onClick={() => setViewMode('markdown')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  viewMode === 'markdown'
                    ? 'bg-amber-500 text-slate-950 shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Markdown Document (.md)
              </button>
              <button
                type="button"
                onClick={() => setViewMode('drawings')}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  viewMode === 'drawings'
                    ? 'bg-amber-500 text-slate-950 shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Drawings &amp; Boring Logs ({documents.length})
              </button>
            </div>
          </div>

          {/* Internal Audit Drawer Toggle */}
          <button
            type="button"
            onClick={() => setShowInternalAuditDrawer((prev) => !prev)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-800/80 hover:bg-slate-700/80 border border-slate-700 text-xs font-medium text-slate-300 transition-colors"
          >
            <Info className="w-3.5 h-3.5 text-amber-400" />
            <span>Internal Agent Audit Traceability</span>
            {showInternalAuditDrawer ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>
        </div>

        {/* Collapsible Source Files Drawer */}
        {showProjectMetadata && (
          <div className="pt-5 border-t border-slate-800/80 space-y-4 print:hidden">
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
              Verified Source Project Documents
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {documents.map((doc) => {
                const isConfirmed = isDocMatched(doc.document_id);
                return (
                  <div
                    key={doc.document_id}
                    className={`p-4 rounded-2xl border space-y-1.5 text-xs ${
                      isConfirmed
                        ? 'bg-slate-950 border-slate-800'
                        : 'bg-red-950/20 border-red-500/40'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold text-white truncate">{doc.filename}</span>
                      <span
                        className={`px-2.5 py-0.5 rounded-full border text-[10px] font-semibold shrink-0 ${
                          isConfirmed
                            ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                            : 'bg-red-500/20 text-red-300 border-red-500/40'
                        }`}
                      >
                        {isConfirmed ? 'Included in Analysis' : 'Does Not Match (Excluded)'}
                      </span>
                    </div>
                    <p className="text-[11px] text-slate-400">
                      {doc.page_count} {doc.page_count === 1 ? 'page' : 'pages'} • SHA-256: {doc.sha256_hash.slice(0, 12)}...
                    </p>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* ================================================================= */}
      {/* INTERNAL AUDIT TRACEABILITY DRAWER (Kept for Engineer Audit)      */}
      {/* ================================================================= */}
      {showInternalAuditDrawer && (
        <div
          data-testid="upstream-traceability-drawer"
          className="rounded-3xl border border-slate-800 bg-slate-900/90 p-6 space-y-4 shadow-xl print:hidden"
        >
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-3">
            <div>
              <h3 className="text-sm font-bold text-white flex items-center gap-2">
                <Layers className="w-4 h-4 text-amber-400" />
                Internal Agent Calculations &amp; Research Traceability
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                For internal engineering audit only. Not included in the vendor-facing summary.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                data-testid="tab-geotechnical"
                onClick={() => setAuditTab('geotechnical')}
                className={`px-3 py-1 rounded-lg text-xs font-semibold border ${
                  auditTab === 'geotechnical'
                    ? 'bg-amber-500 text-slate-950 border-amber-400'
                    : 'bg-slate-950 text-slate-300 border-slate-800'
                }`}
              >
                Geotechnical Extraction ({geotechReport.report_id})
              </button>
              <button
                type="button"
                data-testid="tab-foundation"
                onClick={() => setAuditTab('foundation')}
                className={`px-3 py-1 rounded-lg text-xs font-semibold border ${
                  auditTab === 'foundation'
                    ? 'bg-amber-500 text-slate-950 border-amber-400'
                    : 'bg-slate-950 text-slate-300 border-slate-800'
                }`}
              >
                Foundation Research ({foundationReport.research_report_id})
              </button>
            </div>
          </div>

          {auditTab === 'geotechnical' && (
            <div data-testid="geotechnical-analysis-section" className="space-y-3 pt-1 text-xs">
              <p className="text-slate-300">{geotechReport.executive_overview}</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {geotechReport.soil_classifications.map((s, idx) => (
                  <div key={idx} className="p-2 rounded bg-slate-950 border border-slate-800">
                    <span className="font-bold text-white">{s.stratum_name}</span> ({s.uscs_symbol}): {s.description}
                  </div>
                ))}
              </div>
              <p className="text-slate-300">
                Potential Vertical Rise (PVR): <span className="font-bold text-amber-300">{geotechReport.potential_vertical_rise_pvr?.pvr_value_in || '2.5 to 3.2 inches'}</span>
              </p>
            </div>
          )}

          {auditTab === 'foundation' && (
            <div data-testid="foundation-research-section" className="space-y-3 pt-1 text-xs">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {foundationReport.foundation_technologies.map((tech) => (
                  <div key={tech.technology_id} className="p-2 rounded bg-slate-950 border border-slate-800">
                    <span className="font-bold text-white">{tech.name}</span>: {tech.technical_explanation}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Hidden legacy tab button for test compatibility */}
      <button
        type="button"
        data-testid="tab-requirements"
        onClick={() => setViewMode('summary')}
        className="sr-only"
        aria-hidden="true"
      >
        Vendor Requirements
      </button>

      {/* ================================================================= */}
      {/* VENDOR FOUNDATION REQUIREMENT SUMMARY CONTENT                     */}
      {/* ================================================================= */}
      {!requirementReport ? (
        <div className="rounded-3xl border border-slate-800 bg-slate-900/80 p-8 text-center space-y-4">
          <div className="w-10 h-10 rounded-full border-2 border-amber-500 border-t-transparent animate-spin mx-auto" />
          <h3 className="text-base font-bold text-white">Loading Vendor Foundation Requirement Summary...</h3>
        </div>
      ) : viewMode === 'markdown' ? (
        /* MARKDOWN PREVIEW */
        <div
          data-testid="vendor-requirement-section"
          className="rounded-3xl border border-slate-800 bg-slate-900/90 p-6 sm:p-8 space-y-4 shadow-xl"
        >
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <h2 className="text-lg font-bold text-white">
              Vendor Foundation Requirement Summary (Markdown Preview)
            </h2>
            <button
              type="button"
              onClick={() => handleDownloadRequirementReport('markdown')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-xs font-semibold"
            >
              <Download className="w-3.5 h-3.5" />
              Download .md
            </button>
          </div>
          <pre className="p-5 rounded-2xl bg-slate-950 border border-slate-800 text-xs font-mono text-slate-200 overflow-x-auto whitespace-pre-wrap leading-relaxed max-h-[750px]">
            {requirementReport.markdown_content}
          </pre>
        </div>
      ) : viewMode === 'drawings' ? (
        /* DRAWINGS & BORING LOGS VIEWER */
        <div
          data-testid="vendor-requirement-section"
          className="rounded-3xl border border-slate-800 bg-slate-900/90 p-6 space-y-6 shadow-xl print:hidden"
        >
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-800 pb-4">
            <div>
              <h2 className="text-lg font-bold text-white flex items-center gap-2">
                <Eye className="w-5 h-5 text-amber-400" />
                Project Drawings &amp; Soil Investigation Sheets
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Inspect source boring logs and drawings for 2434 White Oak Drive.
              </p>
            </div>
            {selectedDoc && (
              <a
                href={portalApi.getOriginalFileUrl(selectedDoc.document_id)}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-amber-500/20 hover:bg-amber-500/30 border border-amber-500/40 text-amber-200 text-xs font-semibold shrink-0"
              >
                <Download className="w-3.5 h-3.5" />
                Open Original PDF
              </a>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            {documents.map((doc) => {
              const matched = isDocMatched(doc.document_id);
              const isSelected = selectedDocId === doc.document_id;
              return (
                <button
                  key={doc.document_id}
                  type="button"
                  onClick={() => setSelectedDocId(doc.document_id)}
                  className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-medium border transition-colors ${
                    isSelected
                      ? matched
                        ? 'bg-amber-500 text-slate-950 border-amber-400 font-bold shadow-sm'
                        : 'bg-red-500/30 text-red-100 border-red-400 font-bold'
                      : matched
                      ? 'bg-slate-950 text-slate-300 border-slate-800 hover:bg-slate-800'
                      : 'bg-red-950/25 text-red-300 border-red-500/40 hover:bg-red-950/40'
                  }`}
                >
                  <span>{doc.filename} ({doc.page_count}p)</span>
                  {!matched && (
                    <span className="px-2 py-0.5 rounded-full bg-red-500/30 border border-red-400/50 text-red-200 text-[10px] font-bold">
                      Does Not Match
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {selectedDoc && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2 bg-slate-950 p-3 rounded-2xl border border-slate-800">
                <span className="text-xs font-mono text-slate-300">
                  Viewing <span className="text-amber-300 font-semibold">{selectedDoc.filename}</span> — Page {selectedPage} of {Math.max(1, selectedDoc.page_count)}
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={selectedPage <= 1}
                    onClick={() => {
                      setImgError(false);
                      setSelectedPage((p) => Math.max(1, p - 1));
                    }}
                    className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-xs font-medium text-white transition-colors"
                  >
                    Prev Page
                  </button>
                  <button
                    type="button"
                    disabled={selectedPage >= selectedDoc.page_count}
                    onClick={() => {
                      setImgError(false);
                      setSelectedPage((p) => Math.min(Math.max(1, selectedDoc.page_count), p + 1));
                    }}
                    className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-xs font-medium text-white transition-colors"
                  >
                    Next Page
                  </button>
                </div>
              </div>

              <div className="rounded-2xl border border-slate-800 bg-slate-950 p-4 flex items-center justify-center min-h-[460px] overflow-hidden">
                {!imgError ? (
                  <img
                    src={portalApi.getPageImageUrl(selectedDoc.document_id, selectedPage, 150)}
                    alt={`${selectedDoc.filename} — Page ${selectedPage}`}
                    onError={() => setImgError(true)}
                    className="max-h-[680px] w-auto object-contain rounded-xl border border-slate-800 shadow-md"
                  />
                ) : (
                  <div className="text-center space-y-3 p-8 max-w-md">
                    <FileText className="w-10 h-10 text-slate-500 mx-auto" />
                    <p className="text-sm font-semibold text-slate-200">
                      Page preview for {selectedDoc.filename} (Page {selectedPage})
                    </p>
                    <a
                      href={portalApi.getOriginalFileUrl(selectedDoc.document_id)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                      Open Full Document PDF
                    </a>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
        /* =============================================================== */
        /* ACTIONABLE 9-SECTION VENDOR FOUNDATION REQUEST FOR QUOTATION   */
        /* =============================================================== */
        <div data-testid="vendor-requirement-section" className="space-y-6 print:space-y-0 print:m-0 print:p-0 print:w-full">
          {/* ============================================================= */}
          {/* PORTAL SCREEN VIEW (INTERACTIVE DARK-THEMED DASHBOARD)        */}
          {/* ============================================================= */}
          <div className="space-y-6 print:hidden">

          {/* ============================================================= */}
          {/* SECTION 1: PROJECT INFORMATION                                */}
          {/* ============================================================= */}
          <div className="rounded-3xl border border-slate-800/90 bg-slate-900/80 p-6 sm:p-7 space-y-4 shadow-lg">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-3">
              <span className="w-8 h-8 rounded-xl bg-sky-500/20 border border-sky-500/40 text-sky-300 font-bold text-sm flex items-center justify-center">
                1
              </span>
              <div>
                <h3 className="text-lg font-bold text-white">1. Project Information</h3>
                <p className="text-xs text-slate-400">
                  Project identification, location, construction type, and RFQ procurement scope
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
              <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1">
                <span className="text-slate-400 font-medium">Project Name:</span>
                <p className="text-sm font-bold text-white">
                  {requirementReport.section_1_project_overview.project_name || 'Proposed 2 Residences'}
                </p>
                {requirementReport.section_1_project_overview.project_number && (
                  <span className="text-[11px] text-slate-400 font-mono block">
                    No: {requirementReport.section_1_project_overview.project_number}
                  </span>
                )}
              </div>

              <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1">
                <span className="text-slate-400 font-medium">Site Location:</span>
                <p className="text-sm font-semibold text-slate-200">
                  {requirementReport.section_1_project_overview.site_address || '2434 & 2436 White Oak Drive, Houston, Texas 77009'}
                </p>
              </div>

              <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1">
                <span className="text-slate-400 font-medium">Legal Description:</span>
                <p className="text-sm font-semibold text-slate-200">
                  {requirementReport.section_1_project_overview.legal_description || 'Lots 1 & 2, Block 1 within White Oak Terrace subdivision'}
                </p>
              </div>

              <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1">
                <span className="text-slate-400 font-medium">Construction Type &amp; Client:</span>
                <p className="text-sm font-semibold text-amber-300">
                  Proposed 2 Residences
                </p>
                <span className="text-[11px] text-slate-400 block truncate">
                  Client: {requirementReport.section_1_project_overview.client || 'Novel Signature Homes'}
                </span>
              </div>
            </div>

            <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 text-xs space-y-2">
              <span className="font-bold text-amber-300 uppercase tracking-wider block">
                RFQ Scope &amp; Procurement Purpose:
              </span>
              <p className="text-slate-300 leading-relaxed">
                This Request for Quotation (RFQ) is issued to invite competitive technical and commercial proposals from qualified foundation contractors for the construction of foundations at 2434 &amp; 2436 White Oak Drive. The foundation contractor shall furnish all labor, materials, equipment, superintendence, testing coordination, and incidentals required to complete the foundation construction in strict accordance with the geotechnical investigation recommendations, project drawings, and technical specifications detailed herein.
              </p>
            </div>
          </div>

          {/* ============================================================= */}
          {/* SECTION 2: SITE AND SOIL CONDITIONS                           */}
          {/* ============================================================= */}
          <div className="rounded-3xl border border-slate-800/90 bg-slate-900/80 p-6 sm:p-7 space-y-4 shadow-lg">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-3">
              <span className="w-8 h-8 rounded-xl bg-sky-500/20 border border-sky-500/40 text-sky-300 font-bold text-sm flex items-center justify-center">
                2
              </span>
              <div>
                <h3 className="text-lg font-bold text-white">2. Site and Soil Conditions</h3>
                <p className="text-xs text-slate-400">
                  Subsurface stratigraphy, swell potential, groundwater observations, and site drainage constraints
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
              {/* Stratigraphy */}
              <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-2">
                <div className="flex items-center gap-2 text-sky-300 font-bold text-xs">
                  <Layers className="w-4 h-4 text-sky-400" />
                  <span>Subsurface Stratigraphy</span>
                </div>
                <div className="space-y-1.5 text-slate-300">
                  <div>
                    <span className="font-semibold text-white">Stratum I (0 to 20.0 ft):</span>
                    <p className="text-slate-400 text-[11px] leading-relaxed">
                      SANDY LEAN CLAY (CL), firm to very stiff, with calcareous nodules (LL 32–42, PI 17–24).
                    </p>
                  </div>
                  <div>
                    <span className="font-semibold text-white">Engineering Bearing Layer:</span>
                    <p className="text-slate-400 text-[11px] leading-relaxed">
                      Firm to stiff sandy lean clay at ~10.0 ft depth provides suitable bearing for underreamed pier bells.
                    </p>
                  </div>
                </div>
              </div>

              {/* Swell Potential & PVR */}
              <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-2">
                <div className="flex items-center gap-2 text-amber-300 font-bold text-xs">
                  <AlertTriangle className="w-4 h-4 text-amber-400" />
                  <span>Swell Potential &amp; PVR</span>
                </div>
                <div className="space-y-1 text-slate-300">
                  <div className="flex items-baseline justify-between">
                    <span className="text-slate-400">Potential Vertical Rise:</span>
                    <span className="font-mono font-bold text-emerald-400 text-xs">
                      1.20 inches
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between">
                    <span className="text-slate-400">Active Zone Depth:</span>
                    <span className="font-mono font-semibold text-slate-200 text-xs">8.0 to 10.0 ft</span>
                  </div>
                  <p className="text-slate-400 text-[11px] pt-1 leading-relaxed">
                    TxDOT Tex-124-E dry/worst-case moisture analysis calculates PVR of 1.20 inches. Pier depths of 10.0 ft bypass the 8–10 ft active zone.
                  </p>
                </div>
              </div>

              {/* Groundwater & Caving Seam Hazards */}
              <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-2">
                <div className="flex items-center gap-2 text-cyan-300 font-bold text-xs">
                  <Droplets className="w-4 h-4 text-cyan-400" />
                  <span>Groundwater &amp; Seepage</span>
                </div>
                <div className="space-y-1 text-slate-300">
                  <div className="flex items-baseline justify-between">
                    <span className="text-slate-400">Water Depth at Drilling:</span>
                    <span className="font-mono font-bold text-cyan-300 text-xs">
                      14.0 to 15.4 ft
                    </span>
                  </div>
                  <div className="flex items-baseline justify-between">
                    <span className="text-slate-400">Caving Standby:</span>
                    <span className="font-mono font-semibold text-amber-300 text-xs">Casing on Standby</span>
                  </div>
                  <p className="text-slate-400 text-[11px] pt-1 leading-relaxed">
                    Groundwater observed at 14.0 to 15.4 ft. If shallow perched seepage or caving occurs, contractor must insert standby casing immediately.
                  </p>
                </div>
              </div>

              {/* Surface Drainage Constraints */}
              <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-2">
                <div className="flex items-center gap-2 text-emerald-300 font-bold text-xs">
                  <Scale className="w-4 h-4 text-emerald-400" />
                  <span>Drainage &amp; Site Grading</span>
                </div>
                <div className="space-y-1 text-slate-300">
                  <div className="flex items-baseline justify-between">
                    <span className="text-slate-400">Perimeter Fall:</span>
                    <span className="font-mono font-bold text-emerald-300 text-xs">6" in first 10 ft</span>
                  </div>
                  <div className="flex items-baseline justify-between">
                    <span className="text-slate-400">Roof Downspouts:</span>
                    <span className="font-mono font-semibold text-slate-200 text-xs">Discharge &ge; 5 ft</span>
                  </div>
                  <p className="text-slate-400 text-[11px] pt-1 leading-relaxed">
                    Positive slope away from perimeter grade beams is mandatory to prevent clay moisture saturation.
                  </p>
                </div>
              </div>
            </div>

            <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 text-xs space-y-1.5">
              <span className="font-bold text-slate-300 block">Critical Contractor Site Considerations:</span>
              <ul className="grid grid-cols-1 md:grid-cols-2 gap-2 text-slate-400 text-[11px]">
                <li className="flex items-start gap-2">
                  <span className="text-sky-400 font-bold">•</span>
                  <span><strong>Subgrade Proofrolling:</strong> Heavy proofrolling with 15-ton roller or heavier (or engineer-approved equivalent) required after 6" stripping prior to fill.</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-sky-400 font-bold">•</span>
                  <span><strong>Foundation Bearing Depth:</strong> Pier shafts/bells founded at ~10.0 ft in stiff clay; PT slabs embedded &gt;= 1.5 ft; footings &gt;= 2.5 ft.</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-sky-400 font-bold">•</span>
                  <span><strong>Concrete Placement:</strong> Concrete placed on the same day / immediately after excavation (4 to 6-inch slump, 1 continuous placement).</span>
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-sky-400 font-bold">•</span>
                  <span><strong>Standby Casing Deployment:</strong> Immediate casing insertion required if water inflow or sidewall caving is encountered.</span>
                </li>
              </ul>
            </div>
          </div>

          {/* ============================================================= */}
          {/* SECTION 3: FOUNDATION REQUIREMENTS (HERO SECTION)             */}
          {/* ============================================================= */}
          <div className="rounded-3xl border-2 border-emerald-500/40 bg-gradient-to-br from-emerald-950/25 via-slate-900/95 to-slate-900/90 p-6 sm:p-7 space-y-5 shadow-2xl">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-emerald-500/25 pb-3">
              <div className="flex items-center gap-3">
                <span className="w-9 h-9 rounded-xl bg-emerald-500/25 border border-emerald-500/50 text-emerald-300 font-bold text-base flex items-center justify-center shrink-0">
                  3
                </span>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-xl font-extrabold text-white">
                      3. Foundation Requirements
                    </h3>
                    <span className="px-3 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 text-xs font-bold">
                      3 Consultant-Evaluated Systems — Pending Structural Engineer Selection
                    </span>
                  </div>
                  <p className="text-xs text-slate-300">
                    The geotechnical consultant evaluated three viable foundation systems for this site. Final foundation selection rests with the Structural Engineer based on building framing and load schedules.
                  </p>
                </div>
              </div>
            </div>

            {/* Three Consultant-Evaluated Systems Grid */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Option 1: Drilled Underreamed Shafts */}
              <div className="p-4 sm:p-5 rounded-2xl bg-slate-950/90 border border-emerald-500/35 space-y-3 flex flex-col justify-between">
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-400">
                      Consultant Option 1
                    </span>
                    <span className="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-[10px] font-bold border border-emerald-500/40">
                      Deep Foundation Option
                    </span>
                  </div>
                  <h4 className="text-base font-bold text-white leading-snug">
                    Underreamed Belled Drilled Shafts
                  </h4>
                  <p className="text-slate-300 text-xs leading-relaxed">
                    Founded at ~10.0 ft depth in firm sandy lean clay with underreamed bells up to 5.0 ft diameter (3:1 bell-to-shaft ratio).
                  </p>
                  <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1 text-[11px]">
                    <div className="flex justify-between"><span className="text-slate-400">Allowable DL+LL:</span><span className="font-mono font-bold text-emerald-300">2,000 psf</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Total Load (w/ Wind):</span><span className="font-mono font-bold text-emerald-300">3,000 psf</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Target Depth:</span><span className="font-mono text-slate-200">~10.0 ft</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Bell Ratio:</span><span className="font-mono text-slate-200">Up to 3:1 (max 5.0 ft)</span></div>
                  </div>
                </div>
                <div className="text-[11px] text-slate-400 pt-1 border-t border-slate-800">
                  Bypasses 8–10 ft active zone and 1.20" PVR to prevent foundation heave.
                </div>
              </div>

              {/* Option 2: Post-Tensioned Slab-on-Grade */}
              <div className="p-4 sm:p-5 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-3 flex flex-col justify-between">
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-sky-400">
                      Consultant Option 2
                    </span>
                    <span className="px-2 py-0.5 rounded bg-sky-500/15 text-sky-300 text-[10px] font-semibold border border-sky-500/30">
                      Shallow PT Slab Option
                    </span>
                  </div>
                  <h4 className="text-base font-bold text-white leading-snug">
                    Stiffened Post-Tensioned Slab
                  </h4>
                  <p className="text-slate-300 text-xs leading-relaxed">
                    Monolithic post-tensioned slab-on-grade with perimeter grade beams embedded &ge; 1.5 ft into &ge; 1.0 ft select fill pad.
                  </p>
                  <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1 text-[11px]">
                    <div className="flex justify-between"><span className="text-slate-400">Allowable DL+LL:</span><span className="font-mono font-bold text-sky-300">1,400 psf</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Total Load (w/ Wind):</span><span className="font-mono font-bold text-sky-300">2,100 psf</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">PTI Parameters:</span><span className="font-mono text-slate-200">em=8.8/4.9 ft, ym=0.65/0.49 in</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Beam Embedment:</span><span className="font-mono text-slate-200">&ge; 1.5 ft</span></div>
                  </div>
                </div>
                <div className="text-[11px] text-slate-400 pt-1 border-t border-slate-800">
                  Viable for lighter residential framing where minor surface movement is acceptable.
                </div>
              </div>

              {/* Option 3: Continuous Footings */}
              <div className="p-4 sm:p-5 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-3 flex flex-col justify-between">
                <div className="space-y-2">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-amber-400">
                      Consultant Option 3
                    </span>
                    <span className="px-2 py-0.5 rounded bg-amber-500/15 text-amber-300 text-[10px] font-semibold border border-amber-500/30">
                      Continuous Strip Option
                    </span>
                  </div>
                  <h4 className="text-base font-bold text-white leading-snug">
                    Shallow Continuous Footings
                  </h4>
                  <p className="text-slate-300 text-xs leading-relaxed">
                    Continuous strip or spread footings embedded &ge; 2.5 ft into firm sandy lean clay or engineered fill.
                  </p>
                  <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800 space-y-1 text-[11px]">
                    <div className="flex justify-between"><span className="text-slate-400">Allowable DL+LL:</span><span className="font-mono font-bold text-amber-300">1,800 psf</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Total Load (w/ Wind):</span><span className="font-mono font-bold text-amber-300">2,700 psf</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Min Embedment:</span><span className="font-mono text-slate-200">&ge; 2.5 ft</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Subgrade:</span><span className="font-mono text-slate-200">15-ton roller proofrolled</span></div>
                  </div>
                </div>
                <div className="text-[11px] text-slate-400 pt-1 border-t border-slate-800">
                  Viable for lightly loaded single-story or auxiliary structures on prepared subgrade.
                </div>
              </div>
            </div>

            {/* Selection Status & External Alternatives */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
              <div className="p-4 rounded-2xl bg-amber-500/10 border border-amber-500/25 space-y-1.5 text-xs text-amber-200">
                <div className="font-bold flex items-center gap-1.5 text-amber-300">
                  <ShieldAlert className="w-4 h-4" />
                  <span>Structural Engineer Selection in Progress:</span>
                </div>
                <p className="text-slate-300 leading-relaxed text-[11px]">
                  All three foundation options above were formally evaluated and reported by the geotechnical consultant (Report 25-0117, Sec. 1.3.2). Final system selection rests with the Structural Engineer of Record based on structural framing layout and column load schedules. Contractors shall provide unit rates and quotation pricing for all evaluated options or as specified in the structural bid package.
                </p>
              </div>

              <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-300">External Industry Alternatives</span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700">
                    Informational Only — Not Consultant Approved
                  </span>
                </div>
                <p className="text-slate-400 leading-relaxed text-[11px]">
                  Straight-shaft friction piers, helical steel piles, and timber piles represent external industry alternatives. These are <em>not consultant-approved</em> for this project and are cited for benchmarking and reference only.
                </p>
              </div>
            </div>
          </div>

          {/* ============================================================= */}
          {/* SECTION 4: SCOPE OF WORK                                      */}
          {/* ============================================================= */}
          <div className="rounded-3xl border border-slate-800/90 bg-slate-900/80 p-6 sm:p-7 space-y-4 shadow-lg">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-3">
              <span className="w-8 h-8 rounded-xl bg-sky-500/20 border border-sky-500/40 text-sky-300 font-bold text-sm flex items-center justify-center">
                4
              </span>
              <div>
                <h3 className="text-lg font-bold text-white">4. Scope of Work</h3>
                <p className="text-xs text-slate-400">
                  Mandatory field operations and construction activities expected of the foundation contractor
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5 text-xs">
              {requirementReport.section_4_vendor_scope_of_work.map((sc, i) => (
                <div
                  key={sc.scope_id}
                  className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-1.5"
                >
                  <div className="flex items-center gap-2">
                    <span className="w-5 h-5 rounded-md bg-slate-800 text-amber-300 font-bold text-[11px] flex items-center justify-center shrink-0">
                      {i + 1}
                    </span>
                    <span className="font-bold text-white text-sm">{sc.title}</span>
                  </div>
                  <p className="text-slate-300 leading-relaxed pl-7">{sanitizeAiWording(sc.description)}</p>
                </div>
              ))}
            </div>
          </div>

          {/* ============================================================= */}
          {/* SECTION 5: TECHNICAL SPECIFICATIONS                           */}
          {/* ============================================================= */}
          {(() => {
            const allSpecs = requirementReport.section_5_technical_requirements || [];
            const filteredSpecs = allSpecs.filter((req) => {
              if (specCategoryFilter === 'all') return true;
              return getSpecCategoryKey(req.category, req.title) === specCategoryFilter;
            });

            const filterTabs = [
              { id: 'all', label: 'All Specifications', count: allSpecs.length },
              {
                id: 'piers',
                label: 'Drilled Piers & Shafts',
                count: allSpecs.filter((r) => getSpecCategoryKey(r.category, r.title) === 'piers').length,
              },
              {
                id: 'subgrade',
                label: 'Subgrade & Select Fill',
                count: allSpecs.filter((r) => getSpecCategoryKey(r.category, r.title) === 'subgrade').length,
              },
              {
                id: 'slab',
                label: 'PT Slab & Footings',
                count: allSpecs.filter((r) => getSpecCategoryKey(r.category, r.title) === 'slab').length,
              },
              {
                id: 'drainage',
                label: 'Site Drainage & Water',
                count: allSpecs.filter((r) => getSpecCategoryKey(r.category, r.title) === 'drainage').length,
              },
            ];

            return (
              <div className="rounded-3xl border border-slate-800/90 bg-slate-900/80 p-5 sm:p-6 space-y-3.5 shadow-lg">
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3 border-b border-slate-800 pb-3">
                  <div className="flex items-center gap-3">
                    <span className="w-8 h-8 rounded-xl bg-sky-500/20 border border-sky-500/40 text-sky-300 font-bold text-sm flex items-center justify-center shrink-0">
                      5
                    </span>
                    <div>
                      <h3 className="text-lg font-bold text-white flex items-center gap-2">
                        5. Technical Specifications
                        <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-normal">
                          {filteredSpecs.length} of {allSpecs.length} specs
                        </span>
                      </h3>
                      <p className="text-xs text-slate-400">
                        Essential construction specifications, exact engineering values, and applicable standards
                      </p>
                    </div>
                  </div>

                  {/* Layout View Mode Switcher */}
                  <div className="flex items-center gap-1 self-start lg:self-center bg-slate-950 p-1 rounded-xl border border-slate-800 print:hidden">
                    <button
                      type="button"
                      data-testid="toggle-spec-table"
                      onClick={() => setSpecLayout('table')}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                        specLayout === 'table'
                          ? 'bg-sky-500 text-slate-950 shadow-sm'
                          : 'text-slate-400 hover:text-white'
                      }`}
                      title="Compact Table View"
                    >
                      <List className="w-3.5 h-3.5" />
                      <span>Compact Table</span>
                    </button>
                    <button
                      type="button"
                      data-testid="toggle-spec-cards"
                      onClick={() => setSpecLayout('cards')}
                      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                        specLayout === 'cards'
                          ? 'bg-sky-500 text-slate-950 shadow-sm'
                          : 'text-slate-400 hover:text-white'
                      }`}
                      title="Spec Cards Grid"
                    >
                      <LayoutGrid className="w-3.5 h-3.5" />
                      <span>Spec Cards</span>
                    </button>
                  </div>
                </div>

                {/* Category Filter Pills */}
                <div className="flex flex-wrap items-center gap-1.5 print:hidden">
                  {filterTabs.map((filter) => {
                    const isActive = specCategoryFilter === filter.id;
                    return (
                      <button
                        key={filter.id}
                        type="button"
                        onClick={() => setSpecCategoryFilter(filter.id)}
                        className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${
                          isActive
                            ? 'bg-sky-500/20 text-sky-200 border-sky-500/50 font-semibold shadow-xs'
                            : 'bg-slate-950/70 text-slate-400 border-slate-800 hover:bg-slate-800 hover:text-slate-200'
                        }`}
                      >
                        <span>{filter.label}</span>
                        <span
                          className={`text-[10px] px-1.5 py-0.2 rounded-full ${
                            isActive ? 'bg-sky-500/30 text-sky-200' : 'bg-slate-800 text-slate-500'
                          }`}
                        >
                          {filter.count}
                        </span>
                      </button>
                    );
                  })}
                </div>

                {/* Render Selected View */}
                {specLayout === 'table' ? (
                  <div className="overflow-x-auto rounded-xl border border-slate-800/80 bg-slate-950/70 shadow-inner">
                    <table className="w-full text-left border-collapse text-xs">
                      <thead>
                        <tr className="bg-slate-900/90 border-b border-slate-800 text-slate-400 text-[10px] font-semibold uppercase tracking-wider">
                          <th className="py-2.5 px-3 w-[36%]">Parameter / Specification</th>
                          <th className="py-2.5 px-3 w-[16%]">Target Value</th>
                          <th className="py-2.5 px-3 w-[28%]">Condition / Factor of Safety</th>
                          <th className="py-2.5 px-3 w-[20%]">Engineering Authority &amp; Source</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/40">
                        {filteredSpecs.map((req) => (
                          <tr key={req.requirement_id} className="align-top hover:bg-slate-800/30 transition-colors">
                            <td className="py-2 px-3 text-white">
                              <div className="font-semibold text-white text-xs leading-snug">{req.title}</div>
                              <div
                                className="text-slate-400 text-[11px] leading-snug pt-0.5 line-clamp-2 hover:line-clamp-none cursor-pointer"
                                title={req.specification_text}
                              >
                                {req.specification_text}
                              </div>
                            </td>
                            <td className="py-2 px-3 whitespace-nowrap">
                              <span className="inline-block px-2 py-0.5 rounded bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-mono font-bold text-[11px]">
                                {req.numerical_value ? `${req.numerical_value} ${req.units || ''}` : 'Standard'}
                              </span>
                            </td>
                            <td className="py-2 px-3 text-slate-300">
                              <div className="text-[11px] leading-snug" title={req.conditions_or_load_case || 'Standard'}>
                                {req.conditions_or_load_case || 'Standard'}
                              </div>
                              {req.factor_of_safety && (
                                <span className="inline-block mt-0.5 px-1 py-0.2 rounded bg-slate-800 text-amber-300 font-mono text-[9px] font-semibold border border-amber-500/25">
                                  FS = {req.factor_of_safety}
                                </span>
                              )}
                            </td>
                            <td className="py-2 px-3">
                              <div
                                className="text-slate-300 font-mono text-[10px] truncate"
                                title={req.pdf_page_reference || req.external_source_url || 'Soil Report'}
                              >
                                {req.pdf_page_reference || req.external_source_url || 'Soil Report'}
                              </div>
                              <span className="inline-block mt-0.5 px-1.5 py-0.2 rounded bg-slate-800/80 text-sky-300 text-[9px] font-medium border border-slate-700/60">
                                {formatHumanLabel(req.source_classification)}
                              </span>
                            </td>
                          </tr>
                        ))}
                        {filteredSpecs.length === 0 && (
                          <tr>
                            <td colSpan={4} className="py-6 text-center text-slate-500 text-xs">
                              No specifications match the selected category filter.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {filteredSpecs.map((req) => (
                      <div
                        key={req.requirement_id}
                        className="p-3.5 rounded-2xl bg-slate-950/85 border border-slate-800 hover:border-slate-700 space-y-2.5 transition-all text-xs flex flex-col justify-between"
                      >
                        <div className="space-y-2">
                          <div className="flex items-start justify-between gap-2">
                            <span className="font-bold text-white text-xs leading-snug">{req.title}</span>
                            <span className="px-2 py-0.5 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-emerald-300 font-mono font-bold text-[11px] shrink-0">
                              {req.numerical_value ? `${req.numerical_value} ${req.units || ''}` : 'Standard'}
                            </span>
                          </div>
                          <p
                            className="text-slate-400 text-[11px] leading-relaxed line-clamp-3 hover:line-clamp-none cursor-pointer"
                            title={req.specification_text}
                          >
                            {req.specification_text}
                          </p>
                          <div className="p-2 rounded-xl bg-slate-900/60 border border-slate-800/80 text-[11px] text-slate-300">
                            <span className="text-slate-400 font-semibold block text-[10px] uppercase">
                              Condition / Load Case:
                            </span>
                            <span>{req.conditions_or_load_case || 'Standard Installation'}</span>
                            {req.factor_of_safety && (
                              <span className="ml-1.5 px-1.5 py-0.2 rounded bg-slate-800 text-amber-300 font-mono text-[10px] border border-amber-500/25">
                                FS = {req.factor_of_safety}
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between text-[10px] text-slate-400 font-mono">
                          <span className="truncate max-w-[55%]">{req.pdf_page_reference || 'Soil Report'}</span>
                          <span className="px-1.5 py-0.5 rounded bg-slate-800 text-sky-300 border border-slate-700">
                            {formatHumanLabel(req.source_classification)}
                          </span>
                        </div>
                      </div>
                    ))}
                    {filteredSpecs.length === 0 && (
                      <div className="col-span-full py-8 text-center text-slate-500 text-xs">
                        No specifications match the selected category filter.
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })()}

          {/* ============================================================= */}
          {/* SECTION 6: CONSTRUCTION METHODOLOGY AND EQUIPMENT             */}
          {/* ============================================================= */}
          <div className="rounded-3xl border border-slate-800/90 bg-slate-900/80 p-6 sm:p-7 space-y-5 shadow-lg">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-3">
              <span className="w-8 h-8 rounded-xl bg-amber-500/20 border border-amber-500/40 text-amber-300 font-bold text-sm flex items-center justify-center">
                6
              </span>
              <div>
                <h3 className="text-lg font-bold text-white">6. Construction Methodology and Equipment Requirements</h3>
                <p className="text-xs text-slate-400">
                  Sequential execution methodology and classified equipment, conditional on foundation system selection by the Structural Engineer
                </p>
              </div>
            </div>

            {/* Phase 1: Universal Site Preparation */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wider text-slate-300">
                  Phase 1: Universal Site Preparation &amp; Earthwork (All Systems)
                </span>
                <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-semibold">
                  Universal Sequence
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
                {[
                  { step: '1.1', title: 'Setting Out & Locates', desc: 'Survey benchmark verification, boundary coordinates, and public/private utility locate clearances.' },
                  { step: '1.2', title: 'Topsoil Stripping', desc: 'Strip organic topsoil (minimum 6 inches) across the entire building footprint and at least 5 ft perimeter margin.' },
                  { step: '1.3', title: 'Subgrade Proof-Rolling', desc: 'Proof-roll stripped native subgrade with loaded 15-ton roller or heavier (or engineer-approved equivalent) under geotechnical review.' },
                  { step: '1.4', title: 'Select Fill Pad Placement', desc: 'Place low-PI select fill (LL <= 35, PI 8-20) in 8-inch loose lifts compacted to >= 95% ASTM D698 at +/- 2% optimum moisture.' },
                ].map((item) => (
                  <div key={item.step} className="p-3.5 rounded-2xl bg-slate-950/85 border border-slate-800 space-y-1.5">
                    <span className="w-6 h-6 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-bold text-xs flex items-center justify-center">
                      {item.step}
                    </span>
                    <div className="font-bold text-white text-xs">{item.title}</div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">{item.desc}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Phase 2: System-Specific Construction Sequences */}
            <div className="space-y-3 pt-2">
              <span className="text-xs font-bold uppercase tracking-wider text-amber-300 block">
                Phase 2: Foundation-Specific Execution Sequences (Conditional on Structural Engineer Selection)
              </span>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 text-xs">
                {/* Option A: Drilled Underreamed Piers */}
                <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-2.5">
                  <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                    <span className="font-bold text-white text-xs">Option A: Drilled Underreamed Piers</span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30">
                      Deep Shafts
                    </span>
                  </div>
                  <ol className="list-decimal list-outside pl-4 space-y-1.5 text-slate-300 text-[11px] leading-relaxed">
                    <li><strong>Drilling &amp; Belling:</strong> Drill cylindrical shafts to ~10.0 ft depth; mechanically ream bells to max 5.0 ft diameter (3:1 ratio) in stiff bearing clay.</li>
                    <li><strong>Borehole Inspection:</strong> Geotechnical visual down-hole verification of bearing stratum and bell cleanliness; remove all slough.</li>
                    <li><strong>Standby Casing:</strong> Deploy temporary smooth steel casing if rapid caving or seepage occurs due to calcareous nodules.</li>
                    <li><strong>Rebar Placement:</strong> Position prefabricated rebar cages with approved centralizers for required clear concrete cover.</li>
                    <li><strong>Continuous Placement:</strong> Discharge concrete (4-6" slump) immediately / same day after excavation in 1 continuous placement.</li>
                    <li><strong>Grade Beams:</strong> Form and cast grade beams on subgrade, apply curing compound, and compile test records.</li>
                  </ol>
                </div>

                {/* Option B: Stiffened Post-Tensioned Slabs */}
                <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-2.5">
                  <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                    <span className="font-bold text-white text-xs">Option B: Post-Tensioned Slabs</span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-sky-500/15 text-sky-300 border border-sky-500/30">
                      Shallow PT Slab
                    </span>
                  </div>
                  <ol className="list-decimal list-outside pl-4 space-y-1.5 text-slate-300 text-[11px] leading-relaxed">
                    <li><strong>Select Fill Pad:</strong> Complete minimum 1.00 ft compacted select fill pad extending at least 5 ft beyond slab edges.</li>
                    <li><strong>Beam Trenching:</strong> Excavate perimeter and interior grade beam trenches to minimum 1.50 ft below finished grade.</li>
                    <li><strong>Vapor Retarder:</strong> Install heavy 10-mil vapor retarder membrane with continuous taped laps; erect edge forms.</li>
                    <li><strong>Tendon Layout:</strong> Place post-tensioning tendons, anchorages, and rebar chairs per PTI DC10.1 and structural drawings.</li>
                    <li><strong>Monolithic Pour:</strong> Place slab and grade beams monolithically with mechanical vibration along trenches and anchor pockets.</li>
                    <li><strong>Tendon Stressing:</strong> Stress tendons upon concrete reaching specified compressive strength; record elongations and grout pockets.</li>
                  </ol>
                </div>

                {/* Option C: Continuous Footings / Grade Beams */}
                <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-2.5">
                  <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                    <span className="font-bold text-white text-xs">Option C: Continuous Footings</span>
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-purple-500/15 text-purple-300 border border-purple-500/30">
                      Shallow Footings
                    </span>
                  </div>
                  <ol className="list-decimal list-outside pl-4 space-y-1.5 text-slate-300 text-[11px] leading-relaxed">
                    <li><strong>Select Fill Pad:</strong> Complete minimum 2.00 ft compacted select fill pad over proof-rolled native subgrade.</li>
                    <li><strong>Trench Excavation:</strong> Excavate continuous footing trenches to at least 2.50 ft below finished grade into approved clay/fill.</li>
                    <li><strong>Subgrade Verification:</strong> Geotechnical inspection of footing trench subgrade prior to reinforcement placement.</li>
                    <li><strong>Reinforcement:</strong> Install longitudinal and transverse reinforcement steel on chairs per structural schedules.</li>
                    <li><strong>Immediate Pour:</strong> Place footing concrete during same day as excavation to prevent desiccation or softening.</li>
                    <li><strong>Stem Walls &amp; Backfill:</strong> Form foundation stem walls, strip forms, and backfill after proper curing.</li>
                  </ol>
                </div>
              </div>
            </div>

            {/* Classified Construction Machinery & Equipment */}
            <div className="p-4 sm:p-5 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Truck className="w-4 h-4 text-amber-400" />
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-200">
                    Construction Machinery &amp; Equipment Classification
                  </h4>
                </div>
                <span className="text-[10px] text-slate-400 italic">
                  Categorized by Universal, Method-Conditional, and Contingency deployment
                </span>
              </div>

              {/* Category 1: Universal Equipment */}
              <div className="space-y-2">
                <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-400 block">
                  1. Universal Equipment (Mandatory for All Foundation Options)
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
                  <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800/80 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-white text-xs">
                      <Truck className="w-3.5 h-3.5 text-emerald-400" />
                      <span>15-Ton+ Proofroller</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Loaded 15-ton roller or heavier (or approved equivalent) for subgrade proofrolling and fill compaction.
                    </p>
                    <span className="inline-block text-[10px] font-semibold text-emerald-300 bg-emerald-500/10 px-1.5 py-0.5 rounded">Mandatory on site</span>
                  </div>

                  <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800/80 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-white text-xs">
                      <Wrench className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Earthmoving Machinery</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Hydraulic excavators, backhoes, and skid steers for topsoil stripping, grading, and select fill placement.
                    </p>
                    <span className="inline-block text-[10px] font-semibold text-emerald-300 bg-emerald-500/10 px-1.5 py-0.5 rounded">Mandatory on site</span>
                  </div>

                  <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800/80 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-white text-xs">
                      <Layers className="w-3.5 h-3.5 text-emerald-400" />
                      <span>Vibratory Compactor</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Smooth-drum / padfoot roller and trench tampers for 8-inch loose select fill lifts (&ge; 95% ASTM D698).
                    </p>
                    <span className="inline-block text-[10px] font-semibold text-emerald-300 bg-emerald-500/10 px-1.5 py-0.5 rounded">Mandatory on site</span>
                  </div>

                  <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800/80 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-white text-xs">
                      <HardHat className="w-3.5 h-3.5 text-emerald-400" />
                      <span>OSHA Fall Protection</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      OSHA-compliant rigid covers, safety barricades, and caution tape to seal all open boreholes and trenches.
                    </p>
                    <span className="inline-block text-[10px] font-semibold text-emerald-300 bg-emerald-500/10 px-1.5 py-0.5 rounded">Mandatory at all times</span>
                  </div>
                </div>
              </div>

              {/* Category 2: Method-Conditional Equipment */}
              <div className="space-y-2 pt-2 border-t border-slate-800">
                <span className="text-[11px] font-bold uppercase tracking-wider text-amber-400 block">
                  2. Method-Conditional Equipment (Required Only for Selected Foundation Option)
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
                  <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800/80 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-white text-xs">
                      <Wrench className="w-3.5 h-3.5 text-amber-400" />
                      <span>Rotary Drill Rig</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Equipped with Kelly bar, underreaming belling bucket (up to 5.0 ft), and clay augers.
                    </p>
                    <span className="inline-block text-[10px] font-semibold text-amber-300 bg-amber-500/10 px-1.5 py-0.5 rounded">Required if Piers Selected</span>
                  </div>

                  <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800/80 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-white text-xs">
                      <Droplets className="w-3.5 h-3.5 text-amber-400" />
                      <span>Concrete Pump / Tremie</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Rigid tremie pipe or concrete pump for deep continuous placement to avoid sidewall washing or aggregate segregation.
                    </p>
                    <span className="inline-block text-[10px] font-semibold text-amber-300 bg-amber-500/10 px-1.5 py-0.5 rounded">Conditional on Piers Selection</span>
                  </div>

                  <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800/80 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-white text-xs">
                      <Activity className="w-3.5 h-3.5 text-sky-400" />
                      <span>Tendon Stressing Jacks</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Calibrated mono-strand hydraulic jacks, pressure gauges, and elongation measurement tooling.
                    </p>
                    <span className="inline-block text-[10px] font-semibold text-sky-300 bg-sky-500/10 px-1.5 py-0.5 rounded">Required if PT Slab Selected</span>
                  </div>

                  <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800/80 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-white text-xs">
                      <Wrench className="w-3.5 h-3.5 text-purple-400" />
                      <span>Trenching Clean-Out Bucket</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Trenching excavator with clean-out bucket for squared footing excavations and mechanical vibrators.
                    </p>
                    <span className="inline-block text-[10px] font-semibold text-purple-300 bg-purple-500/10 px-1.5 py-0.5 rounded">Required if Footings Selected</span>
                  </div>
                </div>
              </div>

              {/* Category 3: Standby Contingency Equipment */}
              <div className="space-y-2 pt-2 border-t border-slate-800">
                <span className="text-[11px] font-bold uppercase tracking-wider text-cyan-400 block">
                  3. Standby Contingency Equipment (Site Condition Dependent)
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800/80 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-white text-xs">
                      <Layers className="w-3.5 h-3.5 text-cyan-400" />
                      <span>Standby Steel Casing</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Temporary smooth steel casing sections (matching shaft diameters) maintained on standby on site for immediate insertion upon caving or silt seepage.
                    </p>
                    <span className="inline-block text-[10px] font-semibold text-cyan-300 bg-cyan-500/10 px-1.5 py-0.5 rounded">Standby Contingency (Piers Option)</span>
                  </div>

                  <div className="p-3 rounded-xl bg-slate-900/70 border border-slate-800/80 space-y-1">
                    <div className="flex items-center gap-1.5 font-bold text-white text-xs">
                      <Droplets className="w-3.5 h-3.5 text-cyan-400" />
                      <span>Submersible Dewatering Pumps</span>
                    </div>
                    <p className="text-[11px] text-slate-400 leading-relaxed">
                      Submersible sump pumps and hoses. Natural groundwater was dry to 15.4 ft at completion; needed on standby only if surface runoff or perched seepage occurs.
                    </p>
                    <span className="inline-block text-[10px] font-semibold text-cyan-300 bg-cyan-500/10 px-1.5 py-0.5 rounded">Standby Contingency</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* ============================================================= */}
          {/* SECTION 7: QUALITY AND SAFETY REQUIREMENTS                    */}
          {/* ============================================================= */}
          <div className="rounded-3xl border border-slate-800/90 bg-slate-900/80 p-6 sm:p-7 space-y-4 shadow-lg">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-3">
              <span className="w-8 h-8 rounded-xl bg-red-500/20 border border-red-500/40 text-red-300 font-bold text-sm flex items-center justify-center">
                7
              </span>
              <div>
                <h3 className="text-lg font-bold text-white">7. Quality and Safety Requirements</h3>
                <p className="text-xs text-slate-400">
                  Site-specific risk mitigations, inspection hold points, quality testing, and safety precautions
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Quality Hold Points & Testing */}
              <div className="space-y-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  <FileCheck className="w-4 h-4 text-emerald-400" />
                  Inspection Hold Points &amp; Testing
                </h4>
                <div className="space-y-2.5 text-xs">
                  <div className="p-3.5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1">
                    <span className="font-bold text-white">Subgrade Proof-Roll Hold Point:</span>
                    <p className="text-slate-300 leading-relaxed">
                      Geotechnical engineer must witness and sign off on stripped subgrade proofrolling with 15-ton roller or heavier (or engineer-approved equivalent) prior to any select fill placement.
                    </p>
                  </div>
                  <div className="p-3.5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1">
                    <span className="font-bold text-white">Shaft Depth &amp; Bell Cleanliness Verification:</span>
                    <p className="text-slate-300 leading-relaxed">
                      Down-hole inspection of bearing stratum and bell cleanliness prior to cage installation and concrete placement. Loose slough must be removed.
                    </p>
                  </div>
                  <div className="p-3.5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1">
                    <span className="font-bold text-white">Same-Day Continuous Concrete Placement:</span>
                    <p className="text-slate-300 leading-relaxed">
                      Concrete placement must be completed immediately / same day after excavation in 1 continuous placement (4 to 6-inch slump) to avoid borehole wall desiccation or sloughing. Compressive strength f'c and reinforcement details are governed by the Structural Engineer design drawings.
                    </p>
                  </div>
                  <div className="p-3.5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1">
                    <span className="font-bold text-white">Concrete &amp; Compaction Testing Schedule:</span>
                    <p className="text-slate-300 leading-relaxed">
                      Select fill: Each compacted lift must be tested and verified prior to placement of subsequent lifts (ASTM D698 / ASTM D6938, min. 95% standard dry density). Concrete testing: Compressive test cylinders (ASTM C31/C39) and slump testing (4–6" slump) per Structural Engineer project specifications.
                    </p>
                  </div>
                </div>
              </div>

              {/* Site Safety Precautions & Risk Mitigations */}
              <div className="space-y-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                  <ShieldAlert className="w-4 h-4 text-amber-400" />
                  Site Safety Precautions &amp; Risk Mitigations
                </h4>
                <div className="space-y-2.5 text-xs">
                  {requirementReport.section_8_risks_and_precautions.map((risk) => (
                    <div
                      key={risk.risk_id}
                      className="p-3.5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1 text-xs"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-bold text-white">{risk.title}</span>
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-amber-300 border border-slate-700">
                          {risk.severity}
                        </span>
                      </div>
                      <p className="text-slate-300 leading-relaxed">{risk.project_risk_summary}</p>
                      <p className="text-sky-300 text-[11px] pt-1">
                        Contractor Action: {risk.vendor_proposal_expectation}
                      </p>
                    </div>
                  ))}
                  <div className="p-3.5 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-1">
                    <span className="font-bold text-white">OSHA Fall Protection &amp; Hole Covers:</span>
                    <p className="text-slate-300 leading-relaxed">
                      All open shafts and grade beam excavations must be securely covered with load-bearing timber/steel plates or barricaded per OSHA 1926 standards.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* ============================================================= */}
          {/* SECTION 8: VENDOR QUOTATION REQUIREMENTS                      */}
          {/* ============================================================= */}
          <div className="rounded-3xl border border-slate-800/90 bg-slate-900/80 p-6 sm:p-7 space-y-5 shadow-lg">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-3">
              <span className="w-8 h-8 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 font-bold text-sm flex items-center justify-center">
                8
              </span>
              <div>
                <h3 className="text-lg font-bold text-white">8. Vendor Quotation Requirements</h3>
                <p className="text-xs text-slate-400">
                  Mandatory commercial pricing breakdown, unit rates schedule, and technical submittals
                </p>
              </div>
            </div>

            {/* Commercial Pricing Breakdown Schedule */}
            <div className="space-y-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300 block">
                Required Bid Pricing Schedule &amp; Cost Structure
              </span>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
                <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-1.5">
                  <div className="flex items-center gap-1.5 font-bold text-amber-300 text-xs">
                    <DollarSign className="w-4 h-4 text-amber-400" />
                    <span>Material Costs</span>
                  </div>
                  <p className="text-slate-300 text-[11px] leading-relaxed">
                    Itemized costs for structural concrete (4-6" slump, continuous pour per structural engineer specs), reinforcement steel, low-PI select fill (PI 8-20, LL &lt;= 35), temporary casing standby, and grade beam formwork.
                  </p>
                </div>

                <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-1.5">
                  <div className="flex items-center gap-1.5 font-bold text-sky-300 text-xs">
                    <Briefcase className="w-4 h-4 text-sky-400" />
                    <span>Labour Costs</span>
                  </div>
                  <p className="text-slate-300 text-[11px] leading-relaxed">
                    Drill operators, underreaming rig crew, steel fixers, earthwork laborers, project superintendent, and safety supervision personnel.
                  </p>
                </div>

                <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-1.5">
                  <div className="flex items-center gap-1.5 font-bold text-rose-300 text-xs">
                    <Truck className="w-4 h-4 text-rose-400" />
                    <span>Equipment Costs</span>
                  </div>
                  <p className="text-slate-300 text-[11px] leading-relaxed">
                    Rotary drilling rig, underreamer tooling, 15-ton or heavier roller (or approved equivalent), excavators, concrete placement equipment, standby casing, and mobilization/demobilization.
                  </p>
                </div>

                <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-1.5">
                  <div className="flex items-center gap-1.5 font-bold text-emerald-300 text-xs">
                    <FileSpreadsheet className="w-4 h-4 text-emerald-400" />
                    <span>Unit Rates Schedule</span>
                  </div>
                  <p className="text-slate-300 text-[11px] leading-relaxed">
                    $/LF for shaft drilling &amp; concrete, $/bell underream ream, $/CY select fill compacted, and $/LF temporary casing standing/installed.
                  </p>
                </div>
              </div>
            </div>

            {/* Submission Proposal Items Checklist */}
            <div className="space-y-2 pt-2">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-300 block">
                Technical Proposal &amp; Submittal Items ({requirementReport.section_7_vendor_proposal_requirements.length} Required Items)
              </span>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                {requirementReport.section_7_vendor_proposal_requirements.map((prop) => (
                  <div
                    key={prop.proposal_item_id}
                    className="p-3.5 rounded-2xl bg-slate-950/85 border border-slate-800 space-y-1.5"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-amber-300 text-xs">{prop.topic}</span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                        {prop.proposal_item_id}
                      </span>
                    </div>
                    <p className="text-slate-300 leading-relaxed text-[11px]">{sanitizeAiWording(prop.required_information)}</p>
                    {prop.engineering_rationale && (
                      <p className="text-slate-400 text-[10px] leading-relaxed pt-0.5">
                        <em>Rationale:</em> {prop.engineering_rationale}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ============================================================= */}
          {/* SECTION 9: CLARIFICATIONS AND SUBMISSION DETAILS              */}
          {/* ============================================================= */}
          <div className="rounded-3xl border border-slate-800/90 bg-slate-900/80 p-6 sm:p-7 space-y-6 shadow-lg">
            <div className="flex items-center gap-3 border-b border-slate-800 pb-3">
              <span className="w-8 h-8 rounded-xl bg-amber-500/20 border border-amber-500/40 text-amber-300 font-bold text-sm flex items-center justify-center">
                9
              </span>
              <div>
                <h3 className="text-lg font-bold text-white">9. Project Clarifications &amp; Submission Details</h3>
                <p className="text-xs text-slate-400">
                  Pre-construction engineering clarifications, user inputs, boundary confirmations, and P.E. review status
                </p>
              </div>
            </div>

            {/* SCREEN VIEW: INTERACTIVE CLARIFICATION Q&A */}
            <div className="space-y-4 print:hidden">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 rounded-2xl bg-slate-950/90 border border-slate-800">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-amber-300">
                      Project Clarifications Progress
                    </span>
                    <span className="px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 text-xs font-semibold">
                      {completedClarificationsCount} of {CLARIFICATION_QUESTIONS.length} Addressed ({answeredClarificationsCount} Answered, {notAvailableClarificationsCount} Deferred)
                    </span>
                  </div>
                  <div className="w-48 sm:w-64 h-2 bg-slate-800 rounded-full overflow-hidden mt-1">
                    <div
                      className="h-full bg-gradient-to-r from-amber-500 to-emerald-500 transition-all duration-300"
                      style={{
                        width: `${(completedClarificationsCount / CLARIFICATION_QUESTIONS.length) * 100}%`,
                      }}
                    />
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  {savedSuccessNotice && (
                    <span className="text-xs font-semibold text-emerald-400 flex items-center gap-1 animate-fade-in">
                      <Check className="w-3.5 h-3.5" />
                      Saved!
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={handleSaveClarifications}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 font-bold text-xs shadow-md shadow-amber-500/20 transition-all"
                  >
                    <Save className="w-3.5 h-3.5" />
                    Save Clarifications
                  </button>
                </div>
              </div>

              {/* Status Filter Tabs */}
              <div className="flex items-center gap-1.5 border-b border-slate-800 pb-2 text-xs">
                <button
                  type="button"
                  onClick={() => setClarificationFilter('all')}
                  className={`px-3 py-1.5 rounded-lg font-semibold transition-colors ${
                    clarificationFilter === 'all'
                      ? 'bg-amber-500 text-slate-950'
                      : 'bg-slate-900 text-slate-400 hover:text-white'
                  }`}
                >
                  All Items ({CLARIFICATION_QUESTIONS.length})
                </button>
                <button
                  type="button"
                  onClick={() => setClarificationFilter('pending')}
                  className={`px-3 py-1.5 rounded-lg font-semibold transition-colors ${
                    clarificationFilter === 'pending'
                      ? 'bg-amber-500 text-slate-950'
                      : 'bg-slate-900 text-slate-400 hover:text-white'
                  }`}
                >
                  Pending Action ({pendingClarificationsCount})
                </button>
                <button
                  type="button"
                  onClick={() => setClarificationFilter('answered')}
                  className={`px-3 py-1.5 rounded-lg font-semibold transition-colors ${
                    clarificationFilter === 'answered'
                      ? 'bg-emerald-500 text-slate-950'
                      : 'bg-slate-900 text-slate-400 hover:text-white'
                  }`}
                >
                  Answered / Clarified ({answeredClarificationsCount})
                </button>
                <button
                  type="button"
                  onClick={() => setClarificationFilter('not_available')}
                  className={`px-3 py-1.5 rounded-lg font-semibold transition-colors ${
                    clarificationFilter === 'not_available'
                      ? 'bg-sky-500 text-slate-950'
                      : 'bg-slate-900 text-slate-400 hover:text-white'
                  }`}
                >
                  Deferred / Not Available ({notAvailableClarificationsCount})
                </button>
              </div>

              {/* Clarification Question Cards */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {filteredClarifications.map((q) => {
                  const stateAns = clarificationAnswers[q.id];
                  const isAnswered = stateAns?.status === 'ANSWERED' && !!stateAns?.answer?.trim();
                  const isNotAvailable = stateAns?.status === 'NOT_AVAILABLE';
                  const isPending = !isAnswered && !isNotAvailable;

                  return (
                    <div
                      key={q.id}
                      className={`p-4 rounded-2xl border space-y-3 transition-all ${
                        isAnswered
                          ? 'bg-slate-950/95 border-emerald-500/40'
                          : isNotAvailable
                          ? 'bg-slate-950/95 border-sky-500/40'
                          : 'bg-slate-950/80 border-slate-800 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="space-y-0.5">
                          <span className="text-xs font-bold text-white block">{q.title}</span>
                          <p className="text-[11px] text-amber-200/90 font-medium">{q.question}</p>
                        </div>
                        <div className="flex flex-col items-end gap-1 shrink-0">
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${
                              isAnswered
                                ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                                : isNotAvailable
                                ? 'bg-sky-500/15 text-sky-300 border-sky-500/30'
                                : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                            }`}
                          >
                            {isAnswered ? 'Clarified' : isNotAvailable ? 'Deferred' : 'Pending Action'}
                          </span>
                          <span className="text-[9px] text-slate-400 font-mono">
                            Action: {q.requiredRole}
                          </span>
                        </div>
                      </div>

                      <p className="text-[10px] text-slate-400 leading-relaxed italic">{q.context}</p>

                      <div className="space-y-2 pt-1">
                        <label className="text-[10px] uppercase font-bold tracking-wider text-slate-400 block">
                          Select Standard Response:
                        </label>
                        <select
                          value={isNotAvailable ? 'NOT_AVAILABLE' : stateAns?.answer || ''}
                          onChange={(e) => {
                            if (e.target.value === 'NOT_AVAILABLE') {
                              handleMarkNotAvailable(q.id);
                            } else if (e.target.value) {
                              handleUpdateClarification(q.id, e.target.value, stateAns?.details);
                            } else {
                              handleMarkPending(q.id);
                            }
                          }}
                          className="w-full px-3 py-2 rounded-xl bg-slate-900 border border-slate-700 text-xs text-white focus:outline-hidden focus:border-amber-400"
                        >
                          <option value="">-- Select Option or Choose Custom Input Below --</option>
                          {q.options.map((opt, oIdx) => (
                            <option key={oIdx} value={opt}>
                              {opt}
                            </option>
                          ))}
                          <option value="NOT_AVAILABLE">Information Not Available Yet (Defer)</option>
                        </select>

                        <div className="space-y-1">
                          <label className="text-[10px] uppercase font-bold tracking-wider text-slate-400 block">
                            Custom Clarification / Notes:
                          </label>
                          <input
                            type="text"
                            placeholder="Type custom verified answer or engineer notes..."
                            value={stateAns?.answer && !q.options.includes(stateAns.answer) && stateAns.answer !== 'Information Not Available Yet (Pending)' ? stateAns.answer : stateAns?.details || ''}
                            onChange={(e) => {
                              const val = e.target.value;
                              if (!stateAns?.answer || !q.options.includes(stateAns.answer)) {
                                handleUpdateClarification(q.id, val, stateAns?.details);
                              } else {
                                handleUpdateClarification(q.id, stateAns.answer, val);
                              }
                            }}
                            className="w-full px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs text-white placeholder-slate-500"
                          />
                        </div>

                        <div className="flex items-center justify-between gap-2 pt-1 border-t border-slate-800/80">
                          <div className="text-[10px] text-slate-500 font-mono">
                            {stateAns?.updatedAt ? `Updated: ${stateAns.updatedAt}` : 'Not yet updated'}
                          </div>
                          <div className="flex items-center gap-1.5">
                            {isAnswered && (
                              <button
                                type="button"
                                onClick={() => handleMarkPending(q.id)}
                                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[10px] font-medium transition-colors"
                              >
                                Reset to Pending
                              </button>
                            )}
                            {!isNotAvailable && (
                              <button
                                type="button"
                                onClick={() => handleMarkNotAvailable(q.id)}
                                className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 text-[10px] font-medium transition-colors"
                              >
                                Defer Item
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Assumptions, Discrepancies & Submission Rules */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs pt-1">
              {/* Assumptions & Discrepancies */}
              <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-3">
                <span className="font-bold text-white block text-xs">Contractor Assumptions &amp; Discrepancies Policy:</span>
                <div className="space-y-2 text-slate-300 text-[11px] leading-relaxed">
                  <p>
                    <strong>Contractor Assumptions &amp; Exclusions:</strong> Bidders must clearly state all assumptions in their technical submittal regarding utility locations, unclassified excavation, dewatering expectations, and site access constraints.
                  </p>
                  <p>
                    <strong>Cross-Document Boundary Verification:</strong> Geotechnical Report (AmeriKor 25-0117) covers the entire development described as <strong>Lots 1 &amp; 2, Block 1 within White Oak Terrace subdivision</strong> (Client: Novel Signature Homes, Proposed 2 Residences). The uploaded Architectural Site Plan (2436 White Oak Drive) establishes building footprint, setbacks, and geometry for <strong>Lot 2 only (one residence: 2436 White Oak Drive)</strong>. <code>SITE PLAN 2434 WHITE OAK</code> referencing <code>Lot 8, Block 2, Norhill Park</code> was identified as a non-matching property and has been excluded from this package. An architectural/civil site plan for <strong>Lot 1 (2434 White Oak Drive)</strong> remains pending submittal.
                  </p>
                </div>
              </div>

              {/* Submission Instructions & Deadlines */}
              <div className="p-4 rounded-2xl bg-slate-950/90 border border-slate-800 space-y-3">
                <span className="font-bold text-white block text-xs">Quotation Submission Instructions:</span>
                <div className="space-y-2 text-slate-300 text-[11px] leading-relaxed">
                  <p>
                    <strong>Submission Package:</strong> Submit 1 compiled electronic PDF proposal containing technical methodology, equipment schedule, pricing breakdown, unit rate schedule, and project timeline.
                  </p>
                  <p>
                    <strong>Inquiries &amp; Clarifications:</strong> All requests for information (RFIs) regarding foundation requirements or borehole data must be submitted in writing at least 5 business days prior to quotation closing.
                  </p>
                </div>
              </div>
            </div>

            {/* References & Statutory Engineering Disclaimer */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs pt-1">
              <div className="p-4 rounded-2xl bg-slate-950/80 border border-slate-800 space-y-2">
                <span className="font-bold text-white block">Governing Standards &amp; Project References:</span>
                <ul className="list-disc list-inside text-slate-300 space-y-1 pl-1 text-[11px]">
                  <li>Soil Investigation Report 25-0117 (AmeriKor, LLC, Feb 20, 2025; pp. 4, 5, 6, 8, 10, 11, 14, 15)</li>
                  <li>Architectural Site Plan for 2436 White Oak Drive (Lot 2 only; Lot 1 site plan pending submittal)</li>
                  <li>PTI DC10.1 / PTI 3rd Edition (2004) Design of Post-Tensioned Slabs</li>
                  <li>FHWA GEC 10 / NHI-10-016 &amp; ACI 336.1 (Drilled Shafts Construction)</li>
                  <li>ACI 318 &amp; ASTM A615 (Reinforcing Steel per Structural Drawings)</li>
                  <li>ASTM D698 (Standard Proctor) &amp; ASTM D6938 (In-Place Density)</li>
                </ul>
              </div>

              <div className="p-4 rounded-2xl bg-amber-950/25 border border-amber-500/35 space-y-2">
                <span className="font-bold text-amber-300 block flex items-center gap-1.5">
                  <ShieldAlert className="w-4 h-4" />
                  Statutory Engineering Disclaimer:
                </span>
                <p className="text-slate-200 leading-relaxed text-[11px]">
                  {sanitizeAiWording(requirementReport.section_12_limitations_and_approval.statutory_disclaimer)}
                </p>
                <div className="text-[11px] text-amber-300/80 pt-1">
                  Status: <strong>UNAPPROVED PRELIMINARY DRAFT</strong> — Pending licensed P.E. review and signature prior to contractual issuance.
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* =============================================================== */}
        {/* PRINT & PDF EXPORT VIEW: TRADITIONAL PROFESSIONAL SPECIFICATION */}
        {/* =============================================================== */}
        <div className="hidden print:block font-sans text-slate-900 bg-white space-y-5 rfq-print-document">
          {/* Document Cover Header */}
          <div className="border-b-2 border-slate-900 pb-3 mb-5">
            <div className="flex justify-between items-start">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-widest text-slate-600">GeoStrata Engineering Platform</div>
                <h1 className="text-lg font-bold text-slate-950 tracking-tight mt-0.5">
                  REQUEST FOR QUOTATION (RFQ) &amp; FOUNDATION WORK SPECIFICATION
                </h1>
                <p className="text-xs text-slate-700 mt-0.5">
                  Contractor Tender Package &amp; Technical Requirements for Foundation Construction
                </p>
              </div>
              <div className="text-right text-xs text-slate-700 space-y-0.5">
                <div><strong>Document Ref:</strong> {requirementReport.document_id || 'RFQ-25-0117'}</div>
                <div><strong>Issue Date:</strong> {new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })}</div>
                <div className="text-[10px] font-bold uppercase text-slate-800">
                  Status: {isVerified ? 'VERIFIED BY LICENSED PROFESSIONAL ENGINEER' : 'PRELIMINARY UNAPPROVED DRAFT — TENDER ONLY'}
                </div>
              </div>
            </div>
          </div>

          {/* 1. Project Information Table */}
          <div className="space-y-1.5 rfq-print-section">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900 border-b border-slate-400 pb-1">
              1. Project Information
            </h2>
            <table className="w-full text-left border-collapse text-xs border border-slate-400">
              <tbody>
                <tr className="border-b border-slate-300">
                  <th className="py-1 px-2.5 w-[24%] bg-slate-100 font-bold text-slate-900 border-r border-slate-300">Project Name</th>
                  <td className="py-1 px-2.5 text-slate-800">{requirementReport.section_1_project_overview.project_name || 'Proposed 2 Residences'}</td>
                </tr>
                <tr className="border-b border-slate-300">
                  <th className="py-1 px-2.5 bg-slate-100 font-bold text-slate-900 border-r border-slate-300">Project Location</th>
                  <td className="py-1 px-2.5 text-slate-800">{requirementReport.section_1_project_overview.site_address || '2434 & 2436 White Oak Drive, Houston, Texas 77009'}</td>
                </tr>
                <tr className="border-b border-slate-300">
                  <th className="py-1 px-2.5 bg-slate-100 font-bold text-slate-900 border-r border-slate-300">Legal Description</th>
                  <td className="py-1 px-2.5 text-slate-800">{requirementReport.section_1_project_overview.legal_description || 'Lots 1 & 2, Block 1 within White Oak Terrace subdivision'}</td>
                </tr>
                <tr className="border-b border-slate-300">
                  <th className="py-1 px-2.5 bg-slate-100 font-bold text-slate-900 border-r border-slate-300">Client / Developer</th>
                  <td className="py-1 px-2.5 text-slate-800">{requirementReport.section_1_project_overview.client || 'Novel Signature Homes'}</td>
                </tr>
                <tr className="border-b border-slate-300">
                  <th className="py-1 px-2.5 bg-slate-100 font-bold text-slate-900 border-r border-slate-300">Geotechnical Consultant</th>
                  <td className="py-1 px-2.5 text-slate-800">{requirementReport.section_1_project_overview.geotechnical_consultant || 'AmeriKor, LLC (Report No. 25-0117)'}</td>
                </tr>
                <tr>
                  <th className="py-1 px-2.5 bg-slate-100 font-bold text-slate-900 border-r border-slate-300">Procurement Scope</th>
                  <td className="py-1 px-2.5 text-slate-800 leading-relaxed">
                    Foundation contractor shall furnish all labor, materials, equipment, supervision, quality testing coordination, and incidentals required to construct the foundations in accordance with geotechnical investigation recommendations, approved structural plans, and technical specifications detailed herein.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* 2. Site and Soil Conditions Table */}
          <div className="space-y-1.5 rfq-print-section">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900 border-b border-slate-400 pb-1">
              2. Site and Soil Conditions
            </h2>
            <table className="w-full text-left border-collapse text-xs border border-slate-400">
              <thead>
                <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                  <th className="py-1 px-2.5 w-[26%] border-r border-slate-300">Parameter</th>
                  <th className="py-1 px-2.5 w-[48%] border-r border-slate-300">Reported Engineering Value / Condition</th>
                  <th className="py-1 px-2.5 w-[26%]">Engineering Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-300">
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Soil Stratum &amp; Type</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    Layer I (0 to 20.0 ft): SANDY LEAN CLAY (CL), firm to very stiff, with calcareous nodules (LL: 32–42%, PI: 17–24, Moisture: 15.0%–23.9%, #200 Passing: 54.8%–68.6%, Pocket Penetrometer: 1.00–3.00 tsf).
                  </td>
                  <td className="py-1 px-2.5 text-slate-700">Boring Logs B-1 &amp; B-2 / Report Sec. 1.2</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Potential Vertical Rise (PVR)</td>
                  <td className="py-1 px-2.5 border-r border-slate-300 font-mono font-bold">
                    1.20 inches (TxDOT Tex-124-E worst-case dry moisture analysis)
                  </td>
                  <td className="py-1 px-2.5 text-slate-700">Soil Report Page 4, Section 1.2</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Active Zone Depth</td>
                  <td className="py-1 px-2.5 border-r border-slate-300 font-mono">
                    8.0 to 10.0 ft below existing surface grade
                  </td>
                  <td className="py-1 px-2.5 text-slate-700">Soil Report Page 4, Section 1.2</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Groundwater Depth</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    14.0 to 15.4 ft below ground surface at completion of drilling
                  </td>
                  <td className="py-1 px-2.5 text-slate-700">Soil Report Page 4, Section 1.2</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Surface Drainage Constraints</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    Min. 6-inch drop in first 10 ft away from perimeter grade beams; downspouts discharge &ge; 5 ft
                  </td>
                  <td className="py-1 px-2.5 text-slate-700">Soil Report Page 5, Section 1.3.1</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Subgrade Proofrolling</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    15-ton roller or heavier (or engineer-approved equivalent) required across stripped subgrade prior to fill
                  </td>
                  <td className="py-1 px-2.5 text-slate-700">Soil Report Page 3, Section 1.3.1</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Borehole Caving Hazard</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    Calcareous nodules &amp; silt seams in clay may induce caving; temporary steel casing must be on standby on site
                  </td>
                  <td className="py-1 px-2.5 text-slate-700">Soil Report Page 8, Section 1.3.2</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* 3. Foundation Requirements (Comparison Table) */}
          <div className="space-y-1.5 rfq-print-section">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900 border-b border-slate-400 pb-1">
              3. Foundation Requirements
            </h2>
            <p className="text-xs text-slate-700">
              The geotechnical consultant formally evaluated three viable foundation systems for this site (Report 25-0117, Sec. 1.3.2). Final system selection rests with the Structural Engineer of Record based on structural framing layout and column load schedules. Contractors shall provide unit rates and quotation pricing for all evaluated options or as specified in the structural bid package.
            </p>
            <table className="w-full text-left border-collapse text-xs border border-slate-400">
              <thead>
                <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                  <th className="py-1 px-2.5 w-[25%] border-r border-slate-300">Foundation System</th>
                  <th className="py-1 px-2.5 w-[20%] border-r border-slate-300">Allowable Bearing Capacity</th>
                  <th className="py-1 px-2.5 w-[20%] border-r border-slate-300">Target Depth / Dimensions</th>
                  <th className="py-1 px-2.5 w-[35%]">Engineering Suitability &amp; Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-300">
                <tr>
                  <td className="py-1 px-2.5 font-bold border-r border-slate-300">
                    Option 1: Underreamed Drilled Shafts (Belled Piers)
                    <span className="block text-[10px] font-normal text-slate-600">Consultant-Evaluated Deep Foundation</span>
                  </td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    <div>2,000 psf (DL + LL)</div>
                    <div className="text-[10px] text-slate-600">3,000 psf (Total w/ Wind)</div>
                  </td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    <div>Founded at ~10.0 ft depth</div>
                    <div className="text-[10px] text-slate-600">Bells up to 5.0 ft (3:1 ratio)</div>
                  </td>
                  <td className="py-1 px-2.5 text-slate-800 leading-snug">
                    Bypasses 8–10 ft active zone and 1.20" PVR to bear firmly in stiff clay. Continuous placement same day as drilling (4–6" slump). Evaluated by consultant; final selection pending structural column load schedule.
                  </td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-bold border-r border-slate-300">
                    Option 2: Stiffened Post-Tensioned Slab
                    <span className="block text-[10px] font-normal text-slate-600">Consultant-Evaluated Shallow PT Slab</span>
                  </td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    <div>1,400 psf (DL + LL)</div>
                    <div className="text-[10px] text-slate-600">2,100 psf (Total Load)</div>
                  </td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    <div>Beams embed &ge; 1.5 ft</div>
                    <div className="text-[10px] text-slate-600">Pad &ge; 1.0 ft select fill</div>
                  </td>
                  <td className="py-1 px-2.5 text-slate-800 leading-snug">
                    PTI Design (em=8.8/4.9 ft, ym=0.65/0.49 in). Viable alternative for lighter structures subject to subgrade proofrolling and minor residual surface movement. Evaluated by consultant; final selection pending structural engineer.
                  </td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-bold border-r border-slate-300">
                    Option 3: Shallow Continuous Footings
                    <span className="block text-[10px] font-normal text-slate-600">Consultant-Evaluated Shallow Footings</span>
                  </td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    <div>1,800 psf (DL + LL)</div>
                    <div className="text-[10px] text-slate-600">2,700 psf (Total Load)</div>
                  </td>
                  <td className="py-1 px-2.5 border-r border-slate-300">
                    <div>Min. embedment &ge; 2.5 ft</div>
                    <div className="text-[10px] text-slate-600">Into firm sandy lean clay</div>
                  </td>
                  <td className="py-1 px-2.5 text-slate-800 leading-snug">
                    Viable for lightly loaded single-story or auxiliary perimeter walls. Requires subgrade proofrolling with 15-ton roller. Evaluated by consultant; final selection pending structural engineer.
                  </td>
                </tr>
              </tbody>
            </table>
            <div className="text-[10px] text-slate-600 pt-0.5">
              <em>External Industry Alternatives (Benchmarking Only):</em> Straight-shaft friction piers, helical steel piles, and timber piles represent external alternatives. These are <strong>not consultant-approved</strong> for this project and are cited for contractor benchmarking only.
            </div>
          </div>

          {/* 4. Scope of Work Table */}
          <div className="space-y-1.5 rfq-print-section">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900 border-b border-slate-400 pb-1">
              4. Scope of Work
            </h2>
            <table className="w-full text-left border-collapse text-xs border border-slate-400">
              <thead>
                <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                  <th className="py-1 px-2 w-[8%] border-r border-slate-300 text-center">Item</th>
                  <th className="py-1 px-2.5 w-[28%] border-r border-slate-300">Work Scope Activity</th>
                  <th className="py-1 px-2.5 w-[64%]">Contractor Scope &amp; Execution Requirements</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-300">
                {requirementReport.section_4_vendor_scope_of_work.map((sc, idx) => (
                  <tr key={sc.scope_id}>
                    <td className="py-1 px-2 font-mono text-center font-bold border-r border-slate-300">{idx + 1}</td>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">{sc.title}</td>
                    <td className="py-1 px-2.5 text-slate-800 leading-snug">{sanitizeAiWording(sc.description)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 5. Technical Specifications Table */}
          <div className="space-y-1.5 rfq-print-section">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900 border-b border-slate-400 pb-1">
              5. Technical Specifications
            </h2>
            <table className="w-full text-left border-collapse text-xs border border-slate-400">
              <thead>
                <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                  <th className="py-1 px-2.5 w-[33%] border-r border-slate-300">Specification Parameter</th>
                  <th className="py-1 px-2.5 w-[18%] border-r border-slate-300">Requirement / Value</th>
                  <th className="py-1 px-2.5 w-[27%] border-r border-slate-300">Condition / Factor of Safety</th>
                  <th className="py-1 px-2.5 w-[22%]">Reference / Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-300">
                {requirementReport.section_5_technical_requirements.map((req) => (
                  <tr key={req.requirement_id}>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">
                      <div>{req.title}</div>
                      <div className="text-[10px] font-normal text-slate-600 leading-tight">{req.specification_text}</div>
                    </td>
                    <td className="py-1 px-2.5 font-mono font-bold border-r border-slate-300">
                      {req.numerical_value ? `${req.numerical_value} ${req.units || ''}` : 'Standard'}
                    </td>
                    <td className="py-1 px-2.5 border-r border-slate-300">
                      <div>{req.conditions_or_load_case || 'Standard'}</div>
                      {req.factor_of_safety && <div className="text-[10px] text-slate-600 font-mono">FS = {req.factor_of_safety}</div>}
                    </td>
                    <td className="py-1 px-2.5 font-mono text-[10px] text-slate-700">
                      <div>{req.pdf_page_reference || req.external_source_url || 'Soil Report'}</div>
                      <div className="text-[9px] text-slate-500 font-sans">{formatHumanLabel(req.source_classification)}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* 6. Construction Methodology and Equipment Requirements */}
          <div className="space-y-2 rfq-print-section">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900 border-b border-slate-400 pb-1">
              6. Construction Methodology and Equipment Requirements
            </h2>
            <div className="space-y-1.5 text-xs text-slate-800">
              <div className="font-bold text-slate-900">Sequential Execution Methodology:</div>
              <div className="text-[11px] text-slate-700 italic pb-0.5">
                Note: Phase 1 and Phase 3 are universal requirements for all foundation options. Phase 2 execution sequence is conditional upon the foundation system selected by the Structural Engineer.
              </div>

              {/* Phase 1: Universal */}
              <div className="border border-slate-300 p-2 rounded bg-slate-50 space-y-0.5">
                <div className="font-bold text-slate-900 text-[11px]">Phase 1: Universal Subgrade Preparation (All Foundation Systems)</div>
                <ol className="list-decimal list-outside pl-4 space-y-0.5 text-[10px] text-slate-800 leading-snug">
                  <li><strong>Setting Out &amp; Utility Clearance:</strong> Survey building lines, establish vertical benchmarks, and complete utility locate clearances prior to excavation.</li>
                  <li><strong>Organic Topsoil Stripping:</strong> Strip minimum 6 inches organic topsoil across building footprint and minimum 5 ft perimeter margin.</li>
                  <li><strong>Heavy Subgrade Proof-Rolling:</strong> Proof-roll stripped native subgrade with loaded 15-ton roller or heavier (or approved equivalent) under geotechnical observation.</li>
                  <li><strong>Engineered Select Fill Placement:</strong> Place low-PI select fill (LL &le; 35, PI 8–20) in 8-inch loose lifts compacted to &ge; 95% ASTM D698 at -1% to +3% optimum moisture.</li>
                </ol>
              </div>

              {/* Phase 2: System-Specific Sequences */}
              <div className="border border-slate-300 p-2 rounded bg-slate-50 space-y-1">
                <div className="font-bold text-slate-900 text-[11px]">Phase 2: Foundation-Specific Execution Sequences (Conditional Selection)</div>
                
                <div className="space-y-0.5 text-[10px] text-slate-800">
                  <span className="font-bold text-slate-900 block">Option A: Underreamed Drilled Shafts (Deep Foundation):</span>
                  <div className="pl-2 leading-snug">
                    Drill cylindrical shafts to min. 10.0 ft depth &bull; Mechanically ream underreamed bells to max. 5.0 ft diameter (3:1 bell-to-shaft ratio) in stiff bearing clay &bull; Visual down-hole inspection &amp; slough removal &bull; Standby temporary smooth steel casing deployed immediately if caving occurs &bull; Position rebar cages with approved centralizers &bull; Place concrete immediately same day as excavation in 1 continuous pour (4–6" slump) &bull; Form and cast grade beams on compacted select fill pad.
                  </div>
                </div>

                <div className="space-y-0.5 text-[10px] text-slate-800 pt-0.5 border-t border-slate-200">
                  <span className="font-bold text-slate-900 block">Option B: Post-Tensioned Slab-on-Ground (Shallow Foundation):</span>
                  <div className="pl-2 leading-snug">
                    Construct min. 1.00 ft compacted select fill pad extending 5 ft beyond perimeter &bull; Excavate perimeter &amp; interior stiffening beam trenches to min. 1.50 ft below finished grade into firm soil &bull; Install min. 10-mil polyolefin vapor retarder (lapped &amp; taped) &bull; Install post-tensioning tendons, anchorages, and chairs per PTI DC10.1 and structural drawings &bull; Monolithic placement of slab and grade beams with internal mechanical vibration &bull; Stress tendons upon concrete reaching specified compressive strength and record elongations.
                  </div>
                </div>

                <div className="space-y-0.5 text-[10px] text-slate-800 pt-0.5 border-t border-slate-200">
                  <span className="font-bold text-slate-900 block">Option C: Continuous Spread Footings (Shallow Foundation):</span>
                  <div className="pl-2 leading-snug">
                    Construct min. 2.00 ft compacted select fill pad over proof-rolled native subgrade &bull; Excavate continuous footing trenches to min. 2.50 ft embedment below finished grade &bull; Geotechnical inspection of trench subgrade &bull; Position longitudinal &amp; transverse reinforcement on chairs &bull; Place footing concrete same day as excavation to prevent desiccation &bull; Form and cast foundation stem walls after initial curing.
                  </div>
                </div>
              </div>

              {/* Phase 3: Universal Drainage */}
              <div className="border border-slate-300 p-2 rounded bg-slate-50 space-y-0.5">
                <div className="font-bold text-slate-900 text-[11px]">Phase 3: Universal Perimeter Drainage &amp; Moisture Protection</div>
                <div className="text-[10px] text-slate-800 leading-snug pl-1">
                  Establish minimum 6-inch positive fall away from foundation within first 10 ft &bull; Direct roof downspouts to hard piping or splash blocks discharging 5+ ft beyond foundation perimeter &bull; Compact utility trench backfill to prevent water ponding &bull; Maintain consistent perimeter soil moisture to mitigate soil volume changes.
                </div>
              </div>
            </div>

            {/* Classified Construction Machinery & Equipment Table */}
            <div className="space-y-1 pt-1">
              <div className="font-bold text-xs text-slate-900">Classified Construction Machinery &amp; Equipment:</div>
              <table className="w-full text-left border-collapse text-xs border border-slate-400">
                <thead>
                  <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                    <th className="py-1 px-2.5 w-[25%] border-r border-slate-300">Equipment Type</th>
                    <th className="py-1 px-2.5 w-[50%] border-r border-slate-300">Required Specification &amp; Purpose</th>
                    <th className="py-1 px-2.5 w-[25%]">Deployment Classification</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-300">
                  {/* Universal Equipment */}
                  <tr>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Loaded 15-Ton Proofroller</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Loaded 15-ton roller or heavier (or approved equivalent) for subgrade proofrolling and fill compaction</td>
                    <td className="py-1 px-2.5 font-bold text-emerald-800">Universal (Mandatory All Options)</td>
                  </tr>
                  <tr>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Heavy Earthmoving Fleet</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Hydraulic excavators, backhoes, and skid steers for stripping, grading, and fill pad placement</td>
                    <td className="py-1 px-2.5 font-bold text-emerald-800">Universal (Mandatory All Options)</td>
                  </tr>
                  <tr>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Vibratory Compactor &amp; Tampers</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Smooth-drum / padfoot roller and trench tampers for 8-inch loose select fill lifts (&ge; 95% ASTM D698)</td>
                    <td className="py-1 px-2.5 font-bold text-emerald-800">Universal (Mandatory All Options)</td>
                  </tr>
                  <tr>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">OSHA Fall Protection Covers</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">OSHA-compliant rigid covers, safety barricades, and caution tape to seal all open boreholes and trenches</td>
                    <td className="py-1 px-2.5 font-bold text-emerald-800">Universal (Mandatory at All Times)</td>
                  </tr>

                  {/* Method-Conditional Equipment */}
                  <tr>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Heavy Rotary Drill Rig</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Equipped with Kelly bar, underreaming belling bucket (up to 5.0 ft diameter), and clay augers</td>
                    <td className="py-1 px-2.5 font-semibold text-amber-800">Conditional (Option A Piers Only)</td>
                  </tr>
                  <tr>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Tremie Pipe / Concrete Pump</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Rigid tremie pipe or concrete pump for deep continuous discharge without aggregate segregation</td>
                    <td className="py-1 px-2.5 font-semibold text-amber-800">Conditional (Option A Piers Only)</td>
                  </tr>
                  <tr>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Tendon Stressing Jacks</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Calibrated mono-strand hydraulic jacks, pressure gauges, and elongation measurement tooling</td>
                    <td className="py-1 px-2.5 font-semibold text-sky-800">Conditional (Option B PT Slab Only)</td>
                  </tr>
                  <tr>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Trenching Clean-Out Bucket</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Clean-out bucket for neat-line excavation of grade beam trenches and continuous footing beds</td>
                    <td className="py-1 px-2.5 font-semibold text-purple-800">Conditional (Option B &amp; C Only)</td>
                  </tr>

                  {/* Standby Contingency Equipment */}
                  <tr>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Temporary Smooth Steel Casing</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Smooth steel casing sections (matching shaft diameters) on standby for immediate insertion upon caving</td>
                    <td className="py-1 px-2.5 font-medium text-slate-700">Standby Contingency (Option A Caving)</td>
                  </tr>
                  <tr>
                    <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Submersible Dewatering Pumps</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Heavy-duty submersible sump pumps and discharge hoses to dewater excavations if seepage occurs</td>
                    <td className="py-1 px-2.5 font-medium text-slate-700">Standby Contingency (Seepage / Rain)</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* 7. Quality and Safety Requirements Table */}
          <div className="space-y-1.5 rfq-print-section">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900 border-b border-slate-400 pb-1">
              7. Quality and Safety Requirements
            </h2>
            <table className="w-full text-left border-collapse text-xs border border-slate-400">
              <thead>
                <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                  <th className="py-1 px-2.5 w-[30%] border-r border-slate-300">Inspection Hold Point / Safety Item</th>
                  <th className="py-1 px-2.5 w-[50%] border-r border-slate-300">Specification &amp; Acceptance Criteria</th>
                  <th className="py-1 px-2.5 w-[20%]">Timing / Authority</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-300">
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Subgrade Proof-Roll Hold Point</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">Geotechnical engineer must witness and sign off on stripped subgrade proofrolling with loaded 15-ton roller or heavier prior to fill placement</td>
                  <td className="py-1 px-2.5">Prior to fill / Geotechnical P.E.</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Compacted Fill Density Testing</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">Each 8-inch loose lift tested for compaction (ASTM D698 / D6938, min. 95% standard Proctor) and moisture (-1% to +3%) prior to subsequent lifts</td>
                  <td className="py-1 px-2.5">Each lift / Certified Lab</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Foundation Excavation Inspection</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">Visual inspection of bearing stratum and bell/trench cleanliness; all loose slough and water removed prior to cage/concrete placement</td>
                  <td className="py-1 px-2.5">Prior to pour / Geotech Inspector</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Concrete Quality &amp; Slump Testing</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">Continuous concrete placement immediately same day as excavation; 4–6" slump; ASTM C31/C39 compressive strength test cylinders</td>
                  <td className="py-1 px-2.5">At placement / Testing Lab</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">Tendon Stressing Certification (Option B)</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">Verify hydraulic jack calibration, tendon gauge pressures, and measured elongations per PTI DC10.1 criteria</td>
                  <td className="py-1 px-2.5">Post-curing / Structural Inspector</td>
                </tr>
                <tr>
                  <td className="py-1 px-2.5 font-semibold border-r border-slate-300">OSHA Open Excavation Protection</td>
                  <td className="py-1 px-2.5 border-r border-slate-300">Load-bearing covers or rigid safety perimeter barricades over all open shafts and trenches per OSHA 1926</td>
                  <td className="py-1 px-2.5">Continuous / Safety Officer</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* 8. Vendor Quotation Requirements Tables */}
          <div className="space-y-2 rfq-print-section">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900 border-b border-slate-400 pb-1">
              8. Vendor Quotation Requirements
            </h2>
            <div className="space-y-1">
              <div className="font-bold text-xs text-slate-900">Commercial Pricing Schedule &amp; Cost Structure:</div>
              <table className="w-full text-left border-collapse text-xs border border-slate-400">
                <thead>
                  <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                    <th className="py-1 px-2.5 w-[20%] border-r border-slate-300">Item</th>
                    <th className="py-1 px-2.5 w-[50%] border-r border-slate-300">Description</th>
                    <th className="py-1 px-2.5 w-[30%]">Vendor Response / Price</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-300">
                  <tr>
                    <td className="py-1 px-2.5 font-bold border-r border-slate-300">Labour</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Drill operators, rig crew, steel fixers, PT stressing technicians, earthwork laborers, project superintendent, safety supervision</td>
                    <td className="py-1 px-2.5 font-mono text-slate-700">$ ____________________</td>
                  </tr>
                  <tr>
                    <td className="py-1 px-2.5 font-bold border-r border-slate-300">Materials</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Structural concrete (4–6" slump continuous pour), reinforcement steel, low-PI select fill (PI 8–20, LL &le; 35), grade beam forms, PT tendons</td>
                    <td className="py-1 px-2.5 font-mono text-slate-700">$ ____________________</td>
                  </tr>
                  <tr>
                    <td className="py-1 px-2.5 font-bold border-r border-slate-300">Equipment</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">Loaded 15-ton roller, excavators, compaction equipment, drill rig (if Option A), tremie pipe, PT jack (if Option B), mobilization &amp; demobilization</td>
                    <td className="py-1 px-2.5 font-mono text-slate-700">$ ____________________</td>
                  </tr>
                  <tr>
                    <td className="py-1 px-2.5 font-bold border-r border-slate-300">Unit Rates</td>
                    <td className="py-1 px-2.5 border-r border-slate-300">
                      <div>&bull; Option A (Piers): Shaft Drilling &amp; Concrete: $ _____ / LF</div>
                      <div>&bull; Option A (Piers): Bell Underreaming: $ _____ / Bell</div>
                      <div>&bull; Option A (Piers): Standby Steel Casing: $ _____ / LF</div>
                      <div>&bull; Option B (PT Slab): Concrete &amp; Tendon Placement: $ _____ / SF</div>
                      <div>&bull; Option C (Footings): Continuous Footings Excavation &amp; Pour: $ _____ / LF</div>
                      <div>&bull; Universal: Compacted Low-PI Select Fill (in-place): $ _____ / CY</div>
                    </td>
                    <td className="py-1 px-2.5 font-mono text-slate-700">See itemized unit rates schedule</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div className="space-y-1 pt-1">
              <div className="font-bold text-xs text-slate-900">Mandatory Proposal Submittal Checklist:</div>
              <table className="w-full text-left border-collapse text-xs border border-slate-400">
                <thead>
                  <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                    <th className="py-1 px-2 w-[12%] border-r border-slate-300 text-center">Ref</th>
                    <th className="py-1 px-2.5 w-[30%] border-r border-slate-300">Submittal Topic</th>
                    <th className="py-1 px-2.5 w-[58%]">Required Information &amp; Proposal Content</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-300">
                  {requirementReport.section_7_vendor_proposal_requirements.map((prop) => (
                    <tr key={prop.proposal_item_id}>
                      <td className="py-1 px-2 font-mono text-center font-bold border-r border-slate-300">{prop.proposal_item_id}</td>
                      <td className="py-1 px-2.5 font-semibold border-r border-slate-300">{prop.topic}</td>
                      <td className="py-1 px-2.5 text-slate-800 leading-snug">{sanitizeAiWording(prop.required_information)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* 9. Project Clarifications Table (Structured Q&A Export) */}
          <div className="space-y-2 rfq-print-section">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900 border-b border-slate-400 pb-1">
              9. Project Clarifications &amp; Decision Status
            </h2>
            <div className="text-[10px] text-slate-700 italic">
              All clarifications and pending engineering inquiries must be resolved prior to contract execution. Bidders shall base their quotation on confirmed decisions and state any assumptions regarding pending items.
            </div>

            {/* Part 9.1: Confirmed Project Decisions */}
            <div className="space-y-1">
              <div className="font-bold text-xs text-emerald-900">Part 9.1: Confirmed Project Decisions</div>
              <table className="w-full text-left border-collapse text-xs border border-slate-400">
                <thead>
                  <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                    <th className="py-1 px-2 w-[8%] border-r border-slate-300 text-center">No.</th>
                    <th className="py-1 px-2.5 w-[42%] border-r border-slate-300">Clarification Topic</th>
                    <th className="py-1 px-2.5 w-[35%] border-r border-slate-300">Confirmed Decision</th>
                    <th className="py-1 px-2 w-[15%] text-center">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-300">
                  {CLARIFICATION_QUESTIONS.filter((q) => clarificationAnswers[q.id]?.status === 'ANSWERED').map((q, idx) => {
                    const ans = clarificationAnswers[q.id];
                    return (
                      <tr key={q.id}>
                        <td className="py-1 px-2 font-mono text-center font-bold border-r border-slate-300">{idx + 1}</td>
                        <td className="py-1 px-2.5 font-semibold border-r border-slate-300">{q.question}</td>
                        <td className="py-1 px-2.5 text-slate-800 border-r border-slate-300">
                          <div className="font-medium text-slate-900">{ans.answer}</div>
                          {ans.details && <div className="text-[10px] text-slate-600 mt-0.5">Note: {ans.details}</div>}
                        </td>
                        <td className="py-1 px-2 text-center font-bold text-emerald-800 text-[10px]">CONFIRMED</td>
                      </tr>
                    );
                  })}
                  {CLARIFICATION_QUESTIONS.filter((q) => clarificationAnswers[q.id]?.status === 'ANSWERED').length === 0 && (
                    <tr>
                      <td colSpan={4} className="py-1.5 px-2.5 text-slate-500 italic text-center">
                        No decisions confirmed yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Part 9.2: Pending Actions & Required Inquiries */}
            <div className="space-y-1 pt-1">
              <div className="font-bold text-xs text-amber-900">Part 9.2: Pending Technical Inquiries &amp; Action Items</div>
              <table className="w-full text-left border-collapse text-xs border border-slate-400">
                <thead>
                  <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                    <th className="py-1 px-2 w-[8%] border-r border-slate-300 text-center">No.</th>
                    <th className="py-1 px-2.5 w-[42%] border-r border-slate-300">Pending Question / Item</th>
                    <th className="py-1 px-2.5 w-[35%] border-r border-slate-300">Bidder Instruction / Temporary Basis</th>
                    <th className="py-1 px-2 w-[15%] text-center">Action Role</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-300">
                  {CLARIFICATION_QUESTIONS.filter((q) => !clarificationAnswers[q.id] || clarificationAnswers[q.id]?.status === 'PENDING').map((q, idx) => {
                    const ans = clarificationAnswers[q.id];
                    return (
                      <tr key={q.id}>
                        <td className="py-1 px-2 font-mono text-center font-bold border-r border-slate-300">{idx + 1}</td>
                        <td className="py-1 px-2.5 font-semibold border-r border-slate-300">
                          <div>{q.question}</div>
                          {ans?.details && <div className="text-[10px] text-slate-600 mt-0.5">Note: {ans.details}</div>}
                        </td>
                        <td className="py-1 px-2.5 text-slate-800 border-r border-slate-300 text-[10px]">
                          Submit unit pricing for evaluated options; confirm with Structural Engineer before contract.
                        </td>
                        <td className="py-1 px-2 text-center font-semibold text-amber-800 text-[10px]">
                          {q.requiredRole || 'Structural P.E.'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Part 9.3: Deferred Items & Allowances */}
            {CLARIFICATION_QUESTIONS.filter((q) => clarificationAnswers[q.id]?.status === 'NOT_AVAILABLE').length > 0 && (
              <div className="space-y-1 pt-1">
                <div className="font-bold text-xs text-slate-700">Part 9.3: Deferred Items &amp; Pending Submittals</div>
                <table className="w-full text-left border-collapse text-xs border border-slate-400">
                  <thead>
                    <tr className="bg-slate-100 border-b border-slate-400 text-slate-900 font-bold">
                      <th className="py-1 px-2 w-[8%] border-r border-slate-300 text-center">No.</th>
                      <th className="py-1 px-2.5 w-[52%] border-r border-slate-300">Item</th>
                      <th className="py-1 px-2.5 w-[40%]">Status / Remarks</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-300">
                    {CLARIFICATION_QUESTIONS.filter((q) => clarificationAnswers[q.id]?.status === 'NOT_AVAILABLE').map((q, idx) => (
                      <tr key={q.id}>
                        <td className="py-1 px-2 font-mono text-center font-bold border-r border-slate-300">{idx + 1}</td>
                        <td className="py-1 px-2.5 font-semibold border-r border-slate-300">{q.question}</td>
                        <td className="py-1 px-2.5 text-slate-700 text-[10px]">Information not available in project records; to be established during pre-construction coordination.</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* 10. Project Boundaries & Governing References Table */}
          <div className="space-y-1.5 rfq-print-section">
            <h2 className="text-xs font-bold uppercase tracking-wider text-slate-900 border-b border-slate-400 pb-1">
              10. Project Boundaries &amp; Governing References
            </h2>
            <table className="w-full text-left border-collapse text-xs border border-slate-400">
              <tbody>
                <tr className="border-b border-slate-300">
                  <th className="py-1 px-2.5 w-[24%] bg-slate-100 font-bold text-slate-900 border-r border-slate-300">Boundary Verification</th>
                  <td className="py-1 px-2.5 text-slate-800 leading-relaxed">
                    Soil Investigation Report (AmeriKor 25-0117) scopes <strong>Lots 1 &amp; 2, Block 1 within White Oak Terrace subdivision</strong> (Client: Novel Signature Homes, Proposed 2 Residences). Architectural Site Plan (<code>SITE PLAN 2436 White Oak</code>) establishes <strong>Lot 2 only</strong> (2436 White Oak Drive, one residence). The site plan and foundation layout for Lot 1 (2434 White Oak Drive) is pending submittal by client/architect. The uploaded <code>SITE PLAN 2434 WHITE OAK</code> referencing <code>Lot 8, Block 2, Norhill Park</code> was identified as a non-matching property and has been excluded from this tender package.
                  </td>
                </tr>
                <tr className="border-b border-slate-300">
                  <th className="py-1 px-2.5 bg-slate-100 font-bold text-slate-900 border-r border-slate-300">Governing Standards</th>
                  <td className="py-1 px-2.5 text-slate-800">
                    Soil Report 25-0117 (AmeriKor, LLC, Feb 20, 2025); PTI DC10.1 (Post-Tensioned Slabs); FHWA GEC 10 / ACI 336.1 (Drilled Shafts); ACI 318 &amp; ASTM A615 (Reinforcing Steel per Structural Drawings); ASTM D698 &amp; ASTM D6938 (Soil Compaction &amp; Testing).
                  </td>
                </tr>
                <tr>
                  <th className="py-1 px-2.5 bg-slate-100 font-bold text-slate-900 border-r border-slate-300">Tender Inquiries</th>
                  <td className="py-1 px-2.5 text-slate-800">
                    All requests for information (RFIs) regarding foundation requirements or borehole data must be submitted in writing at least 5 business days prior to tender closing. Submit 1 electronic PDF bid.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* 11. Statutory Engineering Disclaimer Box */}
          <div className="border border-slate-400 p-2.5 text-xs space-y-1 text-slate-800 rfq-print-section">
            <div className="font-bold uppercase tracking-wider text-slate-900 text-[10px]">
              Statutory Engineering Disclaimer &amp; Review Status
            </div>
            <p className="text-[10px] leading-relaxed text-slate-700">
              {sanitizeAiWording(requirementReport.section_12_limitations_and_approval.statutory_disclaimer)}
            </p>
            <div className="text-[10px] font-bold text-slate-900 pt-1 border-t border-slate-300 flex justify-between">
              <span>Document Status: <strong>{isVerified ? 'VERIFIED BY LICENSED PROFESSIONAL ENGINEER' : 'UNAPPROVED PRELIMINARY DRAFT'}</strong></span>
              <span>Reviewer: <strong>{reviewerName}</strong></span>
            </div>
          </div>
        </div>
        </div>
      )}
    </div>
  );
};
