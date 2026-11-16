"use client";

import { useEffect, useState } from "react";

const PUBLIC_KEY = process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY ?? "";

type Status = { enabled: boolean; subscribed: boolean; kinds: Record<string, string>; settings: Record<string, boolean> };
type Support = "checking" | "unsupported" | "ios-browser" | "ok";

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function post(action: string, body: unknown) {
  return fetch(`/api/push/${action}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
}

function detectSupport(): Support {
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const standalone = window.matchMedia("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
  if (ios && !standalone) return "ios-browser";
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported";
  return "ok";
}

/** "Turn on notifications" for this device. Hidden when the keys are not set up. */
export function NotificationSettings({ asset }: { asset: string }) {
  const [support, setSupport] = useState<Support>("checking");
  const [status, setStatus] = useState<Status | null>(null);
  const [endpoint, setEndpoint] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (!PUBLIC_KEY) return;
    const s = detectSupport();
    setSupport(s);
    (async () => {
      let current: string | null = null;
      if (s === "ok") {
        const reg = await navigator.serviceWorker.register("/sw.js").catch(() => null);
        current = (await reg?.pushManager.getSubscription())?.endpoint ?? null;
        setEndpoint(current);
      }
      const response = await post("status", current ? { endpoint: current } : null).catch(() => null);
      if (response?.ok) setStatus(await response.json());
    })();
  }, []);

  if (!PUBLIC_KEY || (status && !status.enabled)) return null;

  async function turnOn() {
    setBusy(true);
    setMessage(null);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setMessage({ tone: "error", text: "Notifications are blocked for this site. Allow them in the browser's site settings, then try again." });
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(PUBLIC_KEY) }));
      const response = await post("subscribe", sub.toJSON());
      if (!response.ok) throw new Error();
      setEndpoint(sub.endpoint);
      setStatus((s) => (s ? { ...s, subscribed: true } : s));
      setMessage({ tone: "ok", text: "Notifications are on for this device." });
    } catch {
      setMessage({ tone: "error", text: "Couldn't turn notifications on. Try again." });
    } finally {
      setBusy(false);
    }
  }

  async function turnOff() {
    setBusy(true);
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await post("unsubscribe", { endpoint: sub.endpoint }).catch(() => null);
      await sub.unsubscribe().catch(() => null);
    }
    setEndpoint(null);
    setStatus((s) => (s ? { ...s, subscribed: false } : s));
    setMessage({ tone: "ok", text: "Notifications are off for this device." });
    setBusy(false);
  }

  async function test() {
    if (!endpoint) return;
    setBusy(true);
    const response = await post("test", { endpoint }).catch(() => null);
    const body = response ? await response.json().catch(() => ({})) : {};
    setMessage({ tone: response?.ok && body.sent ? "ok" : "error", text: body.message ?? "Couldn't send a test." });
    setBusy(false);
  }

  async function toggle(kind: string, on: boolean) {
    if (!status) return;
    setStatus({ ...status, settings: { ...status.settings, [kind]: on } });
    const response = await fetch("/api/settings/alerts", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ kinds: { [kind]: on } }),
    }).catch(() => null);
    if (!response?.ok) setMessage({ tone: "error", text: "Couldn't save that switch." });
  }

  const subscribed = !!endpoint && !!status?.subscribed;
  const button = "min-h-11 rounded-xl px-4 text-sm font-semibold disabled:opacity-50";

  return (
    <div>
      {support === "ios-browser" ? (
        <div className="text-[15px]">
          <p>On iPhone and iPad, notifications work only from the app on your Home Screen:</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5">
            <li>Tap the Share button at the bottom of Safari.</li>
            <li>Choose &ldquo;Add to Home Screen&rdquo;, then &ldquo;Add&rdquo;.</li>
            <li>Open Metal Advisor from the new icon on your Home Screen.</li>
            <li>Come back to Settings and tap &ldquo;Turn on notifications&rdquo;.</li>
          </ol>
        </div>
      ) : support === "unsupported" ? (
        <p className="text-[15px] text-ink-2">This browser can&apos;t show notifications from the app.</p>
      ) : (
        <>
          <p className="text-[15px]">
            This device: <span className="font-semibold">{subscribed ? "notifications on" : "notifications off"}</span>
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {subscribed ? (
              <>
                <button type="button" disabled={busy} onClick={test} className={`${button} bg-accent text-on-accent hover:bg-accent-hover`}>
                  Send a test
                </button>
                <button type="button" disabled={busy} onClick={turnOff} className={`${button} border border-line font-medium hover:bg-hover`}>
                  Turn off
                </button>
              </>
            ) : (
              <button type="button" disabled={busy || support !== "ok"} onClick={turnOn} className={`${button} bg-accent text-on-accent hover:bg-accent-hover`}>
                Turn on notifications
              </button>
            )}
          </div>
        </>
      )}
      {message && <p role="status" className={`mt-2 text-sm ${message.tone === "error" ? "text-wait" : "text-buy"}`}>{message.text}</p>}
      {status && (
        <fieldset className="mt-4">
          <legend className="text-sm font-medium">Tell me when</legend>
          <ul className="mt-1">
            {Object.entries(status.kinds)
              .filter(([kind]) => kind !== "trade" || asset === "silver")
              .map(([kind, label]) => (
                <li key={kind}>
                  <label className="flex min-h-11 items-center gap-3 text-[15px]">
                    <input type="checkbox" className="size-5 accent-[var(--color-accent)]" checked={status.settings[kind] ?? true} onChange={(e) => toggle(kind, e.target.checked)} />
                    {label}
                  </label>
                </li>
              ))}
          </ul>
          <p className="mt-1 text-xs text-ink-2">Checked every 30 minutes, so a notification can be up to 30 minutes late. Switches apply to all your devices.</p>
        </fieldset>
      )}
    </div>
  );
}
