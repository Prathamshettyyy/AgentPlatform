import React, { useState } from 'react';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, RotateCcw, Crosshair } from 'lucide-react';
import { BoundingBox } from '../../api/types';
import { api } from '../../api/client';

interface DocumentViewerProps {
  documentId: string;
  totalPages: number;
  currentPage: number;
  onPageChange: (page: number) => void;
  printedPageNumber?: string | null;
  highlightBox?: BoundingBox | null;
  highlightLabel?: string | null;
}

export const DocumentViewer: React.FC<DocumentViewerProps> = ({
  documentId,
  totalPages,
  currentPage,
  onPageChange,
  printedPageNumber,
  highlightBox,
  highlightLabel,
}) => {
  const [zoom, setZoom] = useState(1.0);
  const [imageError, setImageError] = useState(false);

  const safePage = Math.min(Math.max(currentPage, 0), Math.max(totalPages - 1, 0));
  const imageUrl = api.getPageImageUrl(documentId, safePage);

  React.useEffect(() => {
    setImageError(false);
    if (currentPage !== safePage && totalPages > 0) {
      onPageChange(safePage);
    }
  }, [currentPage, documentId, safePage, totalPages, onPageChange]);

  const prevPage = () => {
    if (currentPage > 0) {
      onPageChange(currentPage - 1);
      setImageError(false);
    }
  };

  const nextPage = () => {
    if (currentPage < totalPages - 1) {
      onPageChange(currentPage + 1);
      setImageError(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-950/80 border border-slate-800 rounded-xl overflow-hidden shadow-lg">
      {/* Top Controls Toolbar */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-900 border-b border-slate-800 text-xs">
        <div className="flex items-center gap-2">
          <button
            onClick={prevPage}
            disabled={currentPage <= 0}
            className="p-1.5 rounded hover:bg-slate-800 disabled:opacity-40 disabled:hover:bg-transparent text-slate-300"
            title="Previous Page"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="font-medium text-slate-300">
            Page {currentPage + 1} of {Math.max(totalPages, 1)}
          </span>
          {printedPageNumber && (
            <span className="px-1.5 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/60 text-cyan-400 text-[11px]">
              Printed: {printedPageNumber}
            </span>
          )}
          <button
            onClick={nextPage}
            disabled={currentPage >= totalPages - 1}
            className="p-1.5 rounded hover:bg-slate-800 disabled:opacity-40 disabled:hover:bg-transparent text-slate-300"
            title="Next Page"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        {/* Zoom Controls */}
        <div className="flex items-center gap-2 text-slate-400">
          <button
            onClick={() => setZoom((z) => Math.max(0.6, z - 0.2))}
            className="p-1.5 rounded hover:bg-slate-800 hover:text-slate-200"
            title="Zoom Out"
          >
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-[11px] font-mono text-slate-400 w-10 text-center">
            {Math.round(zoom * 100)}%
          </span>
          <button
            onClick={() => setZoom((z) => Math.min(2.5, z + 0.2))}
            className="p-1.5 rounded hover:bg-slate-800 hover:text-slate-200"
            title="Zoom In"
          >
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => setZoom(1.0)}
            className="p-1.5 rounded hover:bg-slate-800 hover:text-slate-200"
            title="Reset Zoom"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Rendered Page Image Area with Bounding Box Overlay */}
      <div className="flex-1 overflow-auto p-4 flex justify-center items-start bg-slate-950">
        <div
          className="relative transition-transform duration-150 origin-top shadow-2xl rounded border border-slate-700/80 bg-white"
          style={{ transform: `scale(${zoom})` }}
        >
          {imageError ? (
            <div className="w-[600px] h-[800px] flex flex-col items-center justify-center p-6 text-slate-600 bg-slate-900">
              <Crosshair className="w-10 h-10 mb-2 opacity-50" />
              <p className="text-sm">Page preview image not available</p>
              <button
                onClick={() => setImageError(false)}
                className="mt-2 text-xs text-cyan-400 underline"
              >
                Retry
              </button>
            </div>
          ) : (
            <div className="relative">
              <img
                src={imageUrl}
                alt={`PDF Page ${currentPage + 1}`}
                className="max-w-none block select-none"
                style={{ width: '680px', height: 'auto' }}
                onError={() => setImageError(true)}
              />

              {/* Bounding Box Highlight Overlay */}
              {highlightBox && highlightBox.page_width > 0 && highlightBox.page_height > 0 && (
                <div
                  className="absolute border-2 border-cyan-400 bg-cyan-400/20 rounded-sm shadow-[0_0_12px_rgba(34,211,238,0.5)] animate-pulse pointer-events-none transition-all duration-200"
                  style={{
                    left: `${(highlightBox.x0 / highlightBox.page_width) * 100}%`,
                    top: `${(highlightBox.top / highlightBox.page_height) * 100}%`,
                    width: `${((highlightBox.x1 - highlightBox.x0) / highlightBox.page_width) * 100}%`,
                    height: `${((highlightBox.bottom - highlightBox.top) / highlightBox.page_height) * 100}%`,
                  }}
                >
                  {highlightLabel && (
                    <span className="absolute -top-5 left-0 px-1.5 py-0.5 rounded bg-cyan-950/90 border border-cyan-400 text-cyan-300 text-[10px] font-mono whitespace-nowrap shadow-md">
                      {highlightLabel}
                    </span>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

