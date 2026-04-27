import type { Kind } from '../types';
import { KINDS } from '../types';

type Props = {
  enabled: Set<Kind>;
  toggle: (kind: Kind) => void;
  counts: Record<string, number>;
};

const KIND_TINT: Record<Kind, string> = {
  file: 'border-cyan-500/60 bg-cyan-500/10 text-cyan-200',
  registry: 'border-fuchsia-500/60 bg-fuchsia-500/10 text-fuchsia-200',
  process: 'border-emerald-500/60 bg-emerald-500/10 text-emerald-200',
  network: 'border-amber-500/60 bg-amber-500/10 text-amber-200',
};

export function ProviderToggle({ enabled, toggle, counts }: Props) {
  return (
    <div className="flex items-center gap-1.5 text-xs">
      {KINDS.map((kind) => {
        const on = enabled.has(kind);
        return (
          <button
            key={kind}
            onClick={() => toggle(kind)}
            className={`rounded-full border px-2.5 py-1 transition ${
              on ? KIND_TINT[kind] : 'border-slate-700 bg-slate-950 text-slate-500 hover:text-slate-300'
            }`}
            title={on ? `Disable ${kind} provider` : `Enable ${kind} provider`}
          >
            <span className="uppercase tracking-wide">{kind}</span>
            <span className="ml-1.5 text-[10px] opacity-75">{counts[kind] ?? 0}</span>
          </button>
        );
      })}
    </div>
  );
}
