/** Three-part bar: chance gold ends lower / about the same / higher. */
export function ScenarioBar({ p }: { p: Record<string, number> }) {
  const parts = [
    { key: "bearish", label: "Lower", color: "bg-wait" },
    { key: "neutral", label: "About the same", color: "bg-ink-2/35" },
    { key: "bullish", label: "Higher", color: "bg-buy" },
  ];
  return (
    <div>
      <div className="flex h-2 overflow-hidden rounded-full bg-line" aria-hidden>
        {parts.map((part) => (
          <div key={part.key} className={part.color} style={{ width: `${(p[part.key] ?? 0) * 100}%` }} />
        ))}
      </div>
      <p className="num mt-1.5 flex justify-between text-xs text-ink-2">
        {parts.map((part) => (
          <span key={part.key}>
            {part.label} {Math.round((p[part.key] ?? 0) * 100)}%
          </span>
        ))}
      </p>
    </div>
  );
}
