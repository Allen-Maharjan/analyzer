import { AssetSelector } from "@/components/AssetSelector";
import { Nav } from "@/components/Nav";
import { RefreshButton } from "@/components/RefreshButton";
import { stamp } from "@/lib/format";

export function AppShell({ children, asset = "gold" }: { children: React.ReactNode; asset?: string }) {
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-10 border-b border-line bg-ground/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 px-4 py-2">
          <Nav asset={asset} />
          <RefreshButton />
        </div>
      </header>
      <main className="mx-auto max-w-2xl px-4 pb-20 pt-4"><AssetSelector asset={asset} />{children}</main>
    </div>
  );
}

/** A titled panel. `updated` (ISO time) shows when its numbers were worked out. */
export function Section({ title, updated, children }: { title?: string; updated?: string | null; children: React.ReactNode }) {
  return (
    <section className="mt-4 rounded-2xl border border-line bg-panel p-5">
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
