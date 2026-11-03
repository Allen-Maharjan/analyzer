"""Search recent articles without allowing article text to make decisions.

GDELT's indexed timestamp is when an article was seen, not its publication time.
Only bounded HTTPS links from allowlisted publishers are accepted.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx

from gold_advisor.assets import AssetDefinition
from gold_advisor.collectors.http import get_with_retries
from gold_advisor.collectors.types import SourceSchemaError
from gold_advisor.domain import UTC

URL = "https://api.gdeltproject.org/api/v2/doc/doc"
PUBLISHERS = frozenset({"reuters.com", "apnews.com", "federalreserve.gov", "gold.org"})
MAX_ARTICLES = 20
LOOKBACK = timedelta(hours=24)


@dataclass(frozen=True)
class Article:
    title: str
    url: str
    publisher: str
    seen_at: datetime


def parse(payload: object, *, now: datetime) -> list[Article]:
    if not isinstance(payload, dict) or not isinstance(payload.get("articles"), list):
        raise SourceSchemaError("news search returned an unexpected response")
    articles = []
    seen = set()
    for item in payload["articles"]:
        if not isinstance(item, dict):
            continue
        url, title, timestamp = item.get("url"), item.get("title"), item.get("seendate")
        if not all(isinstance(value, str) for value in (url, title, timestamp)):
            continue
        if not title.strip() or len(title) > 500 or len(url) > 2000:
            continue
        try:
            parsed = urlsplit(url)
            host = parsed.hostname or ""
            publisher = host.removeprefix("www.")
            if parsed.scheme != "https" or publisher not in PUBLISHERS or parsed.username or parsed.password or parsed.port not in (None, 443):
                continue
            observed = datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        if not now - LOOKBACK <= observed <= now or url in seen:
            continue
        seen.add(url)
        articles.append(Article(title.strip(), url, publisher, observed))
        if len(articles) == MAX_ARTICLES:
            break
    return articles


def fetch(client: httpx.Client, asset: AssetDefinition, *, now: datetime) -> list[Article]:
    if asset.id not in ("gold", "silver"):
        raise ValueError("news search is not configured for this asset")
    domains = " OR ".join(f"domainis:{domain}" for domain in sorted(PUBLISHERS))
    response = get_with_retries(client, URL, params={
        "query": f'{asset.label.lower()} (price OR market) ({domains})',
        "mode": "ArtList", "format": "json", "timespan": "24h",
        "maxrecords": MAX_ARTICLES, "sort": "datedesc",
    })
    try:
        payload = response.json()
    except ValueError as error:
        raise SourceSchemaError("news search returned invalid JSON") from error
    return parse(payload, now=now)
