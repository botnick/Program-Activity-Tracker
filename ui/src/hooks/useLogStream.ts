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

export function useLogStream(stream: string, live: boolean) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [streams, setStreams] = useState<LogStreamInfo[]>([]);
  const [connected, setConnected] = useState(false);

  const pendingRef = useRef<LogEntry[]>([]);
  const rafRef = useRef<number | null>(null);

  const flush = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const incoming = pendingRef.current;
      if (incoming.length === 0) return;
      pendingRef.current = [];
      setEntries((cur) => {
        const next = cur.concat(incoming);
        return next.length > MAX_ENTRIES ? next.slice(-MAX_ENTRIES) : next;
      });
    });
  }, []);

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

  // Initial backlog or live tail per stream selection.
  useEffect(() => {
    if (!stream) return;
    let cancelled = false;
    setEntries([]);
    pendingRef.current = [];
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }

    if (!live) {
      api<{ items: LogEntry[] }>(`/api/logs/${stream}?tail=500`)
        .then((res) => {
          if (!cancelled) setEntries(res.items);
        })
        .catch(() => undefined);
      setConnected(false);
      return () => {
        cancelled = true;
      };
    }

    const ws = new WebSocket(
      `${window.location.origin.replace('http', 'ws')}/ws/logs/${stream}`,
    );
    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setConnected(false);
    ws.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data) as LogEntry;
        pendingRef.current.push(payload);
        flush();
      } catch {
        // ignore malformed
      }
    };

    return () => {
      cancelled = true;
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      ws.close();
    };
  }, [stream, live, flush]);

  return { entries, streams, connected };
}
