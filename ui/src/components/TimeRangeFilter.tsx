export type TimeRange = 'live' | '30s' | '5min' | '1h' | 'all';

type Props = {
  value: TimeRange;
  onChange: (value: TimeRange) => void;
};

const RANGES: { value: TimeRange; label: string }[] = [
  { value: 'live', label: 'Live' },
  { value: '30s', label: '30s' },
  { value: '5min', label: '5min' },
  { value: '1h', label: '1h' },
  { value: 'all', label: 'All' },
];

export function TimeRangeFilter({ value, onChange }: Props) {
  return (
    <div className="flex items-center gap-1 rounded-full border border-slate-800 bg-slate-950 p-0.5 text-xs">
      {RANGES.map((r) => {
        const active = r.value === value;
        return (
          <button
            key={r.value}
            onClick={() => onChange(r.value)}
            className={`rounded-full px-3 py-1 transition ${
              active
                ? 'bg-cyan-500/20 text-cyan-200'
                : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
            }`}
          >
            {r.label}
          </button>
        );
      })}
    </div>
  );
}
