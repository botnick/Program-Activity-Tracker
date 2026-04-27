import { memo, useEffect, useRef, useState, type MutableRefObject } from 'react';
import type { ActivityEvent, Kind } from '../types';
import { KINDS } from '../types';

type Props = {
  // App.tsx mirrors `events` state into a ref so the sparkline can sample at
  // 1 Hz without paying the cost of re-rendering on every WS-driven commit.
  // The legacy `events` prop is still accepted for callers that haven't been
  // migrated yet — when given, we pull the latest snapshot from it on tick.
  eventsRef?: MutableRefObject<ActivityEvent[]>;
  events?: ActivityEvent[];
};

const WINDOW_SECONDS = 60;
const KIND_COLOR: Record<Kind, string> = {
  file: '#22d3ee', // cyan-400
  registry: '#e879f9', // fuchsia-400
  process: '#34d399', // emerald-400
  network: '#fbbf24', // amber-400
};

function bin(events: ActivityEvent[], kind: Kind, now: number): number[] {
  const buckets = new Array(WINDOW_SECONDS).fill(0);
  const cutoff = now - WINDOW_SECONDS * 1000;
  for (const event of events) {
    if (event.kind !== kind) continue;
    const ts = Date.parse(event.timestamp);
    if (Number.isNaN(ts) || ts < cutoff) continue;
    const idx = Math.min(
      WINDOW_SECONDS - 1,
      Math.max(0, Math.floor((ts - cutoff) / 1000)),
    );
    buckets[idx] += 1;
  }
  return buckets;
}

function pathFor(buckets: number[], width: number, height: number): { d: string; max: number } {
  const max = Math.max(1, ...buckets);
  const dx = width / (buckets.length - 1 || 1);
  const points = buckets.map((b, i) => {
    const x = i * dx;
    const y = height - (b / max) * (height - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return { d: `M${points.join(' L')}`, max };
}

function Spark({ label, color, buckets }: { label: string; color: string; buckets: number[] }) {
  const width = 140;
  const height = 32;
  const { d, max } = pathFor(buckets, width, height);
  const total = buckets.reduce((a, b) => a + b, 0);
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-slate-800 bg-slate-950 px-3 py-2">
      <div className="flex items-center justify-between text-[10px] uppercase tracking-wide text-slate-500">
        <span style={{ color }}>{label}</span>
        <span className="font-mono text-slate-400">{total}/60s · peak {max}</span>
      </div>
      <svg width={width} height={height} className="block">
        <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
      </svg>
    </div>
  );
}

function RateSparklineInner({ eventsRef, events }: Props) {
  // Mirror the prop into a ref so the 1 Hz tick effect doesn't depend on it.
  const propRef = useRef<ActivityEvent[]>(events ?? []);
  useEffect(() => {
    propRef.current = events ?? [];
  }, [events]);

  // Re-render at most once per second. Bin computation reads from the latest
  // ref value, so high-frequency event ingestion never propagates to a render.
  const [, setTick] = useState(0);
  useEffect(() => {
    const handle = window.setInterval(() => {
      setTick((t) => (t + 1) % 1_000_000);
    }, 1000);
    return () => window.clearInterval(handle);
  }, []);

  const source = eventsRef?.current ?? propRef.current;
  const now = Date.now();
  const series = KINDS.map((kind) => ({ kind, buckets: bin(source, kind, now) }));

  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {series.map(({ kind, buckets }) => (
        <Spark key={kind} label={kind} color={KIND_COLOR[kind]} buckets={buckets} />
      ))}
    </div>
  );
}

export const RateSparkline = memo(RateSparklineInner);
