import React from 'react';
import { useAuth } from '../../context/AuthContext';
import { Server, Key, RefreshCw, Menu } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useSidebar } from '../../context/SidebarContext';

export const Header: React.FC = () => {
  const { isConnected, isChecking, authMode, token, baseUrl, checkConnection } = useAuth();
  const { toggle } = useSidebar();
  const queryClient = useQueryClient();

  const handleRefresh = async () => {
    await checkConnection();
    queryClient.invalidateQueries();
  };

  return (
    <header className="h-14 px-4 glass border-b border-slate-800/60 flex items-center justify-between z-10 shrink-0">
      {/* Left: hamburger + status */}
      <div className="flex items-center gap-3">
        <button
          onClick={toggle}
          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-200 hover:bg-white/[0.06] transition-colors"
          title="Toggle sidebar"
        >
          <Menu className="w-4 h-4" />
        </button>

        {/* Connection pill */}
        <div
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border transition-all ${
            isConnected
              ? 'bg-emerald-500/8 text-emerald-400 border-emerald-500/20'
              : 'bg-rose-500/8 text-rose-400 border-rose-500/20'
          }`}
          title={`API: ${baseUrl}`}
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-rose-400'
            }`}
          />
          <Server className="w-3 h-3" />
          <span>{isConnected ? 'API Connected' : 'API Offline'}</span>
        </div>

        {/* Auth mode pill */}
        <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-mono bg-slate-800/60 text-slate-400 border border-slate-700/50">
          <Key className="w-3 h-3" />
          <span>
            {authMode === 'development'
              ? 'Dev Mode'
              : token
              ? 'Token ✓'
              : 'No Token'}
          </span>
        </div>
      </div>

      {/* Right: refresh */}
      <button
        onClick={handleRefresh}
        disabled={isChecking}
        className="btn-secondary px-3 py-1.5 text-[11px]"
        title="Refresh all data"
      >
        <RefreshCw className={`w-3.5 h-3.5 ${isChecking ? 'animate-spin' : ''}`} />
        <span className="hidden sm:inline">Refresh</span>
      </button>
    </header>
  );
};
