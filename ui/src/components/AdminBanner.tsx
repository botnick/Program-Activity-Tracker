type Props = {
  admin: boolean | null;
  connected: boolean;
};

export function AdminBanner({ admin, connected }: Props) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <span
        className={`rounded-full border px-3 py-1 ${
          connected
            ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
            : 'border-slate-700 bg-slate-900 text-slate-400'
        }`}
      >
        {connected ? 'stream connected' : 'stream idle'}
      </span>
      <span
        className={`rounded-full border px-3 py-1 ${
          admin
            ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
            : admin === false
              ? 'border-amber-500/40 bg-amber-500/10 text-amber-300'
              : 'border-slate-700 bg-slate-900 text-slate-400'
        }`}
      >
        {admin === null ? 'admin: ?' : admin ? 'admin: yes' : 'admin: no'}
      </span>
    </div>
  );
}

export function AdminWarning({ admin }: { admin: boolean | null }) {
  if (admin !== false) return null;
  return (
    <div className="mt-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
      Backend is not running as Administrator. ETW kernel providers cannot be enabled — sessions
      will be created but no real events will stream. Restart the backend in an elevated shell.
    </div>
  );
}
