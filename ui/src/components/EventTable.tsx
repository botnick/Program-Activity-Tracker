import { useEffect, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import type { ActivityEvent } from '../types';

type Props = {
  events: ActivityEvent[];
  autoScroll: boolean;
  onSelectEvent?: (event: ActivityEvent) => void;
  selectedId?: string | null;
};

const ROW_HEIGHT = 32;

function kindClass(kind: string): string {
  if (kind === 'file') return 'bg-cyan-500/10 text-cyan-300';
  if (kind === 'registry') return 'bg-fuchsia-500/10 text-fuchsia-300';
  if (kind === 'process') return 'bg-emerald-500/10 text-emerald-300';
  if (kind === 'network') return 'bg-amber-500/10 text-amber-300';
  return 'bg-slate-500/10 text-slate-300';
}

export function EventTable({ events, autoScroll, onSelectEvent, selectedId }: Props) {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: events.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    getItemKey: (index) => events[index]?.id ?? index,
  });

  useEffect(() => {
    if (!autoScroll) return;
    const el = parentRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [events, autoScroll]);

  const items = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-800">
      <div
        ref={parentRef}
        className="max-h-[68vh] overflow-auto"
        style={{ contain: 'strict' }}
      >
        <div className="sticky top-0 z-10 grid grid-cols-[110px_80px_120px_80px_1fr_1fr] bg-slate-950 text-xs text-slate-400">
          <div className="px-3 py-2">Time</div>
          <div className="px-3 py-2">Kind</div>
          <div className="px-3 py-2">Op</div>
          <div className="px-3 py-2">PID</div>
          <div className="px-3 py-2">Target / Path</div>
          <div className="px-3 py-2">Details</div>
        </div>
        {events.length === 0 ? (
          <div className="px-3 py-6 text-center text-xs text-slate-500">
            no events match the current filters
          </div>
        ) : (
          <div style={{ height: totalSize, position: 'relative' }} className="font-mono text-xs">
            {items.map((vi) => {
              const event = events[vi.index];
              if (!event) return null;
              const isSelected = selectedId === event.id;
              return (
                <div
                  key={vi.key}
                  onClick={() => onSelectEvent?.(event)}
                  className={`grid cursor-pointer grid-cols-[110px_80px_120px_80px_1fr_1fr] border-t border-slate-800 transition-colors ${
                    isSelected ? 'bg-cyan-500/10' : 'hover:bg-slate-800/40'
                  }`}
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
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </div>
                  <div className="px-3 py-1.5">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] uppercase ${kindClass(event.kind)}`}
                    >
                      {event.kind}
                    </span>
                  </div>
                  <div className="truncate px-3 py-1.5 text-slate-300">
                    {event.operation ?? '-'}
                  </div>
                  <div className="px-3 py-1.5 text-slate-500">{event.pid ?? '-'}</div>
                  <div className="truncate px-3 py-1.5 text-slate-200">
                    {event.path ?? event.target ?? '-'}
                  </div>
                  <div className="truncate px-3 py-1.5 text-slate-500">
                    {JSON.stringify(event.details ?? {})}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
