import React, { useRef, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Bot,
  GitBranch,
  PlayCircle,
  FileText,
  CheckSquare,
  Wrench,
  Settings,
  Activity,
  ChevronLeft,
  ChevronRight,
  FolderOpen,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { useSidebar } from '../../context/SidebarContext';

const navItems = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/documents', label: 'Documents', icon: FolderOpen },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/workflows', label: 'Workflows', icon: GitBranch },
  { to: '/runs', label: 'Runs', icon: PlayCircle },
  { to: '/events', label: 'Logs & Events', icon: FileText },
  { to: '/approvals', label: 'Approvals', icon: CheckSquare, hasBadge: true },
  { to: '/tools', label: 'Tools', icon: Wrench },
  { to: '/settings', label: 'Settings', icon: Settings },
];

const navGroups = [
  { label: 'Main', items: navItems.slice(0, 5) },
  { label: 'Observability', items: navItems.slice(5, 7) },
  { label: 'Config', items: navItems.slice(7) },
];

export const Sidebar: React.FC = () => {
  const { isOpen, toggle } = useSidebar();

  const { data: approvals } = useQuery({
    queryKey: ['approvals'],
    queryFn: api.listApprovals,
    refetchInterval: 10000,
    retry: false,
  });

  const pendingCount = approvals?.length || 0;

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={toggle}
        />
      )}

      <aside
        className={`
          fixed lg:relative inset-y-0 left-0 z-30 flex flex-col
          bg-[#0d1424] border-r border-slate-800/60
          sidebar-transition shrink-0
          ${isOpen ? 'w-[240px]' : 'w-[60px]'}
        `}
      >
        {/* Brand / Logo area */}
        <div className={`h-16 flex items-center border-b border-slate-800/60 shrink-0 relative ${isOpen ? 'px-4 gap-3' : 'justify-center px-0'}`}>
          <div className="p-2 rounded-lg bg-blue-600/15 border border-blue-500/25 text-blue-400 shrink-0">
            <Activity className="w-4 h-4" />
          </div>
          {isOpen && (
            <div className="min-w-0 flex-1 overflow-hidden">
              <h1 className="font-bold text-[13px] tracking-wide text-slate-100 truncate">Agent Platform</h1>
              <p className="text-[10px] text-slate-500 truncate">Operations Console</p>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto py-3 space-y-5">
          {navGroups.map((group) => (
            <div key={group.label}>
              {isOpen && (
                <div className="px-4 mb-1">
                  <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-600">
                    {group.label}
                  </span>
                </div>
              )}
              <div className={`space-y-0.5 ${isOpen ? 'px-2' : 'px-1.5'}`}>
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const badge = item.hasBadge ? pendingCount : 0;
                  return (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      end={item.end}
                      title={!isOpen ? item.label : undefined}
                      className={({ isActive }) =>
                        `flex items-center gap-3 rounded-lg text-[13px] font-medium transition-all duration-150 group relative
                        ${isOpen ? 'px-3 py-2.5' : 'px-0 py-2.5 justify-center'}
                        ${
                          isActive
                            ? 'bg-blue-600/15 text-blue-400 border border-blue-500/20'
                            : 'text-slate-400 hover:text-slate-200 hover:bg-white/[0.04] border border-transparent'
                        }`
                      }
                    >
                      {({ isActive }) => (
                        <>
                          <Icon
                            className={`shrink-0 transition-colors ${isOpen ? 'w-4 h-4' : 'w-4.5 h-4.5'} ${isActive ? 'text-blue-400' : 'text-slate-500 group-hover:text-slate-300'}`}
                          />
                          {isOpen && (
                            <>
                              <span className="flex-1 truncate">{item.label}</span>
                              {badge > 0 && (
                                <span className="ml-auto px-1.5 py-0.5 text-[10px] font-bold rounded-full bg-amber-500 text-slate-950 leading-none">
                                  {badge}
                                </span>
                              )}
                            </>
                          )}
                          {/* Collapsed badge dot */}
                          {!isOpen && badge > 0 && (
                            <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-amber-500" />
                          )}
                        </>
                      )}
                    </NavLink>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer */}
        {isOpen && (
          <div className="px-4 pb-3 pt-2 border-t border-slate-800/60">
            <div className="text-[10px] text-slate-600 space-y-1">
              <div className="flex justify-between">
                <span>Engine</span>
                <span className="text-slate-500 font-mono">FastAPI + LangGraph</span>
              </div>
              <div className="flex justify-between">
                <span>Storage</span>
                <span className="text-slate-500 font-mono">SQLite</span>
              </div>
            </div>
          </div>
        )}

        {/* Toggle button */}
        <button
          onClick={toggle}
          title={isOpen ? 'Collapse sidebar' : 'Expand sidebar'}
          className={`
            h-12 flex items-center justify-center text-slate-500 hover:text-slate-200
            border-t border-slate-800/60 transition-colors shrink-0
            hover:bg-white/[0.04]
          `}
        >
          {isOpen ? <ChevronLeft className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>
      </aside>
    </>
  );
};
