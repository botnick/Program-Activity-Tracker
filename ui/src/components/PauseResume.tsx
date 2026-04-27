type Props = {
  paused: boolean;
  setPaused: (value: boolean) => void;
  bufferedCount: number;
};

export function PauseResume({ paused, setPaused, bufferedCount }: Props) {
  return (
    <button
      onClick={() => setPaused(!paused)}
      className={`flex items-center gap-2 rounded-lg border px-3 py-1 text-xs transition ${
        paused
          ? 'border-amber-500/60 bg-amber-500/10 text-amber-200'
          : 'border-slate-700 bg-slate-950 text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200'
      }`}
      title={paused ? 'Resume the live stream' : 'Pause the live stream'}
    >
      <span aria-hidden="true">{paused ? '▶' : '⏸'}</span>
      <span>{paused ? 'Resume' : 'Pause'}</span>
      {paused && bufferedCount > 0 && (
        <span className="rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium">
          +{bufferedCount}
        </span>
      )}
    </button>
  );
}
