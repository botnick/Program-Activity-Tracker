import type { Kind } from '../types';
import { KINDS } from '../types';

type Props = {
  kindFilter: Set<Kind>;
  toggle: (kind: Kind) => void;
  counts: Record<string, number>;
  autoScroll: boolean;
  setAutoScroll: (value: boolean) => void;
};

export function KindFilters({ kindFilter, toggle, counts, autoScroll, setAutoScroll }: Props) {
  return (
    <div className="flex items-center gap-2 text-xs text-slate-400">
      {KINDS.map((kind) => (
        <button
          key={kind}
          onClick={() => toggle(kind)}
          className={`rounded-full border px-2 py-1 transition ${
            kindFilter.has(kind)
              ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-200'
              : 'border-slate-700 bg-slate-950 text-slate-500'
          }`}
        >
          {kind} <span className="ml-1 text-slate-500">{counts[kind] ?? 0}</span>
        </button>
      ))}
      <label className="ml-2 flex items-center gap-1">
        <input
          type="checkbox"
          checked={autoScroll}
          onChange={(e) => setAutoScroll(e.target.checked)}
        />
        follow
      </label>
    </div>
  );
}
