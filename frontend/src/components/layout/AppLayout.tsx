import React from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { SidebarProvider } from '../../context/SidebarContext';

export const AppLayout: React.FC = () => {
  return (
    <SidebarProvider>
      <div className="flex h-screen bg-[#080c14] text-slate-200 overflow-hidden">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <Header />
          <main className="flex-1 overflow-y-auto">
            <div className="w-full px-5 py-6 lg:px-8 lg:py-7">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </SidebarProvider>
  );
};
