"""Vercel entrypoint. Vercel detects a literal `app = FastAPI()` in app.py, so the real API
(src/gold_advisor/api.py) is mounted inside it."""

import sys
from pathlib import Path

from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from gold_advisor.api import app as gold_advisor_api  # noqa: E402

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/", gold_advisor_api)
