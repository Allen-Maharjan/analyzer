"use client";

import { useEffect, useState } from "react";

export type ThemeChoice = "dark" | "light" | "system";
export const THEME_KEY = "theme";
export const DEFAULT_THEME: ThemeChoice = "dark";

/** Runs in <head> before the first paint, so the page never flashes the wrong theme. */
export const THEME_SCRIPT = `(function(){var d=document.documentElement,m=matchMedia("(prefers-color-scheme: light)");function c(){try{return localStorage.getItem("${THEME_KEY}")||"${DEFAULT_THEME}"}catch(e){return "${DEFAULT_THEME}"}}function a(){var p=c();d.dataset.theme=p==="system"?(m.matches?"light":"dark"):p}a();m.addEventListener&&m.addEventListener("change",a);window.addEventListener("storage",a)})()`;

export function applyTheme(choice: ThemeChoice) {
  try {
    localStorage.setItem(THEME_KEY, choice);
  } catch {}
  const light = choice === "system" ? matchMedia("(prefers-color-scheme: light)").matches : choice === "light";
  document.documentElement.dataset.theme = light ? "light" : "dark";
}

export function storedTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(THEME_KEY);
    return v === "light" || v === "system" || v === "dark" ? v : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

/** A colour token's value, for canvas drawing (charts) where CSS variables can't be used directly. */
export function cssColor(value: string): string {
  const m = /^var\((--[\w-]+)\)$/.exec(value);
  if (!m || typeof document === "undefined") return value;
  return getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim() || "#888888";
}

/** The theme in use ("dark" | "light"); changes re-render, so charts can redraw in the new colours. */
export function useResolvedTheme(): string {
  const [theme, setTheme] = useState("dark");
  useEffect(() => {
    const el = document.documentElement;
    const read = () => setTheme(el.dataset.theme ?? "dark");
    read();
    const observer = new MutationObserver(read);
    observer.observe(el, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);
  return theme;
}
