import { useEffect, useMemo, useState } from 'react';
import { api } from './api';
import type { ActivityEvent, Kind, Session } from './types';
import { KINDS } from './types';
import { useEventStream } from './hooks/useEventStream';
import { useProcessList } from './hooks/useProcessList';
import { AdminBanner, AdminWarning } from './components/AdminBanner';
import { ProcessPicker } from './components/ProcessPicker';
import { SessionList } from './components/SessionList';
import { KindFilters } from './components/KindFilters';
import { EventTable } from './components/EventTable';

export function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSession, setSelectedSession] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [kindFilter, setKindFilter] = useState<Set<Kind>>(new Set(KINDS));
  const [eventQuery, setEventQuery] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);

  const { processes, admin, error: processError } = useProcessList();
  const { events, connected, error: streamError } = useEventStream(selectedSession);

  useEffect(() => {
    if (processError) setError(processError);
  }, [processError]);

  useEffect(() => {
    if (streamError) setError(streamError);
  }, [streamError]);

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

  useEffect(() => {
    refreshSessions().catch((err) => setError(String(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const startSession = async (body: { pid?: number; exe_path?: string }) => {
    setBusy(true);
    setError(null);
    try {
      const session = await api<Session>('/api/sessions', {
        method: 'POST',
        body: JSON.stringify(body),
      });
      setSessions((current) => [
        session,
        ...current.filter((s) => s.session_id !== session.session_id),
      ]);
      setSelectedSession(session.session_id);
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

  const visibleEvents = useMemo<ActivityEvent[]>(() => {
    const q = eventQuery.trim().toLowerCase();
    return events.filter((event) => {
      if (
        !kindFilter.has(event.kind as Kind) &&
        (KINDS as readonly string[]).includes(event.kind)
      ) {
        return false;
      }
      if (!q) return true;
      const blob =
        `${event.path ?? ''} ${event.target ?? ''} ${event.operation ?? ''} ${JSON.stringify(event.details ?? {})}`.toLowerCase();
      return blob.includes(q);
    });
  }, [events, kindFilter, eventQuery]);

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
          <AdminBanner admin={admin} connected={connected} />
        </div>
        <AdminWarning admin={admin} />
        {error && (
          <div className="mt-3 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
            {error}
          </div>
        )}
      </header>

      <main className="grid gap-4 p-6 lg:grid-cols-[420px_1fr]">
        <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
          <ProcessPicker processes={processes} busy={busy} onStart={startSession} />
          <SessionList
            sessions={sessions}
            selected={selectedSession}
            onSelect={setSelectedSession}
            onStop={stopSession}
          />
        </section>

        <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">Live event stream</h2>
              <p className="text-sm text-slate-400">{selected?.exe_path ?? 'Select a session'}</p>
            </div>
            <KindFilters
              kindFilter={kindFilter}
              toggle={toggleKind}
              counts={eventCounts}
              autoScroll={autoScroll}
              setAutoScroll={setAutoScroll}
            />
          </div>

          <input
            className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-500"
            placeholder="filter by path, target, operation, or any detail"
            value={eventQuery}
            onChange={(event) => setEventQuery(event.target.value)}
          />

          <EventTable events={visibleEvents} autoScroll={autoScroll} />

          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>
              {visibleEvents.length} shown · {events.length} total (ring buffer)
            </span>
            <span>{selected ? `pid ${selected.pid}` : ''}</span>
          </div>
        </section>
      </main>
    </div>
  );
}
