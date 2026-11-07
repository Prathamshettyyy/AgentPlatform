import React from 'react';
import { LucideIcon, Inbox } from 'lucide-react';

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description: string;
  actionText?: string;
  onAction?: () => void;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon: Icon = Inbox,
  title,
  description,
  actionText,
  onAction,
}) => (
  <div className="flex flex-col items-center justify-center py-16 px-8 text-center rounded-xl border border-dashed border-slate-800/80 bg-slate-900/20">
    <div className="relative mb-4">
      <div className="absolute inset-0 rounded-full bg-blue-500/10 blur-xl scale-150 opacity-50" />
      <div className="relative p-4 bg-slate-800/60 border border-slate-700/50 rounded-2xl text-slate-500">
        <Icon className="w-7 h-7" />
      </div>
    </div>
    <h3 className="text-sm font-semibold text-slate-300 mb-1">{title}</h3>
    <p className="text-xs text-slate-500 max-w-xs leading-relaxed">{description}</p>
    {actionText && onAction && (
      <button
        onClick={onAction}
        className="mt-5 btn-primary"
      >
        {actionText}
      </button>
    )}
  </div>
);
