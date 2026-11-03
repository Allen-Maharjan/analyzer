import { CircleCheck, Eye, Hourglass } from "lucide-react";

const STYLES = {
  BUY: { icon: CircleCheck, label: "Buy", tone: "text-buy", soft: "bg-buy-soft", ring: "border-buy/20" },
  WAIT: { icon: Hourglass, label: "Wait", tone: "text-wait", soft: "bg-wait-soft", ring: "border-wait/20" },
  "WATCH CLOSELY": { icon: Eye, label: "Watch closely", tone: "text-watch", soft: "bg-watch-soft", ring: "border-watch/20" },
} as const;

export function decisionStyle(decision: string) {
  return STYLES[(decision in STYLES ? decision : "WATCH CLOSELY") as keyof typeof STYLES];
}

/** Coloured icon + word. Colour is only ever used for the decision. */
export function DecisionLabel({ decision, className = "" }: { decision: string; className?: string }) {
  const s = decisionStyle(decision);
  const Icon = s.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 font-semibold ${s.tone} ${className}`}>
      <Icon aria-hidden className="size-[1em]" strokeWidth={2} />
      {s.label}
    </span>
  );
}
