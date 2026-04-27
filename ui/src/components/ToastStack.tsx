import type { ToastMessage } from '../types';

type Props = {
  toasts: ToastMessage[];
  onDismiss: (id: string) => void;
};

function toastClass(kind: ToastMessage['kind']): string {
  if (kind === 'error') return 'border-rose-500/40 bg-rose-500/10 text-rose-200';
  if (kind === 'success') return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200';
  return 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200';
}

export function ToastStack({ toasts, onDismiss }: Props) {
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`pointer-events-auto flex items-start justify-between gap-3 rounded-xl border px-3 py-2 text-sm shadow-lg backdrop-blur ${toastClass(toast.kind)}`}
        >
          <div className="flex-1">
            <div className="leading-snug">{toast.message}</div>
            {toast.action && (
              <button
                onClick={() => {
                  toast.action?.run();
                  onDismiss(toast.id);
                }}
                className="mt-1 rounded-md border border-current px-2 py-0.5 text-xs font-medium opacity-80 hover:opacity-100"
              >
                {toast.action.label}
              </button>
            )}
          </div>
          <button
            onClick={() => onDismiss(toast.id)}
            className="text-xs opacity-70 hover:opacity-100"
            aria-label="dismiss"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
