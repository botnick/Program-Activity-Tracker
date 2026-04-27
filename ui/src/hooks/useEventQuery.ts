import { useCallback, useEffect, useRef, useState } from 'react';
import { queryEvents } from '../api';
import type { ActivityEvent, EventQueryParams } from '../types';

type Result = {
  events: ActivityEvent[];
  loading: boolean;
  error: string | null;
  refetch: () => void;
};

const DEBOUNCE_MS = 300;

export function useEventQuery(
  sessionId: string,
  params: EventQueryParams,
  enabled: boolean,
): Result {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const paramsKey = JSON.stringify(params);
  const cancelledRef = useRef(false);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!enabled || !sessionId) {
      setEvents([]);
      setLoading(false);
      setError(null);
      return;
    }
    cancelledRef.current = false;
    setLoading(true);
    setError(null);

    const handle = window.setTimeout(() => {
      queryEvents(sessionId, params)
        .then((result) => {
          if (!cancelledRef.current) {
            setEvents(result.items);
            setLoading(false);
          }
        })
        .catch((err) => {
          if (!cancelledRef.current) {
            setError(String(err));
            setLoading(false);
          }
        });
    }, DEBOUNCE_MS);

    return () => {
      cancelledRef.current = true;
      window.clearTimeout(handle);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, paramsKey, enabled, tick]);

  return { events, loading, error, refetch };
}
