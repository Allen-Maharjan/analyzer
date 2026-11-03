import assert from "node:assert/strict";
import { test } from "node:test";
import { marketPath } from "../src/lib/market-query.ts";

test("builds bounded asset-specific chart requests", () => {
  assert.deepEqual(marketPath("candles", new URLSearchParams("asset=silver&timeframe=1h&limit=99999")),
    { path: "/api/v1/candles?asset=silver&timeframe=1h&limit=192" });
  assert.deepEqual(marketPath("quote", new URLSearchParams("asset=NEPSE%3ANABIL")),
    { path: "/api/v1/quotes/latest?asset=NEPSE%3ANABIL" });
  assert.deepEqual(marketPath("candles", new URLSearchParams()),
    { path: "/api/v1/candles?asset=gold&timeframe=15m&limit=192" });
});

test("rejects invalid identifiers, timeframes, and resources", () => {
  assert.equal("status" in marketPath("candles", new URLSearchParams("asset=gold%26limit%3D9999")), true);
  assert.equal("status" in marketPath("candles", new URLSearchParams("timeframe=1W")), true);
  assert.deepEqual(marketPath("settings", new URLSearchParams()), { status: 404, message: "Unknown market resource." });
});
