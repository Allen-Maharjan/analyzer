"""OpenRouter free-model discovery and structured chat inference.

The key remains on the host runner. No paid model or web-search plugin is used.
"""
import json
import time
import os
import re
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any

API = "https://openrouter.ai/api/v1"
MODEL_ID = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+:free$")


class OpenRouterError(RuntimeError):
    """A safe error suitable for displaying without provider response bodies."""


def _request(path: str, key: str, payload: dict[str, Any] | None = None, timeout: int = 45) -> dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(API + path, data=data, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise OpenRouterError(f"OpenRouter returned HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise OpenRouterError("OpenRouter could not be reached.") from error
    except (ValueError, UnicodeError) as error:
        raise OpenRouterError("OpenRouter returned invalid JSON.") from error
    if not isinstance(result, dict):
        raise OpenRouterError("OpenRouter returned an unexpected response.")
    return result


def free_models(catalog: dict[str, Any]) -> list[str]:
    """Only free chat models with structured output and zero advertised charges."""
    entries = catalog.get("data")
    if not isinstance(entries, list):
        raise OpenRouterError("OpenRouter model catalog has an unexpected format.")
    allowed = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model = entry.get("id")
        pricing = entry.get("pricing")
        architecture = entry.get("architecture") or {}
        if not isinstance(model, str) or not MODEL_ID.fullmatch(model) or len(model) > 64 or not isinstance(pricing, dict):
            continue
        if not isinstance(architecture, dict) or "text" not in (architecture.get("input_modalities") or []):
            continue
        if "structured_outputs" not in (entry.get("supported_parameters") or []):
            continue
        try:
            if not all(Decimal(str(pricing.get(name, "NaN"))) == 0 for name in ("prompt", "completion")):
                continue
            if any(Decimal(str(value)) != 0 for value in pricing.values() if value is not None):
                continue
        except (InvalidOperation, ValueError):
            continue
        allowed.append(model)
    return sorted(set(allowed))


def run(prompt: str, schema: dict[str, Any]) -> dict[str, str]:
    key = os.environ.get("GA_OPENROUTER_API_KEY", "").strip()
    if not key:
        raise OpenRouterError("OpenRouter API key is not configured on the runner.")
    models = free_models(_request("/models", key))
    if not models:
        raise OpenRouterError("No compatible free OpenRouter models are currently available.")
    # Bound attempts: free endpoints can be rate limited or temporarily unavailable. The whole
    # run must finish inside the API's 5-minute "running" window.
    deadline = time.monotonic() + 270
    for model in models[:3]:
        remaining = int(deadline - time.monotonic())
        if remaining < 30:
            break
        payload = {
            "model": model,
            # Free models are mostly reasoning models: keep thinking short and leave room for the
            # answer, or they stop at the token limit with empty content.
            "max_tokens": 8000,
            "reasoning": {"effort": "low", "exclude": True},
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "analysis", "strict": True, "schema": schema}},
            "provider": {"require_parameters": True, "max_price": {"prompt": 0, "completion": 0}},
        }
        try:
            response = _request("/chat/completions", key, payload, timeout=min(150, remaining))
            actual = response.get("model")
            if actual != model:
                raise OpenRouterError("OpenRouter returned an unexpected model.")
            choices = response.get("choices")
            if not isinstance(choices, list) or not choices:
                raise OpenRouterError("OpenRouter returned no answer.")
            choice = choices[0]
            if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                raise OpenRouterError("OpenRouter returned an unexpected answer.")
            content = choice["message"].get("content")
            if not isinstance(content, str) or not content.strip():
                raise OpenRouterError("OpenRouter returned an empty answer.")
            return {"raw_output": content[:200000], "model": model}
        except OpenRouterError:
            continue
    raise OpenRouterError("Compatible free models were unavailable or rate limited.")
