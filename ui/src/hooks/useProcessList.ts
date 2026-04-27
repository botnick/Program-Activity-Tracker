import { useEffect, useState } from 'react';
import { api } from '../api';
import type { ProcessInfo, ProcessList } from '../types';

export function useProcessList() {
  const [processes, setProcesses] = useState<ProcessInfo[]>([]);
  const [admin, setAdmin] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const refresh = async () => {
      try {
        const result = await api<ProcessList>('/api/processes');
        if (cancelled) return;
        setProcesses(result.items);
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
