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
import { McpHowToTab } from './components/McpHowToTab';
import { OperationsFilter } from './components/OperationsFilter';

type TabId = 'events' | 'logs' | 'mcp';

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
  // Operations the user has hidden. Default empty = show everything; the
  // OperationsFilter panel auto-discovers ops from the incoming stream so the
  // user can pick what to hide and save it as a preset (persisted to
  // localStorage). No domain knowledge is hardcoded here.
  const [hiddenOps, setHiddenOps] = useState<Set<string>>(() => new Set());

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
  // Stable, sorted allow-list derived from hiddenOps so paramsKey memo in
  // useEventQuery doesn't churn from set-iteration ordering.
  const allowedOps = useMemo<string[] | undefined>(() => {
    if (hiddenOps.size === 0) return undefined;
    // The empty allow-list is meaningless to the backend; we only switch to
    // server-side filtering when at least one allowed op is known. Otherwise
    // the client-side filter in `visibleEvents` handles it.
    return undefined;
  }, [hiddenOps]);
  const queryParams = useMemo(
    () => ({
      since: queryWindow.since,
      until: queryWindow.until,
      q: eventQuery.trim() || undefined,
      operation: allowedOps,
      limit: 5000,
    }),
    [queryWindow, eventQuery, allowedOps],
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

  const restartSession = useCallback(
    (session: Session) => {
      // Re-run start_session with the same exe_path. Backend's _resolve_target
      // will look up the current pid for that exe; if the process isn't running
      // anymore, the call surfaces a clear 404 toast.
      startSession({ exe_path: session.exe_path });
    },
    [startSession],
  );

  const purgeSession = useCallback(
    async (sessionId: string) => {
      try {
        await api(`/api/sessions/${sessionId}?purge=true`, { method: 'DELETE' });
        // If we just deleted the selected session, drop the selection so the
        // event panel resets cleanly.
        setSelectedSession((current) => (current === sessionId ? '' : current));
        await refreshSessions();
        pushToast({ kind: 'info', message: 'Session deleted' });
      } catch (err) {
        setError(String(err));
      }
    },
    [pushToast, refreshSessions],
  );

  const cleanupSessions = useCallback(async () => {
    try {
      const result = await api<{ count: number; ids: string[] }>(
        '/api/sessions/cleanup',
        { method: 'POST' },
      );
      // If the active selection got swept, drop it.
      setSelectedSession((current) =>
        result.ids.includes(current) ? '' : current,
      );
      await refreshSessions();
      pushToast({
        kind: 'info',
        message: `Cleared ${result.count} stopped session${result.count === 1 ? '' : 's'}`,
      });
    } catch (err) {
      setError(String(err));
    }
  }, [pushToast, refreshSessions]);

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
      if (event.operation && hiddenOps.has(event.operation)) {
        return false;
      }
      if (!q) return true;
      const blob =
        `${event.path ?? ''} ${event.target ?? ''} ${event.operation ?? ''} ${JSON.stringify(event.details ?? {})}`.toLowerCase();
      return blob.includes(q);
    });
  }, [sourceEvents, kindFilter, eventQuery, hiddenOps]);

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
  const showMcpTab = useCallback(() => setActiveTab('mcp'), []);

  const tabs: { id: TabId; label: string; onClick: () => void }[] = [
    { id: 'events', label: 'Events', onClick: showEventsTab },
    { id: 'logs',   label: 'Logs',   onClick: showLogsTab },
    { id: 'mcp',    label: 'MCP How-To', onClick: showMcpTab },
  ];

  return (
    <div className="min-h-screen bg-base text-ink">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/80 backdrop-blur-md">
        <div className="mx-auto max-w-[1600px] px-4 md:px-8">
          <div className="flex flex-wrap items-center justify-between gap-4 py-3 md:py-4">
            <div className="flex items-center gap-3">
              <div
                className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-accent/30 to-kind-registry/20 ring-1 ring-line"
                aria-hidden
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5 text-accent-hover" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14l6 6M14 20l6-6" />
                </svg>
              </div>
              <div>
                <h1 className="text-base font-semibold tracking-tight md:text-lg">Activity Tracker</h1>
                <p className="hidden text-[12px] text-muted sm:block">
                  Real-time Windows process activity — file · registry · process · network
                </p>
              </div>
            </div>
            <AdminBanner admin={admin} connected={connected} />
          </div>
          <AdminWarning admin={admin} />
          <nav className="-mb-px flex items-center gap-1 overflow-x-auto" role="tablist" aria-label="Main tabs">
            {tabs.map((t) => {
              const isActive = activeTab === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  onClick={t.onClick}
                  className={`relative px-4 py-2.5 text-[13px] font-medium transition-colors ${
                    isActive ? 'text-accent-hover' : 'text-muted hover:text-ink'
                  }`}
                >
                  {t.label}
                  {isActive && (
                    <span
                      className="absolute inset-x-3 bottom-0 h-[2px] rounded-full bg-accent"
                      aria-hidden
                    />
                  )}
                </button>
              );
            })}
          </nav>
        </div>
      </header>

      {error && (
        <div className="mx-auto max-w-[1600px] px-4 pt-3 md:px-8">
          <div className="flex items-start justify-between gap-3 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger fade-in">
            <span className="flex-1">{error}</span>
            <button
              onClick={dismissError}
              className="text-xs text-danger/80 hover:text-danger"
            >
              dismiss
            </button>
          </div>
        </div>
      )}

      {activeTab === 'events' && (
      <>
      {/* === EVENTS TAB BODY === */}
      <main className="mx-auto grid max-w-[1600px] gap-4 px-4 py-4 md:gap-5 md:px-8 md:py-6 xl:grid-cols-[minmax(340px,420px)_1fr]">
        <section className="min-w-0 space-y-4 rounded-lg border border-line bg-surface/70 p-3 sm:p-4">
          <ProcessPicker processes={processes} busy={busy} onStart={startSession} />
          <SessionList
            sessions={sessions}
            selected={selectedSession}
            onSelect={setSelectedSession}
            onStop={stopSession}
            onRestart={restartSession}
            onPurge={purgeSession}
            onCleanupAll={cleanupSessions}
          />
        </section>

        <section className="min-w-0 space-y-4 rounded-lg border border-line bg-surface/70 p-3 sm:p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0 flex-1">
              <h2 className="text-base font-semibold tracking-tight">Live event stream</h2>
              <p className="truncate text-[12px] text-muted">
                {selected?.exe_path ?? 'Select a session'}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <label className="flex items-center gap-1.5 text-[11px] text-muted">
                <input
                  type="checkbox"
                  checked={autoScroll}
                  onChange={handleAutoScrollChange}
                  className="accent-accent"
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
                className="btn text-xs"
              >
                {queryLoading ? 'Loading…' : 'Refresh'}
              </button>
            )}
          </div>

          <OperationsFilter
            events={sourceEvents}
            hidden={hiddenOps}
            setHidden={setHiddenOps}
            enabledKinds={kindFilter}
          />

          <div className="relative">
            <svg className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            <input
              className="w-full rounded-lg border border-line bg-base py-2 pl-9 pr-3 text-sm placeholder:text-faint outline-none transition-colors focus:border-accent focus:ring-2 focus:ring-accent/30"
              placeholder="Filter by path, target, operation, or detail…"
              value={eventQuery}
              onChange={handleEventQueryChange}
            />
          </div>

          <RateSparkline eventsRef={sourceEventsRef} />

          <EventTable
            events={visibleEvents}
            autoScroll={autoScroll && !paused && timeRange === 'live'}
            onSelectEvent={handleSelectEvent}
            selectedId={selectedEvent?.id ?? null}
          />

          <div className="flex items-center justify-between text-[11px] text-faint">
            <span>
              {visibleEvents.length.toLocaleString()} shown · {sourceEvents.length.toLocaleString()} total
              {timeRange === 'live' ? ' (ring buffer)' : ' (queried)'}
            </span>
            <span>{selected ? `pid ${selected.pid}` : ''}</span>
          </div>

          {selected && (
            <div className="rounded-lg border border-line bg-base">
              <button
                onClick={toggleTree}
                className="flex w-full items-center justify-between px-4 py-2 text-[12px] text-muted transition-colors hover:text-ink"
              >
                <span>Process tree (pid {selected.pid})</span>
                <span>{showTree ? '▾' : '▸'}</span>
              </button>
              {showTree && (
                <div className="border-t border-line p-2 fade-in">
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

      {activeTab === 'mcp' && <McpHowToTab />}

      <EventDetailDrawer event={selectedEvent} onClose={handleCloseDrawer} />
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
