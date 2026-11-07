import React, { memo } from 'react';
import { Handle, Position, NodeProps } from '@xyflow/react';
import { CheckCircle2 } from 'lucide-react';

export const StartNode: React.FC<NodeProps> = memo(({ data }) => {
  const isHorizontal = (data as any)?.direction !== 'TB';
  return (
    <div className="relative w-[100px] h-[36px] px-3.5 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/30 text-emerald-400 shadow-md backdrop-blur-md flex items-center justify-center gap-2 select-none">
      <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
      <span className="text-xs font-bold tracking-wider font-mono">START</span>
      <Handle
        type="source"
        id="start-source"
        position={isHorizontal ? Position.Right : Position.Bottom}
        className="!w-3 !h-3 !bg-emerald-400 !border-2 !border-slate-950 z-20"
      />
    </div>
  );
});

export const EndNode: React.FC<NodeProps> = memo(({ data }) => {
  const isHorizontal = (data as any)?.direction !== 'TB';
  return (
    <div className="relative w-[100px] h-[36px] px-3.5 py-2 rounded-xl bg-indigo-500/10 border border-indigo-500/30 text-indigo-400 shadow-md backdrop-blur-md flex items-center justify-center gap-2 select-none">
      <CheckCircle2 className="w-3.5 h-3.5 text-indigo-400" />
      <span className="text-xs font-bold tracking-wider font-mono">END</span>
      <Handle
        type="target"
        id="end-target"
        position={isHorizontal ? Position.Left : Position.Top}
        className="!w-3 !h-3 !bg-indigo-400 !border-2 !border-slate-950 z-20"
      />
    </div>
  );
});
