"use client";

import { Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { TRADABLE_ASSETS } from "@/lib/asset";

type Tab = { href: string; label: string; short?: string; icon?: typeof Settings };

const TABS: Tab[] = [
  { href: "/", label: "Today" },
  { href: "/details", label: "Details" },
  { href: "/track-record", label: "Track record", short: "Record" },
  { href: "/trade", label: "Trade" },
  { href: "/settings", label: "Settings", icon: Settings },
];

/** On phones (under 640 px) long labels shorten and Settings becomes an icon, so five tabs fit 360 px. */
export function Nav({ asset = "gold" }: { asset?: string }) {
  const pathname = usePathname();
  const tabs = TABS.filter((tab) => tab.href !== "/trade" || TRADABLE_ASSETS.has(asset));
  return (
    <nav aria-label="Main" className="-ml-2 flex sm:-ml-3">
      {tabs.map((tab) => {
        const active = tab.href === "/" ? pathname === "/" : pathname.startsWith(tab.href);
        const Icon = tab.icon;
        return (
          <Link
            key={tab.href}
            href={`${tab.href}?asset=${encodeURIComponent(asset)}`}
            aria-current={active ? "page" : undefined}
            aria-label={Icon ? tab.label : undefined}
            className={`inline-flex min-h-11 min-w-11 items-center justify-center whitespace-nowrap px-2 text-[15px] transition-colors sm:px-3 ${
              active ? "rounded-lg bg-accent-soft font-semibold text-accent-hover" : "text-ink-2 hover:text-ink"
            }`}
          >
            {Icon ? (
              <>
                <Icon aria-hidden className="size-5 sm:hidden" strokeWidth={1.75} />
                <span className="hidden sm:inline">{tab.label}</span>
              </>
            ) : tab.short ? (
              <>
                <span className="sm:hidden">{tab.short}</span>
                <span className="hidden sm:inline">{tab.label}</span>
              </>
            ) : (
              tab.label
            )}
          </Link>
        );
      })}
    </nav>
  );
}
