"use client";

import { useEffect, useState } from "react";

import { applyTheme, storedTheme, type ThemeChoice } from "@/lib/theme";

const CHOICES: { id: ThemeChoice; label: string }[] = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" },
  { id: "system", label: "Same as phone" },
];

/** Dark, light, or follow the device. Saved on this device only. */
export function ThemeChoiceControl() {
  const [choice, setChoice] = useState<ThemeChoice | null>(null);
  useEffect(() => setChoice(storedTheme()), []);
  return (
    <div role="group" aria-label="Appearance" className="inline-flex flex-wrap rounded-xl border border-line bg-panel p-1">
      {CHOICES.map((c) => (
        <button
          key={c.id}
          type="button"
          aria-pressed={choice === c.id}
          onClick={() => {
            applyTheme(c.id);
            setChoice(c.id);
          }}
          className={`min-h-11 rounded-lg px-4 text-[15px] transition-colors ${
            choice === c.id ? "bg-accent-soft font-semibold text-accent-hover" : "text-ink-2 hover:bg-hover hover:text-ink"
          }`}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}
