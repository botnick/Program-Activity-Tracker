import { useCallback, useEffect, useRef, useState } from 'react';
import type { ToastMessage } from '../types';

type PushArgs = Omit<ToastMessage, 'id'> & { id?: string };

export function useToasts() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const timersRef = useRef<Map<string, number>>(new Map());

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((t) => t.id !== id));
    const timer = timersRef.current.get(id);
    if (timer !== undefined) {
      window.clearTimeout(timer);
      timersRef.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (toast: PushArgs) => {
      const id = toast.id ?? `toast-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const ttl = toast.ttl ?? 4000;
      const next: ToastMessage = { ...toast, id, ttl };
      setToasts((current) => [...current.filter((t) => t.id !== id), next]);
      if (ttl > 0) {
        const handle = window.setTimeout(() => dismiss(id), ttl);
        timersRef.current.set(id, handle);
      }
      return id;
    },
    [dismiss],
  );

  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      timers.forEach((handle) => window.clearTimeout(handle));
      timers.clear();
    };
  }, []);

  return { toasts, push, dismiss };
}
