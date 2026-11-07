import React from 'react';

const STATUS_MAP: Record<
  string,
  { label: string; cls: string; dot?: string }
> = {
  // Run statuses
  succeeded:           { label: 'succeeded',            cls: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25', dot: 'bg-emerald-400' },
  success:             { label: 'success',              cls: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25', dot: 'bg-emerald-400' },
  running:             { label: 'running',              cls: 'bg-blue-500/12 text-blue-400 border-blue-500/25',         dot: 'bg-blue-400 animate-pulse' },
  resuming:            { label: 'resuming',             cls: 'bg-blue-500/12 text-blue-400 border-blue-500/25',         dot: 'bg-blue-400 animate-pulse' },
  failed:              { label: 'failed',               cls: 'bg-rose-500/12 text-rose-400 border-rose-500/25',         dot: 'bg-rose-400' },
  error:               { label: 'error',                cls: 'bg-rose-500/12 text-rose-400 border-rose-500/25',         dot: 'bg-rose-400' },
  waiting_for_approval:{ label: 'Waiting for Approval', cls: 'bg-amber-500/12 text-amber-400 border-amber-500/25',    dot: 'bg-amber-400 animate-pulse' },
  partially_succeeded: { label: 'partially_succeeded',  cls: 'bg-orange-500/12 text-orange-400 border-orange-500/25',   dot: 'bg-orange-400' },
  cancelled:           { label: 'cancelled',            cls: 'bg-slate-500/12 text-slate-400 border-slate-500/25' },

  // Agent / registry statuses
  available:           { label: 'available',            cls: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25', dot: 'bg-emerald-400' },
  enabled:             { label: 'enabled',              cls: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25', dot: 'bg-emerald-400' },
  disabled:            { label: 'disabled',             cls: 'bg-slate-500/12 text-slate-400 border-slate-500/25' },
  disconnected:        { label: 'disconnected',         cls: 'bg-slate-600/15 text-slate-500 border-slate-600/25' },

  // Workflow statuses
  registered:          { label: 'registered',           cls: 'bg-violet-500/12 text-violet-400 border-violet-500/25',   dot: 'bg-violet-400' },
  draft:               { label: 'Draft',                cls: 'bg-slate-700/30 text-slate-400 border-slate-600/25' },

  // Node check statuses
  passed:              { label: 'passed',               cls: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25', dot: 'bg-emerald-400' },
  warning:             { label: 'warning',              cls: 'bg-amber-500/12 text-amber-400 border-amber-500/25' },

  // Document intelligence & extraction statuses
  completed:           { label: 'completed',            cls: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25', dot: 'bg-emerald-400' },
  processing:          { label: 'processing',           cls: 'bg-blue-500/12 text-blue-400 border-blue-500/25',         dot: 'bg-blue-400 animate-pulse' },
  partially_extracted: { label: 'partially_extracted',  cls: 'bg-orange-500/12 text-orange-400 border-orange-500/25',   dot: 'bg-orange-400' },
  duplicate:           { label: 'duplicate',            cls: 'bg-amber-500/12 text-amber-400 border-amber-500/25',     dot: 'bg-amber-400' },
  uploaded:            { label: 'uploaded',             cls: 'bg-cyan-500/12 text-cyan-400 border-cyan-500/25' },
  verified:            { label: 'verified',             cls: 'bg-emerald-500/12 text-emerald-400 border-emerald-500/25', dot: 'bg-emerald-400' },
  unverified:          { label: 'unverified',           cls: 'bg-slate-700/30 text-slate-400 border-slate-600/25' },
  flagged:             { label: 'flagged',              cls: 'bg-rose-500/12 text-rose-400 border-rose-500/25',         dot: 'bg-rose-400' },
};

interface StatusBadgeProps {
  status: string;
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status, className = '' }) => {
  const normalized = (status || '').toLowerCase().replace(/\s+/g, '_');
  const cfg = STATUS_MAP[normalized] ?? {
    label: status,
    cls: 'bg-slate-700/30 text-slate-400 border-slate-600/25',
  };

  return (
    <span
      className={`
        inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md
        text-[11px] font-medium border whitespace-nowrap
        ${cfg.cls} ${className}
      `}
    >
      {cfg.dot && <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />}
      {cfg.label}
    </span>
  );
};
