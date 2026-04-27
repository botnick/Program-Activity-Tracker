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
  const [stream, setStream] = useState<string>('tracker');
  const [live, setLive] = useState<boolean>(true);
  const [search, setSearch] = useState<string>('');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);

  const { entries, streams, connected } = useLogStream(stream, live);

  const visible = useMemo<LogEntry[]>(() => {
    const q = search.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => {
      const blob =
        `${e.message ?? ''} ${e.logger ?? ''} ${e.level ?? ''} ${entryText(e)}`.toLowerCase();
      return blob.includes(q);
    });
  }, [entries, search]);

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
    <main className="grid gap-4 p-6">
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

        <div className="overflow-hidden rounded-2xl border border-slate-800">
          <div
            ref={parentRef}
            className="max-h-[68vh] overflow-auto"
            style={{ contain: 'strict' }}
          >
            <div className="sticky top-0 z-10 grid grid-cols-[110px_70px_180px_1fr] bg-slate-950 text-xs text-slate-400">
              <div className="px-3 py-2">Time</div>
              <div className="px-3 py-2">Level</div>
              <div className="px-3 py-2">Logger</div>
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
                      className="grid grid-cols-[110px_70px_180px_1fr] border-t border-slate-800 hover:bg-slate-800/40"
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
                      <div className="truncate px-3 py-1.5 text-slate-400">
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
