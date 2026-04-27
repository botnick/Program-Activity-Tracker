export type Session = {
  session_id: string;
  exe_path: string;
  pid: number;
  created_at: string;
  status: string;
  capture: string;
  capture_error?: string | null;
};

export type ActivityEvent = {
  id: string;
  session_id: string;
  timestamp: string;
  kind: string;
  pid?: number | null;
  ppid?: number | null;
  path?: string | null;
  target?: string | null;
  operation?: string | null;
  details?: Record<string, unknown>;
};

export type ProcessInfo = {
  pid: number;
  ppid?: number | null;
  name?: string | null;
  exe?: string | null;
  username?: string | null;
};

export type ProcessList = {
  items: ProcessInfo[];
  admin: boolean;
};

export const KINDS = ['file', 'registry', 'process', 'network'] as const;
export type Kind = (typeof KINDS)[number];

export type EventQueryParams = {
  kind?: string;
  pid?: number;
  since?: string;
  until?: string;
  q?: string;
  limit?: number;
  offset?: number;
};

export type ToastKind = 'info' | 'error' | 'success';

export type ToastMessage = {
  id: string;
  kind: ToastKind;
  message: string;
  ttl?: number;
  action?: { label: string; run: () => void };
};

export function captureBadge(capture: string): { label: string; cls: string } {
  if (capture === 'live')
    return { label: 'live', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' };
  if (capture === 'needs_admin')
    return {
      label: 'needs admin',
      cls: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
    };
  if (capture === 'failed')
    return { label: 'failed', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/40' };
  if (capture === 'stopped')
    return { label: 'stopped', cls: 'bg-slate-500/15 text-slate-300 border-slate-500/40' };
  return { label: capture, cls: 'bg-slate-500/15 text-slate-300 border-slate-500/40' };
}
