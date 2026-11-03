---
name: Gold Advisor
description: A plain personal-finance screen that tells one owner whether to buy gold in Nepal today.
colors:
  ground: "#f6f4ef"
  panel: "#ffffff"
  line: "#e4dfd4"
  ink: "#1d1b17"
  ink-2: "#57524a"
  accent: "#855700"
  accent-hover: "#6e4800"
  accent-soft: "#f5ebd5"
  buy: "#146c3a"
  buy-soft: "#e5f3ea"
  wait: "#b3261e"
  wait-soft: "#fbe9e7"
  watch: "#8a4a00"
  watch-soft: "#fcefd9"
typography:
  display:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Noto Sans Devanagari\", sans-serif"
    fontSize: "2.25rem"
    fontWeight: 600
    lineHeight: "2.5rem"
    letterSpacing: "-0.025em"
    fontFeature: "\"tnum\""
  headline:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Noto Sans Devanagari\", sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.25
    letterSpacing: "-0.025em"
  title:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Noto Sans Devanagari\", sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: "2rem"
    letterSpacing: "-0.025em"
  title-sm:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Noto Sans Devanagari\", sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: "1.5rem"
  lead:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Noto Sans Devanagari\", sans-serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.625
  body:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Noto Sans Devanagari\", sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.5
  body-sm:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Noto Sans Devanagari\", sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: "1.25rem"
  label:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Noto Sans Devanagari\", sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: "1.25rem"
  caption:
    fontFamily: "system-ui, -apple-system, \"Segoe UI\", Roboto, \"Noto Sans\", \"Noto Sans Devanagari\", sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: "1rem"
rounded:
  md: "8px"
  lg: "12px"
  full: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  2xl: "24px"
  tap: "44px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.panel}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "44px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-secondary:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "44px"
  button-secondary-hover:
    textColor: "{colors.accent}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 16px"
    height: "44px"
  button-ghost-hover:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
  input-text:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "44px"
  nav-tab:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: "0 12px"
    height: "44px"
  nav-tab-active:
    backgroundColor: "{colors.accent-soft}"
    textColor: "{colors.accent}"
  panel:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.lg}"
    padding: "16px"
  decision-panel-buy:
    backgroundColor: "{colors.buy-soft}"
    textColor: "{colors.buy}"
    rounded: "{rounded.lg}"
    padding: "16px"
  decision-panel-wait:
    backgroundColor: "{colors.wait-soft}"
    textColor: "{colors.wait}"
    rounded: "{rounded.lg}"
    padding: "16px"
  decision-panel-watch:
    backgroundColor: "{colors.watch-soft}"
    textColor: "{colors.watch}"
    rounded: "{rounded.lg}"
    padding: "16px"
  decision-pill-buy:
    backgroundColor: "{colors.buy-soft}"
    textColor: "{colors.buy}"
    rounded: "{rounded.full}"
    padding: "6px 12px"
  decision-pill-wait:
    backgroundColor: "{colors.wait-soft}"
    textColor: "{colors.wait}"
    rounded: "{rounded.full}"
    padding: "6px 12px"
  decision-pill-watch:
    backgroundColor: "{colors.watch-soft}"
    textColor: "{colors.watch}"
    rounded: "{rounded.full}"
    padding: "6px 12px"
  chip-level:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.full}"
    padding: "4px 4px 4px 12px"
---

# Design System: Gold Advisor

## Overview

**Creative North Star: "The Plain Answer"**

Gold Advisor looks like a conventional personal-finance app, played straight. The owner chose this "plain and standard" look on 2026-11-02, so the system has no themed visual world. It uses a light warm-neutral page, white panels with 1px hairline borders, the device's own sans-serif, and one ochre-gold accent. The screen leads with the advice in words. Prices and charts come after it, and they never lead.

The layout is a single column sized for a phone and capped at a reading width on larger screens. Density is moderate: 16px between panels, 16 to 20px inside them, and every control at least 44px tall. Colour carries meaning in one place only, the decision. Green, red and amber appear for BUY, WAIT and WATCH CLOSELY, and each is always paired with an icon and a text label. Everything else stays neutral, so the decision is the only coloured block on the page.

Depth is flat. Panels are separated by borders and the warm ground, not by shadows. The build uses only two small shadows: one on the Refresh button and one on its status popover.

**Key Characteristics:**
- Warm off-white ground (#f6f4ef) with white panels and 1px warm-grey hairlines
- System UI sans for everything, with tabular numerals on every price and number column
- One ochre-gold accent for actions, the active tab, focus rings and the price line
- Decision state colours used only for the decision, always with icon plus label
- Flat surfaces, 8px radius on controls and 12px on panels, 44px minimum tap targets
- Lucide line icons at 16 to 20px, decorative and `aria-hidden`

## Colors

A quiet warm-neutral palette with one brown-gold accent and three state colours that belong to the decision.

### Primary
- **Ochre Gold** (accent): Primary buttons ("View detailed analysis", "Add", "Sign in"), the active nav tab's text, text links, the focus ring, reason bullets, and the Nepal price line. White text on it reaches 6.25:1.
- **Deep Ochre** (accent-hover): Hover fill for primary buttons only.
- **Gold Wash** (accent-soft): Active nav tab background and text selection. Ochre Gold text on it reaches 5.27:1.

### Tertiary (decision states)
- **Buy Green** (buy) on **Mint Wash** (buy-soft): BUY pill, BUY decision panel and headline, success messages, support levels and up-candles on the daily chart. 5.67:1.
- **Wait Red** (wait) on **Rose Wash** (wait-soft): WAIT pill, WAIT decision panel and headline, all error text, resistance levels and down-candles. 5.58:1.
- **Watch Amber** (watch) on **Apricot Wash** (watch-soft): WATCH CLOSELY pill and panel, and the seven-day review note. 6.04:1.

Decision panels and pills draw their border from the state colour at 25% opacity.

### Neutral
- **Warm Paper** (ground): Page background, sticky header (at 95% opacity), browser theme colour, chips, and inset confirm areas.
- **White Panel** (panel): Every content panel, inputs, the secondary button and the Refresh popover.
- **Hairline** (line): All borders and table and list dividers. At 50% opacity it becomes the nav tab hover fill.
- **Ink** (ink): Headings, body text, values.
- **Muted Ink** (ink-2): Secondary text, captions, data ages, table headers, chart axis labels. 7.75:1 on white, 7.05:1 on Warm Paper.

### Named Rules
**The Decision Owns Colour Rule.** Buy Green, Wait Red and Watch Amber appear only for the decision and its direct consequences (errors use Wait Red, success uses Buy Green, chart support and resistance use them). Nothing decorative may use them.

**The Icon And Word Rule.** A state colour is never the only signal. Every decision pill pairs its colour with a Lucide icon (CircleCheck, Hourglass, Eye) and a word.

**The Accent Is Not A Verdict Rule.** Ochre Gold and Watch Amber sit close in hue (about 74° and 59° in OKLCH). Ochre Gold marks actions and focus only; never use it to fill a decision panel or pill.

## Typography

**Display Font:** system-ui (with -apple-system, Segoe UI, Roboto, Noto Sans, Noto Sans Devanagari, sans-serif)
**Body Font:** the same system stack
**Label/Mono Font:** none distinct; numbers use the `tnum` tabular figures of the system face

**Character:** The phone's own sans-serif, so the app reads like the rest of the owner's phone. Noto Sans Devanagari is in the stack so Nepali gold labels such as छापावाल सुन render properly.

### Hierarchy
- **Display** (600, 2.25rem, 2.5rem line, -0.025em, tabular): The Nepal price per tola. One per screen.
- **Headline** (600, 1.75rem, 1.25 line, -0.025em): The decision headline, coloured with the decision's state colour.
- **Title** (600, 1.5rem, -0.025em): Page titles on Details, Settings and Login. Empty-state titles step down to 1.25rem.
- **Title Small** (600, 1rem): Panel titles ("Why", "Nepal gold today", "Prices used").
- **Lead** (400, 1.125rem, 1.625 line, max 60ch): The decision's one-sentence summary.
- **Body** (400, 1rem, 1.5 line): Reasons and paragraphs; reasons use a 1.625 line height.
- **Body Small / Label** (400 or 500, 0.875rem): Panel sub-copy, tables, buttons, nav tabs, field labels.
- **Caption** (400, 0.75rem): Data age lines ("Advice updated 3 min ago"), chart date ranges, rule names.
- **Pill label** (600, 0.875rem or 0.75rem, uppercase, 0.025em tracking): Decision pill text only.

### Named Rules
**The Tabular Numbers Rule.** Every price, percentage and number column uses tabular numerals so digits line up and do not shift on refresh.

**The Age Line Rule.** Every number is followed by a caption or small line in Muted Ink saying how old it is and where it came from.

## Layout

The layout is one column, centred, with a 48rem (768px) maximum width and 16px side padding. Main content has 20px top padding and 64px bottom padding. Panels stack with 16px gaps. Panel padding is 16px, rising to 20px from the 640px breakpoint; the decision panel rises from 16px to 24px.

A sticky header carries the product name (hidden below 640px), Today, Details and Settings tabs, and the Refresh button. Below 640px the Refresh label collapses to its icon, keeping a screen-reader label. The only responsive changes are these and the decision's "How sure / Check again" row, which stacks on phones and sits in a row from 640px. Wide tables on Details scroll sideways inside their panel rather than squeezing.

Spacing follows Tailwind's 4px steps. The values in use are 4, 8, 12, 16, 20 and 24px, with 44px as the minimum height for every tappable control.

## Elevation & Depth

The system is flat. Depth comes from the Warm Paper ground showing between White Panels and from 1px Hairline borders. The sticky header separates itself with a bottom hairline, a 95% opaque ground and a small backdrop blur, not a shadow.

### Shadow Vocabulary
- **Button lift** (`box-shadow: 0 1px 2px rgb(29 27 23 / 0.06)`): The Refresh button only, so it reads as pressable on the header.
- **Popover** (`box-shadow: 0 4px 12px rgb(29 27 23 / 0.10)`): The Refresh status message that floats under the compact button.

### Named Rules
**The Flat Panel Rule.** Panels and cards never take a shadow. Only small floating or header controls may lift.

## Shapes

Corners are gently rounded and consistent. Controls (buttons, inputs, nav tabs, inset areas) use 8px. Panels, the decision panel and the review note use 12px. Pills, chips and the round remove button inside chips are fully round. The focus ring is a 2px Ochre Gold outline, 2px offset, drawn with a 6px radius. Borders are always 1px. Reason bullets are 6px Ochre Gold dots.

## Components

### Buttons
Standard, quiet, and large enough for a thumb.
- **Shape:** gently rounded (8px), at least 44px tall, 16px horizontal padding, 0.875rem text.
- **Primary:** Ochre Gold fill, white semibold text. Used for the main forward action on each surface. Can carry a trailing 16px arrow icon.
- **Hover / Focus:** Primary darkens to Deep Ochre. Focus shows the global 2px Ochre Gold ring. Disabled drops to 50 to 60% opacity.
- **Secondary:** White or transparent with a 1px Hairline border and medium-weight text. On hover the border tints toward Ochre Gold (40%) and the text turns Ochre Gold, or for Cancel the fill becomes Warm Paper.
- **Ghost:** No border, Muted Ink text; hover fills with Warm Paper and the text darkens to Ink.
- **Refresh:** A secondary button with a 16px RefreshCw icon, the button-lift shadow, and a spinning icon with "Checking…" while busy.

### Chips
- **Style:** Watch-level chips are fully round, Warm Paper fill, 1px Hairline border, tabular 0.875rem text, with a 40px round remove button (X icon) inside the right edge.
- **State:** The remove button fills with Hairline on hover.

### Cards / Containers
- **Corner Style:** 12px.
- **Background:** White Panel; the decision panel takes its state wash instead.
- **Shadow Strategy:** none (see The Flat Panel Rule).
- **Border:** 1px Hairline; the decision panel uses its state colour at 25%.
- **Internal Padding:** 16px, 20px from 640px. Optional header row with a Title Small heading and a right-aligned action, 12px above the content.

### Inputs / Fields
- **Style:** White fill, 1px Hairline border, 8px radius, 44px tall, 12px horizontal padding, 1rem text so phones do not zoom. Labels sit above in 0.875rem medium. Number inputs use tabular numerals; placeholders are Muted Ink at 70%.
- **Focus:** The global 2px Ochre Gold outline ring.
- **Error / Disabled:** Errors appear as 0.875rem Wait Red text below the field (`role="alert"` or `role="status"`); success messages use Buy Green.

### Navigation
- **Style:** Three text tabs (Today, Details, Settings) in the sticky header, 0.875rem medium, 44px tall, 8px radius, 4px apart.
- **States:** Default Muted Ink; hover fills with Hairline at 50% and darkens to Ink; active uses Gold Wash fill with Ochre Gold text and `aria-current="page"`.
- **Mobile:** The tabs stay visible; the product name hides below 640px.

### Decision Panel and Pill
The signature component and the first thing on the Today screen. The pill is fully round with a 25% state-colour border, state wash fill, state-colour text, a Lucide icon at 2.25 stroke, and an uppercase semibold word ("Buy", "Wait", "Watch closely"). The large pill (0.875rem, 6px by 12px padding) sits on the decision panel. The small pill (0.75rem) sits next to the Details page title. The panel holds, in order, the pill, the Headline-size advice in the state colour, the Lead summary in Ink, a "How sure / Check again" row, and a caption with the advice's age.

### Price Line Chart
The Nepal price chart is a 120px-high TradingView Lightweight Charts line in Ochre Gold (2px), on a transparent background with faint horizontal gridlines only, 11px Muted Ink axis labels, and scrolling and zoom turned off. A caption below states the date range, and a screen-reader caption states the first and last price. The daily candle chart on Details uses Buy Green and Wait Red candles, Hairline scale borders, and dashed support and resistance lines, with the owner's watch level as a solid Ochre Gold line.

## Do's and Don'ts

### Do:
- **Do** put the decision panel first, above any price or chart.
- **Do** pair every state colour with a Lucide icon and a word.
- **Do** follow every number with its age and source in a Muted Ink caption.
- **Do** use tabular numerals for prices, percentages and table numbers.
- **Do** keep every tappable control at least 44px tall.
- **Do** separate surfaces with 1px Hairline borders on the Warm Paper ground.
- **Do** use the global 2px Ochre Gold focus ring, offset 2px.

### Don't:
- **Don't** use Buy Green, Wait Red or Watch Amber for decoration, branding or non-decision emphasis.
- **Don't** fill a decision panel or pill with Ochre Gold.
- **Don't** add shadows to panels or cards.
- **Don't** add a webfont or a themed visual world; the owner chose the plain, standard look.
- **Don't** show placeholder or demo prices; use the empty and loading panels instead.
