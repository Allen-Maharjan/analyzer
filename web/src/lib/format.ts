const NPT = "Asia/Kathmandu";

/** Nepali digit grouping: 274300 -> "Rs 2,74,300". */
export function rupees(value: number | null | undefined): string {
  if (value == null) return "—";
  const n = Math.round(Math.abs(value)).toString();
  const tail = n.slice(-3);
  let head = n.slice(0, -3);
  const groups: string[] = [];
  while (head.length > 2) {
    groups.unshift(head.slice(-2));
    head = head.slice(0, -2);
  }
  if (head) groups.unshift(head);
  return `${value < 0 ? "−" : ""}Rs ${[...groups, tail].join(",")}`;
}

export function usd(value: number | null | undefined): string {
  if (value == null) return "—";
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value == null) return "—";
  const v = value * 100;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(digits)}%`;
}

export function nepalTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: NPT,
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(iso));
}

export function nepalDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  return new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", weekday: "short", day: "numeric", month: "short" }).format(
    new Date(`${isoDate.slice(0, 10)}T00:00:00Z`),
  );
}

/** "3 Nov, 2:15 pm · 4 min ago": when something was worked out, as a date and as an age. */
export function stamp(iso: string | null | undefined): string {
  if (!iso) return "not yet";
  return `${nepalTime(iso)} · ${ago(iso)}`;
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}
