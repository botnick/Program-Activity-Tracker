import { exportUrl } from '../api';
import type { ToastMessage } from '../types';

type Props = {
  sessionId?: string;
  filters: Record<string, string | string[] | undefined>;
  onToast: (msg: Omit<ToastMessage, 'id'>) => void;
};

export function ExportButtons({ sessionId, filters, onToast }: Props) {
  const disabled = !sessionId;

  const startDownload = (format: 'csv' | 'jsonl') => {
    if (!sessionId) return;
    const url = exportUrl(sessionId, format, filters);
    window.open(url, '_blank', 'noopener,noreferrer');
    onToast({ kind: 'info', message: `Download started (${format.toUpperCase()})` });
  };

  return (
    <div className="flex items-center gap-1 text-xs">
      <button
        disabled={disabled}
        onClick={() => startDownload('csv')}
        className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-1 text-slate-300 transition hover:border-cyan-500/60 hover:text-cyan-200 disabled:opacity-40"
      >
        CSV
      </button>
      <button
        disabled={disabled}
        onClick={() => startDownload('jsonl')}
        className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-1 text-slate-300 transition hover:border-cyan-500/60 hover:text-cyan-200 disabled:opacity-40"
      >
        JSONL
      </button>
    </div>
  );
}
