"""Operator commands: ``gold-advisor backfill`` and ``gold-advisor collect <job>``."""

import argparse
from datetime import date
import json
from dataclasses import asdict
import logging
import sys

from gold_advisor import jobs
from gold_advisor.assets import ASSETS
from gold_advisor.domain import COLLECTED_TIMEFRAMES, Timeframe

JOBS = {
    "gold-spot": jobs.collect_gold_spot,
    "nepal-today": jobs.collect_nepal_today,
    "nepal-history": jobs.collect_nepal_history,
    "fx": jobs.collect_fx,
    "macro": jobs.collect_macro,
    "events": jobs.collect_events,
    "us-releases": jobs.collect_us_releases,
    "analysis": jobs.run_analysis,
    **{f"candles-{tf.value}": (lambda tf=tf: jobs.collect_candles(tf)) for tf in COLLECTED_TIMEFRAMES},
}
# Daily first so long-horizon context is available soonest; 15m last.
BACKFILL_ORDER = ["gold-spot", "nepal-today", "nepal-history", "fx", "macro", "events", "us-releases", "candles-1D", "candles-1h", "candles-15m", "analysis"]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="gold-advisor")
    sub = parser.add_subparsers(dest="command", required=True)
    backfill = sub.add_parser("backfill", help="run every collector once, backfilling empty history")
    backfill.add_argument("--asset", choices=["all", *ASSETS], default="all")
    collect = sub.add_parser("collect", help="run a single collector now")
    collect.add_argument("job", choices=sorted(JOBS))
    collect.add_argument("--asset", choices=list(ASSETS), default="gold")
    evaluate = sub.add_parser("evaluate-local", help="evaluate local-price thresholds against immediate purchase")
    evaluate.add_argument("--asset", choices=list(ASSETS), required=True)
    recorded = sub.add_parser("evaluate-decisions", help="evaluate saved decisions against immediate purchase")
    recorded.add_argument("--asset", choices=list(ASSETS), required=True)
    recorded.add_argument("--days", type=int, choices=range(1, 366), default=365, metavar="1..365")
    replay = sub.add_parser("backtest", help="replay the BUY/WAIT rules over past Nepal publication days")
    replay.add_argument("--asset", choices=list(ASSETS), required=True)
    replay.add_argument("--start", type=date.fromisoformat, default=None, help="YYYY-MM-DD")
    replay.add_argument("--end", type=date.fromisoformat, default=None, help="YYYY-MM-DD")
    replay.add_argument("--lookahead-sample", type=int, default=30, help="days rerun on cut-off history (0 to skip)")
    replay.add_argument("--csv", default=None, help="write one row per day to this file")
    args = parser.parse_args(argv)

    if args.command == "backtest":
        import csv
        from gold_advisor import backtest
        from gold_advisor.persistence.db import session_scope

        asset = ASSETS[args.asset]
        with session_scope() as session:
            history = backtest.load(session, asset)
        days = backtest.run(history, asset, args.start or date.min, args.end or date.max)
        report = backtest.summarise(days)
        if args.lookahead_sample > 0:
            mismatches = backtest.lookahead_check(history, asset, days, args.lookahead_sample)
            report["lookahead_check"] = {"sampled": min(args.lookahead_sample, len(days)), "mismatches": mismatches}
        if args.csv:
            with open(args.csv, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["day", "nepal_price", "decision", "rule", "next_price_change_pct"])
                for d in days:
                    writer.writerow([d.day, d.nepal_price, d.decision.value, d.rule, d.next_price_change_pct])
        print(json.dumps({"asset": asset.id, **report}, default=str, indent=2))
        return 1 if report.get("lookahead_check", {}).get("mismatches") else 0

    if args.command == "evaluate-decisions":
        from datetime import datetime, timedelta
        from gold_advisor.analytics.decision_evaluation import Observation, evaluate as evaluate_decisions
        from gold_advisor.domain import UTC, NEPAL_TZ, Decision
        from gold_advisor.persistence.db import session_scope
        from gold_advisor.persistence.market_data import recorded_decisions

        with session_scope() as session:
            rows = recorded_decisions(session, ASSETS[args.asset], datetime.now(UTC) - timedelta(days=args.days))
            if len(rows) == 50000:
                print("Too many snapshots; choose a smaller --days window.", file=sys.stderr)
                return 1
            daily = {}
            for row in rows:
                day = row.created_at.astimezone(NEPAL_TZ).date()
                latest = row.payload.get("prices", {}).get("nepal_latest") or {}
                price = latest.get("nepal_price")
                if latest.get("rate_date") == day.isoformat() and price is not None:
                    daily[day] = Observation(day, float(price), Decision(row.decision))
        result = evaluate_decisions(list(daily.values()))
        print(json.dumps({"asset": args.asset, "observed_days": len(daily), "result": asdict(result)}, default=str, indent=2))
        return 0

    if args.command == "evaluate-local":
        from sqlalchemy import select
        from gold_advisor.analytics.calibration import Publication, evaluate as evaluate_prices
        from gold_advisor.domain import MassUnit, Source
        from gold_advisor.persistence.db import session_scope
        from gold_advisor.persistence.models import LocalMetalRateRow

        asset = ASSETS[args.asset]
        with session_scope() as session:
            rows = session.execute(select(LocalMetalRateRow.rate_date, LocalMetalRateRow.price_npr).where(
                LocalMetalRateRow.source == Source.FENEGOSIDA.value, LocalMetalRateRow.metal == asset.metal.value,
                LocalMetalRateRow.purity == asset.purity.value, LocalMetalRateRow.unit == MassUnit.TOLA.value
            ).order_by(LocalMetalRateRow.rate_date)).all()
        try:
            result = evaluate_prices([Publication(day, float(price)) for day, price in rows])
        except ValueError as error:
            print(f"Evaluation failed: {error}", file=sys.stderr)
            return 1
        print(json.dumps({"asset": asset.id, "result": asdict(result)}, default=str, indent=2))
        return 0

    names = BACKFILL_ORDER if args.command == "backfill" else [args.job]
    failed: list[str] = []
    for name in names:
        selected = list(ASSETS.values()) if args.asset == "all" else [ASSETS[args.asset]]
        per_asset = name == "gold-spot" or name == "analysis" or name.startswith("candles-")
        for asset in selected if per_asset else [None]:
            label = f"{name} ({asset.id})" if asset else name
            try:
                if name == "gold-spot":
                    result = jobs.collect_gold_spot(asset)
                elif name == "analysis":
                    result = jobs.run_analysis(asset)
                elif name.startswith("candles-"):
                    result = jobs.collect_candles(Timeframe(name.removeprefix("candles-")), asset)
                else:
                    result = JOBS[name]()
            except Exception as exc:  # report and continue with other sources and assets
                failed.append(label)
                print(f"FAILED  {label}: {exc}", file=sys.stderr)
                continue
            if isinstance(result, str):
                print(f"OK      {label}: snapshot {result}")
            else:
                print(f"OK      {label}: +{result.inserted} inserted, {result.revised} revised, {result.unchanged} unchanged")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
