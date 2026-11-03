"""HTTP client construction with bounded retries."""

import random
import ssl
import time
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import certifi
import httpx

from gold_advisor.config import PACKAGE_DIR, get_settings

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_AFTER_SECONDS = 30.0

# nrb.org.np serves its leaf with the wrong intermediate. We add the correct Sectigo
# intermediate (fetched from the leaf's AIA URL) as an untrusted-chain helper; the chain
# must still verify up to a root in certifi, so verification is not weakened.
NRB_INTERMEDIATE = PACKAGE_DIR / "certs" / "sectigo-public-server-authentication-ca-dv-r36.pem"


@lru_cache
def _ssl_context(extra_cert: Path | None) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    if extra_cert is not None:
        ctx.load_verify_locations(cafile=str(extra_cert))
    return ctx


def make_client(*, extra_cert: Path | None = None, headers: Mapping[str, str] | None = None) -> httpx.Client:
    settings = get_settings()
    merged = {"User-Agent": settings.http_user_agent, "Accept": "application/json, text/csv;q=0.9"}
    merged.update(headers or {})
    return httpx.Client(
        timeout=settings.http_timeout_seconds,
        headers=merged,
        verify=_ssl_context(extra_cert),
        follow_redirects=True,
    )


def get_with_retries(
    client: httpx.Client,
    url: str,
    *,
    params: Mapping[str, str | int] | None = None,
    attempts: int = 3,
    base_delay: float = 1.0,
    sleep=time.sleep,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:
            last_error = exc
            delay = base_delay * 2 ** (attempt - 1)
        else:
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()
                return response
            last_error = httpx.HTTPStatusError(
                f"{response.status_code} from {url}", request=response.request, response=response
            )
            delay = _retry_after(response) or base_delay * 2 ** (attempt - 1)
        if attempt < attempts:
            sleep(delay + random.uniform(0, base_delay / 2))
    assert last_error is not None
    raise last_error


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return min(float(value), MAX_RETRY_AFTER_SECONDS)
    except ValueError:
        return None
