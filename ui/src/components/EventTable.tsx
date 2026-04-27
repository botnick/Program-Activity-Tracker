import { memo, useCallback, useEffect, useRef } from 'react';
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

function EventTableInner({ events, autoScroll, onSelectEvent, selectedId }: Props) {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: events.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    getItemKey: (index) => events[index]?.id ?? index,
  });

  // rAF-throttled auto-scroll: many events arriving in the same frame collapse
  // into a single scrollTop write, eliminating reflow churn at high event rates.
  const scrollFrameRef = useRef<number | null>(null);
  useEffect(() => {
    if (!autoScroll) return;
    if (scrollFrameRef.current !== null) return;
    scrollFrameRef.current = requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const el = parentRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    });
    return () => {
      if (scrollFrameRef.current !== null) {
        cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
  }, [events.length, autoScroll]);

  const handleRowClick = useCallback(
    (event: ActivityEvent) => {
      onSelectEvent?.(event);
    },
    [onSelectEvent],
  );

  const items = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-800">
      <div
        ref={parentRef}
        className="max-h-[68vh] overflow-auto"
        style={{ contain: 'strict' }}
      >
        <div className="sticky top-0 z-10 grid grid-cols-[80px_60px_1fr] sm:grid-cols-[100px_70px_100px_2fr] md:grid-cols-[110px_80px_120px_70px_2fr] lg:grid-cols-[110px_80px_120px_80px_1fr_1fr] bg-slate-950 text-xs text-slate-400">
          <div className="px-3 py-2">Time</div>
          <div className="px-3 py-2">Kind</div>
          <div className="hidden px-3 py-2 sm:block">Op</div>
          <div className="hidden px-3 py-2 md:block">PID</div>
          <div className="px-3 py-2">Target / Path</div>
          <div className="hidden px-3 py-2 lg:block">Details</div>
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
                  onClick={() => handleRowClick(event)}
                  className={`grid cursor-pointer grid-cols-[80px_60px_1fr] sm:grid-cols-[100px_70px_100px_2fr] md:grid-cols-[110px_80px_120px_70px_2fr] lg:grid-cols-[110px_80px_120px_80px_1fr_1fr] border-t border-slate-800 transition-colors motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-150 ${
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
                  <div className="hidden truncate px-3 py-1.5 text-slate-300 sm:block">
                    {event.operation ?? '-'}
                  </div>
                  <div className="hidden px-3 py-1.5 text-slate-500 md:block">{event.pid ?? '-'}</div>
                  <div className="truncate px-3 py-1.5 text-slate-200">
                    {event.path ?? event.target ?? '-'}
                  </div>
                  <div className="hidden truncate px-3 py-1.5 text-slate-500 lg:block">
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

export const EventTable = memo(EventTableInner);
