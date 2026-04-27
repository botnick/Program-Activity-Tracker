import { memo, useEffect, useRef, useState } from 'react';
import type { ActivityEvent } from '../types';

type Props = {
  event: ActivityEvent | null;
  onClose: () => void;
};

function kindClass(kind: string): string {
  if (kind === 'file') return 'bg-cyan-500/10 text-cyan-300 border-cyan-500/40';
  if (kind === 'registry') return 'bg-fuchsia-500/10 text-fuchsia-300 border-fuchsia-500/40';
  if (kind === 'process') return 'bg-emerald-500/10 text-emerald-300 border-emerald-500/40';
  if (kind === 'network') return 'bg-amber-500/10 text-amber-300 border-amber-500/40';
  return 'bg-slate-500/10 text-slate-300 border-slate-500/40';
}

function parentDir(path: string): string {
  const m = path.replace(/\\/g, '/');
  const idx = m.lastIndexOf('/');
  return idx > 0 ? m.slice(0, idx) : m;
}

function EventDetailDrawerInner({ event, onClose }: Props) {
  const [copyHint, setCopyHint] = useState<string | null>(null);
  const [openHint, setOpenHint] = useState<string | null>(null);

  // Keep the last-seen event around so the drawer can finish its slide-out
  // animation with content still rendered, instead of unmounting on close.
  const lastEventRef = useRef<ActivityEvent | null>(event);
  useEffect(() => {
    if (event) lastEventRef.current = event;
  }, [event]);
  const display = event ?? lastEventRef.current;

  const isOpen = !!event;
  const state = isOpen ? 'open' : 'closed';

  const target = display?.path ?? display?.target ?? '';
  const isWindowsPath = !!display?.path && /^[A-Za-z]:/.test(display.path);
  const canOpenLocation = display?.kind === 'file' && isWindowsPath;

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopyHint('Copied');
      window.setTimeout(() => setCopyHint(null), 1500);
    } catch {
      setCopyHint('Copy blocked');
      window.setTimeout(() => setCopyHint(null), 2000);
    }
  };

  const openLocation = () => {
    if (!display?.path) return;
    const dir = parentDir(display.path);
    try {
      window.location.href = `file://${encodeURI(dir)}`;
      setOpenHint('Browser may block file:// links');
      window.setTimeout(() => setOpenHint(null), 3500);
    } catch {
      setOpenHint('Browser blocked file:// — copy and open manually');
      window.setTimeout(() => setOpenHint(null), 3500);
    }
  };

  return (
    <>
      <div
        onClick={onClose}
        data-state={state}
        className="fixed inset-0 z-30 bg-slate-950/60 backdrop-blur-sm transition-opacity duration-200 data-[state=closed]:pointer-events-none data-[state=closed]:opacity-0 data-[state=open]:opacity-100"
        aria-hidden="true"
      />
      <aside
        data-state={state}
        className="fixed right-0 top-0 z-40 flex h-full w-full max-w-md flex-col border-l border-slate-800 bg-slate-950 shadow-2xl transition-transform duration-200 ease-out data-[state=closed]:pointer-events-none data-[state=closed]:translate-x-full data-[state=open]:translate-x-0"
        role="dialog"
        aria-hidden={!isOpen}
        aria-label="Event details"
      >
        {display ? (
          <>
            <header className="flex items-start justify-between gap-2 border-b border-slate-800 px-4 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded border px-1.5 py-0.5 text-[10px] uppercase ${kindClass(display.kind)}`}
                  >
                    {display.kind}
                  </span>
                  <span className="text-sm font-medium text-slate-100">
                    {display.operation ?? '-'}
                  </span>
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {new Date(display.timestamp).toLocaleString()}
                </div>
              </div>
              <button
                onClick={onClose}
                className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-rose-500/60 hover:text-rose-200"
              >
                Close
              </button>
            </header>

            <div className="flex-1 space-y-4 overflow-auto px-4 py-4 text-sm">
              <section>
                <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">
                  Path / Target
                </div>
                <div className="flex items-start gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                  <code className="flex-1 break-all font-mono text-xs text-slate-100">
                    {target || '-'}
                  </code>
                  {target && (
                    <button
                      onClick={() => copy(target)}
                      className="shrink-0 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200"
                    >
                      {copyHint ?? 'Copy'}
                    </button>
                  )}
                </div>
                {canOpenLocation && (
                  <div className="mt-2">
                    <button
                      onClick={openLocation}
                      title="Browsers often block file:// navigation. If nothing opens, copy the path and paste into Explorer."
                      className="rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-slate-300 hover:border-emerald-500/60 hover:text-emerald-200"
                    >
                      Open file location
                    </button>
                    {openHint && (
                      <div className="mt-1 text-[11px] text-amber-300">{openHint}</div>
                    )}
                  </div>
                )}
              </section>

              <section className="grid grid-cols-2 gap-2">
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                  <div className="text-xs uppercase tracking-wide text-slate-500">PID</div>
                  <div className="font-mono text-sm text-slate-100">{display.pid ?? '-'}</div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
                  <div className="text-xs uppercase tracking-wide text-slate-500">PPID</div>
                  <div className="font-mono text-sm text-slate-100">{display.ppid ?? '-'}</div>
                </div>
              </section>

              <section>
                <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">Details</div>
                <pre className="overflow-auto rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs text-slate-200">
                  {JSON.stringify(display.details ?? {}, null, 2)}
                </pre>
              </section>

              <section>
                <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">IDs</div>
                <div className="space-y-1 rounded-xl border border-slate-800 bg-slate-900/60 p-3 font-mono text-[11px] text-slate-400">
                  <div>
                    <span className="text-slate-500">event:</span> {display.id}
                  </div>
                  <div>
                    <span className="text-slate-500">session:</span> {display.session_id}
                  </div>
                </div>
              </section>
            </div>
          </>
        ) : (
          <div className="flex-1" aria-hidden="true" />
        )}
      </aside>
    </>
  );
}

export const EventDetailDrawer = memo(EventDetailDrawerInner);
