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

  const clear = useCallback(() => setEvents([]), []);

  // Track the latest event timestamp so reconnect-time fetches can ask for
  // only the events that arrived during the gap (`?since=`) — without this,
  // any events emitted while the WS was disconnected would silently vanish.
  const lastTsRef = useRef<string | null>(null);

  useEffect(() => {
    if (!sessionId) {
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
        if (since) {
          // Append-only on reconnect; preserve in-memory history.
          setEvents((current) => {
            const merged = [...current, ...result.items];
            return merged.length > MAX_EVENTS ? merged.slice(-MAX_EVENTS) : merged;
          });
        } else {
          setEvents(result.items);
        }
        if (result.items.length) {
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
      setEvents((current) => {
        const next = [...current, payload];
        return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
      });
    };

    return () => {
      cancelled = true;
      socket.close();
    };
  }, [sessionId]);

  return { events, connected, clear, error, setEvents };
}
