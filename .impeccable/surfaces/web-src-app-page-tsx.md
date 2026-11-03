---
version: 1
slug: "web-src-app-page-tsx"
primary_target: "web/src/app/page.tsx"
related_targets: []
---

# Surface: dashboard (web/)

Mode: Operate. Phone-first owner dashboard: Today (overview), Details (behind "View detailed analysis"), Settings, Login.

Audience and job: one non-trader owner checks on a phone during the day whether to buy gold now, wait, or keep watching.

Constraints: plain words first; technical detail only on Details. Green BUY, red WAIT, amber WATCH CLOSELY, always with icon and text. Every number shows its age. No demo data; empty and loading states instead.

## Direction contract

THESIS: A calm, standard personal-finance screen whose first answer is the advice itself; it refuses the trading-terminal default of charts and tickers first.
OWN-WORLD: Category standard played straight (user chose "Plain and standard"). Light warm-neutral ground, white panels with 1px hairline borders, one ochre-gold brand accent for actions and focus, state colours only for the decision. System UI sans, tabular numerals for prices, Lucide icons.
STORY: The owner reads one word and one sentence, sees today's Nepal price and how old it is, reads up to five plain reasons, and either acts, waits, or taps through to detail.
FIRST VIEWPORT: Top bar with name, Refresh, and Today/Details/Settings tabs. Decision panel full width: status pill, headline at ~28px, summary sentence, how-sure and next-check line. Directly under it, Nepal price Rs per tola large with a 30-update line showing recent history. Reasons start just above the fold on a 390px phone.
FORM: Canon (standing exit taken), seed key f7dfdf1f.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
