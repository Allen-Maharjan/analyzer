// Fetch XAU/USD candles from Dukascopy and print them as JSON on stdout.
// Usage: node fetch.mjs '{"timeframe":"h1","from":"2026-10-01T00:00:00Z","to":"2026-10-02T00:00:00Z"}'
import { getHistoricalRates } from "dukascopy-node";

const ALLOWED_TIMEFRAMES = new Set(["m15", "h1", "d1"]);

const args = JSON.parse(process.argv[2] ?? "{}");
if (!ALLOWED_TIMEFRAMES.has(args.timeframe)) {
  console.error(`unsupported timeframe: ${args.timeframe}`);
  process.exit(2);
}
const instrument = args.instrument ?? "xauusd";
if (!["xauusd", "xagusd"].includes(instrument)) throw new Error("unsupported instrument");
const from = new Date(args.from);
const to = new Date(args.to);
if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime()) || from >= to) {
  console.error("invalid date range");
  process.exit(2);
}

try {
  const rows = await getHistoricalRates({
    instrument,
    dates: { from, to },
    timeframe: args.timeframe,
    priceType: "bid",
    format: "json",
    volumes: true,
    ignoreFlats: true,
    useCache: false,
    batchSize: 10,
    pauseBetweenBatchesMs: 1000,
    retryCount: 3,
    pauseBetweenRetriesMs: 2000,
    failAfterRetryCount: true,
  });
  process.stdout.write(JSON.stringify(rows));
} catch (err) {
  console.error(err?.message ?? String(err));
  process.exit(1);
}
