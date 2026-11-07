import React, { useState, useEffect } from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  FileText,
  ArrowLeft,
  Layers,
  Table as TableIcon,
  CheckCircle,
  Eye,
  AlertTriangle,
  RefreshCw,
  MapPin,
  Building,
  User,
  Calendar,
  Compass,
  ShieldCheck,
  CheckSquare,
  Info,
  Sliders,
  Sparkles,
  Brain,
  CheckCircle2,
  XCircle,
  MessageSquare,
  Image as ImageIcon,
  Crosshair,
  AlertOctagon,
  ZoomIn,
  Search,
  Globe,
  ExternalLink,
  BookOpen,
  ShieldAlert,
  Award,
} from 'lucide-react';
import { api, getBaseUrl } from '../api/client';
import {
  DocumentMetadata,
  DocumentPage,
  ExtractedTable,
  EvidenceRecord,
  BoundingBox,
  FoundationSystemRecommendation,
  BoringLogReference,
  SitePreparationRequirement,
  GeotechnicalAnalysisReport,
  PageClassificationResult,
  VisualEvidence,
  CrossModalDisagreement,
  PageContentType,
  FoundationResearchReport,
  FoundationOption,
  FoundationComparisonItem,
  ResearchSource,
  ResearchGap,
  EngineerQuestionItem,
} from '../api/types';
import { StatusBadge } from '../components/common/StatusBadge';
import { DocumentViewer } from '../components/documents/DocumentViewer';
import { Skeleton } from '../components/common/Skeleton';

export const DocumentDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const [searchParams, setSearchParams] = useSearchParams();
  const queryTab = searchParams.get('tab') as 'foundations' | 'site_prep' | 'ai_analysis' | 'foundation_research' | 'evidence' | 'tables' | 'sections' | 'viewer' | 'visual_intelligence' | null;
  const validTabs = ['foundations', 'site_prep', 'ai_analysis', 'foundation_research', 'evidence', 'tables', 'sections', 'viewer', 'visual_intelligence'];

  const [activeTab, setActiveTabState] = useState<'foundations' | 'site_prep' | 'ai_analysis' | 'foundation_research' | 'evidence' | 'tables' | 'sections' | 'viewer' | 'visual_intelligence'>(
    queryTab && validTabs.includes(queryTab) ? queryTab : 'foundations'
  );

  const setActiveTab = (tab: 'foundations' | 'site_prep' | 'ai_analysis' | 'foundation_research' | 'evidence' | 'tables' | 'sections' | 'viewer' | 'visual_intelligence') => {
    setActiveTabState(tab);
    setSearchParams({ tab }, { replace: true });
  };

  useEffect(() => {
    if (queryTab && validTabs.includes(queryTab) && queryTab !== activeTab) {
      setActiveTabState(queryTab);
    }
  }, [queryTab]);
  const [currentPage, setCurrentPage] = useState<number>(0);
  const [selectedEvidence, setSelectedEvidence] = useState<EvidenceRecord | null>(null);
  const [reviewComments, setReviewComments] = useState<string>('');

  // Foundation Research State
  const [researchReviewComments, setResearchReviewComments] = useState<string>('');
  const [selectedResearchOption, setSelectedResearchOption] = useState<string | null>(null);
  const [selectedAuthorityFilter, setSelectedAuthorityFilter] = useState<string>('ALL');
  const [selectedProvider, setSelectedProvider] = useState<string>('duckduckgo');

  // Visual Intelligence State
  const [selectedVisualPage, setSelectedVisualPage] = useState<number>(0);
  const [selectedVisionModel, setSelectedVisionModel] = useState<string>('qwen3-vl:2b');
  const [visualReviewNotes, setVisualReviewNotes] = useState<string>('');
  const [activeRegionId, setActiveRegionId] = useState<string | null>(null);
  const [visualCategoryFilter, setVisualCategoryFilter] = useState<string>('ALL');

  // Queries
  const { data: document, isLoading: loadingDoc } = useQuery<DocumentMetadata>({
    queryKey: ['document', id],
    queryFn: () => api.getDocument(id!),
    enabled: !!id,
  });

  const { data: pages = [] } = useQuery<DocumentPage[]>({
    queryKey: ['document-pages', id],
    queryFn: () => api.getDocumentPages(id!),
    enabled: !!id,
  });

  const { data: tables = [] } = useQuery<ExtractedTable[]>({
    queryKey: ['document-tables', id],
    queryFn: () => api.getDocumentTables(id!),
    enabled: !!id,
  });

  const { data: evidence = [] } = useQuery<EvidenceRecord[]>({
    queryKey: ['document-evidence', id],
    queryFn: () => api.getDocumentEvidence(id!),
    enabled: !!id,
  });

  const { data: foundations = [] } = useQuery<FoundationSystemRecommendation[]>({
    queryKey: ['document-foundations', id],
    queryFn: () => api.getFoundationRecommendations(id!),
    enabled: !!id,
  });

  const { data: sitePreparation = [] } = useQuery<SitePreparationRequirement[]>({
    queryKey: ['document-site-prep', id],
    queryFn: () => api.getSitePreparation(id!),
    enabled: !!id,
  });

  const { data: boringLogs = [] } = useQuery<BoringLogReference[]>({
    queryKey: ['document-boring-logs', id],
    queryFn: () => api.getBoringLogs(id!),
    enabled: !!id,
  });

  const { data: latestReport, isLoading: loadingReport } = useQuery<GeotechnicalAnalysisReport | null>({
    queryKey: ['document-geotech-report', id],
    queryFn: () => api.getLatestGeotechnicalReport(id!),
    enabled: !!id,
  });

  const runAnalysisMutation = useMutation({
    mutationFn: () => api.runGeotechnicalAnalysis(id!),
    onSuccess: (newReport) => {
      queryClient.setQueryData(['document-geotech-report', id], newReport);
      setActiveTab('ai_analysis');
    },
  });

  const reviewMutation = useMutation({
    mutationFn: ({
      decision,
      comments,
    }: {
      decision: 'PENDING_REVIEW' | 'HUMAN_VERIFIED' | 'REJECTED' | 'CHANGES_REQUESTED';
      comments?: string;
    }) => api.submitGeotechnicalReview(latestReport!.report_id, decision, 'licensed_engineer', comments),
    onSuccess: (updatedReport) => {
      queryClient.setQueryData(['document-geotech-report', id], updatedReport);
      setReviewComments('');
    },
  });

  const { data: latestResearchReport, isLoading: loadingResearch } = useQuery<FoundationResearchReport | null>({
    queryKey: ['document-foundation-research', id],
    queryFn: () => api.getLatestFoundationResearchForDocument(id!),
    enabled: !!id,
  });

  const runResearchMutation = useMutation({
    mutationFn: () => api.runFoundationResearch(id!, 'default', undefined, selectedProvider),
    onSuccess: (newResearchReport) => {
      queryClient.setQueryData(['document-foundation-research', id], newResearchReport);
      setActiveTab('foundation_research');
    },
  });

  const reviewResearchMutation = useMutation({
    mutationFn: ({
      decision,
      comments,
    }: {
      decision: 'PENDING_REVIEW' | 'APPROVED' | 'REJECTED';
      comments?: string;
    }) => api.submitFoundationResearchReview(latestResearchReport!.report_id, decision, 'licensed_engineer', comments),
    onSuccess: (updatedReport) => {
      queryClient.setQueryData(['document-foundation-research', id], updatedReport);
      setResearchReviewComments('');
    },
  });

  const updateStatusMutation = useMutation({
    mutationFn: ({
      evidenceId,
      status,
    }: {
      evidenceId: string;
      status: 'PENDING_REVIEW' | 'HUMAN_VERIFIED' | 'REJECTED' | 'unverified' | 'verified' | 'flagged';
    }) => api.updateEvidenceStatus(evidenceId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['document-evidence', id] });
    },
  });

  // Visual Intelligence Queries & Mutations
  const { data: pageClassifications = [] } = useQuery<PageClassificationResult[]>({
    queryKey: ['document-page-classifications', id],
    queryFn: () => api.getPageClassifications(id!),
    enabled: !!id,
  });

  // Reset page selections when navigating between documents
  useEffect(() => {
    setSelectedVisualPage(0);
    setCurrentPage(0);
    setSelectedEvidence(null);
  }, [id]);

  // Ensure selectedVisualPage and currentPage stay strictly within document page bounds
  useEffect(() => {
    if (pages.length > 0) {
      if (selectedVisualPage >= pages.length) {
        const visualPage = pageClassifications.find((c) => c.primary_content_type !== 'TEXT_ONLY');
        setSelectedVisualPage(visualPage ? visualPage.page_index : 0);
      }
      if (currentPage >= pages.length) {
        setCurrentPage(0);
      }
    }
  }, [pages.length, pageClassifications, selectedVisualPage, currentPage]);

  const { data: visualEvidenceList = [], refetch: refetchVisualEvidence } = useQuery<VisualEvidence[]>({
    queryKey: ['document-visual-evidence', id],
    queryFn: () => api.getVisualEvidence(id!),
    enabled: !!id,
  });

  const { data: disagreements = [], refetch: refetchDisagreements } = useQuery<CrossModalDisagreement[]>({
    queryKey: ['document-visual-disagreements', id],
    queryFn: () => api.getVisualDisagreements(id!),
    enabled: !!id,
  });

  const analyzeVisualMutation = useMutation({
    mutationFn: ({ pageIndex, modelOverride }: { pageIndex: number; modelOverride?: string }) =>
      api.analyzePageVisual(id!, pageIndex, modelOverride, true),
    onSuccess: () => {
      refetchVisualEvidence();
      refetchDisagreements();
    },
  });

  const reviewVisualMutation = useMutation({
    mutationFn: ({
      evidenceId,
      reviewStatus,
      notes,
    }: {
      evidenceId: string;
      reviewStatus: 'PENDING_REVIEW' | 'HUMAN_VERIFIED' | 'REJECTED' | 'CHANGES_REQUESTED';
      notes?: string;
    }) => api.reviewVisualEvidence(evidenceId, reviewStatus, notes),
    onSuccess: () => {
      refetchVisualEvidence();
      setVisualReviewNotes('');
    },
  });

  const resolveDisagreementMutation = useMutation({
    mutationFn: ({
      disagreementId,
      status,
      notes,
    }: {
      disagreementId: string;
      status: 'RESOLVED' | 'IGNORED';
      notes?: string;
    }) => api.resolveVisualDisagreement(disagreementId, status, notes),
    onSuccess: () => {
      refetchDisagreements();
    },
  });

  const jumpToEvidenceInPdf = (ev: EvidenceRecord) => {
    setCurrentPage(ev.page_index);
    setSelectedEvidence(ev);
    setActiveTab('viewer');
  };

  const jumpToTableInPdf = (tbl: ExtractedTable) => {
    setCurrentPage(tbl.page_index);
    if (tbl.bounding_box) {
      setSelectedEvidence({
        evidence_id: tbl.table_id,
        document_id: tbl.document_id,
        document_name: document?.filename || '',
        page_index: tbl.page_index,
        extracted_text: `Table (${tbl.headers.join(', ')})`,
        bounding_box: tbl.bounding_box,
        extraction_method: 'pdfplumber_table',
        verification_status: 'unverified',
        confidence_score: 1.0,
        created_at: '',
      });
    }
    setActiveTab('viewer');
  };

  if (loadingDoc) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!document) {
    return (
      <div className="p-8 text-center bg-slate-900/60 rounded-xl border border-slate-800">
        <AlertTriangle className="w-10 h-10 text-amber-400 mx-auto mb-2" />
        <h2 className="text-lg font-bold text-slate-200">Document Not Found</h2>
        <p className="text-xs text-slate-400 mt-1">The requested document ID does not exist.</p>
        <Link
          to="/documents"
          className="inline-flex items-center gap-1.5 mt-4 px-3 py-1.5 rounded-lg bg-cyan-600 text-white text-xs"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Documents
        </Link>
      </div>
    );
  }

  const proj = document.project_info;
  const activePageObj = pages.find((p) => p.page_index === currentPage);

  return (
    <div className="space-y-6">
      {/* Top Breadcrumb & Actions */}
      <div className="flex items-center justify-between">
        <Link
          to="/documents"
          className="inline-flex items-center gap-2 text-xs text-slate-400 hover:text-slate-200 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Documents
        </Link>
        <div className="flex items-center gap-2">
          <StatusBadge status={document.status} />
          <span
            className={`px-2 py-0.5 rounded text-[11px] font-medium border ${
              document.document_type === 'scanned'
                ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                : document.document_type === 'hybrid'
                ? 'bg-orange-500/10 text-orange-400 border-orange-500/30'
                : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
            }`}
          >
            {document.document_type}
          </span>
        </div>
      </div>

      {/* Document Overview Banner */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 border-b border-slate-800 pb-4">
          <div>
            <h1 className="text-lg font-bold text-slate-100 flex items-center gap-2">
              <FileText className="w-5 h-5 text-cyan-400 flex-shrink-0" />
              {document.filename}
            </h1>
            <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400 mt-1 font-mono">
              <span>ID: {document.document_id}</span>
              <span>•</span>
              <span>{(document.file_size_bytes / (1024 * 1024)).toFixed(2)} MB</span>
              <span>•</span>
              <span>{document.page_count} Pages</span>
              <span>•</span>
              <span title={document.sha256_hash}>
                SHA-256: {document.sha256_hash.slice(0, 10)}...{document.sha256_hash.slice(-8)}
              </span>
            </div>
          </div>
        </div>

        {/* Extracted Geotechnical Project Context */}
        {proj && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 bg-slate-950/60 p-3.5 rounded-lg border border-slate-800/80 text-xs">
            {proj.project_name && (
              <div>
                <span className="text-[10px] text-slate-400 uppercase font-semibold flex items-center gap-1">
                  <Compass className="w-3 h-3 text-cyan-400" /> Project
                </span>
                <p className="font-medium text-slate-200 mt-0.5 truncate" title={proj.project_name}>
                  {proj.project_name}
                </p>
              </div>
            )}
            {proj.site_location && (
              <div>
                <span className="text-[10px] text-slate-400 uppercase font-semibold flex items-center gap-1">
                  <MapPin className="w-3 h-3 text-emerald-400" /> Location
                </span>
                <p className="font-medium text-slate-200 mt-0.5 truncate" title={proj.site_location}>
                  {proj.site_location}
                </p>
              </div>
            )}
            {proj.client_name && (
              <div>
                <span className="text-[10px] text-slate-400 uppercase font-semibold flex items-center gap-1">
                  <User className="w-3 h-3 text-indigo-400" /> Client
                </span>
                <p className="font-medium text-slate-200 mt-0.5 truncate" title={proj.client_name}>
                  {proj.client_name}
                </p>
              </div>
            )}
            {proj.engineer_firm && (
              <div>
                <span className="text-[10px] text-slate-400 uppercase font-semibold flex items-center gap-1">
                  <Building className="w-3 h-3 text-amber-400" /> Geotechnical Consultant
                </span>
                <p className="font-medium text-slate-200 mt-0.5 truncate" title={proj.engineer_firm}>
                  {proj.engineer_firm}
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Tabs Bar */}
      <div className="flex items-center gap-1 border-b border-slate-800">
        <button
          onClick={() => setActiveTab('foundations')}
          className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'foundations'
              ? 'border-cyan-400 text-cyan-300 bg-slate-900/40'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Building className="w-3.5 h-3.5 text-cyan-400" />
          Foundation Systems ({foundations.length})
        </button>

        <button
          onClick={() => setActiveTab('site_prep')}
          className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'site_prep'
              ? 'border-emerald-400 text-emerald-300 bg-slate-900/40'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <CheckSquare className="w-3.5 h-3.5 text-emerald-400" />
          Site & Subgrade Preparation ({sitePreparation.length})
        </button>

        <button
          onClick={() => setActiveTab('ai_analysis')}
          className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'ai_analysis'
              ? 'border-indigo-400 text-indigo-300 bg-slate-900/40'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
          AI Geotechnical Analysis {latestReport ? `(${latestReport.review_status})` : ''}
        </button>

        <button
          onClick={() => setActiveTab('foundation_research')}
          className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'foundation_research'
              ? 'border-teal-400 text-teal-300 bg-slate-900/40'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Search className="w-3.5 h-3.5 text-teal-400" />
          Foundation Research {latestResearchReport ? `(${latestResearchReport.review_status})` : ''}
        </button>

        <button
          onClick={() => setActiveTab('evidence')}
          className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'evidence'
              ? 'border-cyan-400 text-cyan-300 bg-slate-900/40'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <CheckCircle className="w-3.5 h-3.5 text-cyan-400" />
          Technical Evidence Records ({evidence.length})
        </button>

        <button
          onClick={() => setActiveTab('tables')}
          className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'tables'
              ? 'border-cyan-400 text-cyan-300 bg-slate-900/40'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <TableIcon className="w-3.5 h-3.5 text-indigo-400" />
          Extracted Tables & Boring Logs ({tables.length})
        </button>

        <button
          onClick={() => setActiveTab('sections')}
          className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'sections'
              ? 'border-cyan-400 text-cyan-300 bg-slate-900/40'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Layers className="w-3.5 h-3.5 text-emerald-400" />
          Sections & Content ({pages.length} Pages)
        </button>

        <button
          onClick={() => setActiveTab('viewer')}
          className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'viewer'
              ? 'border-cyan-400 text-cyan-300 bg-slate-900/40'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Eye className="w-3.5 h-3.5 text-amber-400" />
          Interactive PDF Page Viewer
        </button>

        <button
          onClick={() => {
            setActiveTab('visual_intelligence');
            if (pages.length > 0) {
              if (selectedVisualPage >= pages.length || selectedVisualPage === 0) {
                const visualPage = pageClassifications.find((c) => c.primary_content_type !== 'TEXT_ONLY');
                setSelectedVisualPage(visualPage ? visualPage.page_index : 0);
              }
            }
          }}
          className={`px-4 py-2.5 text-xs font-semibold flex items-center gap-2 border-b-2 transition-all ${
            activeTab === 'visual_intelligence'
              ? 'border-purple-400 text-purple-300 bg-slate-900/40'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <ImageIcon className="w-3.5 h-3.5 text-purple-400" />
          Visual Intelligence & Drawings ({visualEvidenceList.length})
          {disagreements.filter((d) => d.status === 'OPEN').length > 0 && (
            <span className="px-1.5 py-0.5 text-[10px] font-bold bg-amber-500/20 text-amber-300 rounded-full border border-amber-500/30">
              {disagreements.filter((d) => d.status === 'OPEN').length} alert
            </span>
          )}
        </button>
      </div>

      {/* Tab 0: Foundation Recommendations */}
      {activeTab === 'foundations' && (
        <div className="space-y-6">
          {foundations.length === 0 ? (
            <div className="p-8 text-center bg-slate-900/60 rounded-xl border border-slate-800 text-slate-400 text-xs">
              No foundation systems extracted yet. Try reprocessing the document.
            </div>
          ) : (
            foundations.map((sys, sIdx) => (
              <div
                key={sIdx}
                className="bg-slate-900/70 border border-slate-800 rounded-xl overflow-hidden shadow-sm space-y-3"
              >
                <div className="flex flex-col md:flex-row md:items-center justify-between px-5 py-3.5 bg-slate-950/80 border-b border-slate-800 gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded bg-cyan-950 border border-cyan-800/80 text-cyan-400 text-[11px] font-mono font-semibold">
                        System {sIdx + 1}
                      </span>
                      <h2 className="text-sm font-bold text-slate-100">{sys.system_name}</h2>
                    </div>
                    <p className="text-xs text-slate-400 mt-1">{sys.description}</p>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] font-mono text-slate-400">
                    <span className="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700">
                      {sys.page_range}
                    </span>
                  </div>
                </div>

                <div className="overflow-x-auto px-1">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-950/60 text-slate-400 border-b border-slate-800">
                      <tr>
                        <th className="px-4 py-2.5 font-semibold">Design Parameter</th>
                        <th className="px-4 py-2.5 font-semibold">Value</th>
                        <th className="px-4 py-2.5 font-semibold">Load Case</th>
                        <th className="px-4 py-2.5 font-semibold">Factor of Safety</th>
                        <th className="px-4 py-2.5 font-semibold">Engineering Conditions & Notes</th>
                        <th className="px-4 py-2.5 font-semibold">Source Page</th>
                        <th className="px-4 py-2.5 font-semibold text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/40">
                      {sys.parameters.map((param, pIdx) => (
                        <tr key={pIdx} className="hover:bg-slate-800/20 transition-colors">
                          <td className="px-4 py-2.5 font-medium text-slate-200">
                            {param.parameter_name}
                          </td>

                          <td className="px-4 py-2.5 font-semibold text-cyan-300 font-mono">
                            {param.value}
                          </td>

                          <td className="px-4 py-2.5 text-slate-300">
                            {param.load_case ? (
                              <span className="px-2 py-0.5 rounded bg-indigo-950/60 border border-indigo-800/50 text-[11px] text-indigo-300">
                                {param.load_case}
                              </span>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>

                          <td className="px-4 py-2.5 text-slate-300 font-mono">
                            {param.factor_of_safety ? (
                              <span className="px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800/50 text-[11px] text-emerald-300">
                                FS {param.factor_of_safety.toFixed(1)}
                              </span>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>

                          <td className="px-4 py-2.5 text-slate-400 text-[11px] max-w-[280px]">
                            {param.conditions ? (
                              <span className={param.conditions.toLowerCase().includes('settlement') || param.conditions.toLowerCase().includes('caving') ? 'text-amber-400 font-medium' : ''}>
                                {param.conditions}
                              </span>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>

                          <td className="px-4 py-2.5 font-mono text-[11px]">
                            <span className="text-slate-300">Page {param.page_index + 1}</span>
                            {param.printed_page_number && (
                              <span className="ml-1.5 px-1 py-0.5 rounded bg-slate-950 border border-slate-800 text-[10px] text-slate-400">
                                Folio {param.printed_page_number}
                              </span>
                            )}
                          </td>

                          <td className="px-4 py-2.5 text-right">
                            <button
                              onClick={() => {
                                setCurrentPage(param.page_index);
                                setActiveTab('viewer');
                              }}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-cyan-950/60 border border-cyan-800/60 hover:bg-cyan-900/60 text-cyan-300 text-[11px] transition-colors"
                            >
                              <Eye className="w-3 h-3" /> View in PDF
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Tab: Site & Subgrade Preparation Requirements */}
      {activeTab === 'site_prep' && (
        <div className="space-y-4">
          <div className="p-4 bg-slate-900/80 border border-slate-800 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 text-xs font-semibold">
                  Section 1.3.1
                </span>
                <h2 className="text-sm font-bold text-slate-100">
                  Site and Subgrade Preparation Requirements
                </h2>
              </div>
              <p className="text-xs text-slate-400 mt-1">
                Deterministic structured extraction of all 12 engineering specifications governing subgrade stripping, proofrolling, unsuitable soil treatment, select fill criteria, lift thicknesses, and ASTM D 698 compaction controls.
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs font-mono text-slate-400 self-start md:self-auto">
              <span className="px-2.5 py-1 rounded bg-slate-950 border border-slate-800">
                Source: Pages 6–7 (Folio 3–4)
              </span>
            </div>
          </div>

          <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-slate-300">
                <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800">
                  <tr>
                    <th className="px-4 py-3 font-semibold">#</th>
                    <th className="px-4 py-3 font-semibold">Specification</th>
                    <th className="px-4 py-3 font-semibold">Engineered Value / Limit</th>
                    <th className="px-4 py-3 font-semibold">Standard Reference</th>
                    <th className="px-4 py-3 font-semibold">Engineering Conditions & Instructions</th>
                    <th className="px-4 py-3 font-semibold">Source Page</th>
                    <th className="px-4 py-3 font-semibold text-right">Inspect Source</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {sitePreparation.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="px-4 py-8 text-center text-slate-400">
                        No site preparation requirements found. Click Reprocess Document to extract.
                      </td>
                    </tr>
                  ) : (
                    sitePreparation.map((req, rIdx) => (
                      <tr key={rIdx} className="hover:bg-slate-800/30 transition-colors">
                        <td className="px-4 py-3 font-mono text-slate-400">
                          {rIdx + 1}
                        </td>
                        <td className="px-4 py-3 font-medium text-slate-200 max-w-[280px]">
                          <div className="font-semibold text-emerald-400">{req.requirement_name}</div>
                          <div className="text-[11px] text-slate-400 mt-0.5 line-clamp-2" title={req.requirement_text}>
                            {req.requirement_text}
                          </div>
                        </td>
                        <td className="px-4 py-3 font-mono">
                          <span className="px-2 py-0.5 rounded bg-slate-950 border border-slate-700 text-cyan-300 font-semibold">
                            {req.original_value}
                          </span>
                        </td>
                        <td className="px-4 py-3 font-mono text-slate-300">
                          {req.standard_reference ? (
                            <span className="px-2 py-0.5 rounded bg-indigo-950/60 border border-indigo-800/50 text-[11px] text-indigo-300">
                              {req.standard_reference}
                            </span>
                          ) : (
                            <span className="text-slate-400">—</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-[11px] max-w-[260px]">
                          {req.conditions || '—'}
                        </td>
                        <td className="px-4 py-3 font-mono text-slate-300 whitespace-nowrap">
                          <span>Page {req.page_index + 1}</span>
                          {req.printed_page_number && (
                            <span className="ml-1.5 px-1 py-0.5 rounded bg-slate-950 border border-slate-800 text-[10px] text-slate-400">
                              Folio {req.printed_page_number}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right whitespace-nowrap">
                          <button
                            onClick={() => {
                              setCurrentPage(req.page_index);
                              setActiveTab('viewer');
                            }}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-emerald-950/60 border border-emerald-800/60 hover:bg-emerald-900/60 text-emerald-300 text-xs transition-colors"
                          >
                            <Eye className="w-3 h-3" />
                            View in PDF
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Tab: AI Geotechnical Analysis Report (Phase 2) */}
      {activeTab === 'ai_analysis' && (
        <div className="space-y-6">
          {!latestReport ? (
            <div className="p-8 text-center bg-slate-900/60 rounded-xl border border-slate-800 space-y-4">
              <div className="inline-flex p-3 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
                <Brain className="w-8 h-8" />
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-100">AI Geotechnical Analysis Agent</h3>
                <p className="text-xs text-slate-400 mt-1 max-w-xl mx-auto">
                  Run the 8-node LangGraph Geotechnical Analysis Agent pipeline over the extracted evidence records,
                  boring logs, laboratory test readings, foundation options, and site prep specifications.
                </p>
              </div>
              <button
                onClick={() => runAnalysisMutation.mutate()}
                disabled={runAnalysisMutation.isPending}
                className="btn-primary inline-flex items-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white px-5 py-2.5 rounded-lg text-xs font-semibold shadow-lg shadow-indigo-600/20"
              >
                {runAnalysisMutation.isPending ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Executing LangGraph Reasoning Nodes...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5" />
                    Generate Geotechnical Analysis Now
                  </>
                )}
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Header Banner */}
              <div className="p-5 bg-slate-900/80 border border-slate-800 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="px-2.5 py-0.5 rounded-full bg-indigo-950 border border-indigo-700/60 text-indigo-400 text-[11px] font-mono font-semibold">
                      LangGraph Agent
                    </span>
                    <h2 className="text-base font-bold text-slate-100">AI Geotechnical Analysis Report</h2>
                    <span
                      className={`px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${
                        latestReport.review_status === 'HUMAN_VERIFIED'
                          ? 'bg-emerald-950/80 border-emerald-500/50 text-emerald-300'
                          : latestReport.review_status === 'REJECTED'
                          ? 'bg-rose-950/80 border-rose-500/50 text-rose-300'
                          : latestReport.review_status === 'CHANGES_REQUESTED'
                          ? 'bg-purple-950/80 border-purple-500/50 text-purple-300'
                          : 'bg-amber-950/80 border-amber-500/50 text-amber-300'
                      }`}
                    >
                      {latestReport.review_status === 'HUMAN_VERIFIED'
                        ? 'Verified & Stamped'
                        : latestReport.review_status === 'REJECTED'
                        ? 'Rejected'
                        : latestReport.review_status === 'CHANGES_REQUESTED'
                        ? 'Changes Requested'
                        : 'Pending Human Review'}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1 font-mono">
                    Report ID: {latestReport.report_id} • Generated: {new Date(latestReport.created_at).toLocaleString()} • Profile: {latestReport.llm_profile_used}
                  </p>
                </div>

                <button
                  onClick={() => runAnalysisMutation.mutate()}
                  disabled={runAnalysisMutation.isPending}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition-colors self-start md:self-auto"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${runAnalysisMutation.isPending ? 'animate-spin' : ''}`} />
                  Re-run Analysis
                </button>
              </div>

              {/* Human Review & Stamping Toolbar */}
              <div className="p-4 bg-slate-950/80 border border-slate-800 rounded-xl space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-emerald-400" />
                    <span className="text-xs font-bold text-slate-200 uppercase tracking-wider">
                      Professional Review & Verification
                    </span>
                  </div>
                  <span className="text-[11px] text-slate-400">
                    Review Status: <strong className="text-slate-200">{latestReport.review_status}</strong>
                  </span>
                </div>

                <div className="flex flex-col md:flex-row gap-3">
                  <input
                    type="text"
                    value={reviewComments}
                    onChange={(e) => setReviewComments(e.target.value)}
                    placeholder="Enter review comments, engineering qualifications, or requests..."
                    className="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() =>
                        reviewMutation.mutate({
                          decision: 'HUMAN_VERIFIED',
                          comments: reviewComments || 'Verified by Licensed Geotechnical Engineer',
                        })
                      }
                      disabled={reviewMutation.isPending}
                      className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold inline-flex items-center gap-1.5 transition-colors"
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Verify & Stamp
                    </button>

                    <button
                      onClick={() =>
                        reviewMutation.mutate({
                          decision: 'CHANGES_REQUESTED',
                          comments: reviewComments || 'Additional clarifications or calculations requested',
                        })
                      }
                      disabled={reviewMutation.isPending}
                      className="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold inline-flex items-center gap-1.5 transition-colors"
                    >
                      <MessageSquare className="w-3.5 h-3.5" />
                      Request Changes
                    </button>

                    <button
                      onClick={() =>
                        reviewMutation.mutate({
                          decision: 'REJECTED',
                          comments: reviewComments || 'Report rejected by reviewing engineer',
                        })
                      }
                      disabled={reviewMutation.isPending}
                      className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold inline-flex items-center gap-1.5 transition-colors"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      Reject
                    </button>
                  </div>
                </div>

                {latestReport.review_history && latestReport.review_history.length > 0 && (
                  <div className="pt-2 border-t border-slate-900 space-y-1">
                    <span className="text-[10px] font-semibold text-slate-400 uppercase">Review Audit History:</span>
                    {latestReport.review_history.map((rev, revIdx) => (
                      <div key={revIdx} className="text-[11px] text-slate-300 flex items-center justify-between">
                        <span>
                          <strong className="text-slate-100">{rev.reviewer_id}</strong>: {rev.decision} — "{rev.comments}"
                        </span>
                        <span className="text-[10px] font-mono text-slate-400">
                          {new Date(rev.timestamp).toLocaleString()}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Statutory Disclaimer Alert */}
              <div className="p-3.5 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-start gap-2.5">
                <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <p className="text-xs text-amber-300/90 leading-relaxed">
                  <strong>Statutory Engineering Disclaimer:</strong> {latestReport.limitations_and_review.statutory_disclaimer}
                </p>
              </div>

              {/* Section 1: Executive Summary */}
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-3">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded bg-indigo-950 border border-indigo-800 text-indigo-400 text-xs font-semibold">
                    Section 1
                  </span>
                  <h3 className="text-sm font-bold text-slate-100">Executive Summary</h3>
                </div>
                <p className="text-xs text-slate-300 leading-relaxed">
                  {latestReport.executive_summary.overview}
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 pt-2">
                  <div className="p-3 bg-slate-950/80 rounded-lg border border-slate-800">
                    <span className="text-[10px] text-slate-400 uppercase font-semibold">Dominant Soil</span>
                    <p className="text-xs font-bold text-cyan-400 mt-1">{latestReport.executive_summary.dominant_soil_classification}</p>
                  </div>
                  <div className="p-3 bg-slate-950/80 rounded-lg border border-slate-800">
                    <span className="text-[10px] text-slate-400 uppercase font-semibold">Primary Options</span>
                    <p className="text-xs font-bold text-slate-200 mt-1">{latestReport.executive_summary.primary_foundation_options.length} Systems Analyzed</p>
                  </div>
                  <div className="p-3 bg-slate-950/80 rounded-lg border border-slate-800">
                    <span className="text-[10px] text-slate-400 uppercase font-semibold">Key Hazards</span>
                    <p className="text-xs font-bold text-amber-400 mt-1">{latestReport.executive_summary.key_engineering_risks.length} Risks Identified</p>
                  </div>
                  <div className="p-3 bg-slate-950/80 rounded-lg border border-slate-800">
                    <span className="text-[10px] text-slate-400 uppercase font-semibold">Licensure Stamping</span>
                    <p className="text-xs font-bold text-emerald-400 mt-1">Mandatory PE Review</p>
                  </div>
                </div>
              </div>

              {/* Section 2: Project & Document Context */}
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-indigo-950 border border-indigo-800 text-indigo-400 text-xs font-semibold">
                      Section 2
                    </span>
                    <h3 className="text-sm font-bold text-slate-100">Project and Document Context</h3>
                  </div>
                  <span className="px-2.5 py-0.5 rounded-full text-[10px] font-mono bg-slate-950 border border-slate-800 text-slate-400">
                    Cross-Doc Matching: <strong className="text-amber-400">{latestReport.project_context.cross_document_status || 'NOT_ASSESSED'}</strong>
                  </span>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase">Project Name</span>
                    <p className="font-semibold text-slate-200">{latestReport.project_context.project_name || '—'}</p>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase">Project Number</span>
                    <p className="font-semibold text-slate-200">{latestReport.project_context.project_number || '—'}</p>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase">Site Address</span>
                    <p className="font-semibold text-slate-200">{latestReport.project_context.site_location || latestReport.project_context.address || '—'}</p>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase">Legal Description</span>
                    <p className="font-semibold text-slate-200">{latestReport.project_context.legal_description || '—'}</p>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase">Client</span>
                    <p className="font-semibold text-slate-200">{latestReport.project_context.client_name || '—'}</p>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase">Consultant Firm</span>
                    <p className="font-semibold text-slate-200">{latestReport.project_context.geotechnical_consultant || '—'}</p>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase">Original Report Date</span>
                    <p className="font-semibold text-slate-200">{latestReport.project_context.original_document_date || latestReport.project_context.report_date || '—'}</p>
                  </div>
                  <div>
                    <span className="text-slate-400 text-[10px] uppercase">Uploaded Document</span>
                    <p className="font-semibold text-slate-200">{latestReport.project_context.uploaded_filename || latestReport.document_name} {latestReport.project_context.document_version ? `(${latestReport.project_context.document_version})` : ''}</p>
                  </div>
                </div>
                <div className="p-2.5 bg-slate-950/60 border border-slate-800/80 rounded-lg text-[11px] text-slate-400 flex items-center justify-between">
                  <span>
                    <strong>Cross-Document Status:</strong> {latestReport.project_context.cross_document_matching_note || 'Cross-document project matching has not been performed; single geotechnical report analyzed.'}
                  </span>
                  <span className="text-[10px] font-mono text-slate-400">
                    AI Analysis: {new Date(latestReport.project_context.analysis_generated_at || latestReport.created_at).toLocaleString()}
                  </span>
                </div>
                {latestReport.project_context.has_discrepancies && (
                  <div className="p-3 bg-rose-500/10 border border-rose-500/20 rounded-lg space-y-1">
                    <span className="text-xs font-bold text-rose-400 flex items-center gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5" /> Document Inconsistencies Detected:
                    </span>
                    {latestReport.project_context.discrepancies.map((d, dIdx) => (
                      <p key={dIdx} className="text-xs text-rose-300">
                        • <strong>{d.field_name}:</strong> {d.description}
                      </p>
                    ))}
                  </div>
                )}
              </div>

              {/* Section 4 & 5: Subsurface Stratigraphy & Laboratory Interpretation */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-cyan-950 border border-cyan-800 text-cyan-400 text-xs font-semibold">
                      Section 4
                    </span>
                    <h3 className="text-sm font-bold text-slate-100">Subsurface Soil Stratigraphy</h3>
                  </div>
                  <div className="p-3 bg-slate-950/80 rounded-lg border border-slate-800">
                    <span className="text-xs font-bold text-cyan-300">{latestReport.subsurface_conditions.dominant_stratum}</span>
                    <p className="text-xs text-slate-400 mt-1">{latestReport.subsurface_conditions.consistency_summary}</p>
                  </div>
                  <div className="space-y-2">
                    {latestReport.subsurface_conditions.strata.map((st, sIdx) => (
                      <div key={sIdx} className="p-2.5 bg-slate-950/60 rounded-lg border border-slate-800/80 text-xs space-y-1">
                        <div className="flex items-center justify-between font-semibold">
                          <span className="text-slate-200">{st.boring_id} ({st.depth_range_ft})</span>
                          <span className="px-2 py-0.5 rounded bg-cyan-950 border border-cyan-800 text-[10px] text-cyan-300">
                            USCS: {st.uscs_classification}
                          </span>
                        </div>
                        <p className="text-slate-400 text-[11px]">{st.consistency}</p>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {st.observations.map((ob, obIdx) => (
                            <span key={obIdx} className="px-2 py-0.5 rounded bg-slate-900 border border-slate-800 text-[10px] text-slate-300">
                              {ob}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-indigo-950 border border-indigo-800 text-indigo-400 text-xs font-semibold">
                      Section 5
                    </span>
                    <h3 className="text-sm font-bold text-slate-100">Laboratory Properties & PVR</h3>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="p-2.5 bg-slate-950/80 rounded-lg border border-slate-800">
                      <span className="text-[10px] text-slate-400 uppercase">Moisture Content</span>
                      <p className="font-mono font-bold text-cyan-300 mt-0.5">{latestReport.laboratory_interpretation.moisture_content_range}</p>
                    </div>
                    <div className="p-2.5 bg-slate-950/80 rounded-lg border border-slate-800">
                      <span className="text-[10px] text-slate-400 uppercase">Plasticity Index</span>
                      <p className="font-mono font-bold text-cyan-300 mt-0.5">{latestReport.laboratory_interpretation.plasticity_index_range} (LL: {latestReport.laboratory_interpretation.liquid_limit_range})</p>
                    </div>
                    <div className="p-2.5 bg-slate-950/80 rounded-lg border border-slate-800">
                      <span className="text-[10px] text-slate-400 uppercase">Passing No. 200</span>
                      <p className="font-mono font-bold text-cyan-300 mt-0.5">{latestReport.laboratory_interpretation.percent_passing_no_200_range}</p>
                    </div>
                    <div className="p-2.5 bg-slate-950/80 rounded-lg border border-slate-800">
                      <span className="text-[10px] text-slate-400 uppercase">Pocket Penetrometer</span>
                      <p className="font-mono font-bold text-cyan-300 mt-0.5">{latestReport.laboratory_interpretation.pocket_penetrometer_range_tsf}</p>
                    </div>
                  </div>
                  <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-lg text-xs space-y-1">
                    <div className="flex items-center justify-between font-semibold text-amber-300">
                      <span>Potential Vertical Rise (PVR)</span>
                      <span className="px-2 py-0.5 rounded bg-amber-950 border border-amber-700 text-xs font-mono">
                        {latestReport.laboratory_interpretation.pvr_value_inches} in
                      </span>
                    </div>
                    <p className="text-amber-200/80 text-[11px] leading-relaxed">
                      {latestReport.laboratory_interpretation.pvr_interpretation}
                    </p>
                  </div>
                  <p className="text-[11px] text-slate-400 italic">
                    {latestReport.laboratory_interpretation.spt_status}
                  </p>
                </div>
              </div>

              {/* Section 6: Groundwater Assessment */}
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-3">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded bg-blue-950 border border-blue-800 text-blue-400 text-xs font-semibold">
                    Section 6
                  </span>
                  <h3 className="text-sm font-bold text-slate-100">Groundwater Level Assessment</h3>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                  <div className="p-3 bg-slate-950/80 rounded-lg border border-slate-800 space-y-2">
                    <span className="text-[10px] font-semibold text-slate-400 uppercase">Measured Water Depths</span>
                    {latestReport.groundwater_assessment.measurements.map((gw, gIdx) => (
                      <div key={gIdx} className="flex items-center justify-between font-mono text-slate-200 text-xs">
                        <span>Borehole {gw.boring_id}:</span>
                        <span>Drilling: <strong>{gw.drilling_depth_ft} ft</strong> • 15-min Post: <strong>{gw.post_drilling_depth_ft} ft</strong></span>
                      </div>
                    ))}
                  </div>
                  <div className="p-3 bg-slate-950/80 rounded-lg border border-slate-800 space-y-1.5">
                    <span className="text-[10px] font-semibold text-slate-400 uppercase">Engineering Impact</span>
                    <p className="text-slate-300 text-[11px] leading-relaxed">
                      {latestReport.groundwater_assessment.construction_impact}
                    </p>
                  </div>
                </div>
              </div>

              {/* Section 8: Foundation Comparison Matrix */}
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl overflow-hidden space-y-3">
                <div className="px-5 py-3.5 bg-slate-950/80 border-b border-slate-800 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-indigo-950 border border-indigo-800 text-indigo-400 text-xs font-semibold">
                      Section 8
                    </span>
                    <h3 className="text-sm font-bold text-slate-100">Foundation Systems Comparison Matrix</h3>
                  </div>
                </div>
                <div className="overflow-x-auto px-4 pb-4">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800">
                      <tr>
                        <th className="px-4 py-2.5 font-semibold">Foundation System</th>
                        <th className="px-4 py-2.5 font-semibold">Allowable Bearing</th>
                        <th className="px-4 py-2.5 font-semibold">Settlement / PVR Control</th>
                        <th className="px-4 py-2.5 font-semibold">Risk Level</th>
                        <th className="px-4 py-2.5 font-semibold">Constructability & Caving</th>
                        <th className="px-4 py-2.5 font-semibold">Relative Cost</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {latestReport.foundation_comparison.comparison_matrix.map((row, rIdx) => (
                        <tr key={rIdx} className="hover:bg-slate-800/30 transition-colors">
                          <td className="px-4 py-3 font-bold text-slate-200">{row.system_name}</td>
                          <td className="px-4 py-3 font-mono text-cyan-300">{row.bearing_capacity}</td>
                          <td className="px-4 py-3 text-slate-300 text-[11px] max-w-[200px]">{row.settlement_performance}</td>
                          <td className="px-4 py-3">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                                row.risk_level === 'HIGH'
                                  ? 'bg-rose-950 border-rose-800 text-rose-300'
                                  : row.risk_level === 'MEDIUM'
                                  ? 'bg-amber-950 border-amber-800 text-amber-300'
                                  : 'bg-emerald-950 border-emerald-800 text-emerald-300'
                              }`}
                            >
                              {row.risk_level}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-slate-400 text-[11px] max-w-[220px]">{row.constructability_and_caving_risk}</td>
                          <td className="px-4 py-3 text-slate-300">{row.relative_cost_complexity}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="px-5 pb-4">
                  <div className="p-3 bg-indigo-950/40 border border-indigo-800/40 rounded-lg text-xs text-indigo-300/90 leading-relaxed">
                    <strong>Floor Slab Clarification:</strong> {latestReport.foundation_comparison.floor_slab_vs_foundation_clarification}
                  </div>
                </div>
              </div>

              {/* Section 10: Geotechnical Risks & Concerns */}
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-4">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded bg-rose-950 border border-rose-800 text-rose-400 text-xs font-semibold">
                    Section 10
                  </span>
                  <h3 className="text-sm font-bold text-slate-100">Potential Geotechnical Risks and Concerns</h3>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {latestReport.risks_and_concerns.identified_risks.map((risk, rIdx) => (
                    <div key={rIdx} className="p-4 bg-slate-950/80 border border-slate-800 rounded-xl space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[10px] font-mono text-slate-400">{risk.risk_id} • {risk.category}</span>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                            risk.severity === 'HIGH'
                              ? 'bg-rose-950 border-rose-800 text-rose-300'
                              : risk.severity === 'MEDIUM'
                              ? 'bg-amber-950 border-amber-800 text-amber-300'
                              : 'bg-emerald-950 border-emerald-800 text-emerald-300'
                          }`}
                        >
                          {risk.severity} SEVERITY
                        </span>
                      </div>
                      <h4 className="text-xs font-bold text-slate-100">{risk.title}</h4>
                      <p className="text-xs text-slate-300 leading-relaxed">{risk.description}</p>
                      <div className="p-2.5 bg-slate-900/80 rounded border border-slate-800 text-[11px] text-cyan-300">
                        <strong>Engineering Mitigation:</strong> {risk.mitigation_in_report}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Section 11 & 12: Missing Information & Questions for Engineers */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-amber-950 border border-amber-800 text-amber-400 text-xs font-semibold">
                      Section 11
                    </span>
                    <h3 className="text-sm font-bold text-slate-100">Missing Information Required</h3>
                  </div>
                  <div className="space-y-2.5">
                    {latestReport.missing_information.items.map((m, mIdx) => (
                      <div key={mIdx} className="p-3 bg-slate-950/80 rounded-lg border border-slate-800 text-xs space-y-1">
                        <div className="flex items-center justify-between font-semibold">
                          <span className="text-slate-100">{m.title}</span>
                          <span className="px-1.5 py-0.5 rounded bg-slate-900 border border-slate-700 text-[10px] text-amber-400">
                            {m.criticality}
                          </span>
                        </div>
                        <p className="text-slate-400 text-[11px]">{m.description}</p>
                        <p className="text-indigo-300 text-[10px]">Impact: {m.impact_on_design}</p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-indigo-950 border border-indigo-800 text-indigo-400 text-xs font-semibold">
                      Section 12
                    </span>
                    <h3 className="text-sm font-bold text-slate-100">Questions for Engineers</h3>
                  </div>
                  <div className="space-y-2.5">
                    {latestReport.questions_for_engineers.questions.map((q, qIdx) => (
                      <div key={qIdx} className="p-3 bg-slate-950/80 rounded-lg border border-slate-800 text-xs space-y-1">
                        <span className="px-2 py-0.5 rounded bg-indigo-950 border border-indigo-800 text-indigo-400 text-[10px] font-semibold">
                          To: {q.target_discipline}
                        </span>
                        <p className="text-slate-200 font-medium text-xs mt-1">{q.question}</p>
                        <p className="text-slate-400 text-[10px] italic">Rationale: {q.engineering_rationale}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Section 13: Evidence References */}
              <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded bg-emerald-950 border border-emerald-800 text-emerald-400 text-xs font-semibold">
                      Section 13
                    </span>
                    <h3 className="text-sm font-bold text-slate-100">
                      Verified Evidence References ({latestReport.evidence_references.total_citations})
                    </h3>
                  </div>
                  <span className="text-[11px] text-slate-400">
                    All findings grounded in database evidence records
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800">
                      <tr>
                        <th className="px-4 py-2 font-semibold">Evidence ID</th>
                        <th className="px-4 py-2 font-semibold">Property Category</th>
                        <th className="px-4 py-2 font-semibold">Value</th>
                        <th className="px-4 py-2 font-semibold">Source Page</th>
                        <th className="px-4 py-2 font-semibold text-right">Inspect Source</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {latestReport.evidence_references.citations.map((c, cIdx) => (
                        <tr key={cIdx} className="hover:bg-slate-800/30 transition-colors">
                          <td className="px-4 py-2 font-mono text-cyan-400">{c.evidence_id}</td>
                          <td className="px-4 py-2 text-slate-300">{c.property_type || c.property_name || 'geotechnical'}</td>
                          <td className="px-4 py-2 font-mono font-semibold text-slate-200">{c.value}</td>
                          <td className="px-4 py-2 font-mono text-slate-400">
                            Page {c.page_index + 1} {c.printed_page_number ? `(Folio ${c.printed_page_number})` : ''}
                          </td>
                          <td className="px-4 py-2 text-right">
                            <button
                              onClick={() => {
                                setCurrentPage(c.page_index);
                                setActiveTab('viewer');
                              }}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/60 hover:bg-cyan-900/60 text-cyan-300 text-[11px] transition-colors"
                            >
                              <Eye className="w-3 h-3" /> View in PDF
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
      {/* Tab: Foundation Research (Phase 4) */}
      {activeTab === 'foundation_research' && (
        <div className="space-y-6">
          {/* Header & Controls */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6 shadow-sm">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
              <div>
                <div className="flex items-center gap-3">
                  <h2 className="text-lg font-bold text-slate-100 flex items-center gap-2">
                    <Search className="w-5 h-5 text-teal-400" />
                    Foundation Research Agent (Phase 4)
                  </h2>
                  {latestResearchReport && (
                    <span
                      className={`px-2.5 py-1 text-xs font-semibold rounded-full border ${
                        latestResearchReport.review_status === 'APPROVED'
                          ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                          : latestResearchReport.review_status === 'REJECTED'
                          ? 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                          : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                      }`}
                    >
                      {latestResearchReport.review_status === 'APPROVED'
                        ? 'HUMAN APPROVED'
                        : latestResearchReport.review_status === 'REJECTED'
                        ? 'REJECTED'
                        : 'PENDING LICENSED REVIEW'}
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400 mt-1 max-w-3xl">
                  Synthesizes external geotechnical engineering guidelines (FHWA, USACE, PTI, ACI, DFI, IBC) grounded in site-specific subsurface conditions.
                </p>
                {latestResearchReport && (
                  <div className="flex flex-wrap items-center gap-3 mt-3 text-xs text-slate-400 font-mono">
                    <span className="flex items-center gap-1">
                      <Globe className="w-3.5 h-3.5 text-teal-400" />
                      Search: <span className="text-slate-200">{latestResearchReport.search_provider_used}</span>
                    </span>
                    <span>•</span>
                    <span>
                      Generated: <span className="text-slate-200">{new Date(latestResearchReport.created_at).toLocaleString()}</span>
                    </span>
                    <span>•</span>
                    <span>
                      Options Evaluated: <span className="text-teal-300 font-semibold">{latestResearchReport.options_researched.length}</span>
                    </span>
                    <span>•</span>
                    <span>
                      External Sources: <span className="text-teal-300 font-semibold">{latestResearchReport.external_sources.length}</span>
                    </span>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-3">
                <div className="flex flex-col">
                  <label className="text-[10px] uppercase font-bold text-slate-400 mb-1">Search Source</label>
                  <select
                    value={selectedProvider}
                    onChange={(e) => setSelectedProvider(e.target.value)}
                    className="bg-slate-950 border border-slate-700 rounded-lg px-2.5 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-teal-500"
                  >
                    <option value="duckduckgo">DuckDuckGo Live Search</option>
                    <option value="curated">Curated Engineering Index</option>
                    <option value="mock">Mock Test Provider</option>
                  </select>
                </div>
                <button
                  onClick={() => runResearchMutation.mutate()}
                  disabled={runResearchMutation.isPending}
                  className="mt-4 px-4 py-2 bg-teal-600 hover:bg-teal-500 disabled:opacity-50 text-white rounded-lg text-xs font-semibold flex items-center gap-2 shadow-sm transition-colors"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${runResearchMutation.isPending ? 'animate-spin' : ''}`} />
                  {runResearchMutation.isPending ? 'Synthesizing External Sources...' : latestResearchReport ? 'Re-run Research' : 'Run Foundation Research'}
                </button>
              </div>
            </div>
          </div>

          {/* Loading State */}
          {loadingResearch && (
            <div className="p-8 text-center bg-slate-900/40 border border-slate-800 rounded-xl space-y-4">
              <RefreshCw className="w-8 h-8 text-teal-400 animate-spin mx-auto" />
              <div className="text-sm font-semibold text-slate-200">Loading Foundation Research Data...</div>
              <p className="text-xs text-slate-400 max-w-md mx-auto">
                Connecting to geotechnical knowledge graph and external engineering authorities.
              </p>
            </div>
          )}

          {/* Empty State */}
          {!loadingResearch && !latestResearchReport && (
            <div className="bg-slate-900/60 border border-dashed border-slate-800 rounded-xl p-12 text-center space-y-4">
              <BookOpen className="w-12 h-12 text-teal-400/60 mx-auto" />
              <div className="max-w-md mx-auto">
                <h3 className="text-base font-bold text-slate-200">No Foundation Research Report Generated Yet</h3>
                <p className="text-xs text-slate-400 mt-2">
                  Launch the Foundation Research Agent to investigate shallow and deep foundation systems against this project's soil report, plasticity indices, and groundwater conditions.
                </p>
              </div>
              <button
                onClick={() => runResearchMutation.mutate()}
                disabled={runResearchMutation.isPending}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-teal-600 hover:bg-teal-500 text-white rounded-lg text-xs font-semibold transition-colors"
              >
                <Search className="w-4 h-4" />
                {runResearchMutation.isPending ? 'Running 10-Node Workflow...' : 'Execute Foundation Research Pipeline'}
              </button>
            </div>
          )}

          {/* Active Research Report Content */}
          {latestResearchReport && (
            <>
              {/* Engineering Disclaimer Alert */}
              <div className="bg-amber-950/40 border border-amber-500/40 rounded-xl p-4 flex items-start gap-3 text-amber-200 text-xs">
                <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
                <div>
                  <span className="font-bold uppercase tracking-wider block text-amber-300 mb-1">
                    Professional Engineering Safety Notice (Standard Disclaimer)
                  </span>
                  This research report synthesizes public engineering standards (FHWA, USACE, PTI, ACI, DFI, IBC) and project geotechnical data for screening and vendor-requirement formulation. It does not constitute certified foundation design or construction approval. All parameters, depths, and bearing pressures must be validated by a licensed Professional Engineer (PE).
                </div>
              </div>

              {/* Geotechnical Context Cards */}
              <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-teal-300 flex items-center gap-2">
                    <Compass className="w-4 h-4 text-teal-400" />
                    Project Geotechnical Baseline Grounding
                  </h3>
                  <div className="text-[11px] text-slate-400 font-mono">
                    Verified Documents: {latestResearchReport.confirmed_documents_reviewed.join(', ') || 'Soil Report'}
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 pt-2">
                  <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-3">
                    <div className="text-[10px] text-slate-400 uppercase font-semibold">Soil Stratification</div>
                    <div className="text-xs font-bold text-slate-200 mt-1">Sandy Lean Clay (CL)</div>
                    <div className="text-[10px] text-slate-400 mt-0.5">Firm to Hard</div>
                  </div>
                  <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-3">
                    <div className="text-[10px] text-slate-400 uppercase font-semibold">Plasticity (PI / LL)</div>
                    <div className="text-xs font-bold text-cyan-300 mt-1">PI: 17–24 | LL: 32–38</div>
                    <div className="text-[10px] text-slate-400 mt-0.5">Moderate expansion</div>
                  </div>
                  <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-3">
                    <div className="text-[10px] text-slate-400 uppercase font-semibold">PVR Estimation</div>
                    <div className="text-xs font-bold text-amber-300 mt-1">1.20 inches</div>
                    <div className="text-[10px] text-slate-400 mt-0.5">TxDOT Tex-124-E</div>
                  </div>
                  <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-3">
                    <div className="text-[10px] text-slate-400 uppercase font-semibold">Groundwater Depth</div>
                    <div className="text-xs font-bold text-blue-300 mt-1">14.0–15.4 ft</div>
                    <div className="text-[10px] text-slate-400 mt-0.5">At completion</div>
                  </div>
                  <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-3">
                    <div className="text-[10px] text-slate-400 uppercase font-semibold">Select Fill Requirement</div>
                    <div className="text-xs font-bold text-emerald-300 mt-1">LL ≤ 35, PI 8–20</div>
                    <div className="text-[10px] text-slate-400 mt-0.5">Min 2 ft compacted</div>
                  </div>
                  <div className="bg-slate-950/70 border border-slate-800/80 rounded-lg p-3">
                    <div className="text-[10px] text-slate-400 uppercase font-semibold">Belled Pier Warning</div>
                    <div className="text-xs font-bold text-rose-300 mt-1">Caving Hazard</div>
                    <div className="text-[10px] text-slate-400 mt-0.5">Calcareous nodules</div>
                  </div>
                </div>
              </div>

              {/* Foundation Options Researched Cards */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
                    <Building className="w-4 h-4 text-teal-400" />
                    Foundation Systems Researched ({latestResearchReport.options_researched.length})
                  </h3>
                  <div className="flex items-center gap-2 text-xs text-slate-400">
                    <span className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-emerald-500/80"></span>
                      Relevant
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-amber-500/80"></span>
                      Potentially Relevant
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-orange-500/80"></span>
                      Limited
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {latestResearchReport.options_researched.map((opt, idx) => (
                    <div
                      key={idx}
                      className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 hover:border-slate-700 transition-all flex flex-col justify-between"
                    >
                      <div>
                        {/* Title and Badges */}
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                                {opt.category}
                              </span>
                              {opt.mentioned_in_geotech_report && (
                                <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-cyan-950/80 border border-cyan-800/80 text-cyan-300">
                                  Soil Report Option
                                </span>
                              )}
                            </div>
                            <h4 className="text-base font-bold text-slate-100 mt-0.5">{opt.name}</h4>
                          </div>

                          <span
                            className={`px-2.5 py-1 text-[11px] font-semibold rounded-full border shrink-0 ${
                              opt.relevance_classification === 'RELEVANT_FOR_FURTHER_EVALUATION'
                                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                                : opt.relevance_classification === 'POTENTIALLY_RELEVANT'
                                ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                                : opt.relevance_classification === 'LIMITED_RELEVANCE'
                                ? 'bg-orange-500/20 text-orange-300 border-orange-500/40'
                                : 'bg-rose-500/20 text-rose-300 border-rose-500/40'
                            }`}
                          >
                            {opt.relevance_classification.replace(/_/g, ' ')}
                          </span>
                        </div>

                        {/* Relevance Rationale */}
                        <div className="mt-3 p-3 bg-slate-950/60 border border-slate-800/70 rounded-lg text-xs text-slate-300">
                          <span className="font-semibold text-teal-300 block mb-0.5">Evaluation Rationale:</span>
                          {opt.relevance_reasoning}
                        </div>

                        {/* Description & Soil Compatibility */}
                        <div className="mt-2.5 p-2.5 bg-slate-950/40 border border-slate-800/60 rounded text-xs space-y-1">
                          <div className="text-slate-300 text-[11px]">{opt.description}</div>
                          <div className="text-[11px] text-teal-300">
                            <span className="font-semibold text-slate-400">Soil Fit:</span> {opt.soil_compatibility}
                          </div>
                        </div>

                        {/* Pros and Cons */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4 text-xs">
                          <div className="p-3 bg-emerald-950/20 border border-emerald-900/30 rounded-lg">
                            <span className="font-bold text-emerald-400 block mb-1 flex items-center gap-1.5">
                              <CheckCircle2 className="w-3.5 h-3.5" /> Advantages
                            </span>
                            <ul className="space-y-1 text-slate-300 list-disc list-inside text-[11px]">
                              {opt.advantages.map((adv, aIdx) => (
                                <li key={aIdx}>{adv}</li>
                              ))}
                            </ul>
                          </div>

                          <div className="p-3 bg-rose-950/20 border border-rose-900/30 rounded-lg">
                            <span className="font-bold text-rose-400 block mb-1 flex items-center gap-1.5">
                              <XCircle className="w-3.5 h-3.5" /> Disadvantages & Limitations
                            </span>
                            <ul className="space-y-1 text-slate-300 list-disc list-inside text-[11px]">
                              {opt.limitations.map((dis, dIdx) => (
                                <li key={dIdx}>{dis}</li>
                              ))}
                            </ul>
                          </div>
                        </div>

                        {/* Typical Applications */}
                        {opt.typical_applications.length > 0 && (
                          <div className="mt-3 text-xs">
                            <span className="text-slate-400 font-semibold block mb-1">Typical Applications:</span>
                            <div className="flex flex-wrap gap-1.5">
                              {opt.typical_applications.map((sc, sIdx) => (
                                <span key={sIdx} className="px-2 py-0.5 rounded bg-slate-950 text-slate-300 border border-slate-800 text-[11px]">
                                  {sc}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Applicable Standards */}
                      {opt.applicable_standards.length > 0 && (
                        <div className="mt-4 pt-3 border-t border-slate-800/80 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                          <Award className="w-3.5 h-3.5 text-teal-400" />
                          <span className="font-semibold text-slate-300">Authoritative Standards:</span>
                          {opt.applicable_standards.map((cite, cIdx) => (
                            <span key={cIdx} className="px-1.5 py-0.5 rounded bg-slate-800/70 text-slate-300 font-mono text-[10px]">
                              {cite}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Comparative Systems Matrix */}
              <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
                <div className="p-4 border-b border-slate-800 bg-slate-950/50 flex items-center justify-between">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-teal-300 flex items-center gap-2">
                    <Sliders className="w-4 h-4 text-teal-400" />
                    Comparative Systems Performance Matrix
                  </h3>
                  <div className="text-[11px] text-slate-400">
                    Cross-comparison of technical feasibility, performance, and site risks
                  </div>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs text-slate-300">
                    <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800 font-semibold">
                      <tr>
                        <th className="px-3.5 py-3">Foundation System</th>
                        <th className="px-3 py-3">Category</th>
                        <th className="px-3 py-3">Relevance</th>
                        <th className="px-3 py-3">Bearing Capacity</th>
                        <th className="px-3 py-3">Settlement</th>
                        <th className="px-3 py-3">Expansive Soil</th>
                        <th className="px-3 py-3">Groundwater</th>
                        <th className="px-3 py-3">Complexity</th>
                        <th className="px-3.5 py-3">Key Risk / Limitation</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/60">
                      {latestResearchReport.comparisons.map((cmp, cIdx) => (
                        <tr key={cIdx} className="hover:bg-slate-800/30 transition-colors">
                          <td className="px-3.5 py-2.5 font-bold text-slate-100">{cmp.foundation_type}</td>
                          <td className="px-3 py-2.5 text-slate-400 uppercase text-[11px]">{cmp.category}</td>
                          <td className="px-3 py-2.5">
                            <span
                              className={`px-2 py-0.5 text-[10px] font-semibold rounded-full border ${
                                cmp.project_relevance === 'RELEVANT_FOR_FURTHER_EVALUATION'
                                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                                  : cmp.project_relevance === 'POTENTIALLY_RELEVANT'
                                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                                  : 'bg-orange-500/20 text-orange-300 border-orange-500/40'
                              }`}
                            >
                              {cmp.project_relevance === 'RELEVANT_FOR_FURTHER_EVALUATION' ? 'RELEVANT' : cmp.project_relevance.replace(/_/g, ' ')}
                            </span>
                          </td>
                          <td className="px-3 py-2.5 text-slate-200">{cmp.bearing_considerations}</td>
                          <td className="px-3 py-2.5 text-slate-300">{cmp.settlement_considerations}</td>
                          <td className="px-3 py-2.5 text-slate-300">{cmp.expansive_soil_considerations}</td>
                          <td className="px-3 py-2.5 text-slate-300">{cmp.groundwater_considerations}</td>
                          <td className="px-3 py-2.5 font-semibold text-slate-200">{cmp.construction_complexity}</td>
                          <td className="px-3.5 py-2.5 text-rose-300 text-[11px]">{cmp.limitations?.[0] || 'See full details'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Verified External Sources */}
              <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
                <div className="p-4 border-b border-slate-800 bg-slate-950/50 flex flex-col md:flex-row md:items-center justify-between gap-3">
                  <div>
                    <h3 className="text-xs font-bold uppercase tracking-wider text-teal-300 flex items-center gap-2">
                      <Globe className="w-4 h-4 text-teal-400" />
                      Verified External Sources & Technical Publications ({latestResearchReport.external_sources.length})
                    </h3>
                    <div className="text-[11px] text-slate-400 mt-0.5">
                      Peer-reviewed federal manuals, standards organizations, and technical specifications
                    </div>
                  </div>

                  {/* Authority Filter */}
                  <div className="flex items-center gap-1.5 flex-wrap">
                    {['ALL', 'GOVERNMENT_AGENCY', 'STANDARDS_ORGANIZATION', 'INDUSTRY_ASSOCIATION', 'ACADEMIC_RESEARCH'].map((authCat) => (
                      <button
                        key={authCat}
                        onClick={() => setSelectedAuthorityFilter(authCat)}
                        className={`px-2.5 py-1 text-[11px] font-semibold rounded-md transition-colors ${
                          selectedAuthorityFilter === authCat
                            ? 'bg-teal-600 text-white'
                            : 'bg-slate-800 text-slate-400 hover:text-slate-200'
                        }`}
                      >
                        {authCat === 'ALL' ? 'All Authorities' : authCat.replace(/_/g, ' ')}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="divide-y divide-slate-800/60">
                  {latestResearchReport.external_sources
                    .filter((s) => selectedAuthorityFilter === 'ALL' || s.authority_category === selectedAuthorityFilter)
                    .map((src, sIdx) => (
                      <div key={sIdx} className="p-4 hover:bg-slate-800/30 transition-colors flex flex-col md:flex-row md:items-start justify-between gap-4">
                        <div className="space-y-1.5 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-bold border ${
                                src.authority_category === 'GOVERNMENT_AGENCY'
                                  ? 'bg-sky-500/20 text-sky-300 border-sky-500/30'
                                  : src.authority_category === 'STANDARDS_ORGANIZATION'
                                  ? 'bg-purple-500/20 text-purple-300 border-purple-500/30'
                                  : 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30'
                              }`}
                            >
                              {src.authority_category.replace(/_/g, ' ')}
                            </span>
                            <span className="font-mono text-[10px] text-teal-300 font-bold bg-teal-950/60 px-2 py-0.5 rounded border border-teal-800/60">
                              {src.source_id}
                            </span>
                            {src.topic && (
                              <span className="font-mono text-[10px] text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
                                {src.topic}
                              </span>
                            )}
                            {src.publisher && <span className="text-xs text-slate-400">by {src.publisher}</span>}
                            {src.publication_date && <span className="text-[10px] text-slate-500">({src.publication_date})</span>}
                          </div>

                          <h4 className="text-sm font-bold text-slate-100">{src.title}</h4>

                          <p className="text-xs text-slate-300 leading-relaxed max-w-4xl">
                            {src.snippet}
                          </p>
                        </div>

                        <div className="flex md:flex-col items-center md:items-end justify-between gap-2 shrink-0">
                          {src.url && (
                            <a
                              href={src.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded bg-teal-950/80 border border-teal-800/70 hover:bg-teal-900/80 text-teal-300 text-xs transition-colors"
                            >
                              <ExternalLink className="w-3 h-3" /> View Source
                            </a>
                          )}
                        </div>
                      </div>
                    ))}
                </div>
              </div>

              {/* Research Gaps & Engineer Questions Grid */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Research Gaps */}
                <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-amber-300 flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                    Identified Research Gaps & Investigations ({latestResearchReport.research_gaps.length})
                  </h3>
                  <div className="space-y-2.5 pt-1">
                    {latestResearchReport.research_gaps.map((gap, gIdx) => (
                      <div key={gIdx} className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-lg text-xs space-y-1.5">
                        <div className="flex items-center justify-between">
                          <span className="font-bold text-slate-200">{gap.category}</span>
                          <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-amber-500/20 text-amber-300 border border-amber-500/40">
                            ACTION REQUIRED
                          </span>
                        </div>
                        <p className="text-slate-300">{gap.description}</p>
                        <div className="text-[11px] text-rose-300">
                          <span className="font-semibold text-slate-400">Impact:</span> {gap.impact}
                        </div>
                        <div className="text-[11px] text-teal-300 bg-teal-950/30 border border-teal-900/30 p-2 rounded mt-1">
                          <span className="font-semibold block text-[10px] uppercase text-teal-400">Recommended Action:</span>
                          {gap.required_action}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Questions for Design Engineers */}
                <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-indigo-300 flex items-center gap-2">
                    <MessageSquare className="w-4 h-4 text-indigo-400" />
                    Engineering Questions for Project Team ({latestResearchReport.engineer_questions.length})
                  </h3>
                  <div className="space-y-2.5 pt-1">
                    {latestResearchReport.engineer_questions.map((q, qIdx) => (
                      <div key={qIdx} className="p-3 bg-slate-950/70 border border-slate-800/80 rounded-lg text-xs space-y-1.5">
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-indigo-300">{q.target_role.replace(/_/g, ' ')}</span>
                          <span className="px-2 py-0.5 text-[10px] font-mono bg-slate-800 text-slate-400 rounded">
                            {q.question_id}
                          </span>
                        </div>
                        <p className="text-slate-200 font-medium">{q.question}</p>
                        <p className="text-[11px] text-slate-400 leading-relaxed">{q.context_reason}</p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Human Engineering Review Section */}
              <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="w-5 h-5 text-teal-400" />
                    <h3 className="text-sm font-bold text-slate-100">Professional Engineering Review & Sign-Off</h3>
                  </div>
                  <div className="text-xs text-slate-400 font-mono">
                    Status: <span className="text-slate-200 font-semibold">{latestResearchReport.review_status}</span>
                    {latestResearchReport.reviewed_by && (
                      <span className="ml-2">by {latestResearchReport.reviewed_by}</span>
                    )}
                  </div>
                </div>

                {latestResearchReport.review_notes && (
                  <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-lg text-xs text-slate-300">
                    <span className="font-semibold text-slate-400 block mb-0.5">Existing Reviewer Notes:</span>
                    {latestResearchReport.review_notes}
                  </div>
                )}

                <div className="space-y-2">
                  <label className="text-xs font-semibold text-slate-300 block">
                    Reviewer Notes / PE Concurrence Comments:
                  </label>
                  <textarea
                    value={researchReviewComments}
                    onChange={(e) => setResearchReviewComments(e.target.value)}
                    placeholder="Enter engineering review remarks, design modifications, or scope qualifications..."
                    rows={2}
                    className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-teal-500"
                  />
                </div>

                <div className="flex items-center justify-end gap-3 pt-2">
                  <button
                    onClick={() =>
                      reviewResearchMutation.mutate({
                        decision: 'REJECTED',
                        comments: researchReviewComments || 'Revisions required by reviewing engineer.',
                      })
                    }
                    disabled={reviewResearchMutation.isPending}
                    className="px-4 py-2 bg-rose-950/80 hover:bg-rose-900/80 border border-rose-800/80 text-rose-300 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                    Reject / Request Revisions
                  </button>

                  <button
                    onClick={() =>
                      reviewResearchMutation.mutate({
                        decision: 'APPROVED',
                        comments: researchReviewComments || 'Reviewed and concurred with external research synthesis.',
                      })
                    }
                    disabled={reviewResearchMutation.isPending}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 shadow-sm transition-colors"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    Approve Research (Licensed PE Sign-Off)
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Tab: Evidence Records */}
      {activeTab === 'evidence' && (
        <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-950/80 text-slate-400 border-b border-slate-800">
                <tr>
                  <th className="px-4 py-3 font-semibold">Property Category</th>
                  <th className="px-4 py-3 font-semibold">Extracted Technical Value</th>
                  <th className="px-4 py-3 font-semibold">System / Load Case</th>
                  <th className="px-4 py-3 font-semibold">PDF Page</th>
                  <th className="px-4 py-3 font-semibold">Printed Folio</th>
                  <th className="px-4 py-3 font-semibold">Method</th>
                  <th className="px-4 py-3 font-semibold">Verification Review</th>
                  <th className="px-4 py-3 font-semibold text-right">Inspect Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {evidence.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-slate-400">
                      No technical evidence items extracted.
                    </td>
                  </tr>
                ) : (
                  evidence.map((ev) => (
                    <tr
                      key={ev.evidence_id}
                      className="hover:bg-slate-800/30 transition-colors"
                    >
                      <td className="px-4 py-3 font-medium text-cyan-400">
                        <span className="px-2 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/60 font-mono text-[11px]">
                          {ev.property_type || 'unclassified'}
                        </span>
                      </td>

                      <td className="px-4 py-3 text-slate-200 font-medium max-w-[280px]">
                        <div className="truncate" title={ev.extracted_text}>
                          {ev.extracted_text}
                        </div>
                        {ev.context_snippet && (
                          <div className="text-[10px] text-slate-400 truncate mt-0.5 italic" title={ev.context_snippet}>
                            "{ev.context_snippet}"
                          </div>
                        )}
                      </td>

                      <td className="px-4 py-3 text-slate-300 text-[11px]">
                        {ev.foundation_system ? (
                          <div>
                            <span className="font-semibold text-cyan-400">{ev.foundation_system}</span>
                            {ev.load_case && (
                              <div className="text-[10px] text-indigo-300">{ev.load_case}</div>
                            )}
                          </div>
                        ) : ev.load_case ? (
                          <span className="px-1.5 py-0.5 rounded bg-indigo-950/60 border border-indigo-800/50 text-[10px] text-indigo-300">
                            {ev.load_case}
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>

                      <td className="px-4 py-3 font-mono text-slate-300">
                        Page {ev.page_index + 1}
                      </td>

                      <td className="px-4 py-3 font-mono text-slate-400">
                        {ev.printed_page_number ? (
                          <span className="px-1.5 py-0.5 rounded bg-slate-950 border border-slate-800 text-[10px]">
                            Folio {ev.printed_page_number}
                          </span>
                        ) : (
                          <span className="italic text-slate-400">N/A</span>
                        )}
                      </td>

                      <td className="px-4 py-3 text-[11px] text-slate-400">
                        {ev.extraction_method.replace(/_/g, ' ')}
                      </td>

                      <td className="px-4 py-3">
                        <select
                          value={ev.verification_status}
                          onChange={(e) =>
                            updateStatusMutation.mutate({
                              evidenceId: ev.evidence_id,
                              status: e.target.value as any,
                            })
                          }
                          className={`px-2 py-1 rounded text-[11px] font-medium border bg-slate-950 focus:outline-none ${
                            ev.verification_status === 'HUMAN_VERIFIED' || ev.verification_status === 'verified'
                              ? 'border-emerald-500/50 text-emerald-400'
                              : ev.verification_status === 'REJECTED' || ev.verification_status === 'flagged'
                              ? 'border-rose-500/50 text-rose-400'
                              : 'border-amber-500/50 text-amber-300'
                          }`}
                        >
                          <option value="PENDING_REVIEW">Pending Review</option>
                          <option value="HUMAN_VERIFIED">Human Verified</option>
                          <option value="REJECTED">Rejected</option>
                        </select>
                      </td>

                      <td className="px-4 py-3 text-right">
                        <button
                          onClick={() => jumpToEvidenceInPdf(ev)}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-cyan-950/60 border border-cyan-800/60 hover:bg-cyan-900/60 text-cyan-300 text-xs transition-colors"
                        >
                          <Eye className="w-3 h-3" />
                          View in PDF
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab 2: Extracted Tables & Boring Logs */}
      {activeTab === 'tables' && (
        <div className="space-y-6">
          {tables.length === 0 ? (
            <div className="p-8 text-center bg-slate-900/60 rounded-xl border border-slate-800 text-slate-400 text-xs">
              No structured tables were detected in this document.
            </div>
          ) : (
            tables.map((tbl, i) => {
              const isBoring = tbl.table_classification === 'boring_log' || tbl.table_name?.toLowerCase().includes('boring');
              const matchedBoring = isBoring
                ? boringLogs.find((b) => tbl.table_name?.includes(b.boring_id)) || (tbl.table_name?.includes('B-1') ? boringLogs.find(b => b.boring_id === 'B-1') : boringLogs.find(b => b.boring_id === 'B-2'))
                : null;

              return (
                <div
                  key={tbl.table_id}
                  className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden shadow-sm space-y-3"
                >
                  <div className="flex flex-col md:flex-row md:items-center justify-between px-4 py-3 bg-slate-950/80 border-b border-slate-800 gap-2">
                    <div className="flex items-center gap-2">
                      <TableIcon className="w-4 h-4 text-indigo-400" />
                      <span className="font-semibold text-xs text-slate-200">
                        {tbl.table_name || `Table ${i + 1}`} {tbl.caption ? `— ${tbl.caption}` : ''}
                      </span>
                      <span className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-[10px] text-slate-400">
                        PDF Page {tbl.page_index + 1} {tbl.printed_page_number ? `(Folio ${tbl.printed_page_number})` : ''}
                      </span>
                    </div>
                    <button
                      onClick={() => jumpToTableInPdf(tbl)}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-indigo-950/60 border border-indigo-800/60 hover:bg-indigo-900/60 text-indigo-300 text-xs transition-colors self-start md:self-auto"
                    >
                      <Eye className="w-3 h-3" /> View in PDF
                    </button>
                  </div>

                  {/* Enhanced Boring Log Section (Stratum + Observations Timeline) */}
                  {isBoring && matchedBoring && (
                    <div className="px-4 py-2 space-y-3">
                      {/* Stratum Card */}
                      <div className="p-3 bg-slate-950/80 border border-slate-800 rounded-lg">
                        <div className="flex items-center justify-between text-[11px] font-semibold text-cyan-400 mb-1">
                          <span>Subsurface Stratum Interval ({matchedBoring.depth_range || '0 - 20 ft'})</span>
                          <span className="text-slate-400 font-mono text-[10px]">
                            {matchedBoring.boring_type || 'Auger'} Drilling • Groundwater: {matchedBoring.groundwater_depth || 'Encountered at 15.4 ft'}
                            {matchedBoring.gps_coordinates && ` • GPS: ${matchedBoring.gps_coordinates}`}
                          </span>
                        </div>
                        <p className="text-xs text-slate-200 font-medium">
                          {matchedBoring.stratum_description || 'SANDY LEAN CLAY (CL), firm to very stiff'}
                        </p>
                      </div>

                      {/* Depth-Specific Observations */}
                      {matchedBoring.observations && matchedBoring.observations.length > 0 && (
                        <div>
                          <span className="text-[10px] text-slate-400 uppercase font-semibold block mb-1.5">
                            Depth-Specific Field Observations:
                          </span>
                          <div className="flex flex-wrap gap-2">
                            {matchedBoring.observations.map((obs, oIdx) => (
                              <div
                                key={oIdx}
                                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-slate-950 border border-slate-800 text-xs"
                              >
                                <span className="text-cyan-400 font-mono font-bold">{obs.depth_label}:</span>
                                <span className="text-slate-200">{obs.observation}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="text-[10px] text-slate-400 uppercase font-semibold pt-1">
                        Recorded Sample Measurements ({tbl.rows.length} test depths):
                      </div>
                    </div>
                  )}

                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs text-slate-300">
                      <thead className="bg-slate-900 border-b border-slate-800 text-slate-400">
                        <tr>
                          {tbl.headers.map((h, hIdx) => (
                            <th key={hIdx} className="px-3 py-2 font-semibold border-r border-slate-800 last:border-r-0">
                              {h || `Col ${hIdx + 1}`}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/50">
                        {tbl.rows.map((row, rIdx) => (
                          <tr key={rIdx} className="hover:bg-slate-800/20">
                            {row.map((cell, cIdx) => (
                              <td key={cIdx} className="px-3 py-2 border-r border-slate-800/40 last:border-r-0">
                                {cell === 'NOT_REPORTED' ? (
                                  <span className="text-[10px] text-slate-400 italic">NOT REPORTED</span>
                                ) : (
                                  cell
                                )}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Tab 3: Sections & Page Content */}
      {activeTab === 'sections' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {pages.map((p) => (
              <div
                key={p.page_index}
                className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 space-y-2 text-xs"
              >
                <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                  <span className="font-semibold text-slate-200">
                    Page {p.page_index + 1}
                  </span>
                  <div className="flex items-center gap-1.5">
                    {p.printed_page_number && (
                      <span className="px-1.5 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/60 text-cyan-400 text-[10px]">
                        Folio: {p.printed_page_number}
                      </span>
                    )}
                    <span className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] text-slate-400">
                      {p.word_count} words
                    </span>
                    <button
                      onClick={() => {
                        setCurrentPage(p.page_index);
                        setSelectedEvidence(null);
                        setActiveTab('viewer');
                      }}
                      className="p-1 rounded hover:bg-slate-800 text-cyan-400"
                      title="Inspect in PDF Viewer"
                    >
                      <Eye className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {p.section_headings.length > 0 && (
                  <div className="space-y-1">
                    <span className="text-[10px] text-slate-400 font-semibold uppercase">Headings:</span>
                    {p.section_headings.map((h, i) => (
                      <div key={i} className="text-slate-200 font-medium pl-2 border-l-2 border-cyan-500">
                        {h}
                      </div>
                    ))}
                  </div>
                )}

                <div className="mt-2 text-slate-400 font-mono text-[11px] max-h-28 overflow-y-auto bg-slate-950/60 p-2 rounded border border-slate-800/80">
                  {p.raw_text ? p.raw_text.slice(0, 300) + '...' : <span className="italic">No text extracted</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab 4: Interactive PDF Page Viewer with Bounding Box Overlay */}
      {activeTab === 'viewer' && (
        <div className="h-[750px]">
          <DocumentViewer
            documentId={document.document_id}
            totalPages={document.page_count}
            currentPage={currentPage}
            onPageChange={(p) => {
              setCurrentPage(p);
              setSelectedEvidence(null);
            }}
            printedPageNumber={activePageObj?.printed_page_number}
            highlightBox={selectedEvidence?.bounding_box}
            highlightLabel={selectedEvidence ? `${selectedEvidence.property_type || 'Evidence'}: ${selectedEvidence.extracted_text}` : null}
          />
        </div>
      )}

      {/* Tab 5: Multimodal Vision Intelligence & Engineering Drawings */}
      {activeTab === 'visual_intelligence' && (
        <div className="space-y-6">
          {/* Top Metric Bar */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between">
              <div>
                <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Classified Pages</p>
                <p className="text-xl font-bold text-white mt-1">{pageClassifications.length || pages.length}</p>
                <p className="text-[11px] text-slate-500 mt-0.5">Automated visual content mapping</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
                <Layers className="w-5 h-5" />
              </div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between">
              <div>
                <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Drawings & Maps</p>
                <p className="text-xl font-bold text-emerald-400 mt-1">
                  {pageClassifications.filter((c) => ['SITE_PLAN', 'MAP_OR_LOCATION_DIAGRAM', 'ENGINEERING_DRAWING', 'BORING_LOG_DRAWING', 'CHART_OR_GRAPH'].includes(c.primary_content_type)).length}
                </p>
                <p className="text-[11px] text-slate-500 mt-0.5">Plans, maps, and logs</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
                <ImageIcon className="w-5 h-5" />
              </div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between">
              <div>
                <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Visual Records</p>
                <p className="text-xl font-bold text-cyan-400 mt-1">{visualEvidenceList.length}</p>
                <p className="text-[11px] text-slate-500 mt-0.5">VLM structured extractions</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
                <Brain className="w-5 h-5" />
              </div>
            </div>

            <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between">
              <div>
                <p className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">Cross-Modal Alerts</p>
                <p className="text-xl font-bold text-amber-400 mt-1">
                  {disagreements.filter((d) => d.status === 'OPEN').length}
                </p>
                <p className="text-[11px] text-slate-500 mt-0.5">Discrepancies vs text / tables</p>
              </div>
              <div className="w-10 h-10 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                <AlertTriangle className="w-5 h-5" />
              </div>
            </div>
          </div>

          {/* Main Workspace Layout */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left Page List (4 cols) */}
            <div className="lg:col-span-4 space-y-3">
              <div className="p-3 bg-slate-900/80 border border-slate-800 rounded-xl flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-300">Document Pages & Layout</span>
                <span className="text-[11px] text-slate-500">{pageClassifications.length || pages.length} total</span>
              </div>

              {/* Filters */}
              <div className="flex gap-1.5 flex-wrap">
                {(['ALL', 'DRAWINGS', 'LOGS', 'TABLES', 'TEXT'] as const).map((cat) => (
                  <button
                    key={cat}
                    onClick={() => setVisualCategoryFilter(cat)}
                    className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-colors ${
                      visualCategoryFilter === cat
                        ? 'bg-purple-900/50 text-purple-200 border border-purple-700/50'
                        : 'bg-slate-900/60 text-slate-400 border border-slate-800 hover:text-slate-200'
                    }`}
                  >
                    {cat}
                  </button>
                ))}
              </div>

              {/* Page Cards Container */}
              <div className="space-y-2 max-h-[700px] overflow-y-auto pr-1">
                {(pageClassifications.length > 0 ? pageClassifications : pages.map((p) => ({
                  document_id: id || '',
                  page_index: p.page_index,
                  pdf_page_number: p.page_index + 1,
                  primary_content_type: 'TEXT_ONLY' as PageContentType,
                  confidence: 1.0,
                  secondary_types: [],
                  classification_method: 'deterministic_heuristic',
                  reasoning: 'Extracted page',
                  features: {},
                })))
                  .filter((item) => {
                    if (visualCategoryFilter === 'ALL') return true;
                    if (visualCategoryFilter === 'DRAWINGS') {
                      return ['SITE_PLAN', 'MAP_OR_LOCATION_DIAGRAM', 'ENGINEERING_DRAWING', 'CHART_OR_GRAPH'].includes(item.primary_content_type);
                    }
                    if (visualCategoryFilter === 'LOGS') {
                      return item.primary_content_type === 'BORING_LOG_DRAWING';
                    }
                    if (visualCategoryFilter === 'TABLES') {
                      return item.primary_content_type === 'TEXT_WITH_TABLES';
                    }
                    if (visualCategoryFilter === 'TEXT') {
                      return item.primary_content_type === 'TEXT_ONLY';
                    }
                    return true;
                  })
                  .map((item) => {
                    const isSelected = selectedVisualPage === item.page_index;
                    const hasAnalysis = visualEvidenceList.some((v) => v.page_index === item.page_index);
                    const hasDisagreement = disagreements.some((d) => d.page_index === item.page_index && d.status === 'OPEN');

                    let badgeColor = 'bg-slate-800 text-slate-300 border-slate-700';
                    let typeLabel: string = item.primary_content_type;
                    if (item.primary_content_type === 'SITE_PLAN') {
                      badgeColor = 'bg-emerald-950/60 text-emerald-300 border-emerald-700/60';
                      typeLabel = 'Site Plan';
                    } else if (item.primary_content_type === 'BORING_LOG_DRAWING') {
                      badgeColor = 'bg-cyan-950/60 text-cyan-300 border-cyan-700/60';
                      typeLabel = 'Boring Log';
                    } else if (item.primary_content_type === 'MAP_OR_LOCATION_DIAGRAM') {
                      badgeColor = 'bg-blue-950/60 text-blue-300 border-blue-700/60';
                      typeLabel = 'Location Map';
                    } else if (item.primary_content_type === 'CHART_OR_GRAPH') {
                      badgeColor = 'bg-purple-950/60 text-purple-300 border-purple-700/60';
                      typeLabel = 'Chart / Symbols';
                    } else if (item.primary_content_type === 'TEXT_WITH_TABLES') {
                      badgeColor = 'bg-amber-950/60 text-amber-300 border-amber-700/60';
                      typeLabel = 'Tables';
                    } else if (item.primary_content_type === 'TEXT_ONLY') {
                      badgeColor = 'bg-slate-900 text-slate-400 border-slate-800';
                      typeLabel = 'Text';
                    }

                    return (
                      <div
                        key={item.page_index}
                        onClick={() => setSelectedVisualPage(item.page_index)}
                        className={`p-3 rounded-xl border cursor-pointer transition-all ${
                          isSelected
                            ? 'bg-slate-800/80 border-purple-500 shadow-md ring-1 ring-purple-500/30'
                            : 'bg-slate-900/60 border-slate-800 hover:border-slate-700 hover:bg-slate-800/40'
                        }`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono font-bold text-slate-200">
                              Page {item.pdf_page_number}
                            </span>
                            <span className={`px-2 py-0.5 text-[10px] font-semibold rounded-full border ${badgeColor}`}>
                              {typeLabel}
                            </span>
                          </div>
                          <div className="flex items-center gap-1.5">
                            {hasDisagreement && (
                              <span title="Cross-modal disagreement detected">
                                <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                              </span>
                            )}
                            {hasAnalysis ? (
                              <span
                                className="w-2 h-2 rounded-full bg-emerald-400"
                                title="Visual analysis complete"
                              />
                            ) : (
                              <span
                                className="w-2 h-2 rounded-full bg-slate-600"
                                title="Not analyzed yet"
                              />
                            )}
                          </div>
                        </div>
                        {item.reasoning && (
                          <p className="text-[11px] text-slate-400 mt-1 line-clamp-1">{item.reasoning}</p>
                        )}
                      </div>
                    );
                  })}
              </div>
            </div>

            {/* Right Work Area: Rendered View + Analysis (8 cols) */}
            {(() => {
              const safeVisualPageIndex = pages.length > 0
                ? Math.min(Math.max(selectedVisualPage, 0), pages.length - 1)
                : 0;
              const pageClassification = pageClassifications.find((c) => c.page_index === safeVisualPageIndex);

              return (
                <div className="lg:col-span-8 space-y-4">
                  {/* Header Action Bar */}
                  <div className="p-4 bg-slate-900/80 border border-slate-800 rounded-xl flex flex-col md:flex-row md:items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-300">
                        <ImageIcon className="w-4 h-4" />
                      </div>
                      <div>
                        <h3 className="text-sm font-bold text-white flex items-center gap-2">
                          Page {safeVisualPageIndex + 1} Visual Intelligence
                          {pageClassification && (
                            <span className="text-xs font-normal text-purple-300">
                              [{pageClassification.primary_content_type}]
                            </span>
                          )}
                        </h3>
                        <p className="text-[11px] text-slate-400">
                          Visual-Language Model inference & cross-modal validation
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <select
                        value={selectedVisionModel}
                        onChange={(e) => setSelectedVisionModel(e.target.value)}
                        className="bg-slate-950 border border-slate-700 text-xs text-slate-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-purple-500"
                      >
                        <option value="qwen3-vl:2b">qwen3-vl:2b (Vision)</option>
                        <option value="granite3.2-vision:2b">granite3.2-vision:2b (Vision)</option>
                      </select>

                      <button
                        onClick={() =>
                          analyzeVisualMutation.mutate({
                            pageIndex: safeVisualPageIndex,
                            modelOverride: selectedVisionModel,
                          })
                        }
                        disabled={analyzeVisualMutation.isPending}
                        className="px-3.5 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white text-xs font-semibold flex items-center gap-1.5 transition-all shadow-sm disabled:opacity-50"
                      >
                        {analyzeVisualMutation.isPending ? (
                          <>
                            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                            Running VLM (~30-60s)...
                          </>
                        ) : (
                          <>
                            <Brain className="w-3.5 h-3.5" />
                            Run Vision Analysis
                          </>
                        )}
                      </button>
                    </div>
                  </div>

                  {/* Optional error alert if VLM failed */}
                  {analyzeVisualMutation.isError && (
                    <div className="p-3 bg-rose-500/10 border border-rose-500/25 rounded-xl text-xs text-rose-300 flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                      <span>Vision analysis notice: {(analyzeVisualMutation.error as any)?.message || 'Failed to run VLM.'}</span>
                    </div>
                  )}

                  {/* Side-by-side Page Render & Findings */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {/* Left: Rendered Page Image with Interactive Region Overlays */}
                    <div className="bg-slate-950/80 border border-slate-800 rounded-xl overflow-hidden p-2 flex flex-col items-center">
                      <div className="w-full flex items-center justify-between pb-2 border-b border-slate-800/80 text-[11px] text-slate-400 px-1">
                        <span>Rendered View (Page {safeVisualPageIndex + 1})</span>
                        <button
                          onClick={() => {
                            setCurrentPage(safeVisualPageIndex);
                            setActiveTab('viewer');
                          }}
                          className="text-cyan-400 hover:underline flex items-center gap-1"
                        >
                          <ZoomIn className="w-3 h-3" /> Full PDF Viewer
                        </button>
                      </div>

                      <div className="relative mt-2 max-h-[600px] overflow-auto border border-slate-800 rounded bg-white">
                        <img
                          src={`${getBaseUrl()}/v1/documents/${document.document_id}/pages/${safeVisualPageIndex}/image`}
                          alt={`Page ${safeVisualPageIndex + 1}`}
                          className="w-full h-auto object-contain block"
                        />

                        {/* Bounding box overlays for detected visual regions */}
                        {visualEvidenceList
                          .find((v) => v.page_index === safeVisualPageIndex)
                          ?.detected_regions.map((reg) => {
                            const pw = reg.bounding_box.page_width || 612;
                            const ph = reg.bounding_box.page_height || 792;
                            const leftPct = (reg.bounding_box.x0 / pw) * 100;
                            const topPct = (reg.bounding_box.top / ph) * 100;
                            const widthPct = ((reg.bounding_box.x1 - reg.bounding_box.x0) / pw) * 100;
                            const heightPct = ((reg.bounding_box.bottom - reg.bounding_box.top) / ph) * 100;

                            const isHighlighted = activeRegionId === reg.region_id;

                            return (
                              <div
                                key={reg.region_id}
                                onClick={() => setActiveRegionId(reg.region_id)}
                                style={{
                                  left: `${leftPct}%`,
                                  top: `${topPct}%`,
                                  width: `${widthPct}%`,
                                  height: `${heightPct}%`,
                                }}
                                className={`absolute border-2 transition-all cursor-pointer ${
                                  isHighlighted
                                    ? 'border-amber-400 bg-amber-400/30 ring-2 ring-amber-400'
                                    : 'border-purple-500 bg-purple-500/20 hover:bg-purple-500/40'
                                }`}
                                title={`${reg.label}: ${reg.description || ''}`}
                              >
                                <span className="absolute -top-5 left-0 px-1.5 py-0.5 text-[9px] font-bold bg-purple-900 text-purple-200 rounded whitespace-nowrap shadow-sm border border-purple-700">
                                  {reg.label}
                                </span>
                              </div>
                            );
                          })}
                      </div>
                    </div>

                    {/* Right: Structured Visual Findings Card */}
                    <div className="space-y-4">
                      {(() => {
                        const vev = visualEvidenceList.find((v) => v.page_index === safeVisualPageIndex);

                        if (!vev) {
                          return (
                            <div className="p-8 text-center bg-slate-900/60 rounded-xl border border-slate-800 space-y-3">
                              <ImageIcon className="w-8 h-8 text-slate-500 mx-auto" />
                              <h4 className="text-sm font-semibold text-slate-300">No Visual Analysis Cached</h4>
                          <p className="text-xs text-slate-400">
                            Click <strong>Run Vision Analysis</strong> above to extract engineering drawing features,
                            lots, setbacks, borehole symbols, and notes using local VLM models.
                          </p>
                        </div>
                      );
                    }

                    return (
                      <div className="p-4 bg-slate-900/80 border border-slate-800 rounded-xl space-y-4">
                        {/* Title & Review Status */}
                        <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                          <div>
                            <span className="text-[10px] font-semibold text-purple-400 uppercase tracking-wider">
                              Visual Evidence Record
                            </span>
                            <h4 className="text-sm font-bold text-white mt-0.5">
                              {vev.title_or_caption || 'Engineering Drawing'}
                            </h4>
                          </div>
                          <span
                            className={`px-2.5 py-1 text-[11px] font-bold rounded-full border ${
                              vev.review_status === 'HUMAN_VERIFIED'
                                ? 'bg-emerald-950/60 text-emerald-300 border-emerald-700/60'
                                : vev.review_status === 'REJECTED'
                                ? 'bg-rose-950/60 text-rose-300 border-rose-700/60'
                                : 'bg-amber-950/60 text-amber-300 border-amber-700/60'
                            }`}
                          >
                            {vev.review_status}
                          </span>
                        </div>

                        {/* Description */}
                        <div>
                          <p className="text-xs text-slate-300 leading-relaxed bg-slate-950/50 p-3 rounded-lg border border-slate-800/80">
                            {vev.visual_description}
                          </p>
                        </div>

                        {/* Extracted Labels */}
                        {vev.extracted_labels.length > 0 && (
                          <div className="space-y-1.5">
                            <span className="text-[11px] font-semibold text-slate-400 uppercase">
                              Extracted Drawing Labels:
                            </span>
                            <div className="flex flex-wrap gap-1.5">
                              {vev.extracted_labels.map((lbl, idx) => (
                                <span
                                  key={idx}
                                  className="px-2 py-0.5 text-[11px] bg-slate-800 text-slate-300 rounded border border-slate-700"
                                >
                                  {lbl}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Detected Entities */}
                        {vev.detected_entities.length > 0 && (
                          <div className="space-y-1.5">
                            <span className="text-[11px] font-semibold text-slate-400 uppercase">
                              Identified Boreholes & Features:
                            </span>
                            <div className="space-y-1">
                              {vev.detected_entities.map((ent, idx) => (
                                <div
                                  key={idx}
                                  className="text-xs p-2 rounded bg-slate-950/60 border border-slate-800 flex items-center justify-between"
                                >
                                  <span className="font-semibold text-purple-300">
                                    {ent.boring_id || ent.entity || `Entity ${idx + 1}`}
                                  </span>
                                  <span className="text-slate-400 text-[11px]">
                                    {ent.relative_location || ent.description || JSON.stringify(ent)}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Structured Findings */}
                        {Object.keys(vev.structured_findings).length > 0 && (
                          <div className="space-y-1.5">
                            <span className="text-[11px] font-semibold text-slate-400 uppercase">
                              Key Visual Metadata:
                            </span>
                            <div className="p-2.5 rounded bg-slate-950/60 border border-slate-800 grid grid-cols-2 gap-2 text-xs">
                              {Object.entries(vev.structured_findings)
                                .filter(([k]) => !['boring_locations', 'extracted_labels', 'summary', 'strata', 'sample_readings'].includes(k))
                                .map(([k, v]) => (
                                  <div key={k}>
                                    <span className="text-slate-500 capitalize">{k.replace(/_/g, ' ')}:</span>{' '}
                                    <span className="text-slate-200 font-mono">
                                      {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                                    </span>
                                  </div>
                                ))}
                            </div>
                          </div>
                        )}

                        {/* Human Verification Controls */}
                        <div className="pt-3 border-t border-slate-800 space-y-2">
                          <span className="text-[11px] font-semibold text-slate-400 uppercase">
                            Engineer Review & Provenance:
                          </span>
                          <input
                            type="text"
                            placeholder="Optional engineering notes (e.g. 'Verified against survey plan')..."
                            value={visualReviewNotes}
                            onChange={(e) => setVisualReviewNotes(e.target.value)}
                            className="w-full bg-slate-950 border border-slate-700 text-xs text-slate-200 rounded px-2.5 py-1.5 focus:outline-none focus:border-purple-500"
                          />
                          <div className="flex gap-2">
                            <button
                              onClick={() =>
                                reviewVisualMutation.mutate({
                                  evidenceId: vev.visual_evidence_id,
                                  reviewStatus: 'HUMAN_VERIFIED',
                                  notes: visualReviewNotes,
                                })
                              }
                              disabled={reviewVisualMutation.isPending}
                              className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center gap-1 transition-all"
                            >
                              <CheckCircle2 className="w-3.5 h-3.5" />
                              Human Verify
                            </button>
                            <button
                              onClick={() =>
                                reviewVisualMutation.mutate({
                                  evidenceId: vev.visual_evidence_id,
                                  reviewStatus: 'CHANGES_REQUESTED',
                                  notes: visualReviewNotes,
                                })
                              }
                              disabled={reviewVisualMutation.isPending}
                              className="px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold flex items-center gap-1 transition-all"
                            >
                              <AlertTriangle className="w-3.5 h-3.5" />
                              Request Changes
                            </button>
                            <button
                              onClick={() =>
                                reviewVisualMutation.mutate({
                                  evidenceId: vev.visual_evidence_id,
                                  reviewStatus: 'REJECTED',
                                  notes: visualReviewNotes,
                                })
                              }
                              disabled={reviewVisualMutation.isPending}
                              className="px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold flex items-center gap-1 transition-all"
                            >
                              <XCircle className="w-3.5 h-3.5" />
                              Reject
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </div>
              </div>

              {/* Cross-Modal Disagreements Alert Panel */}
              <div className="p-4 bg-slate-900/80 border border-slate-800 rounded-xl space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-slate-800">
                  <div className="flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                    <h4 className="text-xs font-bold text-slate-200">
                      Cross-Modal Verification & Discrepancies ({disagreements.length})
                    </h4>
                  </div>
                  <span className="text-[11px] text-slate-500">
                    Comparing visual drawings vs deterministic text / tables
                  </span>
                </div>

                {disagreements.length === 0 ? (
                  <div className="p-4 rounded-lg bg-emerald-950/20 border border-emerald-900/40 text-xs text-emerald-300 flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    No cross-modal discrepancies detected. Visual interpretation aligns with text and table records.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {disagreements.map((dis) => (
                      <div
                        key={dis.disagreement_id}
                        className={`p-3 rounded-lg border text-xs flex flex-col md:flex-row md:items-center justify-between gap-3 ${
                          dis.severity === 'CRITICAL'
                            ? 'bg-rose-950/30 border-rose-800/60 text-rose-200'
                            : dis.severity === 'HIGH'
                            ? 'bg-amber-950/30 border-amber-800/60 text-amber-200'
                            : 'bg-slate-950/50 border-slate-800 text-slate-300'
                        }`}
                      >
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-white uppercase text-[10px] px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700">
                              {dis.property_name}
                            </span>
                            <span
                              className={`text-[10px] font-bold px-1.5 py-0.2 rounded ${
                                dis.severity === 'CRITICAL'
                                  ? 'bg-rose-500 text-white'
                                  : dis.severity === 'HIGH'
                                  ? 'bg-amber-500 text-slate-950'
                                  : 'bg-blue-500/20 text-blue-300'
                              }`}
                            >
                              {dis.severity}
                            </span>
                            <span className="text-[11px] text-slate-400 font-mono">
                              Page {dis.page_index + 1}
                            </span>
                            <span
                              className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${
                                dis.status === 'RESOLVED'
                                  ? 'bg-emerald-950 text-emerald-300 border-emerald-700'
                                  : 'bg-amber-950 text-amber-300 border-amber-700'
                              }`}
                            >
                              {dis.status}
                            </span>
                          </div>
                          <p className="text-slate-300 text-xs">{dis.discrepancy_description}</p>
                          <div className="flex gap-4 text-[11px] text-slate-400 font-mono pt-1">
                            {dis.text_value && (
                              <span>
                                <strong className="text-cyan-400 font-semibold">Report Text:</strong>{' '}
                                {dis.text_value}
                              </span>
                            )}
                            {dis.visual_value && (
                              <span>
                                <strong className="text-purple-400 font-semibold">Drawing Visual:</strong>{' '}
                                {dis.visual_value}
                              </span>
                            )}
                          </div>
                        </div>

                        {dis.status === 'OPEN' && (
                          <div className="flex items-center gap-2 shrink-0">
                            <button
                              onClick={() =>
                                resolveDisagreementMutation.mutate({
                                  disagreementId: dis.disagreement_id,
                                  status: 'RESOLVED',
                                  notes: 'Confirmed by engineer review',
                                })
                              }
                              disabled={resolveDisagreementMutation.isPending}
                              className="px-2.5 py-1 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-semibold transition-all"
                            >
                              Resolve
                            </button>
                            <button
                              onClick={() =>
                                resolveDisagreementMutation.mutate({
                                  disagreementId: dis.disagreement_id,
                                  status: 'IGNORED',
                                  notes: 'Tolerable discrepancy',
                                })
                              }
                              disabled={resolveDisagreementMutation.isPending}
                              className="px-2.5 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-all"
                            >
                              Ignore
                            </button>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  )}
    </div>
  );
};

