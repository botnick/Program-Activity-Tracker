import type { ActivityEvent, EventQueryParams, Session } from './types';

export const api = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
};

export type EventsResponse = { items: ActivityEvent[] };

export const queryEvents = async (
  sessionId: string,
  params: EventQueryParams,
): Promise<EventsResponse> => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return;
    if (Array.isArray(v)) {
      // FastAPI's `list[str] = Query(None)` expects repeated keys, e.g.
      // ?operation=read&operation=write — append, don't join.
      for (const item of v) {
        if (item === undefined || item === null || item === '') continue;
        qs.append(k, String(item));
      }
    } else {
      qs.set(k, String(v));
    }
  });
  return api<EventsResponse>(`/api/sessions/${sessionId}/events?${qs.toString()}`);
};

export const exportUrl = (
  sessionId: string,
  format: 'csv' | 'jsonl',
  filters: Record<string, string | string[] | undefined> = {},
) => {
  const qs = new URLSearchParams();
  qs.set('format', format);
  Object.entries(filters).forEach(([k, v]) => {
    if (v === undefined || v === null || v === '') return;
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item === undefined || item === null || item === '') continue;
        qs.append(k, item);
      }
    } else {
      qs.set(k, v);
    }
  });
  return `/api/sessions/${sessionId}/export?${qs.toString()}`;
};

export const exportSession = (
  sessionId: string,
  format: 'csv' | 'jsonl',
  filters: Record<string, string | string[] | undefined> = {},
) => exportUrl(sessionId, format, filters);

export const fetchSession = (sessionId: string): Promise<Session> =>
  api<Session>(`/api/sessions/${sessionId}`);
