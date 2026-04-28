import { memo } from 'react';

type Props = {
  admin: boolean | null;
  connected: boolean;
};

function AdminBannerInner({ admin, connected }: Props) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={`pill text-[11px] ${
          connected
            ? 'border-success/40 bg-success/10 text-success'
            : 'text-muted'
        }`}
      >
        {connected ? <span className="live-dot" aria-hidden /> : <span className="h-2 w-2 rounded-full bg-faint" aria-hidden />}
        {connected ? 'live' : 'idle'}
      </span>
      <span
        className={`pill text-[11px] ${
          admin
            ? 'border-success/40 bg-success/10 text-success'
            : admin === false
              ? 'border-warning/40 bg-warning/10 text-warning'
              : 'text-muted'
        }`}
      >
        <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2 4 5v6c0 5 3.5 9 8 11 4.5-2 8-6 8-11V5l-8-3z" />
        </svg>
        {admin === null ? 'admin · ?' : admin ? 'admin · yes' : 'admin · no'}
      </span>
    </div>
  );
}

export const AdminBanner = memo(AdminBannerInner);

function AdminWarningInner({ admin }: { admin: boolean | null }) {
  if (admin !== false) return null;
  return (
    <div className="mb-3 mt-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm text-warning fade-in">
      <strong className="font-semibold">Not running as Administrator.</strong>{' '}
      ETW kernel providers can&apos;t be enabled — sessions will be created but no events will stream. Restart the backend in an elevated shell.
    </div>
  );
}

export const AdminWarning = memo(AdminWarningInner);
