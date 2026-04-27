import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import type { ActivityEvent } from '../types';

const MAX_EVENTS = 5000;

export function useEventStream(sessionId: string) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clear = useCallback(() => setEvents([]), []);

  useEffect(() => {
    if (!sessionId) {
      setEvents([]);
      setConnected(false);
      return;
    }

    let cancelled = false;

    api<{ items: ActivityEvent[] }>(`/api/sessions/${sessionId}/events`)
      .then((result) => {
        if (!cancelled) setEvents(result.items);
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });

    const socket = new WebSocket(
      `${window.location.origin.replace('http', 'ws')}/ws/sessions/${sessionId}`,
    );
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);
    socket.onmessage = (msg) => {
      const payload = JSON.parse(msg.data) as ActivityEvent;
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

  return { events, connected, clear, error };
}
