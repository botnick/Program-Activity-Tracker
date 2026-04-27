import type { Session } from '../types';
import { captureBadge } from '../types';

type Props = {
  sessions: Session[];
  selected: string;
  onSelect: (sessionId: string) => void;
  onStop: (sessionId: string) => void;
};

export function SessionList({ sessions, selected, onSelect, onStop }: Props) {
  return (
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
          const isActive = session.session_id === selected;
          return (
            <div
              key={session.session_id}
              className={`rounded-xl border px-3 py-2 text-sm ${
                isActive ? 'border-cyan-500 bg-cyan-500/10' : 'border-slate-800 bg-slate-950'
              }`}
            >
              <button
                onClick={() => onSelect(session.session_id)}
                className="block w-full text-left"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="truncate font-medium">{session.exe_path}</div>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wide ${badge.cls}`}
                  >
                    {badge.label}
                  </span>
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
                  onClick={() => onStop(session.session_id)}
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
  );
}
