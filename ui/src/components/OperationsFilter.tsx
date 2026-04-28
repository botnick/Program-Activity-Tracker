import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type MouseEventHandler,
} from 'react';
import type { ActivityEvent, Kind } from '../types';
import { KINDS } from '../types';

type Props = {
  // Source events to derive the available operation set per kind. The set
  // grows dynamically as new events flow in — never hardcoded.
  events: ActivityEvent[];
  // Set of operation NAMES that are currently HIDDEN. Default empty = show
  // everything. (Stored as a Set so toggle is O(1).)
  hidden: Set<string>;
  setHidden: (next: Set<string>) => void;
  // Only show op groups for the kinds the user has enabled at the kind level.
  enabledKinds: Set<Kind>;
};

const KIND_COLOR: Record<Kind, { dot: string; text: string; ring: string }> = {
  file: { dot: 'bg-cyan-400', text: 'text-cyan-300', ring: 'border-cyan-500/40' },
  registry: { dot: 'bg-fuchsia-400', text: 'text-fuchsia-300', ring: 'border-fuchsia-500/40' },
  process: { dot: 'bg-emerald-400', text: 'text-emerald-300', ring: 'border-emerald-500/40' },
  network: { dot: 'bg-amber-400', text: 'text-amber-300', ring: 'border-amber-500/40' },
};

// localStorage key for user-defined presets. Shape:
//   { [name: string]: string[] }   — list of HIDDEN op names per preset.
const PRESETS_KEY = 'tracker:opPresets:v1';

type SavedPresets = Record<string, string[]>;

function loadPresets(): SavedPresets {
  try {
    const raw = window.localStorage.getItem(PRESETS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== 'object') return {};
    const out: SavedPresets = {};
    for (const [name, ops] of Object.entries(parsed as Record<string, unknown>)) {
      if (Array.isArray(ops) && ops.every((v) => typeof v === 'string')) {
        out[name] = ops as string[];
      }
    }
    return out;
  } catch {
    return {};
  }
}

function savePresets(presets: SavedPresets): void {
  try {
    window.localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
  } catch {
    // localStorage quota / disabled — ignore.
  }
}

function setsEqual(a: Set<string>, b: Iterable<string>): boolean {
  let count = 0;
  for (const v of b) {
    if (!a.has(v)) return false;
    count += 1;
  }
  return count === a.size;
}

function OperationsFilterInner({ events, hidden, setHidden, enabledKinds }: Props) {
  // Default-open so the filter is immediately discoverable. The user can
  // collapse it once they're happy with their selection.
  const [open, setOpen] = useState(true);
  const [presets, setPresets] = useState<SavedPresets>(() => loadPresets());

  // Persist whenever presets change.
  useEffect(() => {
    savePresets(presets);
  }, [presets]);

  // Discover operations and their counts per kind. Memoized — only recomputes
  // when the events array identity changes (rAF-batched commits in
  // useEventStream). Nothing about which ops exist or how to categorise them
  // is hardcoded; this is purely "what showed up in the stream".
  const grouped = useMemo(() => {
    const m = new Map<Kind, Map<string, number>>();
    for (const kind of KINDS) m.set(kind, new Map());
    for (const e of events) {
      if (!e.operation) continue;
      if (!(KINDS as readonly string[]).includes(e.kind)) continue;
      const ops = m.get(e.kind as Kind)!;
      ops.set(e.operation, (ops.get(e.operation) ?? 0) + 1);
    }
    const out: Array<{ kind: Kind; ops: Array<{ name: string; count: number }> }> = [];
    for (const kind of KINDS) {
      const ops = m.get(kind)!;
      const list = Array.from(ops.entries())
        .map(([name, count]) => ({ name, count }))
        .sort((a, b) => b.count - a.count);
      out.push({ kind, ops: list });
    }
    return out;
  }, [events]);

  const allOps = useMemo(() => {
    const out: string[] = [];
    for (const { ops } of grouped) for (const { name } of ops) out.push(name);
    return out;
  }, [grouped]);

  const totalOps = allOps.length;
  const hiddenCount = hidden.size;
  const visibleCount = Math.max(0, totalOps - hiddenCount);

  // Identify which saved preset matches the current `hidden` set.
  const activePresetName = useMemo<string | null>(() => {
    for (const [name, list] of Object.entries(presets)) {
      if (list.length !== hidden.size) continue;
      if (setsEqual(hidden, list)) return name;
    }
    return null;
  }, [hidden, presets]);

  const toggleOp = useCallback(
    (name: string) => {
      const next = new Set(hidden);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      setHidden(next);
    },
    [hidden, setHidden],
  );

  const showAll = useCallback(() => setHidden(new Set()), [setHidden]);

  const hideAll = useCallback(() => {
    setHidden(new Set(allOps));
  }, [allOps, setHidden]);

  const applyPreset = useCallback(
    (name: string) => {
      const list = presets[name];
      if (!list) return;
      setHidden(new Set(list));
    },
    [presets, setHidden],
  );

  const deletePreset = useCallback(
    (name: string) => {
      setPresets((current) => {
        const next = { ...current };
        delete next[name];
        return next;
      });
    },
    [],
  );

  const saveCurrentAsPreset = useCallback(() => {
    const suggested = activePresetName ?? '';
    const raw = window.prompt(
      'Name this filter preset (existing name overwrites):',
      suggested,
    );
    if (raw == null) return;
    const name = raw.trim();
    if (!name) return;
    setPresets((current) => ({ ...current, [name]: Array.from(hidden) }));
  }, [activePresetName, hidden]);

  const hideKind: MouseEventHandler<HTMLButtonElement> = useCallback(
    (e) => {
      e.stopPropagation();
      const kind = e.currentTarget.dataset.kind as Kind | undefined;
      if (!kind) return;
      const next = new Set(hidden);
      for (const op of grouped.find((g) => g.kind === kind)?.ops ?? []) {
        next.add(op.name);
      }
      setHidden(next);
    },
    [grouped, hidden, setHidden],
  );

  const showKind: MouseEventHandler<HTMLButtonElement> = useCallback(
    (e) => {
      e.stopPropagation();
      const kind = e.currentTarget.dataset.kind as Kind | undefined;
      if (!kind) return;
      const next = new Set(hidden);
      for (const op of grouped.find((g) => g.kind === kind)?.ops ?? []) {
        next.delete(op.name);
      }
      setHidden(next);
    },
    [grouped, hidden, setHidden],
  );

  const presetEntries = useMemo(
    () =>
      Object.keys(presets)
        .sort((a, b) => a.localeCompare(b))
        .map((name) => ({ name, list: presets[name] })),
    [presets],
  );

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950">
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs text-slate-300">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 hover:text-slate-100"
          title={open ? 'Collapse the operation list' : 'Expand the operation list'}
        >
          <span>{open ? '▾' : '▸'}</span>
          <span className="font-medium">Filter operations</span>
        </button>
        <span className="text-slate-500">
          {visibleCount} / {totalOps} shown
          {hiddenCount > 0 ? ` · ${hiddenCount} hidden` : ''}
        </span>

        <span className="ml-auto flex flex-wrap items-center gap-1">
          <button
            type="button"
            onClick={showAll}
            className="rounded-md border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200"
            title="Show every operation"
          >
            All
          </button>
          <button
            type="button"
            onClick={hideAll}
            disabled={totalOps === 0}
            className="rounded-md border border-slate-700 bg-slate-900 px-2 py-0.5 text-[10px] uppercase tracking-wide text-slate-300 hover:border-rose-500/60 hover:text-rose-200 disabled:opacity-40"
            title="Hide every operation that has been seen"
          >
            None
          </button>
          {presetEntries.map(({ name }) => {
            const active = activePresetName === name;
            return (
              <span key={name} className="inline-flex items-center">
                <button
                  type="button"
                  onClick={() => applyPreset(name)}
                  className={`rounded-l-md border px-2 py-0.5 text-[10px] uppercase tracking-wide transition ${
                    active
                      ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-200'
                      : 'border-slate-700 bg-slate-900 text-slate-300 hover:border-cyan-500/40 hover:text-cyan-200'
                  }`}
                  title={`Apply preset "${name}"`}
                >
                  {name}
                </button>
                <button
                  type="button"
                  onClick={() => deletePreset(name)}
                  className={`rounded-r-md border border-l-0 px-1.5 py-0.5 text-[10px] transition ${
                    active
                      ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-200 hover:text-rose-300'
                      : 'border-slate-700 bg-slate-900 text-slate-500 hover:border-rose-500/60 hover:text-rose-300'
                  }`}
                  title={`Delete preset "${name}"`}
                >
                  ×
                </button>
              </span>
            );
          })}
          <button
            type="button"
            onClick={saveCurrentAsPreset}
            disabled={totalOps === 0}
            className="rounded-md border border-cyan-500/40 bg-cyan-500/10 px-2 py-0.5 text-[10px] uppercase tracking-wide text-cyan-200 hover:border-cyan-500/70 disabled:opacity-40"
            title="Save the current checkbox state as a named preset (stored in localStorage)"
          >
            Save…
          </button>
        </span>
      </div>

      {totalOps === 0 ? (
        <div className="border-t border-slate-800 px-3 py-2 text-[11px] text-slate-500">
          No operations seen yet. The list is built dynamically from incoming
          events — checkboxes appear as the target process emits them. Pick the
          ones you want to hide, then click <span className="font-mono">Save…</span>
          to remember the filter as a named preset.
        </div>
      ) : (
        open && (
          <div className="grid gap-2 border-t border-slate-800 p-2 sm:grid-cols-2 xl:grid-cols-4">
            {grouped.map(({ kind, ops }) => {
              if (!enabledKinds.has(kind)) return null;
              const colors = KIND_COLOR[kind];
              return (
                <div
                  key={kind}
                  className={`rounded-lg border bg-slate-950/60 p-2 ${colors.ring}`}
                >
                  <div className="mb-1 flex items-center justify-between">
                    <div className="flex items-center gap-1.5 text-[11px] uppercase tracking-wide">
                      <span className={`h-2 w-2 rounded-full ${colors.dot}`} />
                      <span className={colors.text}>{kind}</span>
                      <span className="text-slate-600">({ops.length})</span>
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        data-kind={kind}
                        onClick={showKind}
                        className="rounded text-[9px] uppercase text-slate-500 hover:text-slate-200"
                        title={`Show every ${kind} op`}
                      >
                        all
                      </button>
                      <span className="text-slate-700">·</span>
                      <button
                        type="button"
                        data-kind={kind}
                        onClick={hideKind}
                        className="rounded text-[9px] uppercase text-slate-500 hover:text-slate-200"
                        title={`Hide every ${kind} op`}
                      >
                        none
                      </button>
                    </div>
                  </div>
                  {ops.length === 0 ? (
                    <div className="px-1 py-1 text-[11px] text-slate-600">
                      no events yet
                    </div>
                  ) : (
                    <div className="space-y-0.5">
                      {ops.map(({ name, count }) => {
                        const isHidden = hidden.has(name);
                        return (
                          <label
                            key={name}
                            className={`flex cursor-pointer items-center justify-between gap-2 rounded px-1.5 py-1 text-[11px] hover:bg-slate-900 ${
                              isHidden ? 'opacity-50' : ''
                            }`}
                          >
                            <span className="flex items-center gap-1.5">
                              <input
                                type="checkbox"
                                checked={!isHidden}
                                onChange={() => toggleOp(name)}
                                className="h-3 w-3 accent-cyan-500"
                              />
                              <span className="font-mono text-slate-300">
                                {name}
                              </span>
                            </span>
                            <span className="font-mono text-slate-600">{count}</span>
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )
      )}
    </div>
  );
}

export const OperationsFilter = memo(OperationsFilterInner);
