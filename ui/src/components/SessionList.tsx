import { memo, useMemo, useRef, useState } from 'react';
import type { Session } from '../types';
import { captureBadge } from '../types';
import { ProcessIcon } from './ProcessIcon';

type Props = {
  sessions: Session[];
  selected: string;
  onSelect: (sessionId: string) => void;
  onStop: (sessionId: string) => void;
  onRestart?: (session: Session) => void;
  onPurge?: (sessionId: string) => void;
  onCleanupAll?: () => void;
};

const ACTIVE_CAPTURES = new Set(['live', 'initializing', 'tracking']);

function SessionRow({
  session,
  isActive,
  onSelect,
  onStop,
  onRestart,
  onPurge,
}: {
  session: Session;
  isActive: boolean;
  onSelect: (id: string) => void;
  onStop: (id: string) => void;
  onRestart?: (s: Session) => void;
  onPurge?: (id: string) => void;
}) {
  const badge = captureBadge(session.capture);
  const isLive = session.capture === 'live';
  const canRestart =
    !!onRestart &&
    (session.capture === 'interrupted' ||
      session.capture === 'stopped' ||
      session.capture === 'needs_admin' ||
      session.capture === 'failed');
  const canPurge = !!onPurge && !isLive;

  // Atomic in-flight guard: useRef catches double-clicks within the same
  // React tick (setState is async — two clicks before the first
  // setBusyAction commits would both pass the `if (busy)` check).
  const inFlightRef = useRef<null | 'stop' | 'purge' | 'restart'>(null);
  const [busyAction, setBusyAction] = useState<null | 'stop' | 'purge' | 'restart'>(null);
  const guard = (action: 'stop' | 'purge' | 'restart', fn: () => void) => {
    if (inFlightRef.current) return;
    inFlightRef.current = action;
    setBusyAction(action);
    try {
      fn();
    } finally {
      window.setTimeout(() => {
        inFlightRef.current = null;
        setBusyAction(null);
      }, 600);
    }
  };

  return (
    <div
      className={`rounded-xl border px-3 py-2 text-sm ${
        isActive ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-800 bg-slate-950'
      }`}
    >
      <button
        type="button"
        onClick={() => onSelect(session.session_id)}
        className="block w-full min-w-0 text-left"
      >
        <div className="flex items-center gap-2">
          <ProcessIcon exe={session.exe_path} size={20} className="shrink-0" />
          <span
            className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${badge.cls}`}
          >
            {badge.label}
          </span>
          <span className="ml-auto truncate text-xs text-slate-400">
            pid {session.pid}
          </span>
        </div>
        <div className="mt-1 flex items-center justify-between text-[11px] text-slate-500">
          <span>{new Date(session.created_at).toLocaleString()}</span>
          <span className="font-mono text-slate-600">
            {session.session_id.slice(0, 8)}
          </span>
        </div>
        {session.capture_error && (
          <div className="mt-1 text-xs text-amber-400">{session.capture_error}</div>
        )}
      </button>

      {/* Action row — full-width buttons under the row body so the user can
          never confuse "delete" with "start new session". A live session
          shows only Stop; an inactive session shows Restart + Delete side
          by side. */}
      {isLive && (
        <button
          type="button"
          disabled={busyAction === 'stop'}
          onClick={() => guard('stop', () => onStop(session.session_id))}
          className="mt-3 w-full rounded-md border border-rose-500/40 bg-rose-500/5 px-2 py-1.5 text-xs font-medium text-rose-200 transition-colors hover:border-rose-500/70 hover:bg-rose-500/15 disabled:opacity-40"
        >
          {busyAction === 'stop' ? 'Stopping…' : 'Stop'}
        </button>
      )}
      {(canRestart || canPurge) && !isLive && (
        <div className="mt-3 grid grid-cols-2 gap-2">
          {canRestart ? (
            <button
              type="button"
              disabled={busyAction === 'restart'}
              onClick={() => guard('restart', () => onRestart!(session))}
              className="rounded-md border border-cyan-500/30 bg-cyan-500/5 px-2 py-1.5 text-xs font-medium text-cyan-200 transition-colors hover:border-cyan-500/60 hover:bg-cyan-500/15 disabled:opacity-40"
              title="Start a new session against the same exe"
            >
              {busyAction === 'restart' ? 'Starting…' : 'Start again'}
            </button>
          ) : (
            <span />
          )}
          {canPurge && (
            <button
              type="button"
              disabled={busyAction === 'purge'}
              onClick={(e) => {
                e.stopPropagation();
                e.preventDefault();
                guard('purge', () => onPurge!(session.session_id));
              }}
              className={`flex items-center justify-center gap-1.5 rounded-md border px-2 py-1.5 text-xs font-medium transition-colors disabled:opacity-40 ${
                canRestart ? '' : 'col-span-2'
              } border-rose-500/40 bg-rose-500/5 text-rose-200 hover:border-rose-500/70 hover:bg-rose-500/15`}
              title="Delete this session and all its events"
            >
              <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M3 6h18" />
                <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                <path d="M19 6 17.5 20a2 2 0 0 1-2 1.8h-7a2 2 0 0 1-2-1.8L5 6" />
              </svg>
              {busyAction === 'purge' ? 'Deleting…' : 'Delete'}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function SessionListInner({
  sessions,
  selected,
  onSelect,
  onStop,
  onRestart,
  onPurge,
  onCleanupAll,
}: Props) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  // Group sessions by exe path. Within each group, sort by created_at desc so
  // the most recent attempt is shown as the "head" and older runs collapse
  // under a chevron — exactly what the user asked for: auto-group, no dupes.
  const groups = useMemo(() => {
    const map = new Map<string, Session[]>();
    for (const s of sessions) {
      const key = s.exe_path || `(pid ${s.pid})`;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(s);
    }
    const out: Array<{ exePath: string; head: Session; rest: Session[]; live: number }> = [];
    for (const [exePath, list] of map.entries()) {
      list.sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
      const head = list[0];
      const rest = list.slice(1);
      const live = list.filter((s) => ACTIVE_CAPTURES.has(s.capture)).length;
      out.push({ exePath, head, rest, live });
    }
    // Sort groups: live first (>0 active), then by most-recent head.
    out.sort((a, b) => {
      if (a.live !== b.live) return b.live - a.live;
      return (
        new Date(b.head.created_at).getTime() - new Date(a.head.created_at).getTime()
      );
    });
    return out;
  }, [sessions]);

  const inactiveCount = useMemo(
    () => sessions.filter((s) => !ACTIVE_CAPTURES.has(s.capture)).length,
    [sessions],
  );

  const toggleGroup = (exePath: string) => {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(exePath)) next.delete(exePath);
      else next.add(exePath);
      return next;
    });
  };

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2 text-sm text-slate-400">
        <div className="flex items-center gap-2">
          <span>Sessions</span>
          <span className="text-xs text-slate-500">
            {sessions.length} total · {groups.length} exe{groups.length === 1 ? '' : 's'}
          </span>
        </div>
        {onCleanupAll && inactiveCount > 0 && (
          <button
            type="button"
            onClick={onCleanupAll}
            title="Delete all stopped / interrupted / needs-admin / failed sessions"
            className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-[10px] uppercase tracking-wide text-slate-400 hover:border-rose-500/60 hover:text-rose-300"
          >
            Clear {inactiveCount} stopped
          </button>
        )}
      </div>
      <div className="space-y-2">
        {groups.length === 0 && (
          <div className="rounded-xl border border-slate-800 bg-slate-950 px-3 py-6 text-center text-xs text-slate-500">
            No sessions yet
          </div>
        )}
        {groups.map(({ exePath, head, rest, live }) => {
          const isOpen = expanded.has(exePath);
          const showRest = isOpen && rest.length > 0;
          return (
            <div key={exePath} className="space-y-1">
              <div className="flex items-center gap-2 px-1 text-[11px] text-slate-500">
                <span className="truncate font-medium" title={exePath}>
                  {exePath}
                </span>
                {live > 0 && (
                  <span className="shrink-0 rounded-full bg-emerald-500/15 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-emerald-300">
                    {live} live
                  </span>
                )}
                {rest.length > 0 && (
                  <button
                    type="button"
                    onClick={() => toggleGroup(exePath)}
                    className="ml-auto rounded text-[10px] uppercase tracking-wide text-slate-500 hover:text-slate-300"
                  >
                    {isOpen ? `Hide ${rest.length} older` : `+${rest.length} older`}
                  </button>
                )}
              </div>
              <SessionRow
                session={head}
                isActive={head.session_id === selected}
                onSelect={onSelect}
                onStop={onStop}
                onRestart={onRestart}
                onPurge={onPurge}
              />
              {showRest &&
                rest.map((s) => (
                  <div key={s.session_id} className="ml-3 border-l border-slate-800 pl-2">
                    <SessionRow
                      session={s}
                      isActive={s.session_id === selected}
                      onSelect={onSelect}
                      onStop={onStop}
                      onRestart={onRestart}
                      onPurge={onPurge}
                    />
                  </div>
                ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export const SessionList = memo(SessionListInner);
