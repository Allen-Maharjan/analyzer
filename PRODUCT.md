# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Pinned by the specification: Next.js, TypeScript, Tailwind CSS, TradingView Lightweight Charts, talking to the FastAPI backend in `backend/`. Self-hosted with Docker Compose.

## Users

One household with one owner login. The owner is not a trader and does not understand technical analysis. The owner checks the app on a phone, now and then during the day, to decide whether to make one complete gold purchase now or wait a few days.

## Product Purpose

Tell a non-expert, in plain English, whether today is a reasonable day to buy gold in Nepal (BUY), whether to wait briefly (WAIT), or whether to keep watching (WATCH CLOSELY), and why. Success means the owner makes one purchase at a sensible moment without having to read charts.

## Positioning

The advice is built around Nepal's published FENEGOSIDA price and how it lags world gold, not around world gold alone. It separates "where world gold is heading" from "is this a good moment to buy in Nepal".

## Operating Context

- Nepal gold prices are published once a day (usually 10:00–11:00 Nepal time, no Saturday publication). The dollar rate (NRB) is also daily.
- World gold trades almost around the clock; the app refreshes it every minute.
- Analysis runs every 15 minutes and after each Nepal or dollar-rate update.
- The owner may press a refresh button to re-check daily prices.
- A seven-day waiting review: the app never forces a purchase and never silently restarts the waiting period.

## Capabilities and Constraints

- Free data sources only. Never show invented or demonstration prices as live; empty and loading states instead.
- Main number: Nepal hallmark gold, rupees per tola, in Nepali digit grouping (Rs 2,74,300). World price in USD per ounce appears only in detail.
- Plain-language summary first; technical detail (indicators, scores, levels, premium) only behind a clearly labelled "View detailed analysis" control.
- Decision colours: green BUY, red WAIT, amber WATCH CLOSELY, always paired with a text label and icon.
- Every price shows its age and source; stale data is labelled, not hidden.
- Never recommend splitting the purchase.
- Language: English. Nepali gold labels may appear where the source uses them.

## Brand Commitments

The owner chose a plain, standard look (2026-11-02): a conventional personal-finance app, played straight, without a themed visual world.

## Evidence on Hand

Real collected data only: FENEGOSIDA, NRB, Gold API / Swissquote, Dukascopy, FRED, Federal Reserve calendar. No testimonials, users, or performance claims exist; do not fabricate any.

## Product Principles

1. Lead with what to do, in everyday words.
2. Show how old every number is; old numbers never pass as current.
3. Detail is available, never required.
4. Calm and honest over exciting: no urgency tricks, no false precision.

## Accessibility & Inclusion

Phone-first. Readable without zoom, large tap targets, decision never conveyed by colour alone, WCAG AA contrast.
