import { CalendarClock } from "lucide-react";

import type { components } from "@/lib/api-types";
import { nepalDate, nepalTime, rupees } from "@/lib/format";

type Position = components["schemas"]["PositionOut"];
type KeyLevel = components["schemas"]["KeyLevelOut"];
type Announcements = components["schemas"]["AnnouncementsOut"];
type Split = components["schemas"]["SplitOut"];
type SecondHalf = components["schemas"]["SecondHalfOut"];

const LEVEL_STATE_WORDS: Record<string, string> = {
  touch: "being tested now",
  intrabar_breach: "price is past it now, not yet confirmed",
  confirmed_break: "broken",
  retest: "broken, being tested again",
  reclaim: "broken, then recovered",
};

function held(level: KeyLevel): string {
  if (level.manual) return "your watch level";
  if (level.touches <= 1) return "held once";
  if (level.touches === 2) return "held twice";
  return `held ${level.touches} times`;
}

export function PositionFacts({ position, label }: { position: Position; label: string }) {
  return (
    <>
      {position.plain && <p className="text-[17px] leading-relaxed">{position.plain}</p>}
      {position.nepal_low != null && position.nepal_high != null && (
        <dl className="num mt-3 grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-xl border border-line bg-inset px-3 py-2">
            <dt className="text-ink-2">Lowest of the last {position.nepal_publications} updates</dt>
            <dd className="mt-0.5 font-semibold">{rupees(position.nepal_low)}</dd>
            <dd className="text-xs text-ink-2">{nepalDate(position.nepal_low_date)}</dd>
          </div>
          <div className="rounded-xl border border-line bg-inset px-3 py-2">
            <dt className="text-ink-2">Highest of the last {position.nepal_publications} updates</dt>
            <dd className="mt-0.5 font-semibold">{rupees(position.nepal_high)}</dd>
            <dd className="text-xs text-ink-2">{nepalDate(position.nepal_high_date)}</dd>
          </div>
        </dl>
      )}
      <p className="mt-3 text-xs text-ink-2">Nepal {label} per tola, from FENEGOSIDA&apos;s published prices.</p>
    </>
  );
}

export function KeyLevels({ levels }: { levels: KeyLevel[] }) {
  const floors = levels.filter((l) => l.kind === "floor" && l.rupees != null);
  const ceilings = levels.filter((l) => l.kind === "ceiling" && l.rupees != null);
  const row = (l: KeyLevel) => (
    <li key={`${l.kind}-${l.world_price}`} className="flex flex-wrap items-baseline justify-between gap-x-3 py-2">
      <span>
        {l.kind === "floor" ? "Floor" : "Ceiling"} about <span className="num font-semibold">{rupees(l.rupees)}</span>{" "}
        <span className="text-ink-2">({held(l)})</span>
      </span>
      {LEVEL_STATE_WORDS[l.state] && <span className="text-sm text-ink-2">{LEVEL_STATE_WORDS[l.state]}</span>}
    </li>
  );
  return (
    <>
      {ceilings.length > 0 && <ul className="divide-y divide-line">{[...ceilings].reverse().map(row)}</ul>}
      {floors.length > 0 && <ul className={`divide-y divide-line ${ceilings.length ? "border-t border-line" : ""}`}>{floors.map(row)}</ul>}
      <p className="mt-3 text-xs leading-relaxed text-ink-2">
        Floors are prices where falls stopped before; ceilings are where rises stopped. They are world prices turned into Nepal rupees per
        tola, so they move a little with the dollar rate and Nepal&apos;s usual gap.
      </p>
    </>
  );
}

function cleanTitle(title: string): string {
  return title.replace(/\s*\((?:[A-Z][a-z]+ \d{4})\)$/, "");
}

export function UpcomingAnnouncements({ announcements }: { announcements: Announcements }) {
  if (announcements.calendar_stale) {
    return <p className="text-ink-2">The US economic calendar is not available, so upcoming announcements may be missed.</p>;
  }
  if (!announcements.items.length) return <p className="text-ink-2">No big US announcements in the next 30 days.</p>;
  return (
    <>
      <ul className="divide-y divide-line">
        {announcements.items.map((a) => (
          <li key={`${a.event_type}-${a.scheduled_at}`} className="py-3 first:pt-0 last:pb-0">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3">
              <span className="font-medium">{cleanTitle(a.title)}</span>
              <span className="num inline-flex items-center gap-1 text-sm text-ink-2">
                <CalendarClock aria-hidden className="size-4" strokeWidth={1.75} />
                {nepalTime(a.scheduled_at)}
              </span>
            </div>
            <p className="mt-1 text-[15px] leading-relaxed text-ink-2">{a.plain}</p>
            <p className="mt-1 text-xs font-medium">
              {a.importance === "major" ? (
                <span className="text-wait">Changes the advice: it says Wait in the day before.</span>
              ) : (
                <span className="text-ink-2">Shown as a risk; it does not change the advice by itself.</span>
              )}
            </p>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-ink-2">Times are Nepal time.</p>
    </>
  );
}

export function TwoPartPlan({ split, secondHalf }: { split?: Split | null; secondHalf?: SecondHalf | null }) {
  if (secondHalf) {
    return (
      <>
        <p className="text-[17px] leading-relaxed">{secondHalf.plain}</p>
        <p className="num mt-2 text-sm text-ink-2">
          First half bought {nepalTime(secondHalf.first_part_at)}
          {secondHalf.first_part_price != null && ` at about ${rupees(secondHalf.first_part_price)} per tola`}.
        </p>
      </>
    );
  }
  if (!split) return null;
  return (
    <>
      <p className="text-[15px] text-ink-2">{split.reason} Buy the second half when the first of these happens:</p>
      <ul className="mt-3 space-y-2 text-[17px] leading-relaxed">
        {split.triggers.map((t) => (
          <li key={t} className="flex gap-3">
            <span aria-hidden className="mt-2.5 size-1.5 shrink-0 rounded-full bg-buy" />
            <span>{t}</span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-ink-2">The last day is {split.deadline_reason}.</p>
    </>
  );
}
