import { memo, useMemo, useState } from 'react';
import type { ProcessInfo } from '../types';
import { ProcessIcon } from './ProcessIcon';

type Props = {
  processes: ProcessInfo[];
  busy: boolean;
  onStart: (body: { pid?: number; exe_path?: string }) => void;
};

function ProcessPickerInner({ processes, busy, onStart }: Props) {
  const [processQuery, setProcessQuery] = useState('');
  const [manualPath, setManualPath] = useState('');

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

  return (
    <>
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
              onClick={() => onStart({ pid: proc.pid })}
              className="flex w-full items-start justify-between gap-2 border-b border-slate-800 px-3 py-2 text-left text-xs last:border-0 hover:bg-slate-800/60 disabled:opacity-60"
            >
              <ProcessIcon exe={proc.exe} size={28} className="mr-2 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium text-slate-100">
                  {proc.name ?? '(unknown)'}
                </div>
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
            onClick={() => onStart({ exe_path: manualPath })}
            className="rounded-xl bg-cyan-500 px-4 py-2 text-sm font-medium text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
          >
            Track
          </button>
        </div>
      </div>
    </>
  );
}

export const ProcessPicker = memo(ProcessPickerInner);
