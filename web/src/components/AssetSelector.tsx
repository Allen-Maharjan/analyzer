"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import type { Asset } from "@/lib/asset";
export function AssetSelector({ asset }: { asset: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const [assets, setAssets] = useState<Asset[]>([]);
  useEffect(() => { fetch("/api/assets").then(r => r.ok ? r.json() : []).then(setAssets).catch(() => {}); }, []);
  // Warm up the other assets' pages so a switch shows content sooner.
  useEffect(() => {
    for (const a of assets) if (a.id !== asset) router.prefetch(`${pathname}?asset=${encodeURIComponent(a.id)}`);
  }, [assets, asset, pathname, router]);
  return <label className="flex items-center gap-2 text-sm">Asset
    <select aria-label="Asset" value={asset} className="min-h-11 rounded-md border border-line bg-panel px-2"
      onChange={event => router.push(`${pathname}?asset=${encodeURIComponent(event.target.value)}`)}>
      {assets.length ? assets.map(a => <option key={a.id} value={a.id}>{a.label}</option>) : <option value={asset}>{asset}</option>}
    </select>
  </label>;
}
