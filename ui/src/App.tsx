import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';
import type { ActivityEvent, Kind, Session } from './types';
import { KINDS } from './types';
import { useEventStream } from './hooks/useEventStream';
import { useEventQuery } from './hooks/useEventQuery';
import { useProcessList } from './hooks/useProcessList';
import { useToasts } from './hooks/useToasts';
import { AdminBanner, AdminWarning } from './components/AdminBanner';
import { ProcessPicker } from './components/ProcessPicker';
import { SessionList } from './components/SessionList';
import { EventTable } from './components/EventTable';
import { EventDetailDrawer } from './components/EventDetailDrawer';
import { TimeRangeFilter } from './components/TimeRangeFilter';
import type { TimeRange } from './components/TimeRangeFilter';

function rangeToWindow(range: TimeRange): { since?: string; until?: string } {
  const now = Date.now();
  if (range === 'live' || range === 'all') return {};
  let ms = 0;
  if (range === '30s') ms = 30 * 1000;
  else if (range === '5min') ms = 5 * 60 * 1000;
  else if (range === '1h') ms = 60 * 60 * 1000;
  return { since: new Date(now - ms).toISOString() };
}
import { ExportButtons } from './components/ExportButtons';
import { PauseResume } from './components/PauseResume';
import { ProviderToggle } from './components/ProviderToggle';
import { ProcessTreeView } from './components/ProcessTreeView';
import { RateSparkline } from './components/RateSparkline';
import { ToastStack } from './components/ToastStack';
import { LogsTab } from './components/LogsTab';

type TabId = 'events' | 'logs';

export function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSession, setSelectedSession] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<TabId>('events');
  const [kindFilter, setKindFilter] = useState<Set<Kind>>(new Set(KINDS));
  const [eventQuery, setEventQuery] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [timeRange, setTimeRange] = useState<TimeRange>('live');
  const [paused, setPaused] = useState(false);
  const [selectedEvent, setSelectedEvent] = useState<ActivityEvent | null>(null);
  const [showTree, setShowTree] = useState(false);

  const pauseBufferRef = useRef<ActivityEvent[]>([]);
  const [bufferedCount, setBufferedCount] = useState(0);

  const { toasts, push: pushToast, dismiss: dismissToast } = useToasts();
  const { processes, admin, error: processError } = useProcessList();

  // Stable session refresh ref so other callbacks (e.g. handleStreamError)
  // can call it without taking a dependency on the changing function identity.
  const refreshSessionsRef = useRef<() => Promise<void>>(async () => undefined);

  const handleStreamError = useCallback(
    (err: Event | string) => {
      const msg = typeof err === 'string' ? err : 'WebSocket error';
      pushToast({
        kind: 'error',
        message: `Stream disconnected (${msg})`,
        action: {
          label: 'Retry',
          run: () => {
            // Triggers a refresh of sessions; useEventStream re-subscribes when sessionId changes.
            refreshSessionsRef.current().catch(() => undefined);
          },
        },
        ttl: 6000,
      });
    },
    [pushToast],
  );

  const {
    events: liveEvents,
    connected,
    error: streamError,
    setEvents: setLiveEvents,
  } = useEventStream(timeRange === 'live' ? selectedSession : '', {
    onError: handleStreamError,
  });

  const queryWindow = useMemo(() => rangeToWindow(timeRange), [timeRange]);
  const queryParams = useMemo(
    () => ({
      since: queryWindow.since,
      until: queryWindow.until,
      q: eventQuery.trim() || undefined,
      limit: 5000,
    }),
    [queryWindow, eventQuery],
  );
  const {
    events: queriedEvents,
    loading: queryLoading,
    error: queryError,
    refetch: refetchQuery,
  } = useEventQuery(selectedSession, queryParams, timeRange !== 'live');

  // Pause buffering: when paused, intercept incoming live events into pauseBufferRef
  // and rewind the live event list so they're not yet visible. On resume, drain.
  useEffect(() => {
    if (timeRange !== 'live') {
      pauseBufferRef.current = [];
      setBufferedCount(0);
      return;
    }
    if (!paused) return;
    // While paused, watch liveEvents grow; siphon the tail off into the buffer.
    // We use a ref snapshot baseline of length at pause-start.
  }, [paused, timeRange]);

  // Track baseline length when pausing starts.
  const baselineLenRef = useRef<number>(0);
  useEffect(() => {
    if (paused) {
      baselineLenRef.current = liveEvents.length;
    } else {
      // On resume, drain any buffered events into the visible stream by clearing buffer.
      if (pauseBufferRef.current.length > 0) {
        pauseBufferRef.current = [];
        setBufferedCount(0);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paused]);

  // While paused, when liveEvents grows beyond baseline, siphon tail into buffer.
  useEffect(() => {
    if (!paused || timeRange !== 'live') return;
    if (liveEvents.length > baselineLenRef.current) {
      const newOnes = liveEvents.slice(baselineLenRef.current);
      pauseBufferRef.current = [...pauseBufferRef.current, ...newOnes];
      setBufferedCount(pauseBufferRef.current.length);
      // Trim back to baseline so the table doesn't show them yet.
      setLiveEvents(liveEvents.slice(0, baselineLenRef.current));
    }
  }, [liveEvents, paused, timeRange, setLiveEvents]);

  useEffect(() => {
    if (processError) setError(processError);
  }, [processError]);

  useEffect(() => {
    if (streamError) setError(streamError);
  }, [streamError]);

  useEffect(() => {
    if (queryError) setError(queryError);
  }, [queryError]);

  const selected = useMemo(
    () => sessions.find((session) => session.session_id === selectedSession),
    [sessions, selectedSession],
  );

  const refreshSessions = useCallback(async () => {
    const result = await api<{ items: Session[] }>('/api/sessions');
    setSessions(result.items);
    setSelectedSession((current) => {
      if (current) return current;
      return result.items.length > 0 ? result.items[0].session_id : current;
    });
  }, []);

  useEffect(() => {
    refreshSessionsRef.current = refreshSessions;
  }, [refreshSessions]);

  useEffect(() => {
    refreshSessions().catch((err) => setError(String(err)));
  }, [refreshSessions]);

  const startSession = useCallback(
    async (body: { pid?: number; exe_path?: string }) => {
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
        pushToast({ kind: 'success', message: `Session started for ${session.exe_path}` });
      } catch (err) {
        setError(String(err));
      } finally {
        setBusy(false);
      }
    },
    [pushToast],
  );

  const stopSession = useCallback(
    async (sessionId: string) => {
      try {
        await api(`/api/sessions/${sessionId}`, { method: 'DELETE' });
        await refreshSessions();
        pushToast({ kind: 'info', message: 'Session stopped' });
      } catch (err) {
        setError(String(err));
      }
    },
    [pushToast, refreshSessions],
  );

  const toggleKind = useCallback((kind: Kind) => {
    setKindFilter((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }, []);

  const sourceEvents = timeRange === 'live' ? liveEvents : queriedEvents;

  // Mirror sourceEvents into a ref so child components that don't actually need
  // a re-render on every event commit (e.g. RateSparkline) can sample lazily.
  const sourceEventsRef = useRef<ActivityEvent[]>(sourceEvents);
  useEffect(() => {
    sourceEventsRef.current = sourceEvents;
  }, [sourceEvents]);

  const visibleEvents = useMemo<ActivityEvent[]>(() => {
    const q = eventQuery.trim().toLowerCase();
    return sourceEvents.filter((event) => {
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
  }, [sourceEvents, kindFilter, eventQuery]);

  const eventCounts = useMemo(() => {
    const counts: Record<string, number> = { file: 0, registry: 0, process: 0, network: 0 };
    for (const e of sourceEvents) counts[e.kind] = (counts[e.kind] ?? 0) + 1;
    return counts;
  }, [sourceEvents]);

  const exportFilters = useMemo(() => {
    const f: Record<string, string> = {};
    if (queryWindow.since) f.since = queryWindow.since;
    if (queryWindow.until) f.until = queryWindow.until;
    if (eventQuery.trim()) f.q = eventQuery.trim();
    if (kindFilter.size === 1) f.kind = Array.from(kindFilter)[0];
    return f;
  }, [queryWindow, eventQuery, kindFilter]);

  // Stable handlers passed to memoized children — change only when their
  // genuine dependencies change, preserving React.memo shallow equality.
  const handleSelectEvent = useCallback((event: ActivityEvent) => {
    setSelectedEvent(event);
  }, []);

  const handleCloseDrawer = useCallback(() => {
    setSelectedEvent(null);
  }, []);

  const handleAutoScrollChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setAutoScroll(e.target.checked);
    },
    [],
  );

  const handleEventQueryChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setEventQuery(e.target.value);
    },
    [],
  );

  const dismissError = useCallback(() => setError(null), []);
  const toggleTree = useCallback(() => setShowTree((v) => !v), []);
  const showEventsTab = useCallback(() => setActiveTab('events'), []);
  const showLogsTab = useCallback(() => setActiveTab('logs'), []);

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
        <nav className="mt-3 flex items-center gap-2" role="tablist" aria-label="Main tabs">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'events'}
            onClick={showEventsTab}
            className={`rounded-lg border px-3 py-1 text-xs transition-colors ${
              activeTab === 'events'
                ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-200'
                : 'border-slate-700 bg-slate-950 text-slate-300 hover:border-cyan-500/40 hover:text-cyan-200'
            }`}
          >
            Events
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === 'logs'}
            onClick={showLogsTab}
            className={`rounded-lg border px-3 py-1 text-xs transition-colors ${
              activeTab === 'logs'
                ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-200'
                : 'border-slate-700 bg-slate-950 text-slate-300 hover:border-cyan-500/40 hover:text-cyan-200'
            }`}
          >
            Logs
          </button>
        </nav>
        {error && (
          <div className="mt-3 flex items-start justify-between gap-3 rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-sm text-rose-200">
            <span className="flex-1">{error}</span>
            <button
              onClick={dismissError}
              className="text-xs opacity-70 hover:opacity-100"
            >
              dismiss
            </button>
          </div>
        )}
      </header>

      {activeTab === 'events' && (
      <>
      {/* === EVENTS TAB BODY === */}
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
            <div className="min-w-0">
              <h2 className="text-lg font-semibold">Live event stream</h2>
              <p className="truncate text-sm text-slate-400">
                {selected?.exe_path ?? 'Select a session'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-xs text-slate-400">
                <input
                  type="checkbox"
                  checked={autoScroll}
                  onChange={handleAutoScrollChange}
                />
                follow
              </label>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <ProviderToggle enabled={kindFilter} toggle={toggleKind} counts={eventCounts} />
            <TimeRangeFilter value={timeRange} onChange={setTimeRange} />
            {timeRange === 'live' && (
              <PauseResume
                paused={paused}
                setPaused={setPaused}
                bufferedCount={bufferedCount}
              />
            )}
            <ExportButtons
              sessionId={selectedSession || undefined}
              filters={exportFilters}
              onToast={pushToast}
            />
            {timeRange !== 'live' && (
              <button
                onClick={refetchQuery}
                disabled={queryLoading}
                className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-1 text-xs text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200 disabled:opacity-50"
              >
                {queryLoading ? 'Loading…' : 'Refresh'}
              </button>
            )}
          </div>

          <input
            className="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-cyan-500"
            placeholder="filter by path, target, operation, or any detail"
            value={eventQuery}
            onChange={handleEventQueryChange}
          />

          <RateSparkline eventsRef={sourceEventsRef} />

          <EventTable
            events={visibleEvents}
            autoScroll={autoScroll && !paused && timeRange === 'live'}
            onSelectEvent={handleSelectEvent}
            selectedId={selectedEvent?.id ?? null}
          />

          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>
              {visibleEvents.length} shown · {sourceEvents.length} total
              {timeRange === 'live' ? ' (ring buffer)' : ' (queried)'}
            </span>
            <span>{selected ? `pid ${selected.pid}` : ''}</span>
          </div>

          {selected && (
            <div className="rounded-2xl border border-slate-800 bg-slate-950">
              <button
                onClick={toggleTree}
                className="flex w-full items-center justify-between px-4 py-2 text-xs text-slate-400 hover:text-slate-200"
              >
                <span>Process tree (pid {selected.pid})</span>
                <span>{showTree ? '▾' : '▸'}</span>
              </button>
              {showTree && (
                <div className="border-t border-slate-800 p-2">
                  <ProcessTreeView events={sourceEvents} rootPid={selected.pid} />
                </div>
              )}
            </div>
          )}
        </section>
      </main>
      {/* === END EVENTS TAB BODY === */}
      </>
      )}

      {activeTab === 'logs' && <LogsTab />}

      <EventDetailDrawer event={selectedEvent} onClose={handleCloseDrawer} />
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
