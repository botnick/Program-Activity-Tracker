import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';

export type LogEntry = {
  ts?: string;
  level?: string;
  logger?: string;
  message?: string;
  raw?: boolean;
  trace_id?: string;
  [key: string]: unknown;
};

export type LogStreamInfo = {
  name: string;
  path: string;
  size: number;
  exists: boolean;
};

const MAX_ENTRIES = 2000;

// Logs don't have a unique id field. We compute a synthetic key per entry
// that's strong enough to suppress the 100-line backlog re-send the WS
// produces every reconnect.
function entryKey(e: LogEntry): string {
  // Order matters: ts is the most discriminating prefix.
  return `${e.ts ?? ''}|${e.level ?? ''}|${e.logger ?? ''}|${String(e.message ?? '')}`;
}

export function useLogStream(stream: string, live: boolean) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [streams, setStreams] = useState<LogStreamInfo[]>([]);
  const [connected, setConnected] = useState(false);

  const pendingRef = useRef<LogEntry[]>([]);
  const rafRef = useRef<number | null>(null);
  const seenRef = useRef<Set<string>>(new Set());
  const seenOrderRef = useRef<string[]>([]);
  const SEEN_CAP = MAX_ENTRIES * 2;

  const dedup = useCallback((incoming: LogEntry[]): LogEntry[] => {
    if (incoming.length === 0) return [];
    const seen = seenRef.current;
    const order = seenOrderRef.current;
    const out: LogEntry[] = [];
    for (const e of incoming) {
      const k = entryKey(e);
      if (seen.has(k)) continue;
      seen.add(k);
      order.push(k);
      out.push(e);
    }
    if (order.length > SEEN_CAP) {
      const drop = order.length - SEEN_CAP;
      for (let i = 0; i < drop; i++) seen.delete(order[i]);
      seenOrderRef.current = order.slice(drop);
    }
    return out;
  }, [SEEN_CAP]);

  const flush = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const incoming = pendingRef.current;
      if (incoming.length === 0) return;
      pendingRef.current = [];
      const fresh = dedup(incoming);
      if (fresh.length === 0) return;
      setEntries((cur) => {
        const next = cur.concat(fresh);
        return next.length > MAX_ENTRIES ? next.slice(-MAX_ENTRIES) : next;
      });
    });
  }, [dedup]);

  // Discover streams once on mount.
  useEffect(() => {
    let cancelled = false;
    api<{ streams: LogStreamInfo[]; log_dir: string }>('/api/logs/streams')
      .then((res) => {
        if (!cancelled) setStreams(res.streams);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // Initial backlog or live tail per stream selection. Reconnects use
  // backlog=0 so we don't re-display the same 100 lines we already have.
  useEffect(() => {
    if (!stream) return;
    let cancelled = false;
    let ws: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let backoffMs = 500;

    // Reset state when stream selection changes.
    setEntries([]);
    pendingRef.current = [];
    seenRef.current = new Set();
    seenOrderRef.current = [];
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }

    if (!live) {
      api<{ items: LogEntry[] }>(`/api/logs/${stream}?tail=500`)
        .then((res) => {
          if (!cancelled) {
            const fresh = dedup(res.items);
            setEntries(fresh);
          }
        })
        .catch(() => undefined);
      setConnected(false);
      return () => {
        cancelled = true;
      };
    }

    let firstConnect = true;

    const connect = () => {
      if (cancelled) return;
      // First connect: 100-line backlog. Reconnect: skip backlog entirely
      // (whatever we missed will be picked up by the live tail polling).
      const params = new URLSearchParams();
      params.set('backlog', firstConnect ? '100' : '0');
      firstConnect = false;
      const url = `${window.location.origin.replace('http', 'ws')}/ws/logs/${stream}?${params.toString()}`;
      ws = new WebSocket(url);
      ws.onopen = () => {
        if (cancelled) return;
        backoffMs = 500;
        setConnected(true);
      };
      ws.onclose = (ev) => {
        setConnected(false);
        if (cancelled) return;
        if (ev.code === 1000 || ev.code === 4404) return;
        const delay = backoffMs;
        backoffMs = Math.min(10_000, backoffMs * 2);
        reconnectTimer = window.setTimeout(() => {
          reconnectTimer = null;
          connect();
        }, delay);
      };
      ws.onerror = () => {
        // onclose handles reconnect.
      };
      ws.onmessage = (ev) => {
        try {
          const payload = JSON.parse(ev.data) as LogEntry;
          pendingRef.current.push(payload);
          flush();
        } catch {
          // ignore malformed
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      if (ws) {
        ws.onopen = null;
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        try {
          ws.close(1000, 'unmount');
        } catch {
          // ignore
        }
      }
    };
  }, [stream, live, flush, dedup]);

  return { entries, streams, connected };
}
