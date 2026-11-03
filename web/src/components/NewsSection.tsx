"use client";

import { ChevronDown, ExternalLink, Flag, RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { ago, nepalTime } from "@/lib/format";
import type { NewsOverview } from "@/lib/news";

const STATE_WORDS: Record<string, string> = {
  fresh: "Updated",
  stale: "Out of date, last updated",
  empty: "No recent news found",
  unavailable: "News isn't available right now",
  pending: "Looking for news…",
};

/** Stories shown before "Show more": enough to get the mood without burying the page. */
const FIRST_STORIES = 3;

export function NewsSection({ news, asset, label }: { news: NewsOverview; asset: string; label: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [flagging, setFlagging] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [showAll, setShowAll] = useState(false);
  const q = `?asset=${encodeURIComponent(asset)}`;

  async function post(path: string, body?: unknown) {
    setBusy(true);
    setMessage(null);
    const response = await fetch(`${path}${q}`, {
      method: "POST",
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    const data = await response?.json().catch(() => ({}));
    setBusy(false);
    if (response?.status === 401) {
      window.location.assign("/login");
      return null;
    }
    if (!response || (!response.ok && response.status !== 429)) {
      setMessage({ tone: "error", text: data?.detail ?? data?.message ?? "That didn't work. Try again shortly." });
      return null;
    }
    return data ?? {};
  }

  async function refresh() {
    const data = await post("/api/news/refresh");
    if (data) setMessage({ tone: "ok", text: data.message ?? "Looking for news." });
  }

  async function flag(articleId: string) {
    const data = await post("/api/news/risk", { article_id: articleId, reason });
    if (data) {
      setFlagging(null);
      setReason("");
      router.refresh();
    }
  }

  async function clear() {
    if (await post("/api/news/risk/clear")) router.refresh();
  }

  const s = news.status;
  const cited = new Set(news.ai?.cited ?? []);
  // Keep a story that is being flagged visible even when the list is collapsed.
  const visible = showAll ? news.articles : news.articles.filter((a, i) => i < FIRST_STORIES || a.id === flagging);
  const hidden = news.articles.length - visible.length;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-ink-2">
          {s.refreshing ? STATE_WORDS.pending : STATE_WORDS[s.state] ?? s.state}
          {s.refreshed_at && (s.state === "fresh" || s.state === "stale") ? ` ${ago(s.refreshed_at)}` : ""}
          {s.last_attempt_failed && !s.refreshing ? " · the last check failed" : ""}
        </p>
        <button
          type="button"
          onClick={refresh}
          disabled={busy}
          className="inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-line bg-panel px-3 text-sm font-medium transition-colors hover:bg-hover disabled:cursor-wait disabled:opacity-60"
        >
          <RefreshCw aria-hidden className={`size-4 ${busy ? "animate-spin" : ""}`} strokeWidth={1.75} />
          Check news
        </button>
      </div>

      {news.risk && (
        <div className="mb-4 rounded-xl border border-wait/20 bg-wait-soft p-4 text-[15px]">
          <p>
            <span className="font-semibold">You marked a news story as a reason to wait.</span> “{news.risk.reason}”
          </p>
          <p className="mt-1 text-sm text-ink-2">Ends {nepalTime(news.risk.expires_at)}, when the story is a day old.</p>
          <button type="button" onClick={clear} disabled={busy} className="mt-2 min-h-11 text-sm font-medium underline underline-offset-4">
            Clear this
          </button>
        </div>
      )}

      {news.ai && (
        <div className="mb-4">
          <p className="max-w-[65ch] text-[17px] leading-relaxed">{news.ai.summary}</p>
          <p className="mt-1 text-xs text-ink-2">AI summary of the articles marked below · {ago(news.ai.finished_at)}</p>
        </div>
      )}

      {news.articles.length === 0 ? (
        <p className="text-ink-2">No {label} news saved yet. News is checked each time Nepal's price changes.</p>
      ) : (
        <ul className="-mb-1 divide-y divide-line border-t border-line">
          {visible.map((a) => (
            <li key={a.id} className="py-3">
              <a href={a.url} target="_blank" rel="noopener noreferrer nofollow" className="group inline-flex items-start gap-1.5 font-medium leading-snug hover:underline">
                {a.title}
                <ExternalLink aria-hidden className="mt-1 size-3.5 shrink-0 text-ink-2" strokeWidth={1.75} />
              </a>
              <p className="mt-0.5 text-xs text-ink-2">
                {a.publisher} · {ago(a.published_at)}
                {cited.has(a.id) ? " · used in the AI summary" : ""}
              </p>
              {a.excerpt && <p className="mt-1 line-clamp-2 text-sm leading-relaxed text-ink-2">{a.excerpt}</p>}
              {a.can_flag && !news.risk && flagging !== a.id && (
                <button
                  type="button"
                  onClick={() => setFlagging(a.id)}
                  className="-mb-2 inline-flex min-h-11 items-center gap-1.5 text-sm text-ink-2 transition-colors hover:text-ink"
                >
                  <Flag aria-hidden className="size-3.5" strokeWidth={1.75} /> This is a reason to wait
                </button>
              )}
              {flagging === a.id && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    flag(a.id);
                  }}
                  className="mt-2 grid gap-3 rounded-xl border border-line bg-ground p-3"
                >
                  <label className="grid gap-1 text-sm">
                    <span className="font-medium">Why does this make you want to wait?</span>
                    <input
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      maxLength={300}
                      required
                      className="min-h-11 rounded-xl border border-line bg-panel px-3 text-base"
                    />
                  </label>
                  <p className="text-xs text-ink-2">If the advice says Buy, it will say Wait until this story is a day old or you clear it.</p>
                  <div className="flex gap-2">
                    <button type="submit" disabled={busy || !reason.trim()} className="min-h-11 rounded-xl bg-accent px-4 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:opacity-60">
                      Save
                    </button>
                    <button type="button" onClick={() => setFlagging(null)} className="min-h-11 rounded-xl border border-line bg-panel px-4 text-sm font-medium transition-colors hover:bg-hover">
                      Cancel
                    </button>
                  </div>
                </form>
              )}
            </li>
          ))}
        </ul>
      )}
      {(hidden > 0 || (showAll && news.articles.length > FIRST_STORIES)) && (
        <button
          type="button"
          onClick={() => setShowAll(!showAll)}
          aria-expanded={showAll}
          className="mt-1 inline-flex min-h-11 w-full items-center justify-center gap-1.5 rounded-xl border border-line text-sm font-medium text-ink-2 transition-colors hover:bg-hover hover:text-ink"
        >
          {showAll ? "Show fewer stories" : `Show ${hidden} more ${hidden === 1 ? "story" : "stories"}`}
          <ChevronDown aria-hidden className={`size-4 transition-transform ${showAll ? "rotate-180" : ""}`} strokeWidth={1.75} />
        </button>
      )}
      {message && (
        <p role="status" className={`mt-3 text-sm ${message.tone === "error" ? "text-wait" : "text-ink-2"}`}>
          {message.text}
        </p>
      )}
    </div>
  );
}
