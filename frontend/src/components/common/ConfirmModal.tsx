import React from 'react';
import { AlertTriangle, X, Info } from 'lucide-react';

interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  message: string;
  previewItems?: { label: string; value: string | number; isDestructive?: boolean }[];
  confirmText?: string;
  cancelText?: string;
  isDanger?: boolean;
  isLoading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export const ConfirmModal: React.FC<ConfirmModalProps> = ({
  isOpen,
  title,
  message,
  previewItems,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  isDanger = true,
  isLoading = false,
  onConfirm,
  onCancel,
}) => {
  if (!isOpen) return null;

  const Icon = isDanger ? AlertTriangle : Info;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-md">
      <div
        className="relative w-full max-w-md bg-[#0d1424] border border-slate-700/60 rounded-2xl shadow-2xl overflow-hidden"
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className={`px-6 py-4 border-b flex items-start gap-3 ${
          isDanger
            ? 'bg-rose-500/8 border-rose-500/20'
            : 'bg-amber-500/8 border-amber-500/20'
        }`}>
          <div className={`p-2 rounded-lg shrink-0 ${isDanger ? 'bg-rose-500/15 text-rose-400' : 'bg-amber-500/15 text-amber-400'}`}>
            <Icon className="w-4 h-4" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold text-slate-100">{title}</h3>
            <p className="text-xs text-slate-400 mt-0.5 leading-relaxed">{message}</p>
          </div>
          <button
            onClick={onCancel}
            disabled={isLoading}
            className="text-slate-500 hover:text-slate-200 p-1 rounded-lg hover:bg-slate-800 transition-colors shrink-0"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Preview items */}
        {previewItems && previewItems.length > 0 && (
          <div className="px-6 py-4 bg-slate-950/40 border-b border-slate-800/60">
            <p className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider mb-2">Impact Preview</p>
            <div className="space-y-1.5">
              {previewItems.map((item, idx) => (
                <div key={idx} className="flex justify-between items-center text-xs py-1 border-b border-slate-800/30 last:border-0">
                  <span className="text-slate-500">{item.label}</span>
                  <span className={`font-mono font-medium ${item.isDestructive ? 'text-rose-400' : 'text-slate-300'}`}>
                    {item.value}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="px-6 py-4 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={onCancel}
            disabled={isLoading}
            className="btn-secondary"
          >
            {cancelText}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isLoading}
            className={`inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-white rounded-lg transition-all ${
              isDanger
                ? 'bg-rose-600 hover:bg-rose-500 shadow-sm hover:shadow-rose-500/20'
                : 'bg-blue-600 hover:bg-blue-500 shadow-sm hover:shadow-blue-500/20'
            } disabled:opacity-60`}
          >
            {isLoading ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Processing…
              </>
            ) : (
              confirmText
            )}
          </button>
        </div>
      </div>
    </div>
  );
};
