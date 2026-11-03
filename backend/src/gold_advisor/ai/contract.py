"""What the AI sees, what it must return, and how its answer is checked.

The AI only explains numbers the app already computed. It may nudge the score by at most
±5 points and cannot change the BUY / WAIT / WATCH CLOSELY decision. Any price it quotes
must match a fact it was given; any evidence or level it cites must exist.
"""

import json
import re

PROMPT_VERSION = "ai-2-assets"
MAX_ADJUSTMENT = 5.0
PRICE_TOLERANCE = 0.005
MIN_CHECKED_NUMBER = 100.0
PROVIDERS = ("codex", "claude", "kiro", "openrouter")

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["plain_summary", "outlook", "adjustment", "adjustment_reason", "reasons", "risks", "watch_levels"],
    "properties": {
        "plain_summary": {"type": "string", "maxLength": 420},
        "outlook": {"type": "string", "enum": ["bearish", "neutral", "bullish"]},
        "adjustment": {"type": "number", "minimum": -MAX_ADJUSTMENT, "maximum": MAX_ADJUSTMENT},
        "adjustment_reason": {"type": "string", "maxLength": 300},
        "reasons": {
            "type": "array",
            "minItems": 2,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "evidence_ids"],
                "properties": {
                    "text": {"type": "string", "maxLength": 300},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5},
                },
            },
        },
        "risks": {"type": "array", "maxItems": 4, "items": {"type": "string", "maxLength": 240}},
        "watch_levels": {"type": "array", "maxItems": 4, "items": {"type": "string"}},
    },
}

INSTRUCTIONS = """You are helping one household in Nepal decide when to buy {asset_label}. The owner is not a trader.
You are given FACTS computed by the app. Use only these facts. Do not invent prices, indicators,
probabilities, news, or levels. Every price you write must appear in FACTS.

Return ONLY a JSON object matching SCHEMA:
- plain_summary: 1-3 short sentences in everyday English. No jargon (no RSI, MACD, ATR, Fibonacci, pivot).
  Explain what world {asset_label} is doing and what that means for buying in Nepal. Do not tell them to split the purchase.
- outlook: your view of world {asset_label} over the next few days.
- adjustment: a number from -5 to +5 to nudge the app's score (negative = more bearish). Use 0 unless the
  facts clearly justify it. adjustment_reason explains why in one sentence.
- reasons: 2-5 points; each cites evidence_ids from FACTS.
- risks: what could make this wrong.
- watch_levels: ids of LEVELS (from FACTS) worth watching.
The app's decision ({decision}) is fixed by its rules; do not contradict it, explain it."""


def _fact(facts: list, fid: str, label: str, value, unit: str = "") -> None:
    if value is not None:
        facts.append({"id": fid, "label": label, "value": value, "unit": unit})


def build_input(snapshot_id: str, payload: dict) -> dict:
    asset = payload.get("asset", {"id": "gold", "label": "Gold", "local_label": "Hallmark gold"})
    label = asset["label"].lower()
    facts: list[dict] = []
    prices, lag, score = payload["prices"], payload["nepal_lag"], payload["score"]
    latest = lag.get("latest") or {}
    _fact(facts, "decision", "App decision", payload["decision"]["decision"])
    _fact(facts, "decision_rule", "Rule that produced it", payload["decision"]["rule"])
    _fact(facts, "world_now", f"World {label} now", prices.get("world_usd_now", prices.get("xau_usd_now")), "USD/oz")
    _fact(facts, "nepal_price", f"Nepal {asset['local_label']}, latest", latest.get("nepal_price"), "NPR/tola")
    _fact(facts, "nepal_date", "Nepal price date", latest.get("rate_date"))
    _fact(facts, "usd_npr", "Dollar rate (NRB mid)", prices.get("usd_npr_mid"), "NPR")
    _fact(facts, "nepal_implied", "Nepal price implied by world price now", lag.get("implied_nepal_now"), "NPR/tola")
    _fact(facts, "nepal_change_3", "Nepal change over 3 updates", lag.get("nepal_change_3_publications"), "NPR/tola")
    _fact(facts, "intl_since_nepal", f"World {label} change since Nepal's update", lag.get("intl_change_since_publication_pct"), "fraction")
    for k, v in (prices.get("changes") or {}).items():
        _fact(facts, f"change_{k}", f"World {label} change {k}", v, "fraction")
    _fact(facts, "score", "App score (-100..100)", score.get("deterministic"))
    for name, comp in (score.get("components") or {}).items():
        _fact(facts, f"score_{name}", f"Score part: {name}", comp.get("value"))
    for tf, tech in (payload.get("technical") or {}).items():
        for sig in tech.get("signals", []):
            _fact(facts, f"ind_{tf}_{sig['key']}", f"{tf} {sig['name']}", sig["value"], sig["reading"])
    for f in payload.get("forecasts") or []:
        if f.get("status") != "ok":
            continue
        key = f["label"].replace(" ", "")
        for sc in f["scenarios"]:
            _fact(facts, f"fc_{key}_{sc['name']}", f"Chance {label} is {sc['name']} in {f['label']}", sc["probability"], f"of {f['sample_size']} similar days")
        _fact(facts, f"fc_{key}_range", f"Usual range in {f['label']}", f["range_usd"], "USD/oz")
        _fact(facts, f"fc_{key}_range_npr", f"Usual Nepal range in {f['label']}", f.get("range_npr_per_tola"), "NPR/tola")
    event = payload.get("next_event")
    if event:
        _fact(facts, "next_event", "Next major US event", f"{event['title']} in {event['hours_away']:.0f} hours")
    levels = []
    for tf in ("4h", "1D"):
        for lvl in (payload.get("timeframes", {}).get(tf, {}).get("levels") or []):
            levels.append({"id": lvl["id"], "timeframe": tf, "price": lvl["price"], "kind": lvl["kind"]})
        for st in (payload.get("timeframes", {}).get(tf, {}).get("level_states") or []):
            _fact(facts, f"state_{st['level_id']}", f"{tf} level {st['price']} state", st["state"], st.get("direction") or "")
    pivots = (payload.get("price_levels") or {}).get("pivots")
    if pivots:
        for k, v in pivots["levels"].items():
            levels.append({"id": f"pivot-{k}", "timeframe": "1D", "price": v, "kind": "pivot"})
    return {"asset": asset, "snapshot_id": snapshot_id, "prompt_version": PROMPT_VERSION, "facts": facts, "levels": levels}


def prompt(inp: dict) -> str:
    decision = next((f["value"] for f in inp["facts"] if f["id"] == "decision"), "unknown")
    return (
        INSTRUCTIONS.format(decision=decision, asset_label=inp.get("asset", {}).get("label", "Gold").lower())
        + "\n\nSCHEMA:\n" + json.dumps(OUTPUT_SCHEMA)
        + "\n\nFACTS:\n" + json.dumps(inp["facts"], ensure_ascii=False)
        + "\n\nLEVELS:\n" + json.dumps(inp["levels"])
    )


def extract_json(raw: str) -> dict:
    """Accept the bare object, a CLI JSON envelope, or the first {...} block in text."""
    text = raw.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object in output")
        data = json.loads(text[start : end + 1])
    if isinstance(data, dict):
        for key in ("structured_output", "result"):  # Claude Code --output-format json envelope
            inner = data.get(key)
            if isinstance(inner, dict):
                return inner
            if isinstance(inner, str) and "{" in inner:
                return extract_json(inner)
    if not isinstance(data, dict):
        raise ValueError("output is not a JSON object")
    return data


def _numbers(value) -> list[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [float(value)]
    if isinstance(value, list):
        return [n for v in value for n in _numbers(v)]
    if isinstance(value, str):
        return [float(m.replace(",", "")) for m in re.findall(r"\d[\d,]*\.?\d*", value)]
    return []


def validate(inp: dict, out: dict) -> dict:
    errors: list[str] = []
    for key in OUTPUT_SCHEMA["required"]:
        if key not in out:
            errors.append(f"missing field: {key}")
    if errors:
        return {"ok": False, "errors": errors}
    if out["outlook"] not in ("bearish", "neutral", "bullish"):
        errors.append("outlook must be bearish, neutral, or bullish")
    adj = out["adjustment"]
    if not isinstance(adj, (int, float)) or isinstance(adj, bool) or abs(adj) > MAX_ADJUSTMENT:
        errors.append(f"adjustment must be a number within ±{MAX_ADJUSTMENT}")
    if not isinstance(out["plain_summary"], str) or not out["plain_summary"].strip() or len(out["plain_summary"]) > 420:
        errors.append("plain_summary must be 1-420 characters")
    reasons = out["reasons"] if isinstance(out["reasons"], list) else []
    if not 2 <= len(reasons) <= 5:
        errors.append("reasons must have 2-5 items")
    fact_ids = {f["id"] for f in inp["facts"]}
    level_ids = {lvl["id"] for lvl in inp["levels"]}
    for r in reasons:
        bad = [e for e in (r.get("evidence_ids") or []) if e not in fact_ids and e not in level_ids]
        if bad or not r.get("evidence_ids"):
            errors.append(f"reason cites unknown evidence: {bad or 'none'}")
    for lid in out["watch_levels"] or []:
        if lid not in level_ids:
            errors.append(f"unknown level id: {lid}")

    known = [abs(n) for f in inp["facts"] for n in _numbers(f["value"]) if abs(n) >= MIN_CHECKED_NUMBER]
    known += [float(lvl["price"]) for lvl in inp["levels"]]
    texts = [out["plain_summary"], out["adjustment_reason"], *[r.get("text", "") for r in reasons], *(out["risks"] or [])]
    unverified = sorted(
        {
            n
            for t in texts
            for n in _numbers(t)
            if abs(n) >= MIN_CHECKED_NUMBER
            and not (2000 <= n <= 2100 and float(n).is_integer())  # years
            and not any(abs(n - k) <= PRICE_TOLERANCE * abs(k) for k in known)
        }
    )
    price_facts = [abs(n) for f in inp["facts"] if f.get("unit") in ("USD/oz", "NPR/tola", "NPR") for n in _numbers(f["value"])]
    price_facts += [float(level["price"]) for level in inp["levels"]]
    for text in texts:
        for match in re.finditer(r"(?:US\$|\$|USD|NPR|Rs\.?)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:USD|NPR|dollars|rupees)", text, re.IGNORECASE):
            number = float((match.group(1) or match.group(2)).replace(",", ""))
            if not any(abs(number - known_price) <= PRICE_TOLERANCE * abs(known_price) for known_price in price_facts):
                unverified.append(number)
    if unverified:
        errors.append(f"numbers not found in the facts: {unverified[:5]}")
    return {"ok": not errors, "errors": errors}
