import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';

type Session = {
  session_id: string;
  exe_path: string;
  pid: number;
  created_at: string;
  status: string;
  capture: string;
  capture_error?: string | null;
};

type ActivityEvent = {
  id: string;
  session_id: string;
  timestamp: string;
  kind: string;
  pid?: number | null;
  ppid?: number | null;
  path?: string | null;
  target?: string | null;
  operation?: string | null;
  details?: Record<string, unknown>;
};

type ProcessInfo = {
  pid: number;
  ppid?: number | null;
  name?: string | null;
  exe?: string | null;
  username?: string | null;
};

type ProcessList = {
  items: ProcessInfo[];
  admin: boolean;
};

const KINDS = ['file', 'registry', 'process', 'network'] as const;
type Kind = (typeof KINDS)[number];

const api = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
};

function captureBadge(capture: string): { label: string; cls: string } {
  if (capture === 'live') return { label: 'live', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' };
  if (capture === 'needs_admin') return { label: 'needs admin', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/40' };
  if (capture === 'failed') return { label: 'failed', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/40' };
  if (capture === 'stopped') return { label: 'stopped', cls: 'bg-slate-500/15 text-slate-300 border-slate-500/40' };
  return { label: capture, cls: 'bg-slate-500/15 text-slate-300 border-slate-500/40' };
}

function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSession, setSelectedSession] = useState<string>('');
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [admin, setAdmin] = useState<boolean | null>(null);

  const [processes, setProcesses] = useState<ProcessInfo[]>([]);
  const [processQuery, setProcessQuery] = useState('');
  const [manualPath, setManualPath] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [kindFilter, setKindFilter] = useState<Set<Kind>>(new Set(KINDS));
  const [eventQuery, setEventQuery] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);

  const tableRef = useRef<HTMLDivElement>(null);

  const selected = useMemo(
    () => sessions.find((session) => session.session_id === selectedSession),
    [sessions, selectedSession],
  );

  const refreshSessions = async () => {
    const result = await api<{ items: Session[] }>('/api/sessions');
    setSessions(result.items);
    if (!selectedSession && result.items.length > 0) {
      setSelectedSession(result.items[0].session_id);
    }
  };

  const refreshProcesses = async () => {
    const result = await api<ProcessList>('/api/processes');
    setProcesses(result.items);
    setAdmin(result.admin);
  };

  const loadEvents = async (sessionId: string) => {
    const result = await api<{ items: ActivityEvent[] }>(`/api/sessions/${sessionId}/events`);
    setEvents(result.items);
  };

  useEffect(() => {
    refreshSessions().catch((err) => setError(String(err)));
    refreshProcesses().catch((err) => setError(String(err)));
    const interval = window.setInterval(() => {
      refreshProcesses().catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    if (!selectedSession) {
      setEvents([]);
      return;
    }
    loadEvents(selectedSession).catch((err) => setError(String(err)));
    const socket = new WebSocket(
      `${window.location.origin.replace('http', 'ws')}/ws/sessions/${selectedSession}`,
    );
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);
    socket.onmessage = (msg) => {
      const payload = JSON.parse(msg.data) as ActivityEvent;
      setEvents((current) => {
        const next = [...current, payload];
        return next.length > 5000 ? next.slice(-5000) : next;
      });
    };
    return () => socket.close();
  }, [selectedSession]);

  useEffect(() => {
    if (!autoScroll || !tableRef.current) return;
    tableRef.current.scrollTop = tableRef.current.scrollHeight;
  }, [events, autoScroll]);

  const startSession = async (body: { pid?: number; exe_path?: string }) => {
    setBusy(true);
    setError(null);
    try {
      const session = await api<Session>('/api/sessions', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setSessions((current) => [session, ...current.filter((s) => s.session_id !== session.session_id)]);
      setSelectedSession(session.session_id);
      await loadEvents(session.session_id);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  const stopSession = async (sessionId: string) => {
    try {
      await api(`/api/sessions/${sessionId}`, { method: 'DELETE' });
      await refreshSessions();
    } catch (err) {
      setError(String(err));
    }
  };

  const toggleKind = (kind: Kind) => {
    setKindFilter((current) => {
      const next = new Set(current);
      if (next.has(kind)) {
        next.delete(kind);
      } else {
        next.add(kind);
      }
      return next;
    });
  };

  const visibleEvents = useMemo(() => {
    const q = eventQuery.trim().toLowerCase();
    return events.filter((event) => {
      if (!kindFilter.has(event.kind as Kind) && (KINDS as readonly string[]).includes(event.kind)) {
        return false;
      }
      if (!q) return true;
      const blob = `${event.path ?? ''} ${event.target ?? ''} ${event.operation ?? ''} ${JSON.stringify(event.details ?? {})}`.toLowerCase();
      return blob.includes(q);
    });
  }, [events, kindFilter, eventQuery]);

  const filteredProcesses = useMemo(() => {
    const q = processQuery.trim().toLowerCase();
    if (!q) return processes.slice(0, 200);
    return processes
      .filter((p) => {
        const hay = `${p.name ?? ''} ${p.exe ?? ''} ${p.pid}`.toLowerCase();
        return hay.includes(q);
      })
      .slice(0, 200);
  }, [processes, processQuery]);

  const eventCounts = useMemo(() => {
    const counts: Record<string, number> = { file: 0, registry: 0, process: 0, network: 0 };
    for (const e of events) {
      counts[e.kind] = (counts[e.kind] ?? 0) + 1;
    }
    return counts;
  }, [events]);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800 px-6 py-4">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">Activity Tracker</h1>
            <p className="text-sm text-slate-400">
              Realtime kernel ETW visibility — file, registry, process, network
            </p>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className={`rounded-full border px-3 py-1 ${connected ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-slate-700 bg-slate-900 text-slate-400'}`}>
              {connected ? 'stream connected' : 'stream idle'}
            </span>
            <span className={`rounded-full border px-3 py-1 ${admin ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : admin === false ? 'border-amber-500/40 bg-amber-500/10 text-amber-300' : 'border-slate-700 bg-slate-900 text-slate-400'}`}>
              {admin === null ? 'admin: ?' : admin ? 'admin: yes' : 'admin: no'}
            </span>
          </div>
        </div>
        {admin === false && (
          <div className="mt-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
            Backend is not running as Administrator. ETW kernel providers cannot be enabled — sessions
            will be created but no real events will stream. Restart the backend in an elevated shell.
          </div>
        )}
        {error && (
          <div className="mt-3 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
            {error}
          </div>
        )}
      </header>

      <main className="grid gap-4 p-6 lg:grid-cols-[420px_1fr]">
        <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
          <div>
            <label className="mb-2 block text-sm text-slate-300">Pick a running process</label>
            <input
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-500"
              placeholder="search by name, exe, or pid"
              value={processQuery}
              onChange={(event) => setProcessQuery(event.target.value)}
            />
            <div className="mt-2 max-h-64 overflow-auto rounded-xl border border-slate-800">
              {filteredProcesses.length === 0 && (
                <div className="px-3 py-4 text-center text-xs text-slate-500">no matches</div>
              )}
              {filteredProcesses.map((proc) => (
                <button
                  key={proc.pid}
                  disabled={busy}
                  onClick={() => startSession({ pid: proc.pid })}
                  className="flex w-full items-start justify-between gap-2 border-b border-slate-800 px-3 py-2 text-left text-xs last:border-0 hover:bg-slate-800/60 disabled:opacity-60"
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-slate-100">{proc.name ?? '(unknown)'}</div>
                    <div className="truncate text-slate-500">{proc.exe ?? ''}</div>
                  </div>
                  <div className="shrink-0 text-right text-slate-400">
                    <div>pid {proc.pid}</div>
                    {proc.username && <div className="text-slate-600">{proc.username}</div>}
                  </div>
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="mb-2 block text-sm text-slate-300">…or by exe path</label>
            <div className="flex gap-2">
              <input
                className="flex-1 rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-500"
                placeholder="C:/Path/To/App.exe"
                value={manualPath}
                onChange={(event) => setManualPath(event.target.value)}
              />
              <button
                disabled={busy || !manualPath}
                onClick={() => startSession({ exe_path: manualPath })}
                className="rounded-xl bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
              >
                Track
              </button>
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between text-sm text-slate-400">
              <span>Sessions</span>
              <span className="text-xs text-slate-500">{sessions.length}</span>
            </div>
            <div className="space-y-2">
              {sessions.length === 0 && (
                <div className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-6 text-center text-xs text-slate-500">
                  No sessions yet
                </div>
              )}
              {sessions.map((session) => {
                const badge = captureBadge(session.capture);
                const isActive = session.session_id === selectedSession;
                return (
                  <div
                    key={session.session_id}
                    className={`rounded-xl border px-3 py-2 text-sm ${isActive ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-800 bg-slate-950'}`}
                  >
                    <button onClick={() => setSelectedSession(session.session_id)} className="block w-full text-left">
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate font-medium">{session.exe_path}</div>
                        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${badge.cls}`}>{badge.label}</span>
                      </div>
                      <div className="mt-1 flex items-center justify-between text-xs text-slate-400">
                        <span>pid {session.pid}</span>
                        <span>{new Date(session.created_at).toLocaleTimeString()}</span>
                      </div>
                      {session.capture_error && (
                        <div className="mt-1 text-xs text-amber-400">{session.capture_error}</div>
                      )}
                    </button>
                    {session.capture === 'live' && (
                      <button
                        onClick={() => stopSession(session.session_id)}
                        className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-300 hover:border-rose-500/60 hover:text-rose-300"
                      >
                        Stop
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Live event stream</h2>
              <p className="text-sm text-slate-400">{selected?.exe_path ?? 'Select a session'}</p>
            </div>
            <div className="flex items-center gap-2 text-xs text-slate-400">
              {KINDS.map((kind) => (
                <button
                  key={kind}
                  onClick={() => toggleKind(kind)}
                  className={`rounded-full border px-2 py-1 transition ${kindFilter.has(kind) ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-200' : 'border-slate-700 bg-slate-950 text-slate-500'}`}
                >
                  {kind} <span className="ml-1 text-slate-500">{eventCounts[kind] ?? 0}</span>
                </button>
              ))}
              <label className="ml-2 flex items-center gap-1">
                <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />
                follow
              </label>
            </div>
          </div>

          <input
            className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-500"
            placeholder="filter by path, target, operation, or any detail"
            value={eventQuery}
            onChange={(event) => setEventQuery(event.target.value)}
          />

          <div className="overflow-hidden rounded-2xl border border-slate-800">
            <div ref={tableRef} className="max-h-[68vh] overflow-auto">
              <table className="min-w-full text-left text-xs">
                <thead className="sticky top-0 bg-slate-950 text-slate-400">
                  <tr>
                    <th className="px-3 py-2">Time</th>
                    <th className="px-3 py-2">Kind</th>
                    <th className="px-3 py-2">Op</th>
                    <th className="px-3 py-2">PID</th>
                    <th className="px-3 py-2">Target / Path</th>
                    <th className="px-3 py-2">Details</th>
                  </tr>
                </thead>
                <tbody className="font-mono">
                  {visibleEvents.map((event) => (
                    <tr key={event.id} className="border-t border-slate-800 align-top">
                      <td className="whitespace-nowrap px-3 py-1.5 text-slate-500">
                        {new Date(event.timestamp).toLocaleTimeString()}
                      </td>
                      <td className="px-3 py-1.5">
                        <span className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${
                          event.kind === 'file' ? 'bg-cyan-500/10 text-cyan-300' :
                          event.kind === 'registry' ? 'bg-fuchsia-500/10 text-fuchsia-300' :
                          event.kind === 'process' ? 'bg-emerald-500/10 text-emerald-300' :
                          event.kind === 'network' ? 'bg-amber-500/10 text-amber-300' :
                          'bg-slate-500/10 text-slate-300'
                        }`}>{event.kind}</span>
                      </td>
                      <td className="px-3 py-1.5 text-slate-300">{event.operation ?? '-'}</td>
                      <td className="px-3 py-1.5 text-slate-500">{event.pid ?? '-'}</td>
                      <td className="break-all px-3 py-1.5 text-slate-200">
                        {event.path ?? event.target ?? '-'}
                      </td>
                      <td className="break-all px-3 py-1.5 text-slate-500">
                        {JSON.stringify(event.details ?? {})}
                      </td>
                    </tr>
                  ))}
                  {visibleEvents.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-3 py-6 text-center text-slate-500">
                        no events match the current filters
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>{visibleEvents.length} shown · {events.length} total (ring buffer)</span>
            <span>{selected ? `pid ${selected.pid}` : ''}</span>
          </div>
        </section>
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
