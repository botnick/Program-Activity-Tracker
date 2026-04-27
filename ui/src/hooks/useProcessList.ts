import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { ProcessInfo, ProcessList } from '../types';

export function useProcessList() {
  const [processes, setProcesses] = useState<ProcessInfo[]>([]);
  const [admin, setAdmin] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Cache previous ProcessInfo objects keyed by pid so the diff-update can
  // preserve identity for unchanged rows. Combined with React.memo on the
  // child rows, this stops unchanged rows from re-rendering on every poll.
  const refMap = useRef<Map<number, ProcessInfo>>(new Map());

  useEffect(() => {
    let cancelled = false;

    const refresh = async () => {
      try {
        const result = await api<ProcessList>('/api/processes');
        if (cancelled) return;
        const next: ProcessInfo[] = [];
        const m = refMap.current;
        for (const p of result.items) {
          const prev = m.get(p.pid);
          if (
            prev &&
            prev.name === p.name &&
            prev.exe === p.exe &&
            prev.ppid === p.ppid &&
            prev.username === p.username
          ) {
            // Preserve previous reference identity — React.memo'd children skip.
            next.push(prev);
          } else {
            next.push(p);
          }
        }
        refMap.current = new Map(next.map((p) => [p.pid, p]));
        setProcesses(next);
        setAdmin(result.admin);
      } catch (err) {
        if (!cancelled) setError(String(err));
      }
    };

    refresh();
    const interval = window.setInterval(() => {
      refresh().catch(() => undefined);
    }, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  return { processes, admin, error };
}
