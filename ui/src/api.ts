import type { ActivityEvent, EventQueryParams, Session } from './types';

// ---- auth token ----------------------------------------------------------

const TOKEN_KEY = 'tracker.auth.token';

/** Read the bearer token from localStorage, falling back to the URL `?token=`
 *  query string. The launcher (tracker.exe) opens the browser with the token
 *  in the URL on first run; we hoist it into localStorage and strip it from
 *  the address bar so reloads stay clean.                                */
function readToken(): string {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('token');
    if (fromUrl) {
      window.localStorage.setItem(TOKEN_KEY, fromUrl);
      const url = new URL(window.location.href);
      url.searchParams.delete('token');
      window.history.replaceState({}, '', url.toString());
      return fromUrl;
    }
    return window.localStorage.getItem(TOKEN_KEY) || '';
  } catch {
    return '';
  }
}

let cachedToken = readToken();

/** Attach token to a URL as `?token=...`. Used for resources where headers
 *  aren't an option (WebSocket, <a href> downloads, <img src>).             */
export function withToken(url: string): string {
  if (!cachedToken) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}token=${encodeURIComponent(cachedToken)}`;
}

export function authHeaders(): Record<string, string> {
  return cachedToken ? { Authorization: `Bearer ${cachedToken}` } : {};
}

/** Re-read the token (e.g. if the user pasted a fresh URL).                */
export function refreshToken(): void {
  cachedToken = readToken();
}

// ---- typed fetch helpers --------------------------------------------------

export const api = async <T,>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(init?.headers || {}),
    },
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
  // Export downloads can't carry an Authorization header (they go via plain
  // anchor click), so the token rides on the query string instead.
  return withToken(`/api/sessions/${sessionId}/export?${qs.toString()}`);
};

export const exportSession = (
  sessionId: string,
  format: 'csv' | 'jsonl',
  filters: Record<string, string | string[] | undefined> = {},
) => exportUrl(sessionId, format, filters);

export const fetchSession = (sessionId: string): Promise<Session> =>
  api<Session>(`/api/sessions/${sessionId}`);
