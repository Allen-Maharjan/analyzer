/** Shown immediately while the server prepares the page (for example after switching asset). */
export default function Loading() {
  return (
    <div className="mx-auto max-w-2xl px-4 pt-16" aria-busy="true" aria-live="polite">
      <span className="sr-only">Loading the latest advice…</span>
      <div className="animate-pulse space-y-4">
        <div className="h-40 rounded-2xl bg-line/60" />
        <div className="h-56 rounded-2xl bg-line/50" />
        <div className="h-40 rounded-2xl bg-line/40" />
      </div>
    </div>
  );
}
