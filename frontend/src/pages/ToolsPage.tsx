import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { Wrench, Search, Shield, Code2, CheckCircle2, XCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { TableSkeleton } from '../components/common/Skeleton';
import { EmptyState } from '../components/common/EmptyState';

export const ToolsPage: React.FC = () => {
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedTool, setExpandedTool] = useState<string | null>(null);

  const { data: tools = [], isLoading, error } = useQuery({
    queryKey: ['tools'],
    queryFn: api.listTools,
  });

  const filteredTools = tools.filter(
    (t) =>
      t.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      t.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      (t.description || '').toLowerCase().includes(searchTerm.toLowerCase())
  );

  const toggleExpand = (id: string) => {
    setExpandedTool((prev) => (prev === id ? null : id));
  };

  return (
    <div className="space-y-6 w-full">
      {/* Header */}
      <div className="page-header">
        <div>
          <h2 className="section-title">Registered Tools</h2>
          <p className="section-subtitle">
            Capability primitives available for tool-calling agents and sandboxed routines
          </p>
        </div>
      </div>

      {/* Search */}
      <div className="flex items-center gap-2 px-3 py-2.5 bg-slate-900/60 border border-slate-800/80 rounded-xl">
        <Search className="w-4 h-4 text-slate-500 shrink-0" />
        <input
          type="text"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          placeholder="Search tools by ID, name, or description…"
          className="flex-1 bg-transparent text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none"
        />
        {searchTerm && (
          <button onClick={() => setSearchTerm('')} className="text-[11px] text-slate-500 hover:text-slate-300 transition-colors">
            Clear
          </button>
        )}
      </div>

      {/* Tools Table */}
      {isLoading ? (
        <TableSkeleton rows={4} cols={5} />
      ) : error ? (
        <div className="p-5 rounded-xl bg-rose-500/8 border border-rose-500/25 text-rose-400 text-sm">
          Failed to load tools: {(error as any).message}
        </div>
      ) : filteredTools.length === 0 ? (
        <EmptyState
          icon={Wrench}
          title="No registered tools"
          description={
            searchTerm
              ? 'No tools matched your search query.'
              : 'No tools are currently registered in plugins/tool_manifests.'
          }
        />
      ) : (
        <div className="table-container">
          <table className="w-full text-left">
            <thead className="bg-slate-950/40 border-b border-slate-800/60">
              <tr>
                <th className="table-header">Tool</th>
                <th className="table-header">Status</th>
                <th className="table-header hidden md:table-cell">Permissions</th>
                <th className="table-header hidden sm:table-cell">Approval</th>
                <th className="table-header text-right">Schema</th>
              </tr>
            </thead>
            <tbody>
              {filteredTools.map((tool) => {
                const isExpanded = expandedTool === tool.id;
                const isEnabled = tool.enabled !== false;

                return (
                  <React.Fragment key={tool.id}>
                    <tr className={`table-row ${isExpanded ? 'bg-slate-800/30' : ''}`}>
                      <td className="table-cell">
                        <div className="flex items-center gap-3">
                          <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 shrink-0">
                            <Wrench className="w-4 h-4" />
                          </div>
                          <div className="min-w-0">
                            <span className="font-mono text-sm font-semibold text-slate-100 block">
                              {tool.id}
                            </span>
                            <span className="text-xs text-slate-500 block">{tool.name}</span>
                            {tool.description && (
                              <p className="text-[11px] text-slate-600 line-clamp-1 max-w-md mt-0.5">
                                {tool.description}
                              </p>
                            )}
                          </div>
                        </div>
                      </td>

                      <td className="table-cell">
                        <span
                          className={`badge ${
                            isEnabled
                              ? 'bg-emerald-500/10 border border-emerald-500/25 text-emerald-400'
                              : 'bg-slate-800/60 border border-slate-700/50 text-slate-500'
                          }`}
                        >
                          {isEnabled ? 'Enabled' : 'Disabled'}
                        </span>
                      </td>

                      <td className="table-cell hidden md:table-cell font-mono text-xs text-slate-400">
                        {tool.execution?.permissions && tool.execution.permissions.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {tool.execution.permissions.map((p: string) => (
                              <span
                                key={p}
                                className="badge bg-slate-950 border border-slate-800 text-slate-400"
                              >
                                {p}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-600 italic">None</span>
                        )}
                      </td>

                      <td className="table-cell hidden sm:table-cell">
                        {tool.execution?.requires_approval ? (
                          <span className="inline-flex items-center gap-1 text-[11px] text-amber-400 font-medium">
                            <Shield className="w-3.5 h-3.5" />
                            Required
                          </span>
                        ) : (
                          <span className="text-[11px] text-slate-600">Auto</span>
                        )}
                      </td>

                      <td className="table-cell text-right">
                        <button
                          onClick={() => toggleExpand(tool.id)}
                          className="inline-flex items-center gap-1 text-[11px] text-blue-400 hover:text-blue-300 font-medium transition-colors"
                        >
                          <Code2 className="w-3.5 h-3.5" />
                          <span>{isExpanded ? 'Hide' : 'Inspect'}</span>
                          {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                        </button>
                      </td>
                    </tr>

                    {/* Expanded Schema Row */}
                    {isExpanded && (
                      <tr className="bg-[#080c14]">
                        <td colSpan={5} className="p-4 border-b border-slate-800/60">
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs font-mono">
                            <div>
                              <span className="font-semibold text-slate-400 block mb-1 font-sans text-[11px]">
                                Input Schema:
                              </span>
                              <pre className="p-3 bg-slate-900/80 rounded-lg border border-slate-800/80 text-slate-300 overflow-x-auto max-h-48 text-[11px]">
                                {JSON.stringify(tool.input_schema || {}, null, 2)}
                              </pre>
                            </div>
                            <div>
                              <span className="font-semibold text-slate-400 block mb-1 font-sans text-[11px]">
                                Output Schema:
                              </span>
                              <pre className="p-3 bg-slate-900/80 rounded-lg border border-slate-800/80 text-slate-300 overflow-x-auto max-h-48 text-[11px]">
                                {JSON.stringify(tool.output_schema || {}, null, 2)}
                              </pre>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
          <div className="px-4 py-2.5 border-t border-slate-800/60 bg-slate-950/20 text-[11px] text-slate-600">
            {filteredTools.length} tool{filteredTools.length !== 1 ? 's' : ''}
            {searchTerm ? ` matching "${searchTerm}"` : ' registered'}
          </div>
        </div>
      )}
    </div>
  );
};
