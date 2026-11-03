"""FreeNewsAPI (https://freenewsapi.io): recent gold and silver headlines.

The key is sent only in the ``x-api-key`` header, never in a URL. Article text is untrusted
input: we keep the headline, publisher, publication time, link, and the short excerpt the
provider calls ``incipit``. The full article body is never stored or shown.

Limits: 5,000 requests/day and 2 requests/second. One refresh uses at most
``REQUEST_BUDGET`` requests, spaced ``MIN_INTERVAL`` apart (about 10 seconds in total).
"""

import difflib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx

from gold_advisor.assets import AssetDefinition
from gold_advisor.collectors.http import get_with_retries, make_client
from gold_advisor.collectors.types import SourceSchemaError
from gold_advisor.domain import UTC

BASE_URL = "https://api.freenewsapi.io/v1"
SHARED_TERMS = ("precious metals",)
REQUEST_BUDGET = 20
MIN_INTERVAL = 0.5  # seconds: 2 requests/second
LOOKBACK = timedelta(hours=48)
MAX_DETAILS = 12
MAX_PER_PUBLISHER = 2
MAX_FOR_AI = 5
MAX_TITLE = 300
MAX_EXCERPT = 320
SIMILAR_TITLE = 0.85


class NewsUnavailable(RuntimeError):
    """The search could not run at all (missing key, every request failed)."""


@dataclass(frozen=True)
class Candidate:
    provider_id: str
    title: str
    publisher: str
    published_at: datetime


@dataclass(frozen=True)
class Article:
    provider_id: str
    title: str
    publisher: str
    published_at: datetime
    url: str
    excerpt: str
    language: str


@dataclass
class RefreshResult:
    articles: list[Article] = field(default_factory=list)
    requests_used: int = 0
    failures: list[str] = field(default_factory=list)


def make_news_client(key: str) -> httpx.Client:
    if not key.strip():
        raise NewsUnavailable("FREENEWSAPI_KEY is not configured")
    return make_client(headers={"x-api-key": key.strip(), "Accept": "application/json"})


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _clean(text: object, limit: int) -> str:
    if not isinstance(text, str):
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def safe_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2000:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        return None
    return value


def parse_search(payload: object) -> list[Candidate]:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SourceSchemaError("freenewsapi search: unexpected response")
    out = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        uuid, title, publisher = item.get("uuid"), _clean(item.get("title"), MAX_TITLE), _clean(item.get("publisher"), 120)
        published = _parse_time(item.get("published_at"))
        if isinstance(uuid, str) and re.fullmatch(r"[0-9a-fA-F-]{8,64}", uuid) and title and publisher and published:
            out.append(Candidate(uuid, title, publisher, published))
    return out


def parse_details(payload: object) -> Article | None:
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise SourceSchemaError("freenewsapi details: unexpected response")
    d = payload["data"]
    url = safe_url(d.get("original_url"))
    published = _parse_time(d.get("published_at"))
    title, publisher = _clean(d.get("title"), MAX_TITLE), _clean(d.get("publisher"), 120)
    languages = d.get("languages") if isinstance(d.get("languages"), list) else []
    if not (url and published and title and publisher and isinstance(d.get("uuid"), str)):
        return None
    return Article(
        provider_id=d["uuid"],
        title=title,
        publisher=publisher,
        published_at=published,
        url=url,
        excerpt=_clean(d.get("incipit"), MAX_EXCERPT),
        language=(languages[0] if languages and isinstance(languages[0], str) else ""),
    )


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", title.lower())


def select(candidates: list[Candidate], asset: AssetDefinition, now: datetime, limit: int = MAX_DETAILS) -> list[Candidate]:
    """Relevant, recent, de-duplicated, and spread across publishers; newest first."""
    keywords = tuple(k.lower() for k in asset.news_keywords)
    chosen: list[Candidate] = []
    seen_ids: set[str] = set()
    per_publisher: dict[str, int] = {}
    for c in sorted(candidates, key=lambda c: c.published_at, reverse=True):
        title = _norm(c.title)
        if c.provider_id in seen_ids or not (now - LOOKBACK <= c.published_at <= now + timedelta(minutes=5)):
            continue
        if keywords and not any(k in title for k in keywords):
            continue
        if any(difflib.SequenceMatcher(None, title, _norm(x.title)).ratio() >= SIMILAR_TITLE for x in chosen):
            continue
        if per_publisher.get(c.publisher, 0) >= MAX_PER_PUBLISHER:
            continue
        seen_ids.add(c.provider_id)
        per_publisher[c.publisher] = per_publisher.get(c.publisher, 0) + 1
        chosen.append(c)
        if len(chosen) == limit:
            break
    return chosen


class _Paced:
    """Keeps requests at least MIN_INTERVAL apart and within REQUEST_BUDGET."""

    def __init__(self, client: httpx.Client, budget: int, sleep: Callable[[float], None], clock: Callable[[], float]):
        self.client, self.budget, self.sleep, self.clock = client, budget, sleep, clock
        self.used, self._last = 0, None

    def get(self, path: str, params: dict) -> dict:
        if self.used >= self.budget:
            raise NewsUnavailable("request budget used up")
        if self._last is not None:
            wait = MIN_INTERVAL - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self.used += 1
        try:
            response = get_with_retries(self.client, f"{BASE_URL}{path}", params=params, attempts=2, base_delay=2.0, sleep=self.sleep)
        finally:
            self._last = self.clock()
        try:
            return response.json()
        except ValueError as exc:
            raise SourceSchemaError(f"freenewsapi {path}: invalid JSON") from exc


def refresh(
    client: httpx.Client,
    asset: AssetDefinition,
    *,
    now: datetime,
    budget: int = REQUEST_BUDGET,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> RefreshResult:
    """Search the asset's terms, then fetch details for the best candidates.

    Partial failures are recorded and the refresh continues; it raises NewsUnavailable only
    when every search failed, so "no news" is never confused with "couldn't search".
    """
    paced = _Paced(client, budget, sleep, clock)
    result = RefreshResult()
    candidates: list[Candidate] = []
    terms = (*asset.news_terms, *SHARED_TERMS)
    searches_ok = 0
    for term in terms:
        try:
            candidates += parse_search(paced.get("/news", {"in_title": term, "order_by": "recent"}))
            searches_ok += 1
        except (httpx.HTTPError, SourceSchemaError, NewsUnavailable) as exc:
            result.failures.append(f"search '{term}': {_describe(exc)}")
    if terms and searches_ok == 0:
        result.requests_used = paced.used
        raise NewsUnavailable("; ".join(result.failures) or "every search failed")

    for c in select(candidates, asset, now, limit=min(MAX_DETAILS, budget - paced.used)):
        try:
            article = parse_details(paced.get("/details", {"uuid": c.provider_id}))
        except (httpx.HTTPError, SourceSchemaError, NewsUnavailable) as exc:
            result.failures.append(f"details {c.provider_id}: {_describe(exc)}")
            continue
        if article is None or (article.language and article.language != "en"):
            continue
        result.articles.append(article)
    result.requests_used = paced.used
    return result


def _describe(exc: Exception) -> str:
    # Never include request headers or URLs that might carry credentials.
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.HTTPError):
        return type(exc).__name__
    return str(exc)[:200]


def for_ai(articles: list[Article]) -> list[Article]:
    return sorted(articles, key=lambda a: a.published_at, reverse=True)[:MAX_FOR_AI]
