import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Server, Key, ShieldAlert, CheckCircle2, RefreshCw, Terminal, Globe } from 'lucide-react';

export const SettingsPage: React.FC = () => {
  const {
    baseUrl,
    setBaseUrl,
    token,
    setToken,
    authMode,
    isConnected,
    isChecking,
    checkConnection,
  } = useAuth();

  const [localUrl, setLocalUrl] = useState(baseUrl);
  const [localToken, setLocalToken] = useState(token);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [pingLatency, setPingLatency] = useState<number | null>(null);

  const handleSaveConnection = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaveMsg(null);
    setBaseUrl(localUrl.trim());
    setToken(localToken.trim());

    const start = performance.now();
    await checkConnection();
    const end = performance.now();
    setPingLatency(Math.round(end - start));

    setSaveMsg('Configuration updated and tested against active API.');
  };

  const handleClearToken = () => {
    setLocalToken('');
    setToken('');
    checkConnection();
  };

  return (
    <div className="space-y-6 w-full">
      {/* Header */}
      <div className="page-header">
        <div>
          <h2 className="section-title">Console Settings</h2>
          <p className="section-subtitle">
            Configure API endpoints, in-memory development credentials, and connectivity
          </p>
        </div>
      </div>

      {saveMsg && (
        <div
          className={`p-3.5 rounded-xl text-xs flex items-center gap-2.5 ${
            saveMsg.includes('updated')
              ? 'bg-emerald-500/10 border border-emerald-500/25 text-emerald-400'
              : 'bg-amber-500/10 border border-amber-500/25 text-amber-400'
          }`}
        >
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{saveMsg}</span>
        </div>
      )}

      {/* Grid container for settings */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Connection & Auth Form */}
        <form onSubmit={handleSaveConnection} className="card p-6 space-y-6 flex flex-col justify-between">
          <div className="space-y-6">
            <div className="flex items-center gap-2.5 pb-3 border-b border-slate-800/60">
              <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20 text-blue-400">
                <Server className="w-4 h-4" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-slate-100">Backend Connection</h3>
                <p className="text-[11px] text-slate-500">Configure target API server URL</p>
              </div>
            </div>

            <div className="space-y-2">
              <label className="block text-xs font-medium text-slate-300">
                API Server Base URL
              </label>
              <div className="flex items-center gap-2">
                <Globe className="w-4 h-4 text-slate-500 shrink-0" />
                <input
                  type="text"
                  value={localUrl}
                  onChange={(e) => setLocalUrl(e.target.value)}
                  placeholder="http://127.0.0.1:8000"
                  className="input-base font-mono w-full text-xs"
                />
              </div>
              <p className="text-[11px] text-slate-500">
                The dashboard communicates directly with this address using CORS and typed endpoints.
              </p>
            </div>

            <div className="pt-4 border-t border-slate-800/60 space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Key className="w-4 h-4 text-amber-400" />
                  <span className="text-xs font-semibold text-slate-200">API Bearer Token</span>
                </div>
                {token && (
                  <button
                    type="button"
                    onClick={handleClearToken}
                    className="text-[11px] text-slate-500 hover:text-rose-400 transition-colors"
                  >
                    Clear Token
                  </button>
                )}
              </div>

              <input
                type="password"
                value={localToken}
                onChange={(e) => setLocalToken(e.target.value)}
                placeholder="Enter bearer token (e.g. dev-token-2026)"
                className="input-base font-mono w-full text-xs"
              />

              <div className="p-3 bg-slate-950/60 rounded-xl border border-slate-800/80 text-[11px] text-slate-400 space-y-1">
                <div className="flex items-center gap-1.5 text-slate-300 font-medium">
                  <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
                  Security Policy:
                </div>
                <p className="leading-relaxed">
                  Tokens entered here are stored strictly in browser memory for this session and are never written to localStorage, cookies, or bundled into build assets.
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between pt-4 border-t border-slate-800/60 mt-4">
            <div className="flex items-center gap-2 text-xs font-mono">
              <span className="text-slate-500">Status:</span>
              <span className={isConnected ? 'text-emerald-400 font-semibold' : 'text-rose-400 font-semibold'}>
                {isConnected ? `Online (${authMode || 'required'})` : 'Offline'}
              </span>
              {pingLatency !== null && <span className="text-slate-500">({pingLatency}ms)</span>}
            </div>

            <button
              type="submit"
              disabled={isChecking}
              className="btn-primary"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isChecking ? 'animate-spin' : ''}`} />
              Save & Test
            </button>
          </div>
        </form>

        {/* Backend Startup Modes Guide */}
        <div className="card p-6 space-y-5">
          <div className="flex items-center gap-2.5 pb-3 border-b border-slate-800/60">
            <div className="p-2 rounded-lg bg-purple-500/10 border border-purple-500/20 text-purple-400">
              <Terminal className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-100">Backend Startup Modes</h3>
              <p className="text-[11px] text-slate-500">CLI commands for running the agent platform</p>
            </div>
          </div>

          <div className="space-y-4 text-xs">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-200">Mode A: Local Development</span>
                <span className="badge bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">No token required</span>
              </div>
              <p className="text-slate-500 text-[11px]">
                Allows dashboard connection without authentication for fast local testing:
              </p>
              <pre className="p-3 bg-[#080c14] rounded-lg border border-slate-800/80 font-mono text-purple-300 overflow-x-auto text-[11px]">
$env:AGENT_PLATFORM_AUTH_MODE = "development"<br />
$env:AGENT_PLATFORM_DEV_MODE = "1"<br />
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
              </pre>
            </div>

            <div className="space-y-2 pt-2 border-t border-slate-800/60">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-200">Mode B: Authenticated Mode</span>
                <span className="badge bg-blue-500/10 border border-blue-500/20 text-blue-400">Token enforced</span>
              </div>
              <p className="text-slate-500 text-[11px]">
                Enforces Bearer token verification on all <code className="text-slate-400">/v1/*</code> endpoints:
              </p>
              <pre className="p-3 bg-[#080c14] rounded-lg border border-slate-800/80 font-mono text-blue-300 overflow-x-auto text-[11px]">
$env:AGENT_PLATFORM_API_TOKEN = "my-secret-token"<br />
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
              </pre>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
