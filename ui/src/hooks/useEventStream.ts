import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { ActivityEvent } from '../types';

const MAX_EVENTS = 5000;
const RECONNECT_BACKOFF_MIN_MS = 500;
const RECONNECT_BACKOFF_MAX_MS = 10_000;

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

  // Belt-and-suspenders dedup: even though the backend now honours `?since=`
  // on both the HTTP backfill and the WS replay, race conditions on
  // millisecond-truncated timestamps can re-emit the same id. Keep a Set of
  // recently-seen ids to drop dupes before they hit React state.
  const seenIdsRef = useRef<Set<string>>(new Set());
  const seenOrderRef = useRef<string[]>([]);
  const SEEN_CAP = MAX_EVENTS * 2;

  const dedupAndCommit = useCallback((incoming: ActivityEvent[]): ActivityEvent[] => {
    if (incoming.length === 0) return [];
    const out: ActivityEvent[] = [];
    const seen = seenIdsRef.current;
    const order = seenOrderRef.current;
    for (const e of incoming) {
      const id = e.id;
      if (id && seen.has(id)) continue;
      if (id) {
        seen.add(id);
        order.push(id);
      }
      out.push(e);
    }
    // Cap the seen set so it can't grow without bound.
    if (order.length > SEEN_CAP) {
      const drop = order.length - SEEN_CAP;
      for (let i = 0; i < drop; i++) seen.delete(order[i]);
      seenOrderRef.current = order.slice(drop);
    }
    return out;
  }, [SEEN_CAP]);

  const scheduleFlush = useCallback(() => {
    if (rafRef.current !== null) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null;
      const incoming = pendingRef.current;
      if (incoming.length === 0) return;
      pendingRef.current = [];
      const fresh = dedupAndCommit(incoming);
      if (fresh.length === 0) return;
      setEvents((current) => {
        const next = current.concat(fresh);
        return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
      });
    });
  }, [dedupAndCommit]);

  const clear = useCallback(() => {
    pendingRef.current = [];
    setEvents([]);
    lastTsRef.current = null;
    seenIdsRef.current = new Set();
    seenOrderRef.current = [];
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
      seenIdsRef.current = new Set();
      seenOrderRef.current = [];
      return;
    }

    // Reset dedup state when the sessionId changes — we're showing a different
    // session, the previous ids are irrelevant.
    seenIdsRef.current = new Set();
    seenOrderRef.current = [];

    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let backoffMs = RECONNECT_BACKOFF_MIN_MS;

    const connect = async () => {
      if (cancelled) return;

      // Backfill events that may have arrived during a disconnect (or supply
      // initial history on first load). The `since=` filter on /events is
      // server-side, so this is bounded even on long absences.
      const since = lastTsRef.current;
      const url = since
        ? `/api/sessions/${sessionId}/events?since=${encodeURIComponent(since)}`
        : `/api/sessions/${sessionId}/events`;
      try {
        const result = await api<{ items: ActivityEvent[] }>(url);
        if (cancelled) return;
        if (result.items.length) {
          // Always go through the dedup gate — repeats are filtered, and the
          // visible state stays consistent with WS-delivered events.
          const fresh = dedupAndCommit(result.items);
          if (fresh.length) {
            if (since) {
              setEvents((current) => {
                const merged = current.concat(fresh);
                return merged.length > MAX_EVENTS ? merged.slice(-MAX_EVENTS) : merged;
              });
            } else {
              setEvents(fresh);
            }
          }
          const tail = result.items[result.items.length - 1];
          lastTsRef.current = tail.timestamp ?? lastTsRef.current;
        }
      } catch (err) {
        if (!cancelled) setError(String(err));
        // Don't return — still try the WebSocket; the next reconnect can re-backfill.
      }

      if (cancelled) return;

      // Pass `since` and `replay=false` to the WS so the server doesn't
      // re-send events the HTTP backfill above already delivered. The
      // first fetch above is what populates `lastTsRef`; the WS just needs
      // to start tailing from there.
      const wsBase = `${window.location.origin.replace('http', 'ws')}/ws/sessions/${sessionId}`;
      const wsParams = new URLSearchParams();
      if (lastTsRef.current) {
        wsParams.set('since', lastTsRef.current);
        wsParams.set('replay', 'false');
      }
      const wsUrl = wsParams.toString() ? `${wsBase}?${wsParams.toString()}` : wsBase;
      socket = new WebSocket(wsUrl);

      socket.onopen = () => {
        if (cancelled) return;
        // Successful connect resets the backoff so a transient blip doesn't
        // delay the *next* reconnect attempt later.
        backoffMs = RECONNECT_BACKOFF_MIN_MS;
        setConnected(true);
        setError(null);
      };

      socket.onclose = (ev) => {
        setConnected(false);
        if (cancelled) return;

        const reason = ev.reason || `closed (code ${ev.code})`;
        onErrorRef.current?.(reason);

        // Don't reconnect on:
        //   1000 = normal closure (server / our cleanup)
        //   4404 = backend says session doesn't exist
        if (ev.code === 1000 || ev.code === 4404) return;

        // Schedule reconnect with exponential backoff.
        const delay = backoffMs;
        backoffMs = Math.min(RECONNECT_BACKOFF_MAX_MS, backoffMs * 2);
        reconnectTimer = window.setTimeout(() => {
          reconnectTimer = null;
          connect().catch((err) => {
            if (!cancelled) setError(String(err));
          });
        }, delay);
      };

      socket.onerror = (ev) => {
        if (cancelled) return;
        // Don't flip `connected` here — `onclose` always fires after `onerror`
        // and is the canonical place to manage reconnect state.
        onErrorRef.current?.(ev);
      };

      socket.onmessage = (msg) => {
        const payload = JSON.parse(msg.data) as ActivityEvent;
        lastTsRef.current = payload.timestamp ?? lastTsRef.current;
        pendingRef.current.push(payload);
        scheduleFlush();
      };
    };

    connect().catch((err) => {
      if (!cancelled) setError(String(err));
    });

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
      pendingRef.current = [];
      if (socket) {
        // Detach handlers BEFORE close so the close event doesn't kick off a
        // reconnect against a stale `cancelled` capture from a stale closure.
        socket.onopen = null;
        socket.onclose = null;
        socket.onerror = null;
        socket.onmessage = null;
        try {
          socket.close(1000, 'unmount');
        } catch {
          // ignore
        }
        socket = null;
      }
    };
  }, [sessionId, scheduleFlush]);

  return { events, connected, clear, error, setEvents };
}
