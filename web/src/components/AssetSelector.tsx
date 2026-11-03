"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import type { Asset } from "@/lib/asset";

/** Gold / Silver switch. A segmented control: two choices, both always visible. */
export function AssetSelector({ asset }: { asset: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [pending, startTransition] = useTransition();
  const [target, setTarget] = useState(asset);
  useEffect(() => { fetch("/api/assets").then(r => r.ok ? r.json() : []).then(setAssets).catch(() => {}); }, []);
  useEffect(() => setTarget(asset), [asset]);
  // Warm up the other assets' pages so a switch shows content sooner.
  useEffect(() => {
    for (const a of assets) if (a.id !== asset) router.prefetch(`${pathname}?asset=${encodeURIComponent(a.id)}`);
  }, [assets, asset, pathname, router]);

  // One choice is not a choice: show nothing until there are at least two metals.
  if (assets.length < 2) return <div className="mb-4 min-h-11" aria-hidden />;

  return (
    <div role="group" aria-label="Metal" aria-busy={pending} className="mb-4 inline-flex rounded-xl border border-line bg-panel p-1">
      {assets.map((a) => {
        const active = a.id === target;
        return (
          <button
            key={a.id}
            type="button"
            aria-pressed={active}
            onClick={() => {
              if (a.id === asset) return;
              setTarget(a.id);
              startTransition(() => router.push(`${pathname}?asset=${encodeURIComponent(a.id)}`));
            }}
            className={`min-h-9 min-w-20 rounded-lg px-4 text-[15px] transition-colors ${
              active ? "bg-accent-soft font-semibold text-accent-hover" : "text-ink-2 hover:bg-hover hover:text-ink"
            }`}
          >
            {a.label}
          </button>
        );
      })}
    </div>
  );
}
