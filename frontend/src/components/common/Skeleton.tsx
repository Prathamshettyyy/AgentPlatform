import React from 'react';

export const Skeleton: React.FC<{ className?: string }> = ({ className = '' }) => (
  <div className={`animate-pulse rounded bg-gradient-to-r from-slate-800/50 via-slate-700/30 to-slate-800/50 bg-[length:200%_100%] ${className}`} />
);

export const TableSkeleton: React.FC<{ rows?: number; cols?: number }> = ({ rows = 5, cols = 4 }) => (
  <div className="table-container overflow-hidden">
    {/* fake header */}
    <div className="h-10 bg-slate-950/40 border-b border-slate-800/60 flex items-center px-4 gap-4">
      {Array.from({ length: cols }).map((_, c) => (
        <Skeleton key={c} className="h-3 flex-1 rounded-sm" />
      ))}
    </div>
    {Array.from({ length: rows }).map((_, r) => (
      <div key={r} className="flex items-center gap-4 px-4 py-3.5 border-b border-slate-800/40 last:border-0">
        <Skeleton className="h-8 w-8 rounded-lg shrink-0" />
        <Skeleton className="h-4 flex-1" />
        {Array.from({ length: cols - 2 }).map((_, c) => (
          <Skeleton key={c} className="h-4 flex-1" />
        ))}
        <Skeleton className="h-6 w-16 rounded-lg shrink-0" />
      </div>
    ))}
  </div>
);
