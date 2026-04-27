import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { ActivityEvent } from '../types';

const MAX_EVENTS = 5000;

type Options = {
  onError?: (err: Event | string) => void;
};

export function useEventStream(sessionId: string, options: Options = {}) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onErrorRef = useRef<Options['onError']>(options.onError);
  useEffect(() => {
    onErrorRef.current = options.onError;
  }, [options.onError]);

  // FIFO of pending events flushed on the next animation frame. Keeps the UI
  // smooth by collapsing many WS messages into a single React commit per frame.
  const pendingRef = useRef<ActivityEvent[]>([]);
  const rafRef = useRef<number | null>(null);

  // Track the latest event timestamp so reconnect-time fetches can ask for
  // only the events that arrived during the gap (`?since=`) — without this,
  // any events emitted while the WS was disconnected would silently vanish.
  const lastTsRef = useRef<string | null>(null);

  const scheduleFlush = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const incoming = pendingRef.current;
      if (incoming.length === 0) return;
      pendingRef.current = [];
      setEvents((current) => {
        const next = current.concat(incoming);
        return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
      });
    });
  }, []);

  const clear = useCallback(() => {
    pendingRef.current = [];
    setEvents([]);
    lastTsRef.current = null;
  }, []);

  useEffect(() => {
    if (!sessionId) {
      pendingRef.current = [];
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      setEvents([]);
      setConnected(false);
      lastTsRef.current = null;
      return;
    }

    let cancelled = false;

    const since = lastTsRef.current;
    const url = since
      ? `/api/sessions/${sessionId}/events?since=${encodeURIComponent(since)}`
      : `/api/sessions/${sessionId}/events`;
    api<{ items: ActivityEvent[] }>(url)
      .then((result) => {
        if (cancelled) return;
        if (result.items.length) {
          if (since) {
            // Append-only on reconnect; preserve in-memory history.
            setEvents((current) => {
              const merged = current.concat(result.items);
              return merged.length > MAX_EVENTS ? merged.slice(-MAX_EVENTS) : merged;
            });
          } else {
            setEvents(result.items);
          }
          const tail = result.items[result.items.length - 1];
          lastTsRef.current = tail.timestamp ?? lastTsRef.current;
        }
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });

    const socket = new WebSocket(
      `${window.location.origin.replace('http', 'ws')}/ws/sessions/${sessionId}`,
    );
    socket.onopen = () => setConnected(true);
    socket.onclose = (ev) => {
      setConnected(false);
      const reason = ev.reason || `closed (code ${ev.code})`;
      onErrorRef.current?.(reason);
    };
    socket.onerror = (ev) => {
      setConnected(false);
      onErrorRef.current?.(ev);
    };
    socket.onmessage = (msg) => {
      const payload = JSON.parse(msg.data) as ActivityEvent;
      lastTsRef.current = payload.timestamp ?? lastTsRef.current;
      pendingRef.current.push(payload);
      scheduleFlush();
    };

    return () => {
      cancelled = true;
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      pendingRef.current = [];
      socket.close();
    };
  }, [sessionId, scheduleFlush]);

  return { events, connected, clear, error, setEvents };
}
