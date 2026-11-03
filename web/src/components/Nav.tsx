"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/", label: "Today" },
  { href: "/details", label: "Details" },
  { href: "/settings", label: "Settings" },
];

export function Nav({ asset = "gold" }: { asset?: string }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="-ml-3 flex">
      {TABS.map((tab) => {
        const active = tab.href === "/" ? pathname === "/" : pathname.startsWith(tab.href);
        return (
          <Link
            key={tab.href}
            href={`${tab.href}?asset=${encodeURIComponent(asset)}`}
            aria-current={active ? "page" : undefined}
            className={`inline-flex min-h-11 items-center px-3 text-[15px] transition-colors ${
              active ? "rounded-lg bg-accent-soft font-semibold text-accent-hover" : "text-ink-2 hover:text-ink"
            }`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
