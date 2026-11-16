/** Shown immediately while the server works out the track record. */
export default function Loading() {
  return (
    <div className="mx-auto max-w-2xl px-4 lg:max-w-6xl pt-16" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading the track record…</span>
      <div className="animate-pulse space-y-4">
        <div className="h-28 rounded-2xl bg-line/60" />
        <div className="h-72 rounded-2xl bg-line/50" />
        <div className="h-72 rounded-2xl bg-line/40" />
      </div>
    </div>
  );
}
