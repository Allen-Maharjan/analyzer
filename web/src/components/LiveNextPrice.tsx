"use client";

import { useEffect, useState } from "react";

import type { components } from "@/lib/api-types";
import { ageWords, nepalTime, rupees, usd } from "@/lib/format";

type NextPrice = components["schemas"]["NepalNextOut"];
type Live = components["schemas"]["LiveOut"];

const EVERY_MS = 60_000;

/**
 * "World gold now" with its age, and Nepal's expected next price worked out from that live price.
 * Refreshes every minute while the tab is visible. When no live price is available it shows the
 * snapshot's numbers with their real age and no "live" label.
 */
export function LiveNextPrice({
  asset,
  label,
  nepalPrice,
  snapshotNext,
  snapshotWorld,
  snapshotAt,
}: {
  asset: string;
  label: string;
  nepalPrice: number | null;
  snapshotNext: NextPrice | null;
  snapshotWorld: number | null;
  snapshotAt: string;
}) {
  const [live, setLive] = useState<Live | null>(null);
  const [now, setNow] = useState<number | null>(null); // set after mount, so server and client render alike

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (document.visibilityState !== "visible") return;
      const response = await fetch(`/api/live?asset=${encodeURIComponent(asset)}`, { cache: "no-store" }).catch(() => null);
      const body = response?.ok ? ((await response.json().catch(() => null)) as Live | null) : null;
      if (!cancelled) setLive(body);
    }
    setNow(Date.now());
    load();
    const timer = setInterval(load, EVERY_MS);
    const tick = setInterval(() => setNow(Date.now()), 10_000);
    const onVisible = () => document.visibilityState === "visible" && load();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      clearInterval(timer);
      clearInterval(tick);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [asset]);

  const isLive = !!live?.available && live.price != null && live.observed_at != null;
  const world = isLive ? live!.price! : snapshotWorld;
  const worldAt = isLive ? live!.observed_at! : snapshotAt;
  const ageOf = (iso: string) => (now == null ? null : ageWords(Math.max(0, (now - new Date(iso).getTime()) / 1000)));
  const worldAge = ageOf(worldAt);
  const next = (isLive ? live!.nepal_next : null) ?? snapshotNext;
  const nextIsLive = isLive && !!live!.nepal_next;
  const nextChange = next && nepalPrice != null ? next.estimate - nepalPrice : 0;

  return (
    <>
      {world != null && (
        <p className="num mt-3 text-sm text-ink-2">
          {isLive ? (live!.market_open ? `World ${label} now` : `World ${label} at the market close`) : `World ${label} at the last check`}:{" "}
          <span className="font-medium text-ink">{usd(world)}</span> per ounce{worldAge && ` · ${worldAge} ago`}
        </p>
      )}
      {next && (
        <div className="mt-4 rounded-xl border border-line bg-inset px-4 py-3">
          <p className="text-sm text-ink-2">
            Expected at Nepal&apos;s next update · <span className="num">{nepalTime(next.publish_at)}</span>
            {nextIsLive && <span className="ml-1.5 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-medium text-accent-hover">live</span>}
          </p>
          <p className="num mt-0.5 text-lg font-semibold">
            about {rupees(next.estimate)}
            {nextChange !== 0 && (
              <span className={`ml-2 whitespace-nowrap text-sm font-medium ${nextChange > 0 ? "text-buy" : "text-wait"}`}>
                {nextChange > 0 ? "up" : "down"} {rupees(Math.abs(nextChange))}
              </span>
            )}
          </p>
          <p className="num text-xs leading-relaxed text-ink-2">
            Likely between {rupees(next.low)} and {rupees(next.high)} (about 8 in 10 times). Based on how world {label} and the dollar
            have moved since today&apos;s price was set{nextIsLive ? ", using the world price above" : `, as of ${ageOf(snapshotAt) ?? "the last check"}${now == null ? "" : " ago"}`}.
          </p>
        </div>
      )}
    </>
  );
}
