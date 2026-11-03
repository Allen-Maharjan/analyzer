const TIMEFRAMES = new Set(["15m", "1h", "1D"]);

type MarketPath = { path: string } | { status: number; message: string };

/** Limit browser requests to the supported market reads and bounded history. */
export function marketPath(resource: string, params: URLSearchParams): MarketPath {
  const asset = params.get("asset") ?? "gold";
  if (!/^[a-zA-Z0-9:_-]{1,64}$/.test(asset)) return { status: 400, message: "Invalid asset." };
  const query = new URLSearchParams({ asset });
  if (resource === "candles" || resource === "indicators") {
    const timeframe = params.get("timeframe") ?? "15m";
    if (!TIMEFRAMES.has(timeframe)) return { status: 400, message: "Invalid timeframe." };
    query.set("timeframe", timeframe);
    query.set("limit", "192"); // indicators cover exactly the bars the chart shows
    return { path: `/api/v1/${resource}?${query}` };
  }
  if (resource === "quote") return { path: `/api/v1/quotes/latest?${query}` };
  return { status: 404, message: "Unknown market resource." };
}
