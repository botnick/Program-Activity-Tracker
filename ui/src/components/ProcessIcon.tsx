import React, { useState } from 'react';

type Props = {
  exe?: string | null;
  size?: number;
  className?: string;
};

/**
 * Renders the Windows shell icon for a given EXE path.
 *
 * The image is fetched from `/api/processes/icon?exe=<path>`. If the
 * backend can't extract a real icon it serves a 1x1 transparent PNG, so
 * we additionally swap to a generic SVG placeholder when the request
 * errors out (offline, blocked, missing exe field).
 */
export const ProcessIcon = React.memo(function ProcessIcon({
  exe,
  size = 24,
  className = '',
}: Props) {
  const [errored, setErrored] = useState(false);
  const dim = `${size}px`;

  if (!exe || errored) {
    return (
      <span
        aria-hidden
        className={`inline-flex items-center justify-center rounded bg-slate-700 text-slate-400 ${className}`}
        style={{ width: dim, height: dim }}
      >
        <svg
          viewBox="0 0 24 24"
          width={Math.round(size * 0.7)}
          height={Math.round(size * 0.7)}
          fill="currentColor"
          aria-hidden
        >
          <path d="M19 3H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2V5a2 2 0 00-2-2zm0 16H5V7h14v12z" />
        </svg>
      </span>
    );
  }

  return (
    <img
      alt=""
      loading="lazy"
      decoding="async"
      width={size}
      height={size}
      style={{ width: dim, height: dim }}
      className={`object-contain ${className}`}
      src={`/api/processes/icon?exe=${encodeURIComponent(exe)}`}
      onError={() => setErrored(true)}
    />
  );
});
