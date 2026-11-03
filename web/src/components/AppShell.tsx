import { AssetSelector } from "@/components/AssetSelector";
import { Nav } from "@/components/Nav";
import { RefreshButton } from "@/components/RefreshButton";
import { stamp } from "@/lib/format";

/** Phone: one column. Large screens (1024px+): wider page so cards can sit in two columns (see CardColumns). */
const WIDTH = "max-w-2xl lg:max-w-6xl";

export function AppShell({ children, asset = "gold" }: { children: React.ReactNode; asset?: string }) {
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-10 border-b border-line bg-ground/95 backdrop-blur-sm">
        <div className={`mx-auto flex ${WIDTH} items-center justify-between gap-3 px-4 py-2`}>
          <Nav asset={asset} />
          <RefreshButton />
        </div>
      </header>
      <main className={`mx-auto ${WIDTH} px-4 pb-20 pt-4`}><AssetSelector asset={asset} />{children}</main>
    </div>
  );
}

/**
 * Two independent columns on large screens (1024px+), so each card sits right under the one above
 * it and a short card never leaves a gap beside a tall one. On phones the two lists interleave into
 * one column in reading order: left[0], right[0], left[1], right[1], ...
 *
 * How: on phones the column wrappers use `display: contents`, so every card becomes an item of the
 * single grid and its `order` sets the interleaving. On large screens each column is a flex stack.
 */
export function CardColumns({ left, right }: { left: React.ReactNode[]; right: React.ReactNode[] }) {
  const column = (cards: React.ReactNode[], side: 0 | 1) => (
    <div className="contents lg:flex lg:min-w-0 lg:flex-col lg:gap-4">
      {cards
        .filter((card) => card !== null && card !== undefined && card !== false)
        .map((card, i) => (
          <div key={i} className="min-w-0 [&>*]:mt-0" style={{ order: i * 2 + side }}>
            {card}
          </div>
        ))}
    </div>
  );
  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-2 lg:items-start">
      {column(left, 0)}
      {column(right, 1)}
    </div>
  );
}

/** A titled panel. `updated` (ISO time) shows when its numbers were worked out. */
export function Section({ title, updated, className = "", children }: { title?: string; updated?: string | null; className?: string; children: React.ReactNode }) {
  return (
    <section className={`mt-4 min-w-0 rounded-2xl border border-line bg-panel p-5 ${className}`}>
      {(title || updated) && (
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
          {title && <h2 className="text-base font-semibold">{title}</h2>}
          {updated && <p className="num text-xs text-ink-2">Updated {stamp(updated)}</p>}
        </div>
      )}
      {children}
    </section>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold">Couldn't load the advice</h1>
      <p className="mt-2 text-ink-2">{message} Try Refresh in a minute.</p>
    </div>
  );
}
