import { memo } from 'react';

type Props = {
  paused: boolean;
  setPaused: (value: boolean) => void;
  bufferedCount: number;
};

function PauseResumeInner({ paused, setPaused, bufferedCount }: Props) {
  return (
    <button
      onClick={() => setPaused(!paused)}
      className={`flex items-center gap-2 rounded-lg border px-3 py-1 text-xs transition-colors ${
        paused
          ? 'border-warning/60 bg-warning/10 text-warning'
          : 'border-line bg-base text-muted hover:border-accent/60 hover:text-accent-hover'
      }`}
      title={paused ? 'Resume the live stream' : 'Pause the live stream'}
    >
      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="currentColor" aria-hidden>
        {paused ? (
          <path d="M8 5v14l11-7z" />
        ) : (
          <>
            <rect x="6" y="5" width="4" height="14" rx="1" />
            <rect x="14" y="5" width="4" height="14" rx="1" />
          </>
        )}
      </svg>
      <span>{paused ? 'Resume' : 'Pause'}</span>
      {paused && bufferedCount > 0 && (
        <span className="rounded-full bg-warning/20 px-1.5 py-0.5 text-[10px] font-medium">
          +{bufferedCount}
        </span>
      )}
    </button>
  );
}

export const PauseResume = memo(PauseResumeInner);
