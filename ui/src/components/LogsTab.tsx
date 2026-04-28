import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useLogStream } from '../hooks/useLogStream';
import type { LogEntry, LogStreamInfo } from '../hooks/useLogStream';

const ROW_HEIGHT = 28;

const STREAM_LABELS: Record<string, string> = {
  tracker: 'Tracker',
  events: 'Events',
  requests: 'Requests',
  errors: 'Errors',
  native: 'Native',
};

// Short hint shown next to the stream picker so users know which log to read.
const STREAM_HINTS: Record<string, string> = {
  errors: 'WARN/ERROR only — start here when something looks wrong',
  tracker: 'every backend log line (mixed)',
  events: 'one entry per captured ETW event (very high volume)',
  requests: 'HTTP request access log + trace id + duration',
  native: 'stdout/stderr from the C++ tracker_capture.exe',
};

// Color hint for level chips. Matches names against substrings — any
// unknown level falls back to a neutral chip and is fully toggleable just
// like the known ones. The displayed level list is discovered from the
// incoming entries; nothing about *which* levels exist is hardcoded.
function levelChipClass(name: string): string {
  const n = name.toUpperCase();
  if (n.includes('ERROR') || n === 'CRITICAL' || n === 'FATAL') {
    return 'border-rose-500/60 bg-rose-500/10 text-rose-200';
  }
  if (n.startsWith('WARN')) {
    return 'border-amber-500/60 bg-amber-500/10 text-amber-200';
  }
  if (n === 'INFO') return 'border-cyan-500/60 bg-cyan-500/10 text-cyan-200';
  if (n === 'DEBUG' || n === 'TRACE') {
    return 'border-slate-500/60 bg-slate-500/10 text-slate-200';
  }
  return 'border-slate-500/60 bg-slate-500/10 text-slate-200';
}

function levelClass(level: string | undefined): string {
  const lv = (level ?? '').toUpperCase();
  if (lv === 'ERROR' || lv === 'CRITICAL' || lv === 'FATAL')
    return 'bg-rose-500/10 text-rose-300';
  if (lv === 'WARNING' || lv === 'WARN') return 'bg-amber-500/10 text-amber-300';
  if (lv === 'INFO') return 'bg-cyan-500/10 text-cyan-300';
  if (lv === 'DEBUG') return 'bg-slate-500/10 text-slate-300';
  return 'bg-slate-500/10 text-slate-400';
}

function formatTs(ts: string | undefined): string {
  if (!ts) return '-';
  try {
    const d = new Date(ts);
    if (Number.isNaN(d.getTime())) return ts.slice(0, 19);
    return d.toLocaleTimeString();
  } catch {
    return ts.slice(0, 19);
  }
}

function entryText(entry: LogEntry): string {
  // Build a single searchable / display blob from JSON entry fields.
  const parts: string[] = [];
  if (entry.message !== undefined && entry.message !== null) {
    parts.push(String(entry.message));
  }
  for (const [k, v] of Object.entries(entry)) {
    if (k === 'message' || k === 'ts' || k === 'level' || k === 'logger' || k === 'raw')
      continue;
    if (v === null || v === undefined) continue;
    if (typeof v === 'object') {
      try {
        parts.push(`${k}=${JSON.stringify(v)}`);
      } catch {
        // skip non-serializable
      }
    } else {
      parts.push(`${k}=${String(v)}`);
    }
  }
  return parts.join(' ');
}

function humanSize(bytes: number): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function LogsTabInner() {
  // Default to `errors` so the first impression is "the things you care
  // about" — `tracker` is the everything-mixed firehose.
  const [stream, setStream] = useState<string>('errors');
  const [live, setLive] = useState<boolean>(true);
  const [search, setSearch] = useState<string>('');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  // Set of HIDDEN level names. Default empty = show every discovered level.
  // The level list itself comes from the incoming entries, so a custom
  // CRITICAL/NOTICE/etc. shows up as a chip just like INFO does — never
  // hardcoded into the source.
  const [hiddenLevels, setHiddenLevels] = useState<Set<string>>(() => new Set());
  // Set of logger names the user has HIDDEN. Default empty = show all.
  // Discovered dynamically from the entries themselves — never hardcoded.
  const [hiddenLoggers, setHiddenLoggers] = useState<Set<string>>(() => new Set());
  const [showLoggerPanel, setShowLoggerPanel] = useState(false);

  const { entries, streams, connected } = useLogStream(stream, live);

  const toggleLevel = useCallback((level: string) => {
    setHiddenLevels((current) => {
      const next = new Set(current);
      if (next.has(level)) next.delete(level);
      else next.add(level);
      return next;
    });
  }, []);

  const showAllLevels = useCallback(() => {
    setHiddenLevels(new Set());
  }, []);

  // Discovered levels + counts from the full buffer. Sorted by count desc so
  // the dominant levels surface first. Nothing about *which* levels exist is
  // hardcoded; CRITICAL / NOTICE / TRACE / a custom level all appear as chips
  // automatically.
  const levelEntries = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of entries) {
      const lv = ((e.level ?? '').toString().toUpperCase()) || '(none)';
      counts.set(lv, (counts.get(lv) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [entries]);

  // Logger names + counts — discovered dynamically from the entries so the
  // user gets a one-click toggle for the noisy modules without us hardcoding
  // module names.
  const loggerCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const e of entries) {
      const name = (e.logger ?? '(unknown)') || '(unknown)';
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [entries]);

  const toggleLogger = useCallback((name: string) => {
    setHiddenLoggers((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const showAllLoggers = useCallback(() => setHiddenLoggers(new Set()), []);
  const hideAllLoggers = useCallback(() => {
    setHiddenLoggers(new Set(loggerCounts.map(([name]) => name)));
  }, [loggerCounts]);
  const toggleLoggerPanel = useCallback(() => {
    setShowLoggerPanel((v) => !v);
  }, []);

  const visible = useMemo<LogEntry[]>(() => {
    const q = search.trim().toLowerCase();
    return entries.filter((e) => {
      const lv = ((e.level ?? '').toString().toUpperCase()) || '(none)';
      if (hiddenLevels.has(lv)) return false;
      const loggerName = (e.logger ?? '(unknown)') || '(unknown)';
      if (hiddenLoggers.has(loggerName)) return false;
      if (!q) return true;
      const blob =
        `${e.message ?? ''} ${e.logger ?? ''} ${e.level ?? ''} ${entryText(e)}`.toLowerCase();
      return blob.includes(q);
    });
  }, [entries, search, hiddenLevels, hiddenLoggers]);

  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: visible.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 16,
    getItemKey: (index) => index,
  });

  // rAF-throttled auto-scroll. Same pattern as EventTable.
  const scrollFrameRef = useRef<number | null>(null);
  useEffect(() => {
    if (!autoScroll) return;
    if (scrollFrameRef.current !== null) return;
    scrollFrameRef.current = requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const el = parentRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
    return () => {
      if (scrollFrameRef.current !== null) {
        cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
  }, [visible.length, autoScroll]);

  const handleStreamChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      setStream(e.target.value);
    },
    [],
  );

  const handleLiveChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setLive(e.target.checked);
    },
    [],
  );

  const handleAutoScrollChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setAutoScroll(e.target.checked);
    },
    [],
  );

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setSearch(e.target.value);
    },
    [],
  );

  const items = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();

  const currentStreamInfo: LogStreamInfo | undefined = streams.find(
    (s) => s.name === stream,
  );

  return (
    <main className="grid gap-4 p-4 md:p-6">
      <section className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold">Log streams</h2>
            <p className="truncate text-sm text-slate-400">
              {currentStreamInfo
                ? `${currentStreamInfo.path} (${humanSize(currentStreamInfo.size)})`
                : 'Select a stream'}
            </p>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <span
              className={`inline-flex items-center gap-1 rounded px-2 py-0.5 ${
                live && connected
                  ? 'bg-emerald-500/10 text-emerald-300'
                  : live
                    ? 'bg-amber-500/10 text-amber-300'
                    : 'bg-slate-500/10 text-slate-400'
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${
                  live && connected
                    ? 'bg-emerald-400'
                    : live
                      ? 'bg-amber-400'
                      : 'bg-slate-500'
                }`}
              />
              {live ? (connected ? 'tailing' : 'connecting…') : 'snapshot'}
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs text-slate-400">
            stream
            <select
              value={stream}
              onChange={handleStreamChange}
              className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200 outline-none focus:border-cyan-500"
            >
              {(streams.length > 0
                ? streams
                : Object.keys(STREAM_LABELS).map((name) => ({
                    name,
                    path: '',
                    size: 0,
                    exists: false,
                  }))
              ).map((s) => (
                <option key={s.name} value={s.name}>
                  {STREAM_LABELS[s.name] ?? s.name}
                  {s.exists ? ` · ${humanSize(s.size)}` : ''}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-1 text-xs text-slate-400">
            <input type="checkbox" checked={live} onChange={handleLiveChange} />
            live tail
          </label>

          <label className="flex items-center gap-1 text-xs text-slate-400">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={handleAutoScrollChange}
            />
            follow
          </label>

          <input
            value={search}
            onChange={handleSearchChange}
            placeholder="filter messages, levels, logger names"
            className="ml-auto w-72 rounded-xl border border-slate-700 bg-slate-950 px-3 py-1 text-xs outline-none focus:border-cyan-500"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-slate-500">levels</span>
          {levelEntries.length === 0 ? (
            <span className="text-slate-600">
              none discovered yet — chips appear as the stream emits entries
            </span>
          ) : (
            levelEntries.map(([lv, count]) => {
              const active = !hiddenLevels.has(lv);
              return (
                <button
                  key={lv}
                  type="button"
                  onClick={() => toggleLevel(lv)}
                  className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide transition ${
                    active ? levelChipClass(lv) : 'border-slate-700 bg-slate-950 text-slate-500'
                  }`}
                >
                  {lv} <span className="ml-1 text-slate-500">{count}</span>
                </button>
              );
            })
          )}
          <button
            type="button"
            onClick={showAllLevels}
            className="rounded-full border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-400 hover:border-cyan-500/60 hover:text-cyan-200"
          >
            All
          </button>
          <span className="ml-2 truncate text-slate-500">
            {STREAM_HINTS[stream] ?? ''}
          </span>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-950">
          <button
            type="button"
            onClick={toggleLoggerPanel}
            className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs text-slate-300 hover:bg-slate-900"
          >
            <div className="flex items-center gap-2">
              <span>{showLoggerPanel ? '▾' : '▸'}</span>
              <span className="font-medium">Loggers</span>
              <span className="text-slate-500">
                {loggerCounts.length} discovered
                {hiddenLoggers.size > 0 ? ` · ${hiddenLoggers.size} hidden` : ''}
              </span>
            </div>
            <div
              className="flex items-center gap-1"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                onClick={showAllLoggers}
                className="rounded-md border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200"
              >
                Show all
              </button>
              <button
                type="button"
                onClick={hideAllLoggers}
                className="rounded-md border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300 hover:border-rose-500/60 hover:text-rose-200"
              >
                Hide all
              </button>
            </div>
          </button>
          {showLoggerPanel && (
            <div className="grid gap-1 border-t border-slate-800 p-2 sm:grid-cols-2 lg:grid-cols-3">
              {loggerCounts.length === 0 ? (
                <div className="col-span-full px-2 py-1 text-[11px] text-slate-600">
                  no entries yet — loggers will appear as the stream emits lines
                </div>
              ) : (
                loggerCounts.map(([name, count]) => {
                  const isHidden = hiddenLoggers.has(name);
                  return (
                    <label
                      key={name}
                      className={`flex cursor-pointer items-center justify-between gap-2 rounded px-1.5 py-1 text-[11px] hover:bg-slate-900 ${isHidden ? 'opacity-50' : ''}`}
                    >
                      <span className="flex min-w-0 items-center gap-1.5">
                        <input
                          type="checkbox"
                          checked={!isHidden}
                          onChange={() => toggleLogger(name)}
                          className="h-3 w-3 accent-cyan-500"
                        />
                        <span className="truncate font-mono text-slate-300">
                          {name}
                        </span>
                      </span>
                      <span className="font-mono text-slate-600">{count}</span>
                    </label>
                  );
                })
              )}
            </div>
          )}
        </div>

        <div className="overflow-hidden rounded-2xl border border-slate-800">
          <div
            ref={parentRef}
            className="overflow-auto"
            // contain:strict + no explicit height collapses the container to
            // 0px regardless of how many rows the virtualizer reports. Use
            // `content` and pin a min/max height so the panel is always visible.
            style={{ contain: 'content', minHeight: '50vh', maxHeight: '68vh' }}
          >
            <div className="sticky top-0 z-10 grid grid-cols-[80px_60px_1fr] sm:grid-cols-[100px_70px_140px_1fr] md:grid-cols-[110px_70px_180px_1fr] bg-slate-950 text-xs text-slate-400">
              <div className="px-3 py-2">Time</div>
              <div className="px-3 py-2">Level</div>
              <div className="hidden px-3 py-2 sm:block">Logger</div>
              <div className="px-3 py-2">Message</div>
            </div>
            {visible.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-slate-500">
                {entries.length === 0
                  ? `no entries for ${STREAM_LABELS[stream] ?? stream} yet`
                  : 'no entries match the current filter'}
              </div>
            ) : (
              <div
                style={{ height: totalSize, position: 'relative' }}
                className="font-mono text-xs"
              >
                {items.map((vi) => {
                  const entry = visible[vi.index];
                  if (!entry) return null;
                  const isRaw = entry.raw === true;
                  return (
                    <div
                      key={vi.key}
                      className="grid grid-cols-[80px_60px_1fr] sm:grid-cols-[100px_70px_140px_1fr] md:grid-cols-[110px_70px_180px_1fr] border-t border-slate-800 hover:bg-slate-800/40"
                      style={{
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        right: 0,
                        transform: `translateY(${vi.start}px)`,
                        height: vi.size,
                      }}
                    >
                      <div className="whitespace-nowrap px-3 py-1.5 text-slate-500">
                        {formatTs(entry.ts)}
                      </div>
                      <div className="px-3 py-1.5">
                        <span
                          className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${levelClass(entry.level)}`}
                        >
                          {isRaw ? 'raw' : (entry.level ?? '-')}
                        </span>
                      </div>
                      <div className="hidden truncate px-3 py-1.5 text-slate-400 sm:block">
                        {entry.logger ?? '-'}
                      </div>
                      <div className="truncate px-3 py-1.5 text-slate-200">
                        <span className="text-slate-200">
                          {entry.message ?? ''}
                        </span>
                        <span className="ml-2 text-slate-500">
                          {entryText(entry).replace(
                            String(entry.message ?? ''),
                            '',
                          )}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between text-xs text-slate-500">
          <span>
            {visible.length} shown · {entries.length} buffered
          </span>
          <span>
            {currentStreamInfo?.exists === false
              ? 'file not yet created'
              : `stream: ${stream}`}
          </span>
        </div>
      </section>
    </main>
  );
}

export const LogsTab = memo(LogsTabInner);
